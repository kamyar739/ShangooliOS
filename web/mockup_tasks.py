"""Shared, state-aware mockup operations."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.database import get_artwork_folder
from web.db import (
    get_artwork,
    get_artwork_file_assignments,
    get_artwork_mockup_templates,
    get_collection,
    get_collection_branding_revision,
    invalidate_artwork_mockup_set_approval,
    set_artwork_production_flags,
    upsert_artwork_file,
)
from web.mockup_generator import generate_listing_image
from web.ratio_generator import resolve_assigned_file
from web.template_packs import DEFAULT_TEMPLATE_PACK


# Creative presentation order can differ from permanent artwork numbering.
# Keep this limited to collection cards; collection navigation remains unchanged.
COLLECTION_BRANDING_ORDERS = {
    "ROS": ("ROS-001", "ROS-002", "ROS-003", "ROS-007", "ROS-004", "ROS-005"),
}


def build_mockup_artwork_payload(artwork) -> dict:
    """Add current collection thumbnails to an artwork mockup payload."""
    payload = dict(artwork)
    _, collection_artworks, _ = get_collection(artwork["collection_code"])
    branding_order = COLLECTION_BRANDING_ORDERS.get(
        artwork["collection_code"].upper(), ()
    )
    if branding_order:
        position = {code: index for index, code in enumerate(branding_order)}
        collection_artworks = sorted(
            collection_artworks,
            key=lambda item: (
                position.get(item["artwork_code"], len(position)),
                item["sequence_number"],
            ),
        )
    thumbnail_paths = []
    thumbnail_titles = []
    for item in collection_artworks:
        # Collection identity cards represent the current sellable series.
        # A paused artwork may remain in ShangooliOS for history and recovery,
        # but must not displace its active replacement in the six-piece card.
        if item["status"] == "paused" or item["etsy_paused"]:
            continue
        item_artwork = get_artwork(item["artwork_code"])
        assignments = {
            row["role"]: row
            for row in get_artwork_file_assignments(item["artwork_code"])
        }
        if assignments.get("source"):
            try:
                thumbnail_paths.append(
                    resolve_assigned_file(item_artwork, assignments["source"])
                )
                thumbnail_titles.append(item["public_title"])
            except ValueError:
                pass
    payload["collection_thumbnail_paths"] = thumbnail_paths
    payload["collection_thumbnail_titles"] = thumbnail_titles
    return payload


def collection_branding_is_stale(collection_code: str, artwork_code: str) -> bool:
    """Report whether an artwork's shared collection card predates its collection."""
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork_code)
    }
    card = assignments.get("mockup:collection")
    revision = get_collection_branding_revision(collection_code)
    return bool(
        card is None
        or (
            revision
            and card["updated_at"]
            and card["updated_at"] < revision
        )
    )


def regenerate_collection_branding_card(artwork_code: str) -> dict:
    """Replace only one collection-branding card after generation succeeds."""
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise ValueError("Artwork not found")
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise ValueError("Upload an artwork file before refreshing its collection card")

    source_path = resolve_assigned_file(artwork, source_assignment)
    workspace = get_artwork_folder(artwork)
    output_folder = workspace / "03 Mockups"
    output_folder.mkdir(parents=True, exist_ok=True)
    templates = {
        row["slot_key"]: row["template_key"]
        for row in get_artwork_mockup_templates(artwork_code)
    }
    template_key = templates.get("collection", DEFAULT_TEMPLATE_PACK)
    previous = assignments.get("mockup:collection")
    try:
        previous_path = (
            resolve_assigned_file(artwork, previous) if previous else None
        )
    except (FileNotFoundError, ValueError):
        previous_path = None

    with tempfile.TemporaryDirectory(
        prefix=".collection-card-", dir=output_folder
    ) as temporary:
        temporary_folder = Path(temporary)
        generated = generate_listing_image(
            slot_key="collection",
            artwork=build_mockup_artwork_payload(artwork),
            source_path=source_path,
            output_folder=temporary_folder,
            template_key=template_key,
        )
        generated_path = generated["path"]
        destination = output_folder / generated["stored_filename"]
        backup = temporary_folder / "previous-card"
        destination_existed = destination.is_file()
        if destination_existed:
            shutil.copy2(destination, backup)
        try:
            generated_path.replace(destination)
            upsert_artwork_file(
                artwork_code=artwork_code,
                role="mockup:collection",
                relative_path=str(destination.relative_to(workspace)),
                stored_filename=destination.name,
                original_filename=destination.name,
            )
        except Exception:
            if backup.is_file():
                shutil.copy2(backup, destination)
            elif not destination_existed and destination.is_file():
                destination.unlink()
            raise

    set_artwork_production_flags(artwork_code, mockups_ready=False)
    invalidate_artwork_mockup_set_approval(artwork_code)
    return {
        "artwork_code": artwork_code.upper(),
        "relative_path": str(destination.relative_to(workspace)),
    }
