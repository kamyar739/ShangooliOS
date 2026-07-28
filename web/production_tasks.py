"""Idempotent artwork production tasks shared by manual and collection flows."""

import shutil
import os
import tempfile
from pathlib import Path

from app.database import get_artwork_folder
from PIL import Image
from web.ai_upscaler import candidate_path, upscale_candidate
from web.artwork_certifier import certify_artwork
from web.db import (
    get_artwork,
    get_artwork_certification,
    get_artwork_file_assignments,
    get_artwork_production,
    get_artwork_mockup_set_state,
    get_mockup_scene,
    get_mockup_set,
    get_collection,
    invalidate_artwork_after_source_change,
    record_ai_enhancement,
    record_artwork_mockup_set_generated,
    replace_artwork_ratio_assignments,
    list_mockup_scenes,
    list_mockup_sets,
    save_artwork_mockup_templates,
    set_artwork_production_flags,
    update_artwork_production,
    upsert_artwork_certification,
    upsert_artwork_file,
    upsert_print_master_certification,
)
from web.mockup_generator import (
    GENERATED_SLOTS,
    generate_listing_image,
    generate_scene_mockup,
)
from web.print_master import build_print_master
from web.ratio_generator import generate_ratio_output, resolve_assigned_file
from web.ratio_profiles import get_ratio_profile
from web.template_packs import DEFAULT_TEMPLATE_PACK


QUALITY_THRESHOLD = 80
MOCKUP_SCENES_DIR = Path(__file__).resolve().parent.parent / "data" / "mockup_scenes"
MOCKUP_SCENE_ROOM_TYPES = {
    "room": "Living room",
    "bedroom": "Bedroom",
    "office": "Office",
}


def assignment_map(artwork_code):
    return {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }


def ensure_source_certification(artwork):
    assignments = assignment_map(artwork["artwork_code"])
    source = assignments.get("source")
    if source is None:
        raise ValueError("Source image is missing")
    source_path = resolve_assigned_file(artwork, source)
    result = certify_artwork(source_path).to_dict()
    upsert_artwork_certification(artwork["artwork_code"], result)
    certification = get_artwork_certification(artwork["artwork_code"])
    if certification["valid"] and (
        certification["score"] or 0
    ) >= QUALITY_THRESHOLD:
        source_used = (
            "ai_upscale_4x"
            if "_ai_upscaled_approved" in source["stored_filename"]
            else "original"
        )
        return certification, source, source_path, source_used

    downstream = [
        role for role in assignments
        if role != "source"
    ]
    if downstream:
        raise ValueError(
            "Source needs AI enhancement but existing production files make "
            "the source state ambiguous; review this artwork individually"
        )

    workspace = get_artwork_folder(artwork)
    approved_path = candidate_path(artwork).with_name(
        f"{artwork['artwork_code']}_ai_upscaled_approved.png"
    )
    candidate = candidate_path(artwork)
    if approved_path.is_file():
        enhanced_path = approved_path
    else:
        if not candidate.is_file():
            upscale_candidate(artwork, source_path)
        enhanced_path = candidate
    enhanced = certify_artwork(enhanced_path).to_dict()
    if not enhanced["valid"] or enhanced["score"] < QUALITY_THRESHOLD:
        raise ValueError(
            "AI upscale remains below the accepted quality threshold"
        )
    if enhanced_path != approved_path:
        shutil.copy2(enhanced_path, approved_path)
    with Image.open(source_path) as original:
        original_width, original_height = original.size
    invalidate_artwork_after_source_change(artwork["artwork_code"])
    upsert_artwork_file(
        artwork_code=artwork["artwork_code"],
        role="source",
        relative_path=str(approved_path.relative_to(workspace)),
        stored_filename=approved_path.name,
        original_filename=approved_path.name,
    )
    upsert_artwork_certification(artwork["artwork_code"], enhanced)
    record_ai_enhancement(
        artwork["artwork_code"],
        original_width=original_width,
        original_height=original_height,
        enhanced_width=enhanced["width"],
        enhanced_height=enhanced["height"],
    )
    if candidate.is_file() and candidate != approved_path:
        candidate.unlink()
    approved_assignment = assignment_map(artwork["artwork_code"])["source"]
    return (
        get_artwork_certification(artwork["artwork_code"]),
        approved_assignment,
        approved_path,
        "ai_upscale_4x",
    )


def approve_certified_source(artwork, certification):
    production = get_artwork_production(artwork["artwork_code"])
    profile = get_ratio_profile(certification["orientation"])
    update_artwork_production(
        artwork_code=artwork["artwork_code"],
        orientation=certification["orientation"],
        master_ratio=profile["master_ratio"],
        required_ratios=", ".join(profile["required_ratios"]),
        original_approved=True,
        print_master_ready=bool(production["print_master_ready"]),
        ratio_exports_ready=bool(production["ratio_exports_ready"]),
        mockups_ready=bool(production["mockups_ready"]),
        listing_content_ready=bool(production["listing_content_ready"]),
        notes=production["notes"] or "",
    )


def ensure_print_master(artwork, source, source_path):
    assignments = assignment_map(artwork["artwork_code"])
    if assignments.get("print_master"):
        return "complete"
    result = build_print_master(artwork, source_path)
    upsert_artwork_file(
        artwork_code=artwork["artwork_code"],
        role="print_master",
        relative_path=result.relative_path,
        stored_filename=result.master_filename,
        original_filename=source["original_filename"],
    )
    master_path = get_artwork_folder(artwork) / result.relative_path
    upsert_print_master_certification(
        artwork["artwork_code"], certify_artwork(master_path).to_dict()
    )
    set_artwork_production_flags(artwork["artwork_code"], print_master_ready=True)
    return "created"


def ensure_ratio_files(artwork):
    production = get_artwork_production(artwork["artwork_code"])
    assignments = assignment_map(artwork["artwork_code"])
    master_path = resolve_assigned_file(artwork, assignments.get("print_master"))
    ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]
    created = False
    for ratio in ratios:
        if f"ratio:{ratio}" in assignments:
            continue
        result = generate_ratio_output(
            artwork=artwork,
            source_path=master_path,
            ratio=ratio,
            mode="fit",
            overwrite=False,
        )
        if result["status"] in {"created", "skipped"}:
            upsert_artwork_file(
                artwork_code=artwork["artwork_code"],
                role=f"ratio:{ratio}",
                relative_path=result["relative_path"],
                stored_filename=result["stored_filename"],
                original_filename=result["stored_filename"],
            )
            created = True
    complete = all(
        f"ratio:{ratio}" in assignment_map(artwork["artwork_code"])
        for ratio in ratios
    )
    if not complete:
        raise ValueError("Not all required ratio files could be generated")
    return "created" if created else "complete"


def regenerate_ratio_set(artwork):
    """Stage and atomically replace one artwork's complete required ratio set."""
    code = artwork["artwork_code"]
    production = get_artwork_production(code)
    assignments = assignment_map(code)
    master_path = resolve_assigned_file(artwork, assignments.get("print_master"))
    ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]
    if not ratios:
        raise ValueError("No required ratio set is configured")
    workspace = get_artwork_folder(artwork)
    output_folder = workspace / "02 Print Files"
    output_folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{code}-ratios-", dir=workspace
    ) as temporary:
        temporary_root = Path(temporary)
        staged_folder = temporary_root / "staged"
        backup_folder = temporary_root / "backup"
        staged_folder.mkdir()
        backup_folder.mkdir()
        results = [
            generate_ratio_output(
                artwork=artwork,
                source_path=master_path,
                ratio=ratio,
                mode="fit",
                overwrite=True,
                destination_folder=staged_folder,
            )
            for ratio in ratios
        ]
        failed = [result for result in results if result["status"] != "created"]
        if failed:
            detail = "; ".join(
                f"{item['ratio']}: {item.get('message') or 'failed'}"
                for item in failed
            )
            raise ValueError(f"Ratio replacement failed: {detail}")

        swaps = []
        database_rows = []
        try:
            for result in results:
                staged = staged_folder / result["stored_filename"]
                destination = output_folder / result["stored_filename"]
                backup = backup_folder / result["stored_filename"]
                existed = destination.is_file()
                if existed:
                    os.replace(destination, backup)
                os.replace(staged, destination)
                swaps.append((destination, backup, existed))
                database_rows.append({
                    "role": f"ratio:{result['ratio']}",
                    "relative_path": str(destination.relative_to(workspace)),
                    "stored_filename": destination.name,
                    "original_filename": destination.name,
                })
            replace_artwork_ratio_assignments(code, database_rows)
        except Exception:
            for destination, backup, existed in reversed(swaps):
                if destination.exists():
                    destination.unlink()
                if existed and backup.exists():
                    os.replace(backup, destination)
            raise
    set_artwork_production_flags(code, ratio_exports_ready=False)
    return ratios


def _mockup_payload(artwork):
    payload = dict(artwork)
    _, collection_artworks, _ = get_collection(artwork["collection_code"])
    paths, titles = [], []
    for item in collection_artworks:
        sibling = get_artwork(item["artwork_code"])
        source = assignment_map(item["artwork_code"]).get("source")
        if not source:
            continue
        try:
            paths.append(resolve_assigned_file(sibling, source))
            titles.append(item["public_title"])
        except ValueError:
            continue
    payload["collection_thumbnail_paths"] = paths
    payload["collection_thumbnail_titles"] = titles
    return payload


def ensure_mockups(artwork, *, force=False):
    assignments = assignment_map(artwork["artwork_code"])
    missing = list(GENERATED_SLOTS) if force else [
        slot for slot in GENERATED_SLOTS
        if f"mockup:{slot}" not in assignments
    ]
    if not missing:
        if get_artwork_mockup_set_state(artwork["artwork_code"]) is None:
            default_set = next(
                (row for row in list_mockup_sets() if row["name"] == "Etsy Standard"),
                None,
            )
            if default_set:
                record_artwork_mockup_set_generated(
                    artwork["artwork_code"], default_set["id"]
                )
        return "complete"
    source = assignments.get("print_master") or assignments.get("source")
    source_path = resolve_assigned_file(artwork, source)
    workspace = get_artwork_folder(artwork)
    default_set = next(
        (row for row in list_mockup_sets() if row["name"] == "Etsy Standard"),
        None,
    )
    set_items = {}
    if default_set:
        _, items = get_mockup_set(default_set["id"])
        set_items = {item["slot_key"]: item for item in items}
    selections = {}
    production = get_artwork_production(artwork["artwork_code"])
    orientation = production["orientation"] if production else None
    for slot in missing:
        item = set_items.get(slot)
        scene = None
        room_type = MOCKUP_SCENE_ROOM_TYPES.get(slot)
        if room_type and orientation:
            scene = next(
                (
                    candidate
                    for candidate in list_mockup_scenes(orientation=orientation)
                    if candidate["room_type"] == room_type
                    and candidate["name"].startswith("Shangooli Default · ")
                ),
                None,
            )
        if scene is None and item and item["source_kind"] == "scene" and item["scene_id"]:
            candidate = get_mockup_scene(item["scene_id"])
            if candidate and candidate["active"] and (
                not orientation or candidate["orientation"] in (orientation, "any")
            ):
                scene = candidate
        if scene and scene["active"]:
            result = generate_scene_mockup(
                artwork=_mockup_payload(artwork),
                source_path=source_path,
                scene_path=MOCKUP_SCENES_DIR / scene["image_path"],
                scene=dict(scene),
                output_folder=workspace / "03 Mockups",
                slot_key=slot,
            )
            selections[slot] = f"scene:{scene['id']}"
        else:
            template_slot = (
                item["template_slot"] if item and item["template_slot"] else slot
            )
            result = generate_listing_image(
                slot_key=template_slot,
                artwork=_mockup_payload(artwork),
                source_path=source_path,
                output_folder=workspace / "03 Mockups",
                template_key=(
                    default_set["template_key"]
                    if default_set else DEFAULT_TEMPLATE_PACK
                ),
                output_slot_key=slot,
            )
            selections[slot] = (
                f"template:{template_slot}"
                if default_set else DEFAULT_TEMPLATE_PACK
            )
        upsert_artwork_file(
            artwork_code=artwork["artwork_code"],
            role=result["role"],
            relative_path=str(result["path"].relative_to(workspace)),
            stored_filename=result["stored_filename"],
            original_filename=result["original_filename"],
        )
    save_artwork_mockup_templates(
        artwork["artwork_code"],
        selections,
    )
    if default_set:
        record_artwork_mockup_set_generated(
            artwork["artwork_code"], default_set["id"]
        )
    return "created"
