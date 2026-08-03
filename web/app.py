from pathlib import Path
import re
import secrets
import shutil
import sqlite3
from urllib.parse import urlencode

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette import status
from PIL import Image, UnidentifiedImageError

from app.database import (
    create_artwork as create_artwork_with_workspace,
    get_artwork_folder,
)
from web.db import (
    archive_artwork,
    archive_collection,
    clear_inactive_etsy_link,
    create_collection,
    create_listing,
    create_mockup_scene,
    create_mockup_set,
    add_mockup_set_item,
    duplicate_listing,
    delete_listing,
    disable_mockup_scene,
    get_artwork,
    get_artwork_file_assignments,
    get_artwork_certification,
    get_print_master_certification,	
    get_artwork_mockup_order,
    get_artwork_mockup_templates,
    get_artwork_intelligence,
    get_artwork_listing_content,
    get_artwork_production,
    get_collection,
    get_collections,
    get_dashboard,
    get_listing,
    get_listing_readiness,
    get_listing_status_counts,
    get_standalone_design,
    get_artwork_listings,
    get_mockup_scene,
    get_mockup_set,
    get_artwork_mockup_set_state,
    invalidate_artwork_after_source_change,
    invalidate_artwork_mockup_set_approval,
    restore_artwork,
    remove_mockup_set_item,
    list_listings,
    list_standalone_designs,
    list_standalone_design_products,
    list_standalone_product_summaries,
    prepare_standalone_product_asset,
    list_mockup_scenes,
    list_mockup_sets,
    link_etsy_listing,
    mark_etsy_synced,
    mark_standalone_etsy_synced,
    record_etsy_state,
    record_etsy_inventory_quantity,
    record_etsy_paused,
    record_standalone_marketplace_status,
    record_ai_enhancement,
    record_artwork_mockup_set_generated,
    record_publishing_recovery,
    publish_listing,
    save_printify_product,
    mark_printify_etsy_connected,
    mark_printify_publish_requested,
    save_artwork_mockup_order,
    save_artwork_mockup_template,
    save_artwork_mockup_templates,
    save_collection_order,
    set_collection_cover,
    approve_collection_cover,
    search_artworks,
    set_artwork_production_flags,
    set_standalone_design_archived,
    create_standalone_design,
    replace_standalone_design_source,
    update_standalone_product_copy,
    update_standalone_design,
    update_artwork,
    update_artwork_details,
    update_artwork_status,
    update_artwork_intelligence,
    update_artwork_listing_content,
    update_artwork_production,
    update_collection,
    update_listing,
    update_mockup_scene_placement,
    update_mockup_scene_background,
    update_mockup_set,
    approve_artwork_mockup_set,
    upsert_artwork_file,
    upsert_artwork_certification,
    upsert_print_master_certification,
)
from web.etsy_api import (
    EtsyAPIError,
    begin_etsy_oauth,
    clear_etsy_config,
    complete_etsy_oauth,
    etsy_config,
    get_etsy_listing,
    update_etsy_listing,
    update_etsy_listing_state,
)
from web.etsy_validation import parse_tags, validate_etsy_listing
from web.etsy_sync import (
    build_etsy_sync_preview,
    find_etsy_candidates,
    set_etsy_inventory_quantity,
    sync_etsy_listing,
    sync_etsy_listing_images,
)
from web.file_intake import save_uploaded_file
from web.fast_flow import import_fast_flow_collection
from web.workflow_navigation import collection_workflow_navigation
from web.collection_production import (
    STATE_LABELS,
    collection_production_overview,
    run_collection_production,
)
from web.collection_review import (
    approve_artwork_for_collection,
    approve_many,
    collection_review_overview,
    refresh_selected_collection_cards,
    regenerate_selected_ratio_sets,
    send_artwork_back,
)
from web.publish_readiness import (
    collection_publish_readiness,
    prepare_missing_collection_drafts,
)
from web.collection_printify import (
    automatic_printify_profile,
    collection_printify_overview,
    create_automatic_printify_draft,
    create_selected_printify_drafts,
    printify_file_options,
)
from web.collection_publish import (
    collection_publication_overview,
    collection_recovery_overview,
    publish_selected_listings,
    recover_selected_listings,
)
from web.collection_replacement import (
    replacement_restart_overview,
    restart_collection_with_replacement_sources,
)
from web.listing_publication import (
    recover_listing_publication,
    request_listing_publication,
)
from web.standalone_designs import (
    analyze_design_image,
    design_metadata_from_message,
    MUG_PROFILE,
    check_design_marketplace_status,
    create_mug_draft,
    design_opposite_source_path,
    design_source_path,
    product_asset_path,
    removable_background_preview,
    render_quick_text_design,
    save_design_source,
    save_mug_setup,
    suggested_mug_description,
    suggested_mug_title,
    update_mug_draft_copy,
    update_mug_draft_graphics,
    mug_profile,
)
from web.product_blueprints import (
    DEFAULT_MUG_BLUEPRINT_KEY,
    PRODUCT_BLUEPRINTS,
    get_product_blueprint,
    mug_blueprints,
    normalized_placement_geometry,
    product_readiness,
)
from web.pinterest_bundle import (
    pinterest_bundle_copy,
    pinterest_download_name,
    render_pinterest_bundle,
)
from web.artwork_intelligence import analyze_artwork
from web.artwork_certifier import certify_artwork
from web.ai_upscaler import candidate_path, original_backup_path, upscale_candidate
from web.listing_writer import generate_listing_content
from web.prompt_composer import compose_artwork_prompt
from web.mockup_generator import (
    GENERATED_SLOTS,
    generate_listing_image,
    generate_mockups,
    generate_scene_mockup,
)
from web.mockup_tasks import build_mockup_artwork_payload
from web.marketplace_export import build_listing_export, inspect_listing_export
from web.printify import validate_printify_product
from web.printify_handoff import build_printify_handoff, inspect_printify_handoff
from web.printify_api import (
    PrintifyAPI,
    PrintifyAPIError,
    PrintifyPublishPending,
    clear_printify_local_config,
    clear_printify_runtime,
    complete_printify_runtime,
    configure_printify_runtime,
    configure_printify_token_runtime,
    create_printify_product,
    poster_blueprints,
    printify_configuration_source,
    ratio_role_for_variant,
    save_printify_local_config,
    variant_orientation,
    update_printify_product_artwork,
    wait_for_product_unlock,
)
from web.template_packs import DEFAULT_TEMPLATE_PACK, template_pack_options
from web.print_master import build_print_master, load_print_master_manifest
from web.production import (
    build_production_summary,
    list_workspace_files,
)
from web.production_tasks import QUALITY_THRESHOLD, ensure_mockups
from web.ratio_profiles import get_ratio_profile
from web.ratio_generator import (
    generate_ratio_output,
    resolve_assigned_file,
)
from web.workspace import (
    inspect_workspace,
    open_workspace,
    refresh_workspace,
)

BASE_DIR = Path(__file__).resolve().parent
MOCKUP_SCENES_DIR = BASE_DIR.parent / "data" / "mockup_scenes"

app = FastAPI(title="ShangooliOS")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _price_to_cents(price: str) -> int:
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    try:
        value = Decimal(price.strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, AttributeError):
        raise HTTPException(status_code=400, detail="Enter a valid price")
    if value < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    return int(value * 100)


def _certified_orientation(artwork_code: str) -> str | None:
    master = get_print_master_certification(artwork_code)
    if master and master["valid"] and master["orientation"]:
        return master["orientation"]
    source = get_artwork_certification(artwork_code)
    if source and source["valid"] and source["orientation"]:
        return source["orientation"]
    return None


def _generate_required_ratios(artwork, *, overwrite: bool) -> list[dict]:
    """Generate every configured ratio from the assigned print master."""
    artwork_code = artwork["artwork_code"]
    production = get_artwork_production(artwork_code)
    assignments = get_artwork_file_assignments(artwork_code)
    assignment_map = {row["role"]: row for row in assignments}
    source_path = resolve_assigned_file(
        artwork,
        assignment_map.get("print_master"),
    )
    ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]

    results = []
    for ratio in ratios:
        result = generate_ratio_output(
            artwork=artwork,
            source_path=source_path,
            ratio=ratio,
            mode="fit",
            overwrite=overwrite,
        )
        results.append(result)
        if result["status"] in {"created", "skipped"}:
            upsert_artwork_file(
                artwork_code=artwork_code,
                role=f"ratio:{ratio}",
                relative_path=result["relative_path"],
                stored_filename=result["stored_filename"],
                original_filename=result["stored_filename"],
            )

    # A new master requires a fresh visual approval, even when generation succeeds.
    set_artwork_production_flags(
        artwork_code,
        ratio_exports_ready=False,
    )
    return results


AUTO_SCENE_GROUPS = {
    "room": "Living room",
    "bedroom": "Bedroom",
    "office": "Office",
}


def _scene_candidates_for_item(item, orientation):
    compatible = [dict(scene) for scene in list_mockup_scenes(orientation=orientation)]
    if item["source_kind"] == "scene" and item["scene_id"]:
        selected = get_mockup_scene(item["scene_id"])
        room_type = selected["room_type"] if selected else None
    else:
        room_type = AUTO_SCENE_GROUPS.get(item["template_slot"])
    if not room_type:
        return []
    return [scene for scene in compatible if scene["room_type"] == room_type]


def _mockup_sets_for_artwork(orientation):
    resolved = []
    for summary in list_mockup_sets():
        mockup_set, rows = get_mockup_set(summary["id"])
        items = []
        for row in rows:
            item = dict(row)
            candidates = _scene_candidates_for_item(item, orientation)
            selected_id = item["scene_id"] if any(
                scene["id"] == item["scene_id"] for scene in candidates
            ) else (candidates[0]["id"] if candidates else None)
            item["scene_candidates"] = candidates
            item["selected_scene_id"] = selected_id
            item["selected_scene_name"] = next(
                (scene["name"] for scene in candidates if scene["id"] == selected_id), None
            )
            item["uses_scene"] = selected_id is not None
            items.append(item)
        resolved.append({**dict(mockup_set), "items": items})
    return resolved


def _mockup_artwork_payload(artwork) -> dict:
    return build_mockup_artwork_payload(artwork)


def _listing_external_change_state(listing, assignments, mockup_set_state):
    if not listing or not listing["external_listing_id"]:
        return {"source": False, "etsy_images": False}
    synced_at = listing["etsy_last_synced_at"]
    source = next(
        (item for item in assignments if item["role"] == "source"), None
    )
    source_changed = bool(
        source
        and source["updated_at"]
        and (not synced_at or source["updated_at"] > synced_at)
    )
    latest_mockup_at = max(
        (
            item["updated_at"] for item in assignments
            if item["role"].startswith("mockup:") and item["updated_at"]
        ),
        default=None,
    )
    approved_at = (
        mockup_set_state["approved_at"] if mockup_set_state else None
    )
    etsy_images_changed = bool(
        approved_at
        and (
            not synced_at
            or approved_at > synced_at
            or (latest_mockup_at and latest_mockup_at > synced_at)
        )
    )
    return {"source": source_changed, "etsy_images": etsy_images_changed}


def _artwork_context(artwork_code: str, active_stage="details", **extra):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    production = get_artwork_production(artwork_code)
    files = list_workspace_files(artwork)
    assignments = get_artwork_file_assignments(artwork_code)

    production_summary = build_production_summary(
        artwork,
        production,
        files,
        assignments,
    )

    saved_order = {
        row["slot_key"]: row["position"]
        for row in get_artwork_mockup_order(artwork_code)
    }
    saved_templates = {
        row["slot_key"]: row["template_key"]
        for row in get_artwork_mockup_templates(artwork_code)
    }
    for item in production_summary["mockup_status"]:
        item["position"] = saved_order.get(
            item["slot_key"], item["default_position"]
        )
        item["template_key"] = saved_templates.get(
            item["slot_key"], DEFAULT_TEMPLATE_PACK
        )
    production_summary["mockup_status"].sort(
        key=lambda item: item["position"]
    )
    for item in production_summary["mockup_status"]:
        if item["slot_key"] in AUTO_SCENE_GROUPS:
            scene_item = {
                "source_kind": "template", "scene_id": None,
                "template_slot": item["slot_key"],
            }
            candidates = _scene_candidates_for_item(
                scene_item, production["orientation"] if production else "any"
            )
            item["scene_candidates"] = candidates
            item["selected_scene_id"] = candidates[0]["id"] if candidates else None

    mockup_set_state = get_artwork_mockup_set_state(artwork_code)
    artwork_listings = [dict(item) for item in get_artwork_listings(artwork_code)]
    for item in artwork_listings:
        changes = _listing_external_change_state(
            item, assignments, mockup_set_state
        )
        item["source_update_required"] = changes["source"]
        item["etsy_images_need_sync"] = changes["etsy_images"]
    linked_sync_times = [
        str(item["etsy_last_synced_at"])
        for item in artwork_listings
        if item["external_listing_id"] and item["etsy_last_synced_at"]
    ]
    latest_etsy_sync = max(linked_sync_times, default=None)
    changed_mockup_count = sum(
        1
        for assignment in assignments
        if assignment["role"].startswith("mockup:")
        and assignment["updated_at"]
        and (
            latest_etsy_sync is None
            or str(assignment["updated_at"]) > latest_etsy_sync
        )
    ) if any(item["external_listing_id"] for item in artwork_listings) else 0
    artwork_intelligence = get_artwork_intelligence(artwork_code)
    collection, collection_artworks, _ = get_collection(artwork["collection_code"])
    artwork_position = next(
        (index for index, item in enumerate(collection_artworks)
         if item["artwork_code"] == artwork["artwork_code"]),
        None,
    )
    previous_artwork = (
        collection_artworks[artwork_position - 1]
        if artwork_position is not None and artwork_position > 0 else None
    )
    next_artwork = (
        collection_artworks[artwork_position + 1]
        if artwork_position is not None and artwork_position + 1 < len(collection_artworks)
        else None
    )
    image_artworks = [
        item for item in collection_artworks if item["has_source_image"]
    ]
    image_artwork_position = next(
        (
            index
            for index, item in enumerate(image_artworks)
            if item["artwork_code"] == artwork["artwork_code"]
        ),
        None,
    )
    previous_image_artwork = (
        image_artworks[image_artwork_position - 1]
        if image_artwork_position is not None and image_artwork_position > 0
        else None
    )
    next_image_artwork = (
        image_artworks[image_artwork_position + 1]
        if (
            image_artwork_position is not None
            and image_artwork_position + 1 < len(image_artworks)
        )
        else None
    )
    auto_update_listing = next((
        item for item in artwork_listings
        if item["status"] == "published"
        and item["printify_product_id"] and item["external_listing_id"]
    ), None)
    printify_profile = _printify_profile_for_orientation(
        production["orientation"] if production else "",
        artwork["collection_code"],
    )
    ai_candidate_certification = None
    ai_candidate = candidate_path(artwork)
    if not production["ai_enhanced_at"] and ai_candidate.is_file():
        try:
            ai_candidate_certification = certify_artwork(ai_candidate).to_dict()
        except (OSError, ValueError):
            ai_candidate_certification = {
                "valid": False,
                "score": 0,
                "status": "Invalid candidate",
                "width": 0,
                "height": 0,
                "orientation": "unknown",
                "warnings": ["The generated candidate could not be validated."],
            }
    context = {
        "artwork": artwork,
        "collection": collection,
        "workspace": inspect_workspace(artwork),
        "production": production,
        "workspace_files": files,
        "file_assignments": assignments,
        "production_summary": production_summary,
        "workflow": production_summary["workflow"],
        "artwork_intelligence": artwork_intelligence,
        "final_generation_prompt": compose_artwork_prompt(
            collection["prompt"], artwork["prompt"]
        ),
        "listing_content": get_artwork_listing_content(artwork_code),
        "listings": artwork_listings,
        "certification": get_artwork_certification(artwork_code),
        "print_master_certification": get_print_master_certification(artwork_code),
        "certified_orientation": _certified_orientation(artwork_code),
        "template_packs": template_pack_options(),
        "mockup_scenes": list_mockup_scenes(
            orientation=production["orientation"] if production else None
        ),
        "mockup_sets": _mockup_sets_for_artwork(
            production["orientation"] if production else "any"
        ),
        "mockup_set_state": mockup_set_state,
        "changed_mockup_count": changed_mockup_count,
        "default_template_pack": DEFAULT_TEMPLATE_PACK,
        "saved_template_packs": saved_templates,
        "print_master_manifest": load_print_master_manifest(artwork),
        # A second click can finish after the approved 4× source is saved.
        # It is only a stale temporary candidate, never a new review state.
        "ai_upscale_candidate": bool(
            not production["ai_enhanced_at"] and candidate_path(artwork).is_file()
        ),
        "ai_candidate_certification": ai_candidate_certification,
        "ai_original_backup": original_backup_path(artwork).is_file(),
        "auto_update_listing": auto_update_listing,
        "printify_profile": printify_profile,
        "previous_artwork": previous_artwork,
        "next_artwork": next_artwork,
        "previous_image_artwork": previous_image_artwork,
        "next_image_artwork": next_image_artwork,
        "workflow_nav": _workflow_navigation(
            artwork,
            production=production,
            assignments=assignments,
            listings=artwork_listings,
            active_stage=active_stage,
        ),
    }
    context.update(extra)
    return context


def _workflow_navigation(
    artwork,
    *,
    production=None,
    assignments=None,
    listings=None,
    listing=None,
    active_stage="details",
):
    production = production or get_artwork_production(artwork["artwork_code"])
    assignments = assignments or get_artwork_file_assignments(artwork["artwork_code"])
    listings = list(listings or get_artwork_listings(artwork["artwork_code"]))
    listing = listing or (listings[0] if listings else None)
    roles = {row["role"] for row in assignments}
    _, collection_artworks, _ = get_collection(artwork["collection_code"])
    artwork_url = f"/artworks/{artwork['artwork_code']}"
    certification = get_artwork_certification(artwork["artwork_code"])
    intelligence = get_artwork_intelligence(artwork["artwork_code"])
    mockup_set_state = get_artwork_mockup_set_state(artwork["artwork_code"])
    mockup_set_approved = bool(
        mockup_set_state and mockup_set_state["approved_at"]
    )
    intelligence_complete = bool(
        intelligence
        and (
            intelligence["analyzed_at"]
            or intelligence["theme"]
            or intelligence["style"]
        )
    )
    has_source = "source" in roles
    has_print_files = "print_master" in roles or any(role.startswith("ratio:") for role in roles)
    required_ratio_roles = {
        f"ratio:{ratio.strip()}"
        for ratio in (production["required_ratios"] or "").split(",")
        if ratio.strip()
    }
    has_all_ratio_files = bool(required_ratio_roles) and required_ratio_roles.issubset(roles)
    has_mockups = any(role.startswith("mockup:") for role in roles)
    has_listing_work = bool(listing or get_artwork_listing_content(artwork["artwork_code"])["etsy_title"])
    print_complete = bool(production["print_master_ready"] and production["ratio_exports_ready"])
    all_current = bool(
        has_source and production["original_approved"] and print_complete
        and production["mockups_ready"] and mockup_set_approved
        and production["listing_content_ready"]
    )
    live_listing = next(
        (item for item in listings if item["status"] == "published" and item["external_listing_id"]),
        None,
    )
    external_changes = _listing_external_change_state(
        live_listing, assignments, mockup_set_state
    )
    external_update_required = external_changes["source"]
    etsy_image_update_required = external_changes["etsy_images"]

    def stage(key, label, state, complete=False):
        labels = {
            "not_started": "Not started", "in_progress": "In progress",
            "needs_review": "Needs review", "out_of_date": "Out of date",
            "complete": "Complete", "published": "Published",
            "unpublished_changes": "Unpublished changes",
        }
        return {
            "key": key, "label": label, "href": f"{artwork_url}?step={key}",
            "state": state, "state_label": labels[state], "complete": complete,
        }

    stages = [
        stage("details", "Details", "complete" if artwork["public_title"] else "in_progress", bool(artwork["public_title"])),
        stage("source", "Source", "complete" if has_source else "not_started", has_source),
        stage(
            "certification", "Quality",
            "complete" if certification and production["original_approved"]
            else "needs_review" if certification or has_source else "not_started",
            bool(certification and production["original_approved"]),
        ),
        stage(
            "intelligence", "Intelligence",
            "complete" if intelligence_complete
            else "needs_review" if has_source else "not_started",
            intelligence_complete,
        ),
        stage(
            "print", "Print files",
            "complete" if print_complete
            else "out_of_date" if has_print_files and not production["print_master_ready"]
            else "needs_review" if has_all_ratio_files
            else "in_progress" if has_print_files
            else "not_started",
            print_complete,
        ),
        stage(
            "mockups", "Mockups",
            "complete" if production["mockups_ready"] and mockup_set_approved
            else "needs_review" if has_mockups
            else "not_started",
            bool(production["mockups_ready"] and mockup_set_approved),
        ),
        stage(
            "story", "Story & SEO",
            "complete" if production["listing_content_ready"] else "out_of_date" if has_listing_work else "not_started",
            bool(production["listing_content_ready"]),
        ),
        stage(
            "listing", "Listing",
            "unpublished_changes" if external_update_required
            else "complete" if listing else "not_started",
            bool(listing and not external_update_required),
        ),
        stage(
            "printify", "Printify",
            "unpublished_changes" if external_update_required
            else "complete" if listing and listing["printify_product_id"]
            else "in_progress" if listing
            else "not_started",
            bool(listing and listing["printify_product_id"] and not external_update_required),
        ),
        stage(
            "publish", "Publish",
            "published" if (
                live_listing and all_current and live_listing["etsy_last_synced_at"]
                and not external_update_required and not etsy_image_update_required
            )
            else "unpublished_changes" if (
                live_listing
                and (external_update_required or etsy_image_update_required or not all_current)
            )
            else "in_progress" if listing and listing["printify_product_id"]
            else "not_started",
            bool(
                live_listing and all_current and live_listing["etsy_last_synced_at"]
                and not external_update_required and not etsy_image_update_required
            ),
        ),
    ]
    normalized_active = {"etsy": "publish"}.get(active_stage, active_stage)
    return {
        "collection": {"code": artwork["collection_code"], "name": artwork["collection_name"]},
        "artwork": {"code": artwork["artwork_code"], "title": artwork["public_title"]},
        "collection_artworks": collection_artworks,
        "stages": stages,
        "active_stage": normalized_active,
    }


@app.get("/")
def home(request: Request, dashboard_view: str = Query("artworks", alias="view")):
    normalized_view = dashboard_view.strip().lower()
    if normalized_view not in ("", "artworks", "listings", "ready", "attention"):
        raise HTTPException(status_code=400, detail="Invalid dashboard view")
    context = get_dashboard()
    context["dashboard_view"] = normalized_view
    collections_by_code = {
        collection["code"]: collection
        for collection in context["collections"]
    }
    context["continue_collection"] = None
    for collection_code in context["recent_collection_codes"]:
        collection = collections_by_code.get(collection_code)
        if (
            not collection
            or collection["status"] == "paused"
            or not collection["artwork_count"]
        ):
            continue
        navigation = collection_workflow_navigation(
            collection_code, active_stage=""
        )
        if not navigation["complete"]:
            context["continue_collection"] = navigation
            break
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )


@app.get("/designs")
def standalone_designs_page(
    request: Request,
    search: str = Query(""),
    tag: str = Query(""),
    design_status: str = Query("all", alias="status"),
    product_key: str = Query("all", alias="product"),
    page: int = Query(1, ge=1),
):
    show_archived = request.query_params.get("show") == "archived"
    normalized_search = search.strip()
    normalized_tag = tag.strip()
    normalized_status = design_status.strip().lower() or "all"
    normalized_product = product_key.strip() or "all"
    if normalized_status not in {
        "all", "draft", "printify", "etsy", "etsy_sync", "paused"
    }:
        raise HTTPException(status_code=400, detail="Invalid design status")
    blueprint_options = mug_blueprints()
    valid_products = {item["key"] for item in blueprint_options}
    if normalized_product not in {"all", "none", *valid_products}:
        raise HTTPException(status_code=400, detail="Invalid product type")
    designs = [
        dict(item)
        for item in list_standalone_designs()
        if (item["status"] == "archived") == show_archived
    ]
    products_by_design = {}
    for row in list_standalone_product_summaries():
        products_by_design.setdefault(row["design_id"], {})[
            row["product_type"]
        ] = dict(row)
    blueprint_labels = {
        item["key"]: item["label"] for item in blueprint_options
    }
    for item in designs:
        item["tag_list"] = parse_tags(item.get("tags") or "")
        item["products"] = []
        for saved_key, product in products_by_design.get(item["id"], {}).items():
            needs_etsy_sync = bool(
                product["etsy_listing_id"]
                and str(product["etsy_state"] or "").lower() == "active"
                and not product["etsy_paused_at"]
                and not product["etsy_last_synced_at"]
            )
            if product["etsy_paused_at"]:
                state_label = "Paused"
            elif needs_etsy_sync:
                state_label = "Needs Etsy Sync"
            elif str(product["etsy_state"] or "").lower() == "active":
                state_label = "Live"
            elif product["printify_product_id"]:
                state_label = "Printify"
            else:
                state_label = "Prepared"
            item["products"].append(
                {
                    **product,
                    "key": saved_key,
                    "label": blueprint_labels.get(saved_key, saved_key),
                    "state_label": state_label,
                    "needs_etsy_sync": needs_etsy_sync,
                }
            )
    available_tags = sorted(
        {
            saved_tag
            for item in designs
            for saved_tag in item["tag_list"]
        },
        key=str.casefold,
    )
    if normalized_search:
        search_key = normalized_search.casefold()
        designs = [
            item
            for item in designs
            if search_key
            in " ".join(
                str(item.get(field) or "")
                for field in (
                    "name",
                    "message",
                    "description",
                    "tags",
                    "product_title",
                    "product_description",
                )
            ).casefold()
            or search_key
            in " ".join(
                str(product.get(field) or "")
                for product in item["products"]
                for field in ("label", "title", "description")
            ).casefold()
        ]
    if normalized_tag:
        tag_key = normalized_tag.casefold()
        designs = [
            item
            for item in designs
            if tag_key in {
                saved_tag.casefold() for saved_tag in item["tag_list"]
            }
        ]
    if normalized_product == "none":
        designs = [item for item in designs if not item["products"]]
    elif normalized_product != "all":
        designs = [
            item
            for item in designs
            if any(
                product["key"] == normalized_product
                for product in item["products"]
            )
        ]

    def status_products(item):
        if normalized_product in valid_products:
            return [
                product
                for product in item["products"]
                if product["key"] == normalized_product
            ]
        return item["products"]

    if normalized_status == "draft":
        designs = [
            item
            for item in designs
            if not status_products(item)
            or all(
                not product["printify_product_id"]
                for product in status_products(item)
            )
        ]
    elif normalized_status == "printify":
        designs = [
            item for item in designs
            if any(
                product["printify_product_id"]
                and not product["etsy_listing_id"]
                for product in status_products(item)
            )
        ]
    elif normalized_status == "etsy":
        designs = [
            item for item in designs
            if any(
                str(product["etsy_state"] or "").lower() == "active"
                and not product["etsy_paused_at"]
                for product in status_products(item)
            )
        ]
    elif normalized_status == "etsy_sync":
        designs = [
            item for item in designs
            if any(
                product["needs_etsy_sync"]
                for product in status_products(item)
            )
        ]
    elif normalized_status == "paused":
        designs = [
            item for item in designs
            if any(
                product["etsy_paused_at"]
                for product in status_products(item)
            )
        ]
    for item in designs:
        item["display_products"] = (
            [
                product
                for product in item["products"]
                if product["key"] == normalized_product
            ]
            if normalized_product in valid_products
            else item["products"]
        )
        if item["status"] == "archived":
            item["catalog_state"] = "Archived"
            item["catalog_state_class"] = "listing-status-archived"
        elif any(
            product["needs_etsy_sync"]
            for product in item["display_products"]
        ):
            item["catalog_state"] = "Needs Etsy Sync"
            item["catalog_state_class"] = "listing-status-ready"
        elif any(
            product["etsy_paused_at"]
            for product in item["display_products"]
        ):
            item["catalog_state"] = "Paused on Etsy"
            item["catalog_state_class"] = "listing-status-ready"
        elif any(
            str(product["etsy_state"] or "").lower() == "active"
            for product in item["display_products"]
        ):
            item["catalog_state"] = "Live on Etsy"
            item["catalog_state_class"] = "listing-status-published"
        elif any(
            product["printify_product_id"]
            for product in item["display_products"]
        ):
            item["catalog_state"] = "On Printify"
            item["catalog_state_class"] = "listing-status-published"
        else:
            item["catalog_state"] = "Draft"
            item["catalog_state_class"] = "listing-status-draft"
    page_size = 24
    total_designs = len(designs)
    total_pages = max(1, (total_designs + page_size - 1) // page_size)
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    designs = designs[offset : offset + page_size]
    query_values = {
        "search": normalized_search,
        "tag": normalized_tag,
        "status": normalized_status,
        "product": normalized_product,
    }
    if show_archived:
        query_values["show"] = "archived"
    query_values = {key: value for key, value in query_values.items() if value}
    previous_url = (
        f"/designs?{urlencode({**query_values, 'page': page - 1})}"
        if page > 1
        else None
    )
    next_url = (
        f"/designs?{urlencode({**query_values, 'page': page + 1})}"
        if page < total_pages
        else None
    )
    return templates.TemplateResponse(
        request=request,
        name="designs.html",
        context={
            "designs": designs,
            "show_archived": show_archived,
            "active_search": normalized_search,
            "active_tag": normalized_tag,
            "active_design_status": normalized_status,
            "active_product_key": normalized_product,
            "product_options": blueprint_options,
            "available_tags": available_tags,
            "total_designs": total_designs,
            "page": page,
            "total_pages": total_pages,
            "previous_url": previous_url,
            "next_url": next_url,
            "dashboard_sidebar_active": "designs",
        },
    )


@app.get("/designs/new")
def new_standalone_design_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="design_form.html",
        context={
            "design": None,
            "dashboard_sidebar_active": "designs",
        },
    )


@app.get("/designs/quick-text")
def quick_text_design_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="design_quick_text.html",
        context={"dashboard_sidebar_active": "designs"},
    )


@app.post("/designs/quick-text")
def create_quick_text_design_post(message: str = Form(...)):
    saved = None
    try:
        normalized_message = "\n".join(
            " ".join(line.split()) for line in message.splitlines()
            if line.strip()
        ).strip()
        image = render_quick_text_design(normalized_message)
        saved = save_design_source(image, "shangooli-quick-text.png")
        generated = design_metadata_from_message(normalized_message)
        design_id = create_standalone_design(
            name=generated["name"],
            message=" ".join(normalized_message.split()),
            description=generated["description"],
            tags=generated["tags"],
            source_filename=saved["filename"],
            source_original_filename=saved["original_filename"],
            image_width=saved["width"],
            image_height=saved["height"],
        )
    except ValueError as error:
        if saved:
            (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "designs"
                / saved["filename"]
            ).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/designs/{design_id}?created=1", status_code=303
    )


@app.post("/designs/analyze-upload")
async def analyze_standalone_design_upload(image: UploadFile = File(...)):
    try:
        result = analyze_design_image(await image.read(), image.filename or "")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return JSONResponse(result)


@app.post("/designs/message-metadata")
def standalone_design_message_metadata(message: str = Form(...)):
    return JSONResponse(design_metadata_from_message(message))


@app.post("/designs")
async def create_standalone_design_post(
    image: UploadFile = File(...),
    name: str = Form(...),
    message: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
):
    saved = None
    try:
        saved = save_design_source(await image.read(), image.filename or "")
        design_id = create_standalone_design(
            name=name,
            message=message,
            description=description,
            tags=tags,
            source_filename=saved["filename"],
            source_original_filename=saved["original_filename"],
            image_width=saved["width"],
            image_height=saved["height"],
        )
    except ValueError as error:
        if saved:
            (Path(__file__).resolve().parents[1] / "assets" / "designs" / saved["filename"]).unlink(
                missing_ok=True
            )
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/designs/{design_id}?created=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/designs/{design_id}")
def standalone_design_page(request: Request, design_id: int):
    design = get_standalone_design(design_id)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    saved_products = {
        item["product_type"]: item
        for item in list_standalone_design_products(design_id)
    }
    product_options = []
    for blueprint in mug_blueprints():
        product = saved_products.get(blueprint["key"])
        product_design = get_standalone_design(design_id, blueprint["key"])
        readiness = product_readiness(
            product=product,
            source_exists=(
                product_asset_path(product_design) is not None
                if product is not None
                else design_source_path(design) is not None
            ),
            blueprint=blueprint,
        )
        product_options.append(
            {**blueprint, "product": product, "readiness": readiness}
        )
    return templates.TemplateResponse(
        request=request,
        name="design_detail.html",
        context={
            "design": design,
            "background_cleanup_available": bool(
                removable_background_preview(design)
            ),
            "product_options": product_options,
            "dashboard_sidebar_active": "designs",
        },
    )


@app.get("/designs/{design_id}/background-preview")
def standalone_design_background_preview(design_id: int):
    design = get_standalone_design(design_id)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    preview = removable_background_preview(design)
    if preview is None:
        raise HTTPException(
            status_code=400,
            detail="This design does not have a safely removable solid background",
        )
    return Response(
        content=preview,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/designs/{design_id}/remove-background")
def remove_standalone_design_background_post(
    design_id: int,
    confirmed: bool = Form(False),
):
    design = get_standalone_design(design_id)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    if not confirmed:
        raise HTTPException(
            status_code=400, detail="Confirm the transparent preview"
        )
    preview = removable_background_preview(design)
    if preview is None:
        raise HTTPException(
            status_code=400,
            detail="This design does not have a safely removable solid background",
        )
    saved = save_design_source(
        preview,
        f"{Path(design['source_original_filename'] or 'design').stem}-transparent.png",
    )
    replace_standalone_design_source(
        design_id,
        source_filename=saved["filename"],
        source_original_filename=saved["original_filename"],
        image_width=saved["width"],
        image_height=saved["height"],
    )
    return RedirectResponse(
        f"/designs/{design_id}?background_removed=1", status_code=303
    )


@app.post("/designs/{design_id}")
def update_standalone_design_post(
    design_id: int,
    name: str = Form(...),
    message: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
):
    try:
        update_standalone_design(
            design_id,
            name=name,
            message=message,
            description=description,
            tags=tags,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        f"/designs/{design_id}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/designs/{design_id}/archive")
def archive_standalone_design_post(
    design_id: int,
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm archiving this design")
    try:
        set_standalone_design_archived(design_id, True)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse("/designs?archived=1", status_code=303)


@app.post("/designs/{design_id}/restore")
def restore_standalone_design_post(design_id: int):
    try:
        set_standalone_design_archived(design_id, False)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        f"/designs/{design_id}?restored=1", status_code=303
    )


@app.post("/designs/{design_id}/marketplace/check")
def check_standalone_design_marketplace_post(
    design_id: int,
    etsy_listing: str = Form(""),
    product_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    result, error = _check_standalone_design_marketplace(
        design_id, etsy_listing, product_key
    )
    if error:
        return RedirectResponse(
            f"/designs/{design_id}?"
            + _standalone_product_query(product_key, marketplace_error=error)
            + f"#product-{product_key}",
            status_code=303,
        )
    outcome = "linked" if result["linked"] else "waiting"
    return RedirectResponse(
        f"/designs/{design_id}?"
        + _standalone_product_query(product_key, marketplace_status=outcome)
        + f"#product-{product_key}",
        status_code=303,
    )


def _check_standalone_design_marketplace(
    design_id: int,
    etsy_listing: str = "",
    product_key: str = DEFAULT_MUG_BLUEPRINT_KEY,
):
    try:
        supplied = (etsy_listing or "").strip()
        if supplied:
            match = re.search(r"(?:listing-editor/edit/|listing/)?(\d{6,})", supplied)
            if not match:
                raise ValueError("Paste a valid Etsy listing URL or listing ID")
            etsy_id = match.group(1)
            remote = get_etsy_listing(etsy_id)
            etsy_state = str(remote.get("state") or "").strip().lower()
            record_standalone_marketplace_status(
                design_id,
                etsy_listing_id=etsy_id,
                etsy_listing_url=f"https://www.etsy.com/listing/{etsy_id}",
                etsy_state=etsy_state,
                paused=etsy_state != "active",
                message=f"Etsy listing linked with status: {etsy_state or 'unknown'}.",
                product_key=product_key,
            )
            result = {"linked": True}
        else:
            result = (
                check_design_marketplace_status(design_id)
                if product_key == DEFAULT_MUG_BLUEPRINT_KEY
                else check_design_marketplace_status(
                    design_id, product_key=product_key
                )
            )
    except (EtsyAPIError, ValueError) as error:
        return None, str(error)
    return result, ""


def _standalone_product_query(product_key, **values):
    if product_key != DEFAULT_MUG_BLUEPRINT_KEY:
        values["product_key"] = product_key
    return urlencode(values)


@app.get("/designs/{design_id}/etsy/finish")
def standalone_design_finish_etsy_page(
    request: Request,
    design_id: int,
    product_key: str = Query(DEFAULT_MUG_BLUEPRINT_KEY),
):
    design = get_standalone_design(design_id, product_key)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    if not design["printify_product_id"]:
        raise HTTPException(
            status_code=400, detail="Create the Printify product first"
        )
    return templates.TemplateResponse(
        request=request,
        name="design_finish_etsy.html",
        context={
            "design": design,
            "product_key": product_key,
            "dashboard_sidebar_active": "designs",
        },
    )


@app.post("/designs/{design_id}/etsy/finish")
def standalone_design_finish_etsy_post(
    design_id: int,
    etsy_listing: str = Form(""),
    product_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    result, error = _check_standalone_design_marketplace(
        design_id, etsy_listing, product_key
    )
    if error:
        return RedirectResponse(
            f"/designs/{design_id}/etsy/finish?"
            + _standalone_product_query(
                product_key, finish_error=error
            ),
            status_code=303,
        )
    if result["linked"]:
        linked_query = {"linked": 1}
        if product_key != DEFAULT_MUG_BLUEPRINT_KEY:
            linked_query["product_key"] = product_key
        return RedirectResponse(
            f"/designs/{design_id}/etsy?"
            + urlencode(linked_query),
            status_code=303,
        )
    waiting_query = {"waiting": 1}
    if product_key != DEFAULT_MUG_BLUEPRINT_KEY:
        waiting_query["product_key"] = product_key
    return RedirectResponse(
        f"/designs/{design_id}/etsy/finish?"
        + urlencode(waiting_query),
        status_code=303,
    )


def _standalone_design_etsy_content(design):
    return {
        "title": design["product_title"] or design["name"] or "",
        "description": (
            design["product_description"] or design["description"] or ""
        ),
        "tags": design["tags"] or "",
        "price_cents": design["price_cents"] or 0,
    }


@app.get("/designs/{design_id}/etsy")
def standalone_design_etsy_review_page(
    request: Request,
    design_id: int,
    product_key: str = Query(DEFAULT_MUG_BLUEPRINT_KEY),
):
    design = get_standalone_design(design_id, product_key)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    content = _standalone_design_etsy_content(design)
    checks = validate_etsy_listing(content)
    remote = None
    error = ""
    if not design["etsy_listing_id"]:
        error = "Find and link the Etsy listing before synchronizing its details."
    else:
        try:
            remote = get_etsy_listing(str(design["etsy_listing_id"]))
        except EtsyAPIError as caught:
            error = str(caught)
    changes = []
    if remote is not None:
        changes = [
            {
                "label": "Title",
                "before": remote.get("title") or "",
                "after": content["title"],
            },
            {
                "label": "Description",
                "before": remote.get("description") or "",
                "after": content["description"],
            },
            {
                "label": "Tags",
                "before": ", ".join(remote.get("tags") or []),
                "after": ", ".join(parse_tags(content["tags"])),
            },
        ]
        for item in changes:
            item["changed"] = item["before"] != item["after"]
    return templates.TemplateResponse(
        request=request,
        name="design_etsy_sync.html",
        context={
            "design": design,
            "product_key": product_key,
            "checks": checks,
            "ready": all(item["passed"] for item in checks),
            "remote": remote,
            "changes": changes,
            "error": error,
            "dashboard_sidebar_active": "designs",
        },
    )


@app.post("/designs/{design_id}/etsy/sync")
def standalone_design_etsy_sync_post(
    design_id: int,
    confirmed: bool = Form(False),
    product_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    if not confirmed:
        raise HTTPException(
            status_code=400, detail="Confirm the Etsy details update"
        )
    design = get_standalone_design(design_id, product_key)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    if not design["etsy_listing_id"]:
        raise HTTPException(
            status_code=400, detail="Find and link the Etsy listing first"
        )
    content = _standalone_design_etsy_content(design)
    problems = [
        item["detail"]
        for item in validate_etsy_listing(content)
        if not item["passed"]
    ]
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    try:
        get_etsy_listing(str(design["etsy_listing_id"]))
        update_etsy_listing(
            str(design["etsy_listing_id"]),
            title=content["title"],
            description=content["description"],
            tags=parse_tags(content["tags"]),
        )
        record_standalone_marketplace_status(
            design_id,
            message=(
                "Etsy title, description, and tags synchronized from "
                "ShangooliOS."
            ),
            product_key=product_key,
        )
        mark_standalone_etsy_synced(
            design_id, product_key=product_key
        )
    except EtsyAPIError as error:
        return RedirectResponse(
            f"/designs/{design_id}/etsy?"
            + _standalone_product_query(
                product_key, etsy_sync_error=str(error)
            ),
            status_code=303,
        )
    return RedirectResponse(
        f"/designs/{design_id}/etsy?"
        + _standalone_product_query(product_key, synced=1),
        status_code=303,
    )


@app.post("/designs/{design_id}/etsy/pause")
def pause_standalone_design_etsy_post(
    design_id: int,
    confirmed: bool = Form(False),
    product_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    design = get_standalone_design(design_id, product_key)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm pausing Etsy sales")
    if not design["etsy_listing_id"]:
        raise HTTPException(status_code=400, detail="Check Etsy status first")
    try:
        update_etsy_listing_state(str(design["etsy_listing_id"]), "inactive")
        record_standalone_marketplace_status(
            design_id,
            etsy_state="inactive",
            paused=True,
            message="Etsy sales are paused.",
            product_key=product_key,
        )
    except (EtsyAPIError, ValueError) as error:
        return RedirectResponse(
            f"/designs/{design_id}?"
            + _standalone_product_query(
                product_key, marketplace_error=str(error)
            )
            + f"#product-{product_key}",
            status_code=303,
        )
    return RedirectResponse(
        f"/designs/{design_id}?"
        + _standalone_product_query(product_key, etsy_paused=1)
        + f"#product-{product_key}",
        status_code=303,
    )


@app.post("/designs/{design_id}/etsy/reactivate")
def reactivate_standalone_design_etsy_post(
    design_id: int,
    confirmed: bool = Form(False),
    product_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    design = get_standalone_design(design_id, product_key)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm reactivating Etsy sales")
    if not design["etsy_listing_id"]:
        raise HTTPException(status_code=400, detail="Check Etsy status first")
    try:
        update_etsy_listing_state(str(design["etsy_listing_id"]), "active")
        record_standalone_marketplace_status(
            design_id,
            etsy_state="active",
            paused=False,
            message="Etsy sales are active.",
            product_key=product_key,
        )
    except (EtsyAPIError, ValueError) as error:
        return RedirectResponse(
            f"/designs/{design_id}?"
            + _standalone_product_query(
                product_key, marketplace_error=str(error)
            )
            + f"#product-{product_key}",
            status_code=303,
        )
    return RedirectResponse(
        f"/designs/{design_id}?"
        + _standalone_product_query(product_key, etsy_reactivated=1)
        + f"#product-{product_key}",
        status_code=303,
    )


@app.post("/designs/{design_id}/replace-image")
async def replace_standalone_design_image_post(
    design_id: int,
    image: UploadFile = File(...),
    replacement_message: str = Form(""),
):
    saved = None
    try:
        saved = save_design_source(await image.read(), image.filename or "")
        replace_standalone_design_source(
            design_id,
            source_filename=saved["filename"],
            source_original_filename=saved["original_filename"],
            image_width=saved["width"],
            image_height=saved["height"],
        )
        normalized_message = " ".join(replacement_message.split()).strip()
        if normalized_message:
            current = get_standalone_design(design_id)
            generated = design_metadata_from_message(normalized_message)
            update_standalone_design(
                design_id,
                name=generated["name"],
                message=normalized_message,
                description=generated["description"],
                tags=generated["tags"],
            )
            if current and current["product_id"]:
                save_mug_setup(
                    design_id,
                    title=f"{generated['name']} 11 oz Mug",
                    description=generated["description"],
                    price_cents=current["price_cents"],
                    placement_x=current["placement_x"],
                    placement_y=current["placement_y"],
                    placement_scale=current["placement_scale"],
                    placement_mode=current["placement_mode"],
                    opposite_source_filename=current[
                        "opposite_source_filename"
                    ],
                )
    except ValueError as error:
        if saved:
            (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "designs"
                / saved["filename"]
            ).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/designs/{design_id}?replaced=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/designs/{design_id}/image")
def standalone_design_image(design_id: int):
    design = get_standalone_design(design_id)
    source = design_source_path(design)
    if source is None:
        raise HTTPException(status_code=404, detail="Design image not found")
    return FileResponse(source)


@app.get("/designs/{design_id}/products/{blueprint_key}/image")
def standalone_design_product_image(design_id: int, blueprint_key: str):
    try:
        get_product_blueprint(blueprint_key)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    design = get_standalone_design(design_id, blueprint_key)
    source = (
        product_asset_path(design)
        if design and design["product_id"]
        else design_source_path(design)
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Product image not found")
    return FileResponse(source)


def _pinterest_bundle_design(design_id, blueprint_key):
    try:
        get_product_blueprint(blueprint_key)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    design = get_standalone_design(design_id, blueprint_key)
    if design is None or not design["product_id"]:
        raise HTTPException(status_code=404, detail="Product setup not found")
    if not design["etsy_listing_url"]:
        raise HTTPException(
            status_code=400,
            detail="Connect the Etsy listing before creating its Pinterest bundle",
        )
    if product_asset_path(design) is None:
        raise HTTPException(status_code=400, detail="Prepared product graphic is missing")
    return design


@app.get("/designs/{design_id}/products/{blueprint_key}/pinterest")
def standalone_product_pinterest_bundle_page(
    request: Request, design_id: int, blueprint_key: str
):
    design = _pinterest_bundle_design(design_id, blueprint_key)
    _, blueprint = get_product_blueprint(blueprint_key)
    return templates.TemplateResponse(
        request=request,
        name="design_pinterest_bundle.html",
        context={
            "design": design,
            "blueprint_key": blueprint_key,
            "blueprint": blueprint,
            "bundle": pinterest_bundle_copy(design, blueprint_key),
            "dashboard_sidebar_active": "designs",
        },
    )


@app.get("/designs/{design_id}/products/{blueprint_key}/pinterest/image")
def standalone_product_pinterest_bundle_image(
    design_id: int,
    blueprint_key: str,
    download: bool = Query(False),
):
    design = _pinterest_bundle_design(design_id, blueprint_key)
    try:
        content = render_pinterest_bundle(design, blueprint_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="{pinterest_download_name(design, blueprint_key)}"'
        )
    return Response(content=content, media_type="image/png", headers=headers)


@app.get("/designs/{design_id}/mug/opposite-image")
def standalone_design_opposite_image(
    design_id: int,
    product_key: str = Query(DEFAULT_MUG_BLUEPRINT_KEY),
):
    design = get_standalone_design(design_id, product_key)
    source = design_opposite_source_path(design)
    if source is None:
        raise HTTPException(
            status_code=404, detail="Opposite-side graphic not found"
        )
    return FileResponse(source)


@app.get("/designs/{design_id}/mug")
def standalone_mug_review_page(request: Request, design_id: int):
    return _standalone_product_review_page(
        request, design_id, DEFAULT_MUG_BLUEPRINT_KEY, legacy_route=True
    )


@app.get("/designs/{design_id}/products/{blueprint_key}")
def standalone_product_review_page(
    request: Request, design_id: int, blueprint_key: str
):
    return _standalone_product_review_page(
        request, design_id, blueprint_key, legacy_route=False
    )


def _standalone_product_review_page(
    request, design_id, blueprint_key, *, legacy_route
):
    try:
        profile = mug_profile(blueprint_key)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    design = get_standalone_design(design_id, blueprint_key)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    suggested_title = suggested_mug_title(
        design["message"] or design["name"], blueprint_key
    )
    default_title = suggested_title or (
        f"{design['name']} {profile['product_name']}"
    )
    edit_copy = (
        request.query_params.get("edit_copy") == "1"
        and bool(design["printify_product_id"])
    )
    readiness = product_readiness(
        product=design if design["product_id"] else None,
        source_exists=(
            product_asset_path(design) is not None
            if design["product_id"]
            else design_source_path(design) is not None
        ),
        blueprint=PRODUCT_BLUEPRINTS[blueprint_key],
    )
    product_url_base = (
        f"/designs/{design_id}/mug"
        if legacy_route
        else f"/designs/{design_id}/products/{blueprint_key}"
    )
    placement_x = design["placement_x"] if design["product_id"] else profile["placement_x"]
    placement_y = design["placement_y"] if design["product_id"] else profile["placement_y"]
    placement_scale = (
        design["placement_scale"] if design["product_id"] else profile["placement_scale"]
    )
    placement_mode = design["placement_mode"] if design["product_id"] else "both"
    suggested_description = suggested_mug_description(
        design["product_description"] or design["description"] or "",
        blueprint_key,
        placement_mode,
    )
    return templates.TemplateResponse(
        request=request,
        name="design_mug_review.html",
        context={
            "design": design,
            "mug_profile": profile,
            "blueprint_key": blueprint_key,
            "product_url_base": product_url_base,
            "product_readiness": readiness,
            "placement_geometry": normalized_placement_geometry(
                PRODUCT_BLUEPRINTS[blueprint_key],
                x=placement_x,
                y=placement_y,
                scale=placement_scale,
            ),
            "default_title": default_title,
            "suggested_title": suggested_title,
            "suggested_description": suggested_description,
            "edit_copy": edit_copy,
            "configuration_source": printify_configuration_source(),
            "dashboard_sidebar_active": "designs",
        },
    )


@app.post("/designs/{design_id}/products/{blueprint_key}/copy")
def update_standalone_product_copy_post(
    design_id: int,
    blueprint_key: str,
    title: str = Form(...),
    description: str = Form(""),
):
    try:
        get_product_blueprint(blueprint_key)
        update_standalone_product_copy(
            design_id,
            blueprint_key,
            title=title,
            description=description,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    product_url = (
        f"/designs/{design_id}/mug"
        if blueprint_key == DEFAULT_MUG_BLUEPRINT_KEY
        else f"/designs/{design_id}/products/{blueprint_key}"
    )
    return RedirectResponse(
        f"{product_url}?copy_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/designs/{design_id}/mug/setup")
async def save_standalone_mug_setup_post(
    design_id: int,
    blueprint_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
    title: str = Form(...),
    description: str = Form(""),
    price: str = Form(...),
    placement_scale: float = Form(MUG_PROFILE["placement_scale"]),
    placement_x: float = Form(MUG_PROFILE["placement_x"]),
    placement_y: float = Form(MUG_PROFILE["placement_y"]),
    placement_mode: str = Form("front"),
    opposite_image: UploadFile | None = File(None),
):
    saved_opposite = None
    try:
        if opposite_image and opposite_image.filename:
            saved_opposite = save_design_source(
                await opposite_image.read(),
                opposite_image.filename,
            )
            if not saved_opposite["has_transparency"]:
                raise ValueError(
                    "The opposite-side graphic is fully opaque. Upload a PNG "
                    "with real transparent pixels."
                )
        save_mug_setup(
            design_id,
            blueprint_key=blueprint_key,
            title=title,
            description=description,
            price_cents=_price_to_cents(price),
            placement_scale=placement_scale,
            placement_x=placement_x,
            placement_y=placement_y,
            placement_mode=placement_mode,
            opposite_source_filename=(
                saved_opposite["filename"] if saved_opposite else None
            ),
        )
    except ValueError as error:
        if saved_opposite:
            (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "designs"
                / saved_opposite["filename"]
            ).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    product_url = (
        f"/designs/{design_id}/mug"
        if blueprint_key == DEFAULT_MUG_BLUEPRINT_KEY
        else f"/designs/{design_id}/products/{blueprint_key}"
    )
    return RedirectResponse(
        f"{product_url}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/designs/{design_id}/mug/create")
def create_standalone_mug_draft_post(
    design_id: int,
    confirmed: bool = Form(False),
    blueprint_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    try:
        result = create_mug_draft(
            design_id, confirmed=confirmed, blueprint_key=blueprint_key
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    product_url = (
        f"/designs/{design_id}/mug"
        if blueprint_key == DEFAULT_MUG_BLUEPRINT_KEY
        else f"/designs/{design_id}/products/{blueprint_key}"
    )
    return RedirectResponse(
        f"{product_url}?result={result['outcome']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/designs/{design_id}/mug/update-graphics")
def update_standalone_mug_graphics_post(
    design_id: int,
    confirmed: bool = Form(False),
    blueprint_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    try:
        result = update_mug_draft_graphics(
            design_id,
            confirmed=confirmed,
            blueprint_key=blueprint_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    product_url = (
        f"/designs/{design_id}/mug"
        if blueprint_key == DEFAULT_MUG_BLUEPRINT_KEY
        else f"/designs/{design_id}/products/{blueprint_key}"
    )
    return RedirectResponse(
        f"{product_url}?result={result['outcome']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/designs/{design_id}/mug/update-copy")
def update_standalone_mug_copy_post(
    design_id: int,
    confirmed: bool = Form(False),
    blueprint_key: str = Form(DEFAULT_MUG_BLUEPRINT_KEY),
):
    try:
        result = update_mug_draft_copy(
            design_id,
            confirmed=confirmed,
            blueprint_key=blueprint_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    product_url = (
        f"/designs/{design_id}/mug"
        if blueprint_key == DEFAULT_MUG_BLUEPRINT_KEY
        else f"/designs/{design_id}/products/{blueprint_key}"
    )
    return RedirectResponse(
        f"{product_url}?result={result['outcome']}&update=copy",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/designs/{design_id}/products/{blueprint_key}/prepare-latest")
def prepare_standalone_product_latest_asset_post(
    design_id: int,
    blueprint_key: str,
    confirmed: bool = Form(False),
):
    try:
        get_product_blueprint(blueprint_key)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm preparation of the latest design graphic",
        )
    design = get_standalone_design(design_id, blueprint_key)
    source = design_source_path(design)
    if design is None or source is None:
        raise HTTPException(status_code=404, detail="Design graphic not found")
    try:
        prepare_standalone_product_asset(
            design_id, blueprint_key, design["source_filename"]
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    product_url = (
        f"/designs/{design_id}/mug"
        if blueprint_key == DEFAULT_MUG_BLUEPRINT_KEY
        else f"/designs/{design_id}/products/{blueprint_key}"
    )
    return RedirectResponse(
        f"{product_url}?prepared=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def build_collection_sequence(collection, artworks):
    artworks_by_number = {
        int(item["artwork_code"].rsplit("-", 1)[-1]): item for item in artworks
    }
    upper_bound = max(
        collection["target_artwork_count"] or 0,
        max(artworks_by_number, default=0),
    )
    return [
        {"number": number, "artwork": artworks_by_number.get(number)}
        for number in range(1, upper_bound + 1)
    ]


@app.get("/collections")
def collections_page(
    request: Request,
    collection_code: str = Query("", alias="collection"),
    show_retired: bool = Query(False),
):
    context = get_dashboard()
    context["collections"] = sorted(
        context["collections"],
        key=lambda item: (
            item["status"] == "paused",
            item.get("display_order") or 0,
        ),
    )
    normalized_code = collection_code.strip().upper()
    if not normalized_code and context["collections"]:
        normalized_code = context["collections"][0]["code"]
    context["selected_collection"] = None
    context["collection_artworks"] = []
    if normalized_code:
        collection, artworks, retired_artworks = get_collection(normalized_code)
        if collection is None or collection["status"] == "archived":
            raise HTTPException(status_code=404, detail="Collection not found")
        summary = next(
            (
                item for item in context["collections"]
                if item["code"] == normalized_code
            ),
            {},
        )
        context["selected_collection"] = {**dict(collection), **summary}
        context["collection_artworks"] = artworks
        context["retired_artworks"] = retired_artworks
        context["show_retired"] = show_retired
        context["collection_sequence"] = build_collection_sequence(
            collection, artworks
        )
        collection_listings = [
            listing
            for artwork in [*artworks, *retired_artworks]
            for listing in get_artwork_listings(artwork["artwork_code"])
            if listing["external_listing_id"]
        ]
        context["selected_collection"]["etsy_live_listing_count"] = sum(
            1
            for listing in collection_listings
            if listing["etsy_state"] == "active" and not listing["etsy_paused_at"]
        )
        context["selected_collection"]["etsy_paused_listing_count"] = sum(
            1 for listing in collection_listings if listing["etsy_paused_at"]
        )
        context["workflow_navigation"] = collection_workflow_navigation(
            normalized_code, active_stage=""
        )
    return templates.TemplateResponse(
        request=request,
        name="collections_index.html",
        context=context,
    )


@app.post("/collections/{collection_code}/etsy/pause")
def pause_collection_on_etsy(
    collection_code: str,
    confirmed: bool = Form(False),
):
    collection, artworks, retired_artworks = get_collection(collection_code)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm pausing this collection")
    targets = [
        listing
        for artwork in [*artworks, *retired_artworks]
        for listing in get_artwork_listings(artwork["artwork_code"])
        if listing["external_listing_id"]
        and listing["etsy_state"] == "active"
        and not listing["etsy_paused_at"]
    ]
    changed = 0
    failures = []
    for listing in targets:
        try:
            update_etsy_listing_state(str(listing["external_listing_id"]), "inactive")
            record_etsy_paused(listing["id"], True)
            changed += 1
        except (EtsyAPIError, ValueError) as failure:
            failures.append(f"{listing['public_title']}: {failure}")
    params = {"collection": collection["code"], "etsy_collection_paused": changed}
    if failures:
        params["etsy_collection_error"] = " | ".join(failures[:3])
    return RedirectResponse(
        f"/collections?{urlencode(params)}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/collections/{collection_code}/etsy/reactivate")
def reactivate_collection_on_etsy(
    collection_code: str,
    confirmed: bool = Form(False),
):
    collection, artworks, retired_artworks = get_collection(collection_code)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm reactivating this collection")
    targets = [
        listing
        for artwork in [*artworks, *retired_artworks]
        for listing in get_artwork_listings(artwork["artwork_code"])
        if listing["external_listing_id"] and listing["etsy_paused_at"]
    ]
    changed = 0
    failures = []
    for listing in targets:
        try:
            update_etsy_listing_state(str(listing["external_listing_id"]), "active")
            record_etsy_paused(listing["id"], False)
            changed += 1
        except (EtsyAPIError, ValueError) as failure:
            failures.append(f"{listing['public_title']}: {failure}")
    params = {"collection": collection["code"], "etsy_collection_reactivated": changed}
    if failures:
        params["etsy_collection_error"] = " | ".join(failures[:3])
    return RedirectResponse(
        f"/collections?{urlencode(params)}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/mockup-studio")
def mockup_studio_page(request: Request):
    mockup_sets = []
    for summary in list_mockup_sets():
        mockup_set, items = get_mockup_set(summary["id"])
        mockup_sets.append({**dict(mockup_set), "items": [dict(item) for item in items]})
    return templates.TemplateResponse(
        request=request,
        name="mockup_studio.html",
        context={
            "scenes": list_mockup_scenes(),
            "preview_artworks": [
                artwork for artwork in search_artworks("")
                if artwork["has_source_image"]
            ],
            "mockup_sets": mockup_sets,
            "template_packs": template_pack_options(),
        },
    )


@app.post("/mockup-studio/sets")
def create_mockup_set_post(
    name: str = Form(...), description: str = Form(""),
    template_key: str = Form(DEFAULT_TEMPLATE_PACK), scene_id: int | None = Form(None),
):
    try:
        create_mockup_set(name, description, template_key, scene_id)
    except (ValueError, sqlite3.IntegrityError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse("/mockup-studio?set_saved=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/mockup-studio/sets/{set_id}")
async def update_mockup_set_post(set_id: int, request: Request):
    form = await request.form()
    _, current_items = get_mockup_set(set_id)
    try:
        items = []
        for current in current_items:
            slot = current["slot_key"]
            source = str(form.get(f"source_{slot}") or "").split(":", 1)
            if len(source) != 2 or source[0] not in {"template", "scene"}:
                raise ValueError("Choose an image source for every position")
            source_kind, source_value = source
            if source_kind == "template" and source_value not in GENERATED_SLOTS:
                raise ValueError("Choose a valid generated image")
            if source_kind == "scene" and not source_value.isdigit():
                raise ValueError("Choose a valid reusable scene")
            items.append({
                "slot_key": slot,
                "label": str(form.get(f"label_{slot}") or "Listing image").strip(),
                "source_kind": source_kind,
                "template_slot": source_value if source_kind == "template" else None,
                "scene_id": int(source_value) if source_kind == "scene" else None,
                "position": int(form[f"position_{slot}"]),
            })
        update_mockup_set(
            set_id, name=str(form.get("name") or ""),
            description=str(form.get("description") or ""),
            template_key=str(form.get("template_key") or DEFAULT_TEMPLATE_PACK),
            lead_slot=str(form.get("lead_slot") or "hero"),
            items=items,
        )
    except (KeyError, ValueError, sqlite3.IntegrityError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse("/mockup-studio?set_updated=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/mockup-studio/sets/{set_id}/items")
def add_mockup_set_item_post(set_id: int):
    add_mockup_set_item(set_id)
    return RedirectResponse("/mockup-studio?set_updated=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/mockup-studio/sets/{set_id}/items/{slot_key}/remove")
def remove_mockup_set_item_post(set_id: int, slot_key: str):
    try:
        remove_mockup_set_item(set_id, slot_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse("/mockup-studio?set_updated=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/mockup-studio/scenes")
def create_mockup_scene_post(
    name: str = Form(...), room_type: str = Form(...),
    orientation: str = Form("any"), upload: UploadFile = File(...),
    placement_x: float = Form(25), placement_y: float = Form(15),
    placement_width: float = Form(50), placement_height: float = Form(50),
    source_url: str = Form(""), creator: str = Form(""),
    license_name: str = Form(""), frame_color: str = Form("#2d2b29"),
    frame_width: float = Form(2), mat_color: str = Form("#faf8f3"),
    mat_width: float = Form(1.2), shadow_strength: float = Form(35),
):
    normalized_orientation = orientation.strip().lower()
    if normalized_orientation not in {"horizontal", "vertical", "square", "any"}:
        raise HTTPException(status_code=400, detail="Choose a valid artwork orientation")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG, or WebP room image")
    MOCKUP_SCENES_DIR.mkdir(parents=True, exist_ok=True)
    destination = MOCKUP_SCENES_DIR / f"scene-{secrets.token_hex(8)}{suffix}"
    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        with Image.open(destination) as image:
            image.verify()
        scene_id = create_mockup_scene(
            name=name, room_type=room_type, orientation=normalized_orientation,
            image_path=destination.name, placement_x=placement_x,
            placement_y=placement_y, placement_width=placement_width,
            placement_height=placement_height,
            source_url=source_url, creator=creator, license_name=license_name,
            frame_color=frame_color, frame_width=frame_width,
            mat_color=mat_color, mat_width=mat_width,
            shadow_strength=shadow_strength,
        )
    except (ValueError, UnidentifiedImageError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()
    return RedirectResponse(
        f"/mockup-studio?scene_saved=1&scene={scene_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/mockup-studio/scenes/{scene_id}/image")
def view_mockup_scene(scene_id: int):
    scene = get_mockup_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Mockup scene not found")
    path = MOCKUP_SCENES_DIR / scene["image_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Mockup scene image not found")
    return FileResponse(path)


@app.post("/mockup-studio/scenes/{scene_id}/placement")
def update_mockup_scene_placement_post(
    scene_id: int, placement_x: float = Form(...), placement_y: float = Form(...),
    placement_width: float = Form(...), placement_height: float = Form(...),
    frame_color: str = Form("#2d2b29"), frame_width: float = Form(2),
    mat_color: str = Form("#faf8f3"), mat_width: float = Form(1.2),
    shadow_strength: float = Form(35),
):
    try:
        update_mockup_scene_placement(
            scene_id, placement_x=placement_x, placement_y=placement_y,
            placement_width=placement_width, placement_height=placement_height,
            frame_color=frame_color, frame_width=frame_width,
            mat_color=mat_color, mat_width=mat_width,
            shadow_strength=shadow_strength,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/mockup-studio?scene_updated=1&scene={scene_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/mockup-studio/scenes/{scene_id}/background")
def replace_mockup_scene_background_post(
    scene_id: int, upload: UploadFile = File(...),
    source_url: str = Form(""), creator: str = Form(""),
    license_name: str = Form(""), confirmed: bool = Form(False),
):
    scene = get_mockup_scene(scene_id)
    if scene is None or not scene["active"]:
        raise HTTPException(status_code=404, detail="Reusable scene not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the background replacement")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG, or WebP room image")
    destination = MOCKUP_SCENES_DIR / f"scene-{secrets.token_hex(8)}{suffix}"
    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        with Image.open(destination) as image:
            image.verify()
        update_mockup_scene_background(
            scene_id, image_path=destination.name, source_url=source_url,
            creator=creator, license_name=license_name,
        )
    except (ValueError, UnidentifiedImageError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()
    old_background = MOCKUP_SCENES_DIR / scene["image_path"]
    if old_background != destination:
        old_background.unlink(missing_ok=True)
    return RedirectResponse(
        f"/mockup-studio?background_replaced=1&scene={scene_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/mockup-studio/scenes/{scene_id}/disable")
def disable_mockup_scene_post(scene_id: int):
    try:
        disable_mockup_scene(scene_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        "/mockup-studio?scene_disabled=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/recent")
def recently_updated_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="recently_updated.html",
        context=get_dashboard(),
    )


@app.get("/fast-flow")
def fast_flow_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="fast_flow.html",
        context={"error": None, "manifest_text": ""},
    )


@app.post("/fast-flow/import")
def fast_flow_import_post(
    request: Request,
    manifest: str = Form(...),
    images: list[UploadFile] = File(...),
):
    try:
        result = import_fast_flow_collection(manifest, images)
    except ValueError as error:
        for upload in images:
            upload.file.close()
        return templates.TemplateResponse(
            request=request,
            name="fast_flow.html",
            context={"error": str(error), "manifest_text": manifest},
            status_code=400,
        )
    return RedirectResponse(
        url=(
            f"/collections/{result['collection_code']}/production"
            f"?fast_flow_imported={len(result['artwork_codes'])}"
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/order")
async def reorder_collections(request: Request):
    try:
        payload = await request.json()
        codes = payload.get("codes", [])
        if not isinstance(codes, list):
            raise ValueError("Collection order must be a list")
        save_collection_order(codes)
    except (ValueError, AttributeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"saved": True}


@app.get("/etsy/connect")
def etsy_connect_page(request: Request):
    config = etsy_config()
    return templates.TemplateResponse(
        request=request,
        name="etsy_connect.html",
        context={
            "config": config,
            "connected": bool(config["access_token"] and config["shop_id"]),
            "store_url": f"https://www.etsy.com/shop/{config['shop_name']}" if config["shop_name"] else "https://www.etsy.com/your/shops/me",
            "error": None,
        },
    )


@app.get("/printify/connect")
def printify_connect_page(request: Request):
    api = PrintifyAPI.from_env()
    return templates.TemplateResponse(
        request=request,
        name="printify_connect.html",
        context={
            "configured": api is not None,
            "source": printify_configuration_source(),
            "shop_id": api.shop_id if api else "",
            "store_url": f"https://printify.com/app/store/{api.shop_id}/products" if api else "",
        },
    )


@app.post("/printify/connect")
def printify_connect_save(api_token: str = Form(...), shop_id: str = Form(...)):
    try:
        save_printify_local_config(api_token, shop_id)
        configure_printify_runtime(api_token, shop_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse("/printify/connect?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/printify/disconnect")
def printify_disconnect():
    clear_printify_runtime()
    clear_printify_local_config()
    return RedirectResponse("/printify/connect?disconnected=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/etsy/connect")
def etsy_connect_post(
    api_key: str = Form(...),
    shared_secret: str = Form(...),
    remember: bool = Form(False),
):
    try:
        authorization_url = begin_etsy_oauth(api_key, shared_secret, remember)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/etsy/oauth/callback")
def etsy_oauth_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
    error_description: str = Query(""),
):
    if error:
        message = error_description or error
    else:
        try:
            complete_etsy_oauth(code, state)
            return RedirectResponse(
                "/etsy/connect?connected=1", status_code=status.HTTP_303_SEE_OTHER
            )
        except (EtsyAPIError, KeyError, ValueError) as failure:
            message = str(failure)
    config = etsy_config()
    return templates.TemplateResponse(
        request=request,
        name="etsy_connect.html",
        context={"config": config, "connected": False, "error": message},
        status_code=400,
    )


@app.post("/etsy/disconnect")
def etsy_disconnect_post():
    clear_etsy_config()
    return RedirectResponse("/etsy/connect", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/etsy/reconnect")
def etsy_reconnect_post():
    config = etsy_config()
    if not config["api_key"] or not config["shared_secret"]:
        return RedirectResponse("/etsy/connect", status_code=status.HTTP_303_SEE_OTHER)
    authorization_url = begin_etsy_oauth(
        config["api_key"], config["shared_secret"], remember=True
    )
    return RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/search")
def search_page(
    request: Request,
    q: str = Query("", max_length=100),
):
    query = q.strip()

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "query": query,
            "results": search_artworks(query) if query else [],
        },
    )


@app.get("/listings")
def listings_page(
    request: Request,
    listing_status: str = Query("", alias="status"),
    listing_view: str = Query("", alias="view"),
    collection_code: str = Query("", alias="collection"),
    collection_state: str = Query("active"),
    artwork_state: str = Query("current"),
    item_type: str = Query("artwork"),
    search: str = Query(""),
):
    normalized_status = listing_status.strip().lower()
    normalized_view = listing_view.strip().lower()
    requested_collection = collection_code.strip()
    normalized_collection_state = collection_state.strip().lower() or "active"
    normalized_artwork_state = artwork_state.strip().lower() or "current"
    normalized_item_type = item_type.strip().lower() or "artwork"
    normalized_search = search.strip()
    if normalized_view not in ("", "ready", "attention"):
        raise HTTPException(status_code=400, detail="Invalid listing view")
    if normalized_collection_state not in ("active", "paused", "all"):
        raise HTTPException(status_code=400, detail="Invalid collection state")
    if normalized_artwork_state not in ("current", "retired", "all"):
        raise HTTPException(status_code=400, detail="Invalid artwork state")
    if normalized_item_type not in ("artwork", "designs", "all"):
        raise HTTPException(status_code=400, detail="Invalid item type")
    if normalized_status and normalized_view:
        raise HTTPException(status_code=400, detail="Choose a status or readiness view, not both")
    collections = list(get_collections())
    collections_by_code = {item["code"].upper(): item for item in collections}
    collections_by_name = {item["name"].strip().casefold(): item for item in collections}
    matched_collection = (
        collections_by_code.get(requested_collection.upper())
        or collections_by_name.get(requested_collection.casefold())
        if requested_collection
        else None
    )
    if requested_collection and matched_collection is None:
        raise HTTPException(status_code=400, detail="Invalid collection filter")
    normalized_collection = matched_collection["code"] if matched_collection else ""
    try:
        listing_rows = list_listings(
            normalized_status or None, normalized_collection or None
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    listings = []
    for row in listing_rows:
        item = dict(row)
        item["readiness"] = get_listing_readiness(item["id"])
        item["missing_labels"] = [
            check["label"]
            for check in item["readiness"]["items"]
            if not check["passed"]
        ]
        if item["status"] == "archived":
            item["primary_action"] = {
                "label": "Review archived listing",
                "url": f"/listings/{item['id']}",
                "external": False,
            }
        elif not item["readiness"]["ready"]:
            item["primary_action"] = {
                "label": "Fix missing items",
                "url": f"/listings/{item['id']}",
                "external": False,
            }
        elif item["etsy_paused_at"]:
            item["primary_action"] = {
                "label": "Review paused listing",
                "url": f"/listings/{item['id']}",
                "external": False,
            }
        elif item["status"] == "published":
            item["primary_action"] = {
                "label": "Open on Etsy" if item["marketplace_url"] else "Open listing",
                "url": item["marketplace_url"] or f"/listings/{item['id']}",
                "external": bool(item["marketplace_url"]),
            }
        elif item["printify_publish_requested_at"]:
            item["primary_action"] = {
                "label": "Check Etsy status",
                "url": f"/collections/{item['collection_code']}/publish/recover",
                "external": False,
            }
        elif item["printify_product_url"]:
            item["primary_action"] = {
                "label": "Publish to Etsy",
                "url": f"/collections/{item['collection_code']}/publish",
                "external": False,
            }
        else:
            item["primary_action"] = {
                "label": "Send to Printify",
                "url": f"/collections/{item['collection_code']}/printify",
                "external": False,
            }
        listings.append(item)
    if normalized_view == "ready":
        listings = [
            item for item in listings
            if item["readiness"]["ready"]
            and item["status"] not in ("published", "archived")
        ]
    elif normalized_view == "attention":
        listings = [
            item for item in listings
            if not item["readiness"]["ready"] and item["status"] != "archived"
        ]
    elif not normalized_status:
        listings = [item for item in listings if item["status"] != "archived"]
    if normalized_collection_state != "all":
        listings = [
            item for item in listings
            if item["collection_status"] == normalized_collection_state
        ]
    if normalized_artwork_state == "current":
        listings = [
            item for item in listings if item["artwork_status"] != "retired"
        ]
    elif normalized_artwork_state == "retired":
        listings = [
            item for item in listings if item["artwork_status"] == "retired"
        ]
    if normalized_search:
        search_key = normalized_search.casefold()
        listings = [
            item
            for item in listings
            if search_key
            in " ".join(
                str(item.get(field) or "")
                for field in (
                    "title",
                    "description",
                    "artwork_code",
                    "public_title",
                    "collection_name",
                    "collection_code",
                )
            ).casefold()
        ]
    designs = [dict(item) for item in list_standalone_designs()]
    designs = [item for item in designs if item["status"] != "archived"]
    if normalized_search:
        search_key = normalized_search.casefold()
        designs = [
            item
            for item in designs
            if search_key
            in " ".join(
                str(item.get(field) or "")
                for field in (
                    "name",
                    "message",
                    "description",
                    "tags",
                    "product_title",
                    "product_description",
                )
            ).casefold()
        ]
    for design in designs:
        if design["etsy_paused_at"]:
            design["display_state"] = "Paused on Etsy"
            design["state_class"] = "attention"
        elif str(design["etsy_state"] or "").lower() == "active":
            design["display_state"] = "Live on Etsy"
            design["state_class"] = "printify"
        elif design["external_state"] in {
            "needs_update",
            "failed",
            "outcome_unknown",
            "update_outcome_unknown",
        }:
            design["display_state"] = "Needs attention"
            design["state_class"] = "attention"
        elif design["printify_product_id"]:
            design["display_state"] = "Printify product"
            design["state_class"] = "printify"
        else:
            design["display_state"] = "Design draft"
            design["state_class"] = "draft"
    if normalized_item_type == "designs":
        listings = []
    elif normalized_item_type == "artwork":
        designs = []
    visible_collections = [
        item
        for item in collections
        if normalized_collection_state == "all"
        or item["status"] == normalized_collection_state
    ]
    return templates.TemplateResponse(
        request=request,
        name="listings.html",
        context={
            "listings": listings,
            "active_status": normalized_status,
            "active_view": normalized_view,
            "active_collection": normalized_collection,
            "active_collection_name": (
                matched_collection["name"] if matched_collection else ""
            ),
            "collections": visible_collections,
            "statuses": ("draft", "ready", "published", "archived"),
            "status_counts": get_listing_status_counts(
                None
                if normalized_collection_state == "all"
                else normalized_collection_state,
                normalized_artwork_state,
            ),
            "active_collection_state": normalized_collection_state,
            "active_artwork_state": normalized_artwork_state,
            "active_item_type": normalized_item_type,
            "active_search": normalized_search,
            "designs": designs,
        },
    )


@app.get("/artworks/{artwork_code}/listings/new")
def new_listing_form(request: Request, artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    content = get_artwork_listing_content(artwork_code)
    return templates.TemplateResponse(
        request=request,
        name="listing_form.html",
        context={
            "artwork": artwork,
            "listing": None,
            "prefill": content,
            "statuses": ("draft", "ready", "archived"),
            "workflow_nav": _workflow_navigation(artwork, active_stage="listing"),
        },
    )


@app.post("/artworks/{artwork_code}/listings/new")
def create_listing_post(
    artwork_code: str,
    marketplace: str = Form("Etsy"),
    product: str = Form("Poster"),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    price: str = Form("0.00"),
    listing_status: str = Form("draft"),
):
    if listing_status == "published":
        raise HTTPException(
            status_code=400,
            detail="Create the listing first, then use the Etsy publishing section",
        )
    try:
        listing_id = create_listing(
            artwork_code, marketplace=marketplace.strip() or "Etsy",
            product=product.strip() or "Poster", title=title.strip(),
            description=description.strip(), tags=tags.strip(),
            price_cents=_price_to_cents(price), status=listing_status,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/listings/{listing_id}")
def listing_page(request: Request, listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    _, collection_artworks, _ = get_collection(listing["collection_code"])
    artwork_position = next(
        (
            index
            for index, item in enumerate(collection_artworks)
            if item["artwork_code"] == listing["artwork_code"]
        ),
        None,
    )

    def sibling_destination(position):
        if position is None or position < 0 or position >= len(collection_artworks):
            return None
        sibling = collection_artworks[position]
        sibling_listings = list(get_artwork_listings(sibling["artwork_code"]))
        sibling_listing = next(
            (item for item in sibling_listings if item["status"] == "published"),
            sibling_listings[0] if sibling_listings else None,
        )
        return {
            "title": sibling["public_title"],
            "href": (
                f"/listings/{sibling_listing['id']}"
                if sibling_listing
                else f"/artworks/{sibling['artwork_code']}?step=listing"
            ),
        }

    previous_listing_artwork = sibling_destination(
        artwork_position - 1 if artwork_position is not None else None
    )
    next_listing_artwork = sibling_destination(
        artwork_position + 1 if artwork_position is not None else None
    )
    readiness = get_listing_readiness(listing_id)
    printify_state = validate_printify_product(listing)
    production = get_artwork_production(listing["artwork_code"])
    automatic_profile = _printify_profile_for_orientation(
        production["orientation"] if production else "",
        listing["collection_code"],
    )
    available_printify_roles = {
        item["role"] for item in _printify_file_options(listing)
    }
    automatic_profile_roles = {
        ratio_role_for_variant(title)
        for _, title, _ in automatic_profile["variants"]
    } if automatic_profile else set()
    return templates.TemplateResponse(
        request=request,
        name="listing_form.html",
        context={
            "artwork": listing, "listing": listing, "prefill": None,
            "statuses": (
                ("draft", "ready", "published", "archived")
                if listing["status"] == "published"
                else ("draft", "ready", "archived")
            ),
            "readiness": readiness,
            "export_state": inspect_listing_export(listing, readiness),
            "printify_state": printify_state,
            "printify_automation_available": bool(
                readiness["ready"]
                and automatic_profile
                and automatic_profile_roles.issubset(available_printify_roles)
            ),
            "printify_profile": automatic_profile,
            "printify_handoff": (
                inspect_printify_handoff(listing, readiness)
                if printify_state["required"] else None
            ),
            "previous_listing_artwork": previous_listing_artwork,
            "next_listing_artwork": next_listing_artwork,
            "workflow_nav": _workflow_navigation(
                listing,
                listing=listing,
                active_stage="publish" if printify_state["ready"] else "printify",
            ),
        },
    )


@app.post("/listings/{listing_id}/export")
def export_listing_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    readiness = get_listing_readiness(listing_id)
    try:
        result = build_listing_export(listing, readiness)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return FileResponse(
        path=result["path"],
        filename=result["filename"],
        media_type="application/zip",
    )


@app.get("/listings/{listing_id}/etsy")
def etsy_sync_page(request: Request, listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        preview = build_etsy_sync_preview(listing)
        if preview.get("linked") and preview.get("remote"):
            record_etsy_state(listing_id, preview["remote"].get("state", ""))
            listing = get_listing(listing_id)
        error = None
    except EtsyAPIError as failure:
        preview = None
        error = str(failure)
    return templates.TemplateResponse(
        request=request,
        name="etsy_sync.html",
        context={
            "listing": listing,
            "preview": preview,
            "error": error,
            "workflow_nav": _workflow_navigation(
                listing, listing=listing, active_stage="etsy"
            ),
        },
    )


@app.post("/listings/{listing_id}/etsy/link")
def link_etsy_listing_post(listing_id: int, external_listing_id: str = Form(...)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        remote = get_etsy_listing(external_listing_id.strip())
        config = etsy_config()
        if str(remote.get("shop_id", "")) != str(config["shop_id"]):
            raise ValueError("That listing does not belong to the connected Etsy shop")
        link_etsy_listing(listing_id, external_listing_id)
        record_etsy_state(listing_id, remote.get("state", ""))
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/listings/{listing_id}/etsy?linked=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/listings/{listing_id}/etsy/sync")
def sync_etsy_listing_post(listing_id: int, confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the Etsy changes before syncing")
    readiness = get_listing_readiness(listing_id)
    if not readiness or not readiness["ready"]:
        raise HTTPException(status_code=400, detail="Complete listing readiness before syncing")
    try:
        result = sync_etsy_listing(listing)
        mark_etsy_synced(listing_id, result.get("state", ""))
        record_publishing_recovery(
            listing_id,
            "etsy_ready_for_review",
            "Etsy has the final ShangooliOS title, description, tags, images, and section. Final Etsy review remains.",
        )
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/listings/{listing_id}/etsy?synced=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/listings/{listing_id}/title/sync")
def sync_listing_title(listing_id: int, title: str = Form(...), confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    normalized = title.strip()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not normalized or len(normalized) > 140:
        raise HTTPException(status_code=400, detail="Enter a marketplace title up to 140 characters")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the marketplace title sync")
    try:
        if listing["printify_product_id"]:
            api = PrintifyAPI.from_env()
            if api is None:
                raise ValueError("Connect Printify before syncing the marketplace title")
            api.update_product(listing["printify_product_id"], {"title": normalized})
        if listing["external_listing_id"]:
            update_etsy_listing(
                listing["external_listing_id"], title=normalized,
                description=listing["description"] or "",
                tags=[tag.strip() for tag in (listing["tags"] or "").split(",") if tag.strip()],
            )
            mark_etsy_synced(listing_id, listing["etsy_state"] or "")
    except (PrintifyAPIError, EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    update_listing(
        listing_id, marketplace=listing["marketplace"], product=listing["product"],
        title=normalized, description=listing["description"] or "", tags=listing["tags"] or "",
        price_cents=listing["price_cents"], status=listing["status"],
    )
    return RedirectResponse(
        f"/artworks/{listing['artwork_code']}?step=details&marketplace_title_synced=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/etsy/inventory")
def update_etsy_inventory_post(
    listing_id: int,
    quantity: int = Form(...),
    confirmed: bool = Form(False),
):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the inventory change")
    try:
        set_etsy_inventory_quantity(listing, quantity)
        record_etsy_inventory_quantity(listing_id, quantity)
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/listings/{listing_id}/etsy?inventory_updated={quantity}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/etsy/inventory/sold-out")
def mark_etsy_listing_sold_out(listing_id: int, confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm pausing Etsy sales")
    try:
        update_etsy_listing_state(str(listing["external_listing_id"]), "inactive")
        record_etsy_paused(listing_id, True)
    except (EtsyAPIError, ValueError) as failure:
        return RedirectResponse(
            f"/listings?{urlencode({'etsy_error': str(failure)})}", status_code=303
        )
    return RedirectResponse("/listings?etsy_paused=1", status_code=303)


@app.post("/listings/{listing_id}/etsy/inventory/restore")
def restore_etsy_listing_inventory(listing_id: int, confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the inventory restore")
    try:
        update_etsy_listing_state(str(listing["external_listing_id"]), "active")
        record_etsy_paused(listing_id, False)
    except (EtsyAPIError, ValueError) as failure:
        return RedirectResponse(
            f"/listings?{urlencode({'etsy_error': str(failure)})}", status_code=303
        )
    return RedirectResponse(
        "/listings?etsy_reactivated=1", status_code=303
    )


@app.post("/listings/{listing_id}")
def update_listing_post(
    listing_id: int,
    marketplace: str = Form("Etsy"),
    product: str = Form("Poster"),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    price: str = Form("0.00"),
    listing_status: str = Form("draft"),
):
    current_listing = get_listing(listing_id)
    if current_listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing_status == "published" and current_listing["status"] != "published":
        raise HTTPException(
            status_code=400,
            detail="Use the Etsy publishing section to mark this listing published",
        )
    try:
        update_listing(
            listing_id, marketplace=marketplace.strip() or "Etsy",
            product=product.strip() or "Poster", title=title.strip(),
            description=description.strip(), tags=tags.strip(),
            price_cents=_price_to_cents(price), status=listing_status,
        )
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/publish")
def publish_listing_post(
    listing_id: int,
    marketplace_url: str = Form(...),
    external_listing_id: str = Form(...),
):
    try:
        publish_listing(
            listing_id,
            marketplace_url=marketplace_url,
            external_listing_id=external_listing_id,
        )
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?published=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify")
def save_printify_product_post(
    listing_id: int,
    product_url: str = Form(...),
    product_id: str = Form(...),
    provider: str = Form(...),
    sizes: str = Form(...),
    base_cost: str = Form(...),
):
    try:
        save_printify_product(
            listing_id,
            product_url=product_url,
            product_id=product_id,
            provider=provider,
            sizes=sizes,
            base_cost_cents=_price_to_cents(base_cost),
        )
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _printify_file_options(listing):
    return printify_file_options(listing)


@app.get("/listings/{listing_id}/printify/create")
def create_printify_page(
    request: Request,
    listing_id: int,
    blueprint_id: int | None = None,
    provider_id: int | None = None,
):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    api = PrintifyAPI.from_env()
    token_api = api or PrintifyAPI.with_available_token()
    context = {
        "listing": listing,
        "workflow_nav": _workflow_navigation(
            listing, listing=listing, active_stage="printify"
        ),
        "configured": api is not None,
        "configuration_source": printify_configuration_source(),
        "token_available": token_api is not None,
        "shops": [],
        "blueprints": [], "providers": [], "variants": [],
        "blueprint_id": blueprint_id, "provider_id": provider_id,
        "provider_name": "", "print_files": _printify_file_options(listing),
        "error": None,
    }
    if api is None and token_api is not None:
        try:
            context["shops"] = token_api.list_shops()
        except PrintifyAPIError as error:
            context["error"] = str(error)
    if api is not None:
        try:
            production = get_artwork_production(listing["artwork_code"])
            artwork_orientation = production["orientation"] if production else None
            context["blueprints"] = poster_blueprints(
                api.list_blueprints(), artwork_orientation
            )
            if blueprint_id:
                context["providers"] = api.list_providers(blueprint_id)
            if blueprint_id and provider_id:
                provider = next(
                    (item for item in context["providers"] if item["id"] == provider_id),
                    None,
                )
                if provider is None:
                    raise ValueError("Choose a valid Printify provider")
                context["provider_name"] = provider["title"]
                context["variants"] = []
                available_file_roles = {
                    item["role"] for item in context["print_files"]
                }
                for item in api.list_variants(blueprint_id, provider_id):
                    if not item.get("is_available", True):
                        continue
                    variant = dict(item)
                    expected_role = ratio_role_for_variant(variant.get("title", ""))
                    variant["recommended_file_role"] = (
                        expected_role if expected_role in available_file_roles else None
                    )
                    context["variants"].append(variant)
        except (PrintifyAPIError, ValueError) as error:
            context["error"] = str(error)
    return templates.TemplateResponse(
        request=request, name="printify_create.html", context=context
    )


def _printify_profile_for_orientation(orientation, collection_code=None):
    if not collection_code:
        return None
    collection, _, _ = get_collection(collection_code)
    return (
        automatic_printify_profile(collection, orientation)
        if collection is not None else None
    )


@app.post("/listings/{listing_id}/printify/prepare")
def prepare_printify_product_post(
    listing_id: int,
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the Printify draft setup")
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing["printify_product_id"]:
        raise HTTPException(status_code=400, detail="This listing already has a Printify product")
    readiness = get_listing_readiness(listing_id)
    if not readiness or not readiness["ready"]:
        raise HTTPException(status_code=400, detail="Complete listing readiness first")
    production = get_artwork_production(listing["artwork_code"])
    profile = _printify_profile_for_orientation(
        production["orientation"] if production else "",
        listing["collection_code"],
    )
    if profile is None:
        raise HTTPException(
            status_code=400,
            detail="Automatic Printify setup requires a certified vertical or horizontal orientation",
        )
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")

    try:
        create_automatic_printify_draft(
            api,
            collection=get_collection(listing["collection_code"])[0],
            listing=listing,
            before_save=lambda: clear_inactive_etsy_link(listing_id),
        )
    except (ValueError, PrintifyAPIError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_created=1&automatic=1#one-click-printify",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/configure")
def configure_printify_post(
    listing_id: int,
    api_token: str = Form(...),
    shop_id: str = Form(...),
    remember: bool = Form(False),
):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        configure_printify_runtime(api_token, shop_id)
        if remember:
            save_printify_local_config(api_token, shop_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?configured=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/connect-token")
def connect_printify_token_post(
    listing_id: int,
    api_token: str = Form(...),
    remember: bool = Form(False),
):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        configure_printify_token_runtime(api_token, remember=remember)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?token_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/select-shop")
def select_printify_shop_post(listing_id: int, shop_id: str = Form(...)):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    api = PrintifyAPI.with_available_token()
    if api is None:
        raise HTTPException(status_code=400, detail="Enter the Printify API token first")
    try:
        shops = api.list_shops()
        selected = next(
            (shop for shop in shops if str(shop["id"]) == str(shop_id)), None
        )
        if selected is None:
            raise ValueError("Choose a valid Printify shop")
        complete_printify_runtime(str(selected["id"]))
    except (PrintifyAPIError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?configured=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/replace-token")
def replace_printify_token_post(listing_id: int):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    clear_printify_runtime()
    clear_printify_local_config()
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?replace_token=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/create")
async def create_printify_product_post(request: Request, listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")
    form = await request.form()
    try:
        blueprint_id = int(form["blueprint_id"])
        provider_id = int(form["provider_id"])
        selected_ids = {int(value) for value in form.getlist("variant_ids")}
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Choose a product, provider, and variants") from error

    file_options = {item["role"]: item for item in _printify_file_options(listing)}
    try:
        production = get_artwork_production(listing["artwork_code"])
        artwork_orientation = production["orientation"] if production else None
        providers = api.list_providers(blueprint_id)
        provider = next(item for item in providers if item["id"] == provider_id)
        variants = {
            item["id"]: item for item in api.list_variants(blueprint_id, provider_id)
        }
        selections = []
        for variant_id in selected_ids:
            variant = variants[variant_id]
            selected_orientation = variant_orientation(variant["title"])
            if artwork_orientation in {"horizontal", "vertical", "square"} and (
                selected_orientation != artwork_orientation
            ):
                raise ValueError(
                    f"Choose {artwork_orientation} Printify sizes for this artwork; "
                    f"{variant['title']} is {selected_orientation or 'an unknown orientation'}."
                )
            role = form[f"file_{variant_id}"]
            expected_role = ratio_role_for_variant(variant["title"])
            if expected_role not in file_options:
                raise ValueError(
                    f"No prepared {expected_role or 'ratio'} print file is available for "
                    f"{variant['title']}."
                )
            if role != expected_role:
                raise ValueError(
                    f"Use the {expected_role.replace('ratio:', 'Ratio ')} print file for "
                    f"{variant['title']}."
                )
            file_option = file_options[role]
            selections.append(
                {
                    "variant_id": variant_id,
                    "title": variant["title"],
                    "cost_cents": (
                        int(variant["cost"]) if variant.get("cost") is not None else None
                    ),
                    "price_cents": _price_to_cents(form[f"price_{variant_id}"]),
                    "path": file_option["path"],
                }
            )
        result = create_printify_product(
            api,
            listing=listing,
            blueprint_id=blueprint_id,
            provider_id=provider_id,
            provider_name=provider["title"],
            selections=selections,
        )
        product = result["product"]
        save_printify_product(
            listing_id,
            product_url=result["product_url"],
            product_id=str(product["id"]),
            provider=result["provider"],
            sizes=result["sizes"],
            base_cost_cents=result["base_cost_cents"],
        )
    except (KeyError, StopIteration, ValueError, PrintifyAPIError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_created=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/publish")
def publish_printify_product_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")
    result = request_listing_publication(listing_id, api=api)
    if result["outcome"] != "requested":
        raise HTTPException(status_code=400, detail=result["message"])
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_published=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/publishing/recover")
def recover_listing_publication_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    printify = validate_printify_product(listing)
    if not printify["ready"]:
        raise HTTPException(status_code=400, detail="Create the Printify draft first")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")

    recover_listing_publication(
        listing_id,
        api=api,
        find_candidates=find_etsy_candidates,
        get_remote_listing=get_etsy_listing,
        get_config=etsy_config,
        build_preview=build_etsy_sync_preview,
        sync_listing=sync_etsy_listing,
    )
    return RedirectResponse(
        f"/listings/{listing_id}?recovery_checked=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify-export")
def export_printify_handoff_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        result = build_printify_handoff(listing, get_listing_readiness(listing_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return FileResponse(
        path=result["path"], filename=result["filename"], media_type="application/zip"
    )


@app.post("/listings/{listing_id}/printify-connected")
def mark_printify_connected_post(listing_id: int):
    try:
        mark_printify_etsy_connected(listing_id)
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_connected=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/duplicate")
def duplicate_listing_post(listing_id: int):
    try:
        new_listing_id = duplicate_listing(listing_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{new_listing_id}?duplicated=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/delete")
def delete_listing_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        delete_listing(listing_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        url=f"/artworks/{listing['artwork_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/new")
def new_collection_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="new_collection.html",
        context={},
    )


@app.post("/collections/new")
def create_collection_post(
    code: str = Form(...),
    name: str = Form(...),
    target_artwork_count: int = Form(0),
    collection_status: str = Form("planned"),
    etsy_section_name: str = Form(""),
    description: str = Form(""),
    prompt: str = Form(""),
    price_tier_1: str = Form("29.00"),
    price_tier_2: str = Form("34.00"),
    price_tier_3: str = Form("39.00"),
    price_tier_4: str = Form("46.00"),
    price_tier_5: str = Form("58.00"),
    price_tier_6: str = Form("72.00"),
):
    collection_code = create_collection(
        code=code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
        etsy_section_name=etsy_section_name,
        description=description,
        prompt=prompt,
        default_prices=tuple(
            _price_to_cents(value) for value in (
                price_tier_1, price_tier_2, price_tier_3,
                price_tier_4, price_tier_5, price_tier_6,
            )
        ),
    )

    return RedirectResponse(
        url=f"/collections/{collection_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}")
def collection_page(request: Request, collection_code: str):
    collection, artworks, archived_artworks = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="collection.html",
        context={
            "collection": collection,
            "artworks": artworks,
            "collection_sequence": build_collection_sequence(collection, artworks),
            "archived_artworks": archived_artworks,
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage=""
            ),
        },
    )


@app.get("/collections/{collection_code}/production")
def collection_production_page(request: Request, collection_code: str):
    try:
        collection, items, latest_run = collection_production_overview(
            collection_code
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_production.html",
        context={
            "collection": collection,
            "items": items,
            "latest_run": latest_run,
            "state_labels": STATE_LABELS,
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="production"
            ),
        },
    )


@app.get("/collections/{collection_code}/replacement-restart")
def collection_replacement_restart_page(
    request: Request, collection_code: str
):
    try:
        collection, items, blockers = replacement_restart_overview(
            collection_code
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_replacement_restart.html",
        context={
            "collection": collection,
            "items": items,
            "blockers": blockers,
        },
    )


@app.post("/collections/{collection_code}/replacement-restart")
def collection_replacement_restart_post(
    collection_code: str,
    sources_confirmed: bool = Form(False),
    archive_confirmed: bool = Form(False),
):
    try:
        restart_collection_with_replacement_sources(
            collection_code,
            sources_confirmed=sources_confirmed,
            archive_confirmed=archive_confirmed,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=(
            f"/collections/{collection_code.upper()}/production"
            "?replacement_restarted=1"
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/production/run")
def run_collection_production_post(
    collection_code: str,
    source_approval_confirmed: bool = Form(False),
):
    try:
        run_collection_production(
            collection_code,
            source_approval_confirmed=source_approval_confirmed,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _, items, _ = collection_production_overview(collection_code)
    destination = (
        f"/collections/{collection_code.upper()}/production?ran=1"
        if any(
            item["overall_status"] in {"blocked", "failed"} for item in items
        )
        else f"/collections/{collection_code.upper()}/review?production_complete=1"
    )
    return RedirectResponse(
        url=destination, status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/collections/{collection_code}/production/retry")
def retry_collection_production_post(collection_code: str):
    try:
        run_collection_production(
            collection_code,
            source_approval_confirmed=True,
            retry_failed=True,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _, items, _ = collection_production_overview(collection_code)
    destination = (
        f"/collections/{collection_code.upper()}/production?retried=1"
        if any(
            item["overall_status"] in {"blocked", "failed"} for item in items
        )
        else f"/collections/{collection_code.upper()}/review?production_complete=1"
    )
    return RedirectResponse(
        url=destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}/review")
def collection_review_page(request: Request, collection_code: str):
    try:
        collection, items, visual_review_complete = collection_review_overview(
            collection_code
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_review.html",
        context={
            "collection": collection,
            "items": items,
            "visual_review_complete": visual_review_complete,
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="review"
            ),
        },
    )


@app.post("/collections/{collection_code}/review/{artwork_code}/approve")
def approve_collection_artwork_post(collection_code: str, artwork_code: str):
    try:
        approve_artwork_for_collection(collection_code, artwork_code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _, _, review_complete = collection_review_overview(collection_code)
    destination = (
        f"/collections/{collection_code.upper()}/publish-readiness"
        "?review_complete=1"
        if review_complete
        else f"/collections/{collection_code.upper()}/review"
        f"?approved={artwork_code.upper()}"
    )
    return RedirectResponse(
        destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/review/{artwork_code}/correct")
def send_collection_artwork_back_post(
    collection_code: str,
    artwork_code: str,
    correction_note: str = Form(""),
):
    artwork = get_artwork(artwork_code)
    if artwork is None or artwork["collection_code"] != collection_code.upper():
        raise HTTPException(status_code=404, detail="Artwork not found")
    send_artwork_back(artwork_code, correction_note)
    return RedirectResponse(
        f"/collections/{collection_code.upper()}/review?correction={artwork_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/review/selected")
async def approve_selected_collection_artwork_post(
    collection_code: str, request: Request
):
    form = await request.form()
    selected = [str(value) for value in form.getlist("artwork_codes")]
    if not selected:
        raise HTTPException(status_code=400, detail="Select at least one artwork")
    result = approve_many(collection_code, selected)
    _, _, review_complete = collection_review_overview(collection_code)
    destination = (
        f"/collections/{collection_code.upper()}/publish-readiness"
        f"?review_complete=1"
        if review_complete
        else f"/collections/{collection_code.upper()}/review"
        f"?approved_count={len(result['approved'])}"
        f"&skipped_count={len(result['skipped'])}"
    )
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/collections/{collection_code}/review/eligible")
def approve_all_eligible_collection_artwork_post(collection_code: str):
    result = approve_many(collection_code, [])
    _, _, review_complete = collection_review_overview(collection_code)
    destination = (
        f"/collections/{collection_code.upper()}/publish-readiness"
        f"?review_complete=1"
        if review_complete
        else f"/collections/{collection_code.upper()}/review"
        f"?approved_count={len(result['approved'])}"
        f"&skipped_count={len(result['skipped'])}"
    )
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/collections/{collection_code}/review/ratios/regenerate")
async def regenerate_selected_collection_ratios_post(
    collection_code: str, request: Request
):
    form = await request.form()
    selected = [str(value) for value in form.getlist("artwork_codes")]
    if not selected:
        raise HTTPException(status_code=400, detail="Select at least one artwork")
    result = regenerate_selected_ratio_sets(collection_code, selected)
    params = {}
    if result["successes"]:
        params["ratio_success"] = ", ".join(result["successes"])
    if result["failures"]:
        params["ratio_failure"] = " | ".join(
            f"{item['artwork_code']}: {item['message']}"
            for item in result["failures"]
        )
    return RedirectResponse(
        f"/collections/{collection_code.upper()}/review?{urlencode(params)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/review/collection-cards/refresh")
async def refresh_selected_collection_cards_post(
    collection_code: str, request: Request
):
    form = await request.form()
    selected = [str(value) for value in form.getlist("artwork_codes")]
    if not selected:
        raise HTTPException(status_code=400, detail="Select at least one artwork")
    result = refresh_selected_collection_cards(collection_code, selected)
    params = {}
    if result["successes"]:
        params["collection_card_success"] = ", ".join(result["successes"])
    if result["failures"]:
        params["collection_card_failure"] = " | ".join(
            f"{item['artwork_code']}: {item['message']}"
            for item in result["failures"]
        )
    return RedirectResponse(
        f"/collections/{collection_code.upper()}/review?{urlencode(params)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}/publish-readiness")
def collection_publish_readiness_page(
    request: Request, collection_code: str
):
    try:
        collection, items, counts, ready, latest_run = (
            collection_publish_readiness(collection_code)
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="publish_readiness.html",
        context={
            "collection": collection,
            "items": items,
            "counts": counts,
            "collection_ready": ready,
            "latest_run": latest_run,
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="readiness"
            ),
        },
    )


@app.post("/collections/{collection_code}/publish-readiness/prepare-drafts")
def prepare_collection_listing_drafts_post(collection_code: str):
    try:
        result = prepare_missing_collection_drafts(collection_code)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    params = {
        "draft_created": ",".join(result["created"]),
        "draft_existing": ",".join(result["existing"]),
        "draft_failed": " | ".join(
            f"{item['artwork_code']}: {item['message']}"
            for item in result["failed"]
        ),
    }
    _, _, counts, ready, _ = collection_publish_readiness(collection_code)
    if ready and counts["ready"]:
        destination = (
            f"/collections/{collection_code.upper()}/printify?"
            f"{urlencode(params)}"
        )
    elif ready and counts["printify_linked"]:
        destination = f"/collections/{collection_code.upper()}/publish"
    else:
        destination = (
            f"/collections/{collection_code.upper()}/publish-readiness?"
            f"{urlencode(params)}"
        )
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/collections/{collection_code}/printify")
def collection_printify_review_page(
    request: Request, collection_code: str
):
    try:
        collection, eligible, protected = collection_printify_overview(
            collection_code
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_printify_review.html",
        context={
            "collection": collection,
            "eligible": eligible,
            "protected": protected,
            "configuration_source": printify_configuration_source(),
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="printify"
            ),
        },
    )


@app.post("/collections/{collection_code}/printify")
async def create_collection_printify_drafts_post(
    request: Request, collection_code: str
):
    form = await request.form()
    selected = [str(value) for value in form.getlist("artwork_codes")]
    confirmed = str(form.get("confirmed", "")).lower() in {
        "1", "true", "on", "yes"
    }
    try:
        collection, results = create_selected_printify_drafts(
            collection_code, selected, confirmed=confirmed
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_printify_results.html",
        context={
            "collection": collection,
            "results": results,
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="printify"
            ),
        },
    )


@app.get("/collections/{collection_code}/publish")
def collection_publish_review_page(request: Request, collection_code: str):
    try:
        collection, items = collection_publication_overview(collection_code)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_publish_review.html",
        context={
            "collection": collection,
            "items": items,
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="etsy"
            ),
        },
    )


@app.post("/collections/{collection_code}/publish")
async def collection_publish_post(request: Request, collection_code: str):
    form = await request.form()
    selected = [str(value) for value in form.getlist("listing_ids")]
    confirmed = str(form.get("confirmed", "")).lower() in {
        "1", "true", "on", "yes"
    }
    try:
        collection, results = publish_selected_listings(
            collection_code, selected, confirmed=confirmed
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_publish_results.html",
        context={
            "collection": collection,
            "results": results,
            "mode": "publish",
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="etsy"
            ),
        },
    )


@app.get("/collections/{collection_code}/publish/recover")
def collection_publish_recovery_page(request: Request, collection_code: str):
    try:
        collection, items = collection_recovery_overview(collection_code)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_publish_recovery.html",
        context={
            "collection": collection,
            "items": items,
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="etsy"
            ),
        },
    )


@app.post("/collections/{collection_code}/publish/recover")
async def collection_publish_recovery_post(
    request: Request, collection_code: str
):
    form = await request.form()
    selected = [str(value) for value in form.getlist("listing_ids")]
    try:
        collection, results = recover_selected_listings(
            collection_code, selected
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="collection_publish_results.html",
        context={
            "collection": collection,
            "results": results,
            "mode": "recovery",
            "workflow_navigation": collection_workflow_navigation(
                collection_code, active_stage="etsy"
            ),
        },
    )


@app.get("/collections/{collection_code}/edit")
def edit_collection_form(request: Request, collection_code: str):
    collection, _, _ = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="edit_collection.html",
        context={"collection": collection},
    )


@app.post("/collections/{collection_code}/edit")
def edit_collection_post(
    collection_code: str,
    code: str = Form(""),
    name: str = Form(...),
    target_artwork_count: int = Form(0),
    collection_status: str = Form(...),
    etsy_section_name: str = Form(""),
    description: str = Form(""),
    prompt: str = Form(""),
    price_tier_1: str = Form("29.00"),
    price_tier_2: str = Form("34.00"),
    price_tier_3: str = Form("39.00"),
    price_tier_4: str = Form("46.00"),
    price_tier_5: str = Form("58.00"),
    price_tier_6: str = Form("72.00"),
):
    updated_code = update_collection(
        collection_code=collection_code,
        new_code=code or collection_code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
        etsy_section_name=etsy_section_name,
        description=description,
        prompt=prompt,
        default_prices=tuple(
            _price_to_cents(value) for value in (
                price_tier_1, price_tier_2, price_tier_3,
                price_tier_4, price_tier_5, price_tier_6,
            )
        ),
    )

    return RedirectResponse(
        url=f"/collections?collection={updated_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/archive")
def archive_collection_post(collection_code: str):
    archive_collection(collection_code)

    return RedirectResponse(
        url="/",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/cover")
def upload_collection_cover(collection_code: str, upload: UploadFile = File(...)):
    collection, _, _ = get_collection(collection_code)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG, or WebP image")
    relative = Path("assets") / "collections" / collection_code.upper() / f"collection-cover{suffix}"
    destination = BASE_DIR.parent / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        with Image.open(destination) as image:
            image.verify()
        set_collection_cover(collection_code, str(relative), approved=False)
    except (OSError, UnidentifiedImageError, ValueError) as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()
    return RedirectResponse(
        f"/collections?collection={collection_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/cover/approve")
def approve_collection_cover_post(collection_code: str):
    try:
        approve_collection_cover(collection_code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/collections?collection={collection_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}/cover")
def view_collection_cover(collection_code: str):
    collection, _, _ = get_collection(collection_code)
    if collection is None or not collection["cover_image_path"]:
        raise HTTPException(status_code=404, detail="Collection cover not found")
    path = (BASE_DIR.parent / collection["cover_image_path"]).resolve()
    if BASE_DIR.parent not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Collection cover not found")
    return FileResponse(path)


@app.get("/collections/{collection_code}/new")
def new_artwork_form(request: Request, collection_code: str):
    collection, _, _ = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="new_artwork.html",
        context={"collection": collection},
    )


@app.post("/collections/{collection_code}/new")
def create_artwork_post(
    collection_code: str,
    public_title: str = Form(...),
    description: str = Form(""),
    prompt: str = Form(""),
):
    result = create_artwork_with_workspace(
        collection_code=collection_code,
        public_title=public_title,
        description=description,
        prompt=prompt,
    )

    return RedirectResponse(
        url=f"/artworks/{result['artwork_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/intelligence/analyze")
def analyze_artwork_post(
    artwork_code: str,
    analysis_mode: str = Form("fill_blanks"),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    source = None
    if assignments.get("source") is not None:
        try:
            source = resolve_assigned_file(artwork, assignments.get("source"))
        except ValueError:
            source = None
    result = analyze_artwork(artwork, source)
    if analysis_mode == "replace":
        update_artwork_intelligence(artwork_code, **result)
    else:
        existing = get_artwork_intelligence(artwork_code)
        updates = {
            key: value
            for key, value in result.items()
            if key != "analyzed_at"
            and not str(existing[key] if existing and key in existing.keys() else "").strip()
        }
        if updates and result.get("analyzed_at"):
            updates["analyzed_at"] = result["analyzed_at"]
        update_artwork_intelligence(artwork_code, **updates)
    return RedirectResponse(url=f"/artworks/{artwork_code}?step=intelligence", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/intelligence")
def save_artwork_intelligence_post(
    artwork_code: str,
    theme: str = Form(""), style: str = Form(""), mood: str = Form(""),
    primary_colors: str = Form(""), suggested_room: list[str] = Form([]),
    target_customer: list[str] = Form([]), ai_model: str = Form(""),
    analysis_notes: str = Form(""),
):
    values = {
        "theme": theme.strip(), "style": style.strip(), "mood": mood.strip(),
        "primary_colors": primary_colors.strip(),
        "suggested_room": ", ".join(suggested_room),
        "target_customer": ", ".join(target_customer),
        "ai_model": ai_model.strip(),
        "analysis_notes": analysis_notes.strip(),
    }
    update_artwork_intelligence(artwork_code, **values)
    return RedirectResponse(url=f"/artworks/{artwork_code}?step=intelligence", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/listing-content/generate")
def generate_listing_content_post(
    artwork_code: str,
    generation_mode: str = Form("fill_blanks"),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    intelligence = get_artwork_intelligence(artwork_code)
    result = generate_listing_content(artwork, intelligence)
    if generation_mode == "replace":
        update_artwork_listing_content(artwork_code, **result)
    else:
        existing = get_artwork_listing_content(artwork_code)
        updates = {
            key: value
            for key, value in result.items()
            if key != "generated_at"
            and not str(existing[key] if existing and key in existing.keys() else "").strip()
        }
        if updates and result.get("generated_at"):
            updates["generated_at"] = result["generated_at"]
        update_artwork_listing_content(artwork_code, **updates)
    set_artwork_production_flags(artwork_code, listing_content_ready=True)
    return RedirectResponse(
        url=f"/artworks/{artwork_code}?step=story",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/prepare")
def prepare_artwork_post(
    artwork_code: str,
    price: str = Form(...),
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm automatic preparation")
    price_cents = _price_to_cents(price)
    if price_cents <= 0:
        raise HTTPException(status_code=400, detail="Enter a price greater than $0.00")

    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    production = get_artwork_production(artwork_code)
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    source_assignment = assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload source artwork first")
    if not production["original_approved"]:
        raise HTTPException(status_code=400, detail="Approve the source artwork first")

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    certified_orientation = _certified_orientation(artwork_code)
    if not certified_orientation:
        certification = certify_artwork(source_path).to_dict()
        if not certification["valid"]:
            raise HTTPException(
                status_code=400,
                detail="The source artwork did not pass automatic certification",
            )
        upsert_artwork_certification(artwork_code, certification)
        certified_orientation = certification["orientation"]
        ratio_profile = get_ratio_profile(certified_orientation)
        update_artwork_production(
            artwork_code=artwork_code,
            orientation=certified_orientation,
            master_ratio=ratio_profile["master_ratio"],
            required_ratios=", ".join(ratio_profile["required_ratios"]),
            original_approved=bool(production["original_approved"]),
            print_master_ready=bool(production["print_master_ready"]),
            ratio_exports_ready=bool(production["ratio_exports_ready"]),
            mockups_ready=bool(production["mockups_ready"]),
            listing_content_ready=bool(production["listing_content_ready"]),
            notes=production["notes"] or "",
        )
        production = get_artwork_production(artwork_code)
    if production["orientation"] != certified_orientation:
        raise HTTPException(
            status_code=400,
            detail=f"Orientation must match the certified {certified_orientation} artwork",
        )

    try:
        workspace = get_artwork_folder(artwork)
        if assignments.get("print_master") is None:
            master = build_print_master(artwork, source_path)
            upsert_artwork_file(
                artwork_code=artwork_code,
                role="print_master",
                relative_path=master.relative_path,
                stored_filename=master.master_filename,
                original_filename=source_assignment["original_filename"],
            )
            master_path = workspace / master.relative_path
            upsert_print_master_certification(
                artwork_code, certify_artwork(master_path).to_dict()
            )
            set_artwork_production_flags(artwork_code, print_master_ready=True)

        artwork = get_artwork(artwork_code)
        _generate_required_ratios(artwork, overwrite=False)
        assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
        required_ratios = {
            value.strip()
            for value in (production["required_ratios"] or "").split(",")
            if value.strip()
        }
        if not required_ratios or not all(f"ratio:{ratio}" in assignments for ratio in required_ratios):
            raise ValueError("Not all required ratio files could be generated")

        missing_mockups = [
            slot_key for slot_key in GENERATED_SLOTS
            if f"mockup:{slot_key}" not in assignments
        ]
        if missing_mockups:
            master_assignment = assignments.get("print_master") or source_assignment
            master_path = resolve_assigned_file(artwork, master_assignment)
            for slot_key in missing_mockups:
                result = generate_listing_image(
                    slot_key=slot_key,
                    artwork=_mockup_artwork_payload(artwork),
                    source_path=master_path,
                    output_folder=workspace / "03 Mockups",
                    template_key=DEFAULT_TEMPLATE_PACK,
                )
                upsert_artwork_file(
                    artwork_code=artwork_code,
                    role=result["role"],
                    relative_path=str(result["path"].relative_to(workspace)),
                    stored_filename=result["stored_filename"],
                    original_filename=result["original_filename"],
                )
            save_artwork_mockup_templates(
                artwork_code,
                {slot_key: DEFAULT_TEMPLATE_PACK for slot_key in missing_mockups},
            )

        source_path = resolve_assigned_file(artwork, source_assignment)
        generated_intelligence = analyze_artwork(artwork, source_path)
        existing_intelligence = dict(get_artwork_intelligence(artwork_code))
        intelligence = {
            key: (
                existing_intelligence.get(key)
                if str(existing_intelligence.get(key) or "").strip()
                else value
            )
            for key, value in generated_intelligence.items()
        }
        update_artwork_intelligence(artwork_code, **intelligence)

        generated_listing_content = generate_listing_content(
            artwork, get_artwork_intelligence(artwork_code)
        )
        existing_listing_content = dict(get_artwork_listing_content(artwork_code))
        listing_content = {
            key: (
                existing_listing_content.get(key)
                if str(existing_listing_content.get(key) or "").strip()
                else value
            )
            for key, value in generated_listing_content.items()
        }
        update_artwork_listing_content(artwork_code, **listing_content)
        if not (artwork["story"] or "").strip():
            update_artwork(
                artwork_code,
                artwork["public_title"],
                artwork["working_title"] or "",
                artwork["theme"] or "",
                listing_content["long_story"],
                artwork["prompt"] or "",
                artwork["status"],
            )

        set_artwork_production_flags(
            artwork_code,
            print_master_ready=True,
            ratio_exports_ready=True,
            mockups_ready=True,
            listing_content_ready=True,
        )

        listings = list(get_artwork_listings(artwork_code))
        editable_listing = next(
            (item for item in listings if item["status"] in ("draft", "ready")),
            None,
        )
        if editable_listing:
            prepared_listing_id = editable_listing["id"]
            update_listing(
                editable_listing["id"],
                marketplace=editable_listing["marketplace"],
                product=editable_listing["product"],
                title=editable_listing["title"] or listing_content["etsy_title"],
                description=editable_listing["description"] or listing_content["etsy_description"],
                tags=editable_listing["tags"] or listing_content["etsy_tags"],
                price_cents=price_cents,
                status="ready",
            )
        elif not listings:
            prepared_listing_id = create_listing(
                artwork_code,
                marketplace="Etsy",
                product="Poster",
                title=listing_content["etsy_title"],
                description=listing_content["etsy_description"],
                tags=listing_content["etsy_tags"],
                price_cents=price_cents,
                status="ready",
            )
        else:
            prepared_listing_id = listings[0]["id"]
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/listings/{prepared_listing_id}?prepared=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/listing-content")
def save_listing_content_post(
    artwork_code: str,
    short_story: str = Form(""),
    long_story: str = Form(""),
    etsy_title: str = Form(""),
    etsy_description: str = Form(""),
    etsy_tags: str = Form(""),
    alt_text: str = Form(""),
    keywords: str = Form(""),
):
    values = {
        "short_story": short_story.strip(),
        "long_story": long_story.strip(),
        "etsy_title": etsy_title.strip(),
        "etsy_description": etsy_description.strip(),
        "etsy_tags": etsy_tags.strip(),
        "alt_text": alt_text.strip(),
        "keywords": keywords.strip(),
    }
    update_artwork_listing_content(artwork_code, **values)
    required_ready = all(values[key] for key in ("etsy_title", "etsy_description", "etsy_tags", "alt_text"))
    set_artwork_production_flags(artwork_code, listing_content_ready=required_ready)
    return RedirectResponse(
        url=f"/artworks/{artwork_code}?step=story",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/artworks/{artwork_code}")
def artwork_page(
    request: Request, artwork_code: str,
    step: str = Query("details"),
):
    allowed_steps = {
        "details", "source", "certification", "print", "mockups", "listing", "publish"
    }
    active_step = step if step in allowed_steps else "details"
    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context=_artwork_context(
            artwork_code,
            active_stage=active_step,
            workflow_error=request.query_params.get("workflow_error"),
        ),
    )


@app.post("/artworks/{artwork_code}")
def save_artwork(
    request: Request,
    artwork_code: str,
    public_title: str = Form(...),
    description: str = Form(""),
    prompt: str = Form(""),
    status_value: str = Form(..., alias="status"),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    normalized_status = status_value.strip().lower()

    if normalized_status == "listed":
        context = _artwork_context(artwork_code)
        workflow = context["workflow"]
        current_step = workflow.current_step

        listing_is_ready = (
            current_step is None
            or current_step["key"] == "published"
        )

        if not listing_is_ready:
            missing_steps = [
                step["label"]
                for step in workflow.steps
                if not step["complete"]
                and step["key"] != "published"
            ]

            missing_text = ", ".join(missing_steps)

            message = (
                "This artwork cannot be marked Listed yet. "
                f"Complete: {missing_text}."
            )

            query_string = urlencode({"workflow_error": message})

            return RedirectResponse(
                url=(
                    f"/artworks/{artwork_code.upper()}"
                    f"?{query_string}"
                ),
                status_code=status.HTTP_303_SEE_OTHER,
            )

    update_artwork_details(
        artwork_code=artwork_code,
        public_title=public_title,
        description=description,
        prompt=prompt,
        status=normalized_status,
    )

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=details",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/status")
def save_artwork_status(
    artwork_code: str,
    artwork_status: str = Form(..., alias="status"),
    return_to: str = Form("/collections"),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        update_artwork_status(artwork_code, artwork_status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    safe_return = return_to if return_to.startswith("/") and not return_to.startswith("//") else "/collections"
    return RedirectResponse(url=safe_return, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/production")
def save_artwork_production(
    artwork_code: str,
    orientation: str = Form(""),
    production_notes: str = Form(""),
):
    production = get_artwork_production(artwork_code)
    if production is None:
        raise HTTPException(status_code=404, detail="Artwork production record not found")
    certified_orientation = _certified_orientation(artwork_code)
    if certified_orientation and orientation != certified_orientation:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Orientation is locked to {certified_orientation} by the certified "
                "print-ready file. Replace or rotate that file to change it."
            ),
        )
    effective_orientation = certified_orientation or orientation
    ratio_profile = get_ratio_profile(effective_orientation)

    update_artwork_production(
        artwork_code=artwork_code,
        orientation=effective_orientation,
        master_ratio=ratio_profile["master_ratio"],
        required_ratios=", ".join(ratio_profile["required_ratios"]),
        original_approved=bool(production["original_approved"]),
        print_master_ready=bool(production["print_master_ready"]),
        ratio_exports_ready=bool(production["ratio_exports_ready"]),
        mockups_ready=bool(production["mockups_ready"]),
        listing_content_ready=bool(production["listing_content_ready"]),
        notes=production_notes,
    )

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=print&production_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _replacement_overview(artwork_code: str, *, begin_new: bool = False) -> dict:
    context = _artwork_context(artwork_code, active_stage="source")
    production = context["production"]
    certification = context["certification"]
    summary = context["production_summary"]
    listing = next(
        (
            item for item in context["listings"]
            if item["printify_product_id"] and item["external_listing_id"]
        ),
        None,
    )
    quality_ready = bool(
        certification
        and certification["valid"]
        and certification["score"] >= QUALITY_THRESHOLD
        and production["original_approved"]
    )
    source_assignment = summary["source_assignment"]
    source_updated_at = source_assignment["updated_at"] if source_assignment else None
    dependent_assignments = [
        summary["assignment_map"].get("print_master"),
        *[
            item["assigned"]
            for item in summary["ratio_status"]
        ],
        *[
            item["assignment"]
            for item in summary["mockup_status"]
        ],
    ]
    assets_current = bool(
        source_updated_at
        and all(
            assignment
            and assignment["updated_at"]
            and assignment["updated_at"] >= source_updated_at
            for assignment in dependent_assignments
        )
    )
    files_ready = bool(
        summary["master_ready"]
        and not summary["missing_ratios"]
        and not summary["missing_mockups"]
        and assets_current
    )
    mockups_ready = bool(
        production["mockups_ready"]
        and context["mockup_set_state"]
        and context["mockup_set_state"]["approved_at"]
    )
    sync_needed = bool(
        listing
        and (
            listing["source_update_required"]
            or listing["etsy_images_need_sync"]
        )
    )
    recovery_pending = bool(
        listing
        and (listing["publishing_recovery_stage"] or "").startswith("update_")
        and listing["publishing_recovery_stage"] != "update_complete"
    )
    if not summary["source_ready"]:
        active = "source"
    elif not quality_ready:
        active = "quality"
    elif not files_ready:
        active = "production"
    elif not mockups_ready:
        active = "review"
    elif sync_needed or recovery_pending:
        active = "sync"
    else:
        active = "complete"
    if begin_new and active == "complete":
        active = "source"
    stage_order = ("source", "quality", "production", "review", "sync")
    active_index = stage_order.index(active) if active in stage_order else len(stage_order)
    labels = {
        "source": "Replace source",
        "quality": "Quality",
        "production": "Rebuild files",
        "review": "Review mockups",
        "sync": "Update shops",
    }
    stages = []
    for index, key in enumerate(stage_order):
        if index < active_index or active == "complete":
            state = "complete"
        elif key == active:
            state = "active"
        else:
            state = "pending"
        stages.append({"key": key, "label": labels[key], "state": state})
    return {
        **context,
        "replacement": {
            "active": active,
            "stages": stages,
            "quality_ready": quality_ready,
            "files_ready": files_ready,
            "mockups_ready": mockups_ready,
            "sync_needed": sync_needed,
            "recovery_pending": recovery_pending,
            "listing": listing,
            "candidate_ready": candidate_path(context["artwork"]).is_file(),
        },
    }


@app.get("/artworks/{artwork_code}/replace")
def replace_artwork_page(request: Request, artwork_code: str):
    begin_new = not bool(request.query_params)
    return templates.TemplateResponse(
        request=request,
        name="artwork_replace.html",
        context=_replacement_overview(artwork_code, begin_new=begin_new),
    )


def _mockup_replacement_overview(
    artwork_code: str, *, begin_new: bool = False
) -> dict:
    context = _artwork_context(artwork_code, active_stage="mockups")
    listing = next(
        (
            item for item in context["listings"]
            if item["external_listing_id"]
        ),
        None,
    )
    mockups_complete = not context["production_summary"]["missing_mockups"]
    set_state = context["mockup_set_state"]
    approved = bool(
        mockups_complete
        and context["production"]["mockups_ready"]
        and set_state
        and set_state["approved_at"]
    )
    sync_needed = bool(listing and listing["etsy_images_need_sync"])
    if not mockups_complete:
        active = "replace"
    elif not approved:
        active = "review"
    elif sync_needed:
        active = "sync"
    else:
        active = "complete"
    if begin_new and active == "complete":
        active = "replace"
    order = ("replace", "review", "sync")
    active_index = order.index(active) if active in order else len(order)
    labels = {
        "replace": "Replace images",
        "review": "Review set",
        "sync": "Update Etsy",
    }
    stages = []
    for index, key in enumerate(order):
        state = (
            "complete"
            if index < active_index or active == "complete"
            else ("active" if key == active else "pending")
        )
        stages.append({"key": key, "label": labels[key], "state": state})
    return {
        **context,
        "mockup_replacement": {
            "active": active,
            "stages": stages,
            "complete": mockups_complete,
            "approved": approved,
            "sync_needed": sync_needed,
            "listing": listing,
        },
    }


@app.get("/artworks/{artwork_code}/replace-mockup")
def replace_mockup_page(request: Request, artwork_code: str):
    return templates.TemplateResponse(
        request=request,
        name="mockup_replace.html",
        context=_mockup_replacement_overview(
            artwork_code,
            begin_new=not bool(request.query_params),
        ),
    )


@app.post("/artworks/{artwork_code}/replace-mockup/approve")
def approve_mockup_replacement(
    artwork_code: str,
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Review the complete image set first")
    overview = _mockup_replacement_overview(artwork_code)
    if not overview["mockup_replacement"]["complete"]:
        raise HTTPException(status_code=400, detail="All eight listing images must be present")
    set_state = overview["mockup_set_state"]
    if set_state is None:
        raise HTTPException(status_code=400, detail="Generate a curated mockup set first")
    approve_artwork_mockup_set(artwork_code, set_state["set_id"])
    set_artwork_production_flags(artwork_code, mockups_ready=True)
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}/replace-mockup?reviewed=1#mockup-sync",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/replace-mockup/sync")
def sync_mockup_replacement(
    artwork_code: str,
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the Etsy image update")
    overview = _mockup_replacement_overview(artwork_code)
    if not overview["mockup_replacement"]["approved"]:
        raise HTTPException(status_code=400, detail="Approve the complete image set first")
    listing = overview["mockup_replacement"]["listing"]
    if listing is None:
        raise HTTPException(status_code=400, detail="This artwork is not linked to Etsy")
    try:
        result = sync_etsy_listing_images(get_listing(listing["id"]))
        mark_etsy_synced(listing["id"], result.get("state", ""))
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}/replace-mockup?synced=1#mockup-sync",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/replace/rebuild")
def rebuild_replacement_assets(
    artwork_code: str,
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the local rebuild")
    artwork = get_artwork(artwork_code)
    certification = get_artwork_certification(artwork_code)
    production = get_artwork_production(artwork_code)
    if artwork is None or certification is None:
        raise HTTPException(status_code=400, detail="Complete the quality check first")
    if (
        not certification["valid"]
        or certification["score"] < QUALITY_THRESHOLD
        or not production["original_approved"]
    ):
        raise HTTPException(
            status_code=400,
            detail="Approve a source that passes the quality threshold first",
        )
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork_code)
    }
    source = assignments.get("source")
    if source is None:
        raise HTTPException(status_code=400, detail="Upload the replacement source first")
    try:
        workspace = get_artwork_folder(artwork)
        source_path = resolve_assigned_file(artwork, source)
        master = build_print_master(artwork, source_path)
        upsert_artwork_file(
            artwork_code=artwork_code,
            role="print_master",
            relative_path=master.relative_path,
            stored_filename=master.master_filename,
            original_filename=source["original_filename"],
        )
        upsert_print_master_certification(
            artwork_code,
            certify_artwork(workspace / master.relative_path).to_dict(),
        )
        set_artwork_production_flags(artwork_code, print_master_ready=True)
        _generate_required_ratios(artwork, overwrite=True)
        ensure_mockups(artwork, force=True)
        set_artwork_production_flags(
            artwork_code,
            print_master_ready=True,
            ratio_exports_ready=False,
            mockups_ready=False,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}/replace?rebuilt=1#replacement-review",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/replace/approve")
def approve_replacement_assets(
    artwork_code: str,
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Review the replacement outputs first")
    overview = _replacement_overview(artwork_code)
    if not overview["replacement"]["files_ready"]:
        raise HTTPException(status_code=400, detail="Rebuild the print files first")
    set_state = overview["mockup_set_state"]
    if set_state is None:
        raise HTTPException(status_code=400, detail="Generate the marketplace mockup set first")
    if overview["production_summary"]["missing_mockups"]:
        raise HTTPException(status_code=400, detail="All listing images must be present")
    approve_artwork_mockup_set(artwork_code, set_state["set_id"])
    set_artwork_production_flags(
        artwork_code,
        ratio_exports_ready=True,
        mockups_ready=True,
        listing_content_ready=True,
    )
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}/replace?reviewed=1#replacement-sync",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/files/source")
def upload_source_file(
    artwork_code: str,
    upload: UploadFile = File(...),
    use_as_master: bool = Form(False),
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    previous_production = get_artwork_production(artwork_code)

    try:
        old_candidate = candidate_path(artwork)
        old_approved = old_candidate.with_name(
            f"{artwork_code.upper()}_ai_upscaled_approved.png"
        )
        old_candidate.unlink(missing_ok=True)
        old_approved.unlink(missing_ok=True)
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="source",
        )
        invalidate_artwork_after_source_change(artwork_code)
        if replacement_flow and previous_production["listing_content_ready"]:
            set_artwork_production_flags(artwork_code, listing_content_ready=True)
        upsert_artwork_file(
            artwork_code=artwork_code,
            **saved,
        )
        workspace = get_artwork_folder(artwork)
        source_path = workspace / saved["relative_path"]
        certification = certify_artwork(source_path).to_dict()
        upsert_artwork_certification(artwork_code, certification)

        if use_as_master:
            master = build_print_master(artwork, source_path)
            upsert_artwork_file(
                artwork_code=artwork_code,
                role="print_master",
                relative_path=master.relative_path,
                stored_filename=master.master_filename,
                original_filename=saved["original_filename"],
            )
            set_artwork_production_flags(
                artwork_code,
                print_master_ready=True,
            )
            master_path = workspace / master.relative_path
            upsert_print_master_certification(
                artwork_code,
                certify_artwork(master_path).to_dict(),
            )
            _generate_required_ratios(artwork, overwrite=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    destination = (
        f"/artworks/{artwork_code.upper()}/replace?source_saved=1#replacement-quality"
        if replacement_flow
        else f"/artworks/{artwork_code.upper()}?step=source&file_saved=source"
    )
    return RedirectResponse(
        url=destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/ai-upscale")
def generate_ai_upscale(
    artwork_code: str,
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    production = get_artwork_production(artwork_code)
    if production["ai_enhanced_at"]:
        raise HTTPException(
            status_code=400,
            detail="This source has already been AI enhanced. Upload a new original to reset it.",
        )
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    if "source" not in assignments:
        raise HTTPException(status_code=400, detail="Upload source artwork first")
    try:
        source = resolve_assigned_file(artwork, assignments["source"])
        upscale_candidate(artwork, source)
    except ValueError as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    destination = (
        f"/artworks/{artwork_code.upper()}/replace?ai_upscaled=1#replacement-quality"
        if replacement_flow
        else f"/artworks/{artwork_code.upper()}?step=certification&ai_upscaled=1"
    )
    return RedirectResponse(
        destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/artworks/{artwork_code}/ai-upscale/view")
def view_ai_upscale(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None or not candidate_path(artwork).is_file():
        raise HTTPException(status_code=404, detail="AI upscale not found")
    return FileResponse(candidate_path(artwork), media_type="image/png")


@app.post("/artworks/{artwork_code}/ai-upscale/discard")
def discard_ai_upscale(
    artwork_code: str,
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    candidate_path(artwork).unlink(missing_ok=True)
    destination = (
        f"/artworks/{artwork_code.upper()}/replace?candidate_discarded=1#replacement-quality"
        if replacement_flow
        else f"/artworks/{artwork_code.upper()}?step=certification&candidate_discarded=1"
    )
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/ai-upscale/restore-original")
def restore_original_before_ai_upscale(
    artwork_code: str,
    confirmed: bool = Form(False),
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    backup = original_backup_path(artwork)
    if not confirmed or not backup.is_file():
        raise HTTPException(status_code=400, detail="Saved original is unavailable")
    certification = certify_artwork(backup).to_dict()
    if not certification["valid"]:
        raise HTTPException(status_code=400, detail="Saved original is invalid")
    workspace = get_artwork_folder(artwork)
    invalidate_artwork_after_source_change(artwork_code)
    upsert_artwork_file(
        artwork_code=artwork_code,
        role="source",
        relative_path=str(backup.relative_to(workspace)),
        stored_filename=backup.name,
        original_filename=backup.name,
    )
    upsert_artwork_certification(artwork_code, certification)
    destination = (
        f"/artworks/{artwork_code.upper()}/replace?original_restored=1#replacement-quality"
        if replacement_flow
        else f"/artworks/{artwork_code.upper()}?step=certification&original_restored=1"
    )
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/certification/run")
def run_source_certification(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload source artwork first")
    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
        certification = certify_artwork(source_path).to_dict()
        upsert_artwork_certification(artwork_code, certification)
    except ValueError as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=certification&quality_checked=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/certification/approve")
def approve_current_source_certification(
    artwork_code: str,
    confirmed: bool = Form(False),
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    certification = get_artwork_certification(artwork_code)
    if artwork is None or certification is None:
        raise HTTPException(status_code=400, detail="Certify a source artwork first")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the source review")
    set_artwork_production_flags(artwork_code, original_approved=True)
    destination = (
        f"/artworks/{artwork_code.upper()}/replace?certification_approved=1#replacement-production"
        if replacement_flow
        else f"/artworks/{artwork_code.upper()}?step=certification&certification_approved=1"
    )
    return RedirectResponse(
        destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/ai-upscale/approve")
def approve_ai_upscale(
    artwork_code: str,
    confirmed: bool = Form(False),
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    path = candidate_path(artwork)
    if not confirmed or not path.is_file():
        raise HTTPException(status_code=400, detail="Review and approve the AI upscale first")
    production = get_artwork_production(artwork_code)
    if production["ai_enhanced_at"]:
        raise HTTPException(
            status_code=400,
            detail="This source has already been AI enhanced. Upload a new original to reset it.",
        )
    current_certification = get_artwork_certification(artwork_code)
    workspace = get_artwork_folder(artwork)
    approved_path = path.with_name(f"{artwork_code.upper()}_ai_upscaled_approved.png")
    certification = certify_artwork(path).to_dict()
    if not certification["valid"] or certification["score"] < QUALITY_THRESHOLD:
        raise HTTPException(
            status_code=400,
            detail="The AI-upscaled candidate still does not meet the accepted quality threshold",
        )
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork_code)
    }
    current_source = assignments.get("source")
    if current_source is None:
        raise HTTPException(status_code=400, detail="Upload source artwork first")
    current_source_path = resolve_assigned_file(artwork, current_source)
    backup = original_backup_path(artwork)
    if not backup.is_file():
        with Image.open(current_source_path) as opened:
            opened.convert("RGB").save(backup, "PNG")
    shutil.copy2(path, approved_path)
    invalidate_artwork_after_source_change(artwork_code)
    upsert_artwork_file(
        artwork_code=artwork_code, role="source",
        relative_path=str(approved_path.relative_to(workspace)), stored_filename=approved_path.name,
        original_filename=approved_path.name,
    )
    upsert_artwork_certification(artwork_code, certification)
    master = build_print_master(artwork, approved_path)
    upsert_artwork_file(
        artwork_code=artwork_code, role="print_master", relative_path=master.relative_path,
        stored_filename=master.master_filename, original_filename=path.name,
    )
    upsert_print_master_certification(
        artwork_code, certify_artwork(workspace / master.relative_path).to_dict()
    )
    _generate_required_ratios(artwork, overwrite=True)
    set_artwork_production_flags(
        artwork_code, original_approved=True, print_master_ready=True,
        ratio_exports_ready=False, mockups_ready=False,
    )
    record_ai_enhancement(
        artwork_code,
        original_width=current_certification["width"] if current_certification else 0,
        original_height=current_certification["height"] if current_certification else 0,
        enhanced_width=certification["width"], enhanced_height=certification["height"],
    )
    path.unlink()
    live_listing = next((
        item for item in get_artwork_listings(artwork_code)
        if item["status"] == "published"
        and item["printify_product_id"] and item["external_listing_id"]
    ), None)
    update_pending = False
    if live_listing and not replacement_flow:
        update_result = update_artwork_everywhere(
            artwork_code, live_listing["id"], upload=None, confirmed=True
        )
        update_pending = "update_pending=1" in update_result.headers.get("location", "")
    destination = (
        f"/artworks/{artwork_code.upper()}/replace?ai_upscale_approved=1#replacement-production"
        if replacement_flow
        else (
            f"/artworks/{artwork_code.upper()}?step=certification&ai_upscale_approved=1"
            f"{'&update_pending=1' if update_pending else '&updated_everywhere=1' if live_listing else ''}"
        )
    )
    return RedirectResponse(
        destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _prepare_artwork_update_assets(
    artwork,
    source_path: Path,
    original_filename: str,
) -> None:
    """Preserve the original single-listing preparation behavior."""
    artwork_code = artwork["artwork_code"]
    workspace = get_artwork_folder(artwork)
    certification = certify_artwork(source_path).to_dict()
    if not certification["valid"]:
        raise ValueError("The replacement artwork did not pass certification")
    upsert_artwork_certification(artwork_code, certification)
    refreshed_intelligence = analyze_artwork(artwork, source_path)
    update_artwork_intelligence(artwork_code, **refreshed_intelligence)
    master = build_print_master(artwork, source_path)
    upsert_artwork_file(
        artwork_code=artwork_code, role="print_master",
        relative_path=master.relative_path, stored_filename=master.master_filename,
        original_filename=original_filename,
    )
    master_path = workspace / master.relative_path
    upsert_print_master_certification(
        artwork_code, certify_artwork(master_path).to_dict()
    )
    _generate_required_ratios(artwork, overwrite=True)
    saved_templates = {
        row["slot_key"]: row["template_key"]
        for row in get_artwork_mockup_templates(artwork_code)
    }
    saved_scene_key = saved_templates.get("room", "")
    saved_scene = None
    saved_scene_id = saved_scene_key.removeprefix("scene:")
    if saved_scene_key.startswith("scene:") and saved_scene_id.isdigit():
        saved_scene = get_mockup_scene(int(saved_scene_id))
        if saved_scene is not None and not saved_scene["active"]:
            saved_scene = None
    mockups = generate_mockups(
        artwork=_mockup_artwork_payload(artwork), source_path=master_path,
        output_folder=workspace / "03 Mockups", template_key=DEFAULT_TEMPLATE_PACK,
    )
    for result in mockups:
        upsert_artwork_file(
            artwork_code=artwork_code, role=result["role"],
            relative_path=str(result["path"].relative_to(workspace)),
            stored_filename=result["stored_filename"],
            original_filename=result["original_filename"],
        )
    if saved_scene is not None:
        scene_result = generate_scene_mockup(
            artwork=dict(artwork), source_path=master_path,
            scene_path=MOCKUP_SCENES_DIR / saved_scene["image_path"],
            scene=dict(saved_scene), output_folder=workspace / "03 Mockups",
        )
        upsert_artwork_file(
            artwork_code=artwork_code, role=scene_result["role"],
            relative_path=str(scene_result["path"].relative_to(workspace)),
            stored_filename=scene_result["stored_filename"],
            original_filename=scene_result["original_filename"],
        )
    template_assignments = {
        slot: DEFAULT_TEMPLATE_PACK for slot in GENERATED_SLOTS
    }
    if saved_scene is not None:
        template_assignments["room"] = saved_scene_key
    save_artwork_mockup_templates(artwork_code, template_assignments)


@app.post("/artworks/{artwork_code}/listings/{listing_id}/update-everywhere")
def update_artwork_everywhere(
    artwork_code: str,
    listing_id: int,
    upload: UploadFile | None = File(None),
    confirmed: bool = Form(False),
    prepared: bool = Form(False),
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    listing = get_listing(listing_id)
    if artwork is None or listing is None or listing["artwork_code"] != artwork_code.upper():
        raise HTTPException(status_code=404, detail="Artwork listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Approve the replacement artwork first")
    if not listing["printify_product_id"] or not listing["external_listing_id"]:
        raise HTTPException(status_code=400, detail="Connect both Printify and Etsy before updating everywhere")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Connect Printify before updating everywhere")
    try:
        workspace = get_artwork_folder(artwork)
        if upload and upload.filename:
            saved = save_uploaded_file(artwork=artwork, upload=upload, role="source")
            invalidate_artwork_after_source_change(artwork_code)
            upsert_artwork_file(artwork_code=artwork_code, **saved)
            source_path = workspace / saved["relative_path"]
            original_filename = saved["original_filename"]
        else:
            assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
            if "source" not in assignments:
                raise ValueError("Upload or approve replacement artwork first")
            source_path = resolve_assigned_file(artwork, assignments["source"])
            original_filename = assignments["source"]["original_filename"]
        if not prepared:
            _prepare_artwork_update_assets(
                artwork, source_path, original_filename
            )
        else:
            certification = get_artwork_certification(artwork_code)
            production = get_artwork_production(artwork_code)
            set_state = get_artwork_mockup_set_state(artwork_code)
            if (
                certification is None
                or not certification["valid"]
                or certification["score"] < QUALITY_THRESHOLD
                or not production["original_approved"]
                or not production["print_master_ready"]
                or not production["ratio_exports_ready"]
                or not production["mockups_ready"]
                or set_state is None
                or not set_state["approved_at"]
            ):
                raise ValueError("Finish and approve the replacement review before syncing")
        assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
        files_by_role = {
            role: resolve_assigned_file(artwork, assignment)
            for role, assignment in assignments.items() if role.startswith("ratio:")
        }
        update_printify_product_artwork(
            api, product_id=listing["printify_product_id"], listing=listing,
            files_by_role=files_by_role,
        )
        record_publishing_recovery(
            listing_id, "update_printify_ready",
            "The new artwork is saved in Printify and is ready to publish.",
        )
        set_state = get_artwork_mockup_set_state(artwork_code)
        if set_state is not None and not prepared:
            record_artwork_mockup_set_generated(artwork_code, set_state["set_id"])
        if not prepared:
            set_artwork_production_flags(
                artwork_code, print_master_ready=True, ratio_exports_ready=True,
                mockups_ready=set_state is None, original_approved=True,
            )
        api.publish_product(listing["printify_product_id"], include_images=False)
        mark_printify_publish_requested(listing_id)
        record_publishing_recovery(
            listing_id, "update_waiting_for_printify",
            "Printify is publishing the new artwork. The upload will not be repeated.",
        )
        wait_for_product_unlock(api, listing["printify_product_id"])
        record_publishing_recovery(
            listing_id, "update_waiting_for_etsy",
            "Printify finished. ShangooliOS is applying the final Etsy details.",
        )
        result = sync_etsy_listing(get_listing(listing_id))
        mark_etsy_synced(listing_id, result.get("state", ""))
        record_publishing_recovery(
            listing_id, "update_complete",
            (
                "Printify published the reviewed replacement and Etsy has the final "
                "ShangooliOS details."
                if prepared else
                "Artwork Intelligence was refreshed, Printify published the replacement, "
                "and Etsy has the final ShangooliOS details."
            ),
        )
    except PrintifyPublishPending as failure:
        record_publishing_recovery(
            listing_id, "update_waiting_for_printify", str(failure)
        )
        destination = (
            f"/artworks/{artwork_code.upper()}/replace?update_pending=1#replacement-sync"
            if replacement_flow
            else f"/artworks/{artwork_code.upper()}?step=publish&update_pending=1"
        )
        return RedirectResponse(
            destination,
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, PrintifyAPIError, EtsyAPIError) as failure:
        checkpoint = get_listing(listing_id)["publishing_recovery_stage"]
        if checkpoint in {
            "update_printify_ready", "update_waiting_for_printify", "update_waiting_for_etsy"
        }:
            record_publishing_recovery(listing_id, checkpoint, f"Paused safely: {failure}")
            destination = (
                f"/artworks/{artwork_code.upper()}/replace?update_pending=1#replacement-sync"
                if replacement_flow
                else f"/artworks/{artwork_code.upper()}?step=publish&update_pending=1"
            )
            return RedirectResponse(
                destination,
                status_code=status.HTTP_303_SEE_OTHER,
            )
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    finally:
        if upload:
            upload.file.close()
    destination = (
        f"/artworks/{artwork_code.upper()}/replace?updated_everywhere=1#replacement-sync"
        if replacement_flow
        else f"/artworks/{artwork_code.upper()}?step=publish&updated_everywhere=1"
    )
    return RedirectResponse(
        destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/listings/{listing_id}/update-everywhere/recover")
def recover_artwork_update_everywhere(
    artwork_code: str,
    listing_id: int,
    replacement_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    listing = get_listing(listing_id)
    if artwork is None or listing is None or listing["artwork_code"] != artwork_code.upper():
        raise HTTPException(status_code=404, detail="Artwork listing not found")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Connect Printify before continuing")
    stage = listing["publishing_recovery_stage"] or ""
    try:
        if stage == "update_printify_ready":
            api.publish_product(listing["printify_product_id"], include_images=False)
            mark_printify_publish_requested(listing_id)
            record_publishing_recovery(
                listing_id, "update_waiting_for_printify",
                "Printify is publishing the new artwork. The upload was not repeated.",
            )
            stage = "update_waiting_for_printify"
        if stage == "update_waiting_for_printify":
            wait_for_product_unlock(api, listing["printify_product_id"])
            record_publishing_recovery(
                listing_id, "update_waiting_for_etsy",
                "Printify finished. ShangooliOS is applying the final Etsy details.",
            )
            stage = "update_waiting_for_etsy"
        if stage == "update_waiting_for_etsy":
            result = sync_etsy_listing(get_listing(listing_id))
            mark_etsy_synced(listing_id, result.get("state", ""))
            record_publishing_recovery(
                listing_id, "update_complete",
                "Printify published the replacement and Etsy has the final ShangooliOS details.",
            )
    except PrintifyPublishPending as failure:
        record_publishing_recovery(
            listing_id, "update_waiting_for_printify", str(failure)
        )
    except (ValueError, PrintifyAPIError, EtsyAPIError) as failure:
        current = get_listing(listing_id)["publishing_recovery_stage"] or stage
        record_publishing_recovery(listing_id, current, f"Paused safely: {failure}")
    completed = get_listing(listing_id)["publishing_recovery_stage"] == "update_complete"
    destination = (
        f"/artworks/{artwork_code.upper()}/replace?"
        f"{'updated_everywhere' if completed else 'update_pending'}=1#replacement-sync"
        if replacement_flow
        else (
            f"/artworks/{artwork_code.upper()}?step=publish&"
            f"{'updated_everywhere' if completed else 'update_pending'}=1"
        )
    )
    return RedirectResponse(
        destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/print-master/build")
def create_print_master_from_source(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload source artwork first")

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
        master = build_print_master(artwork, source_path)
        upsert_artwork_file(
            artwork_code=artwork_code,
            role="print_master",
            relative_path=master.relative_path,
            stored_filename=master.master_filename,
            original_filename=source_assignment["original_filename"],
        )
        set_artwork_production_flags(artwork_code, print_master_ready=True)
        master_path = get_artwork_folder(artwork) / master.relative_path
        upsert_print_master_certification(
            artwork_code,
            certify_artwork(master_path).to_dict(),
        )
        _generate_required_ratios(artwork, overwrite=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=print&master_built=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/files/print-master")
def upload_print_master(
    artwork_code: str,
    upload: UploadFile = File(...),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    get_artwork_production(artwork_code)

    try:
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="print_master",
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            **saved,
        )
        workspace = get_artwork_folder(artwork)
        master_path = workspace / saved["relative_path"]
        certification = certify_artwork(master_path).to_dict()
        upsert_print_master_certification(artwork_code, certification)        
        set_artwork_production_flags(
            artwork_code,
            print_master_ready=True,
        )
        _generate_required_ratios(artwork, overwrite=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=print&file_saved=master",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/files/ratio")
def upload_ratio_output(
    artwork_code: str,
    ratio: str = Form(...),
    upload: UploadFile = File(...),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="ratio_output",
            ratio=ratio,
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            **saved,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=print&file_saved=ratio",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/ratios/generate")
def generate_ratio_files(
    request: Request,
    artwork_code: str,
    overwrite_existing: bool = Form(False),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        results = _generate_required_ratios(
            artwork,
            overwrite=overwrite_existing,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context=_artwork_context(
            artwork_code,
            ratio_generation_results=results,
        ),
    )



@app.post("/artworks/{artwork_code}/mockups/generate")
def generate_mockups_post(artwork_code: str, template_key: str = Form(DEFAULT_TEMPLATE_PACK)):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise HTTPException(
            status_code=400,
            detail="Upload an artwork file before generating mockups",
        )

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
        workspace = get_artwork_folder(artwork)
        results = generate_mockups(
            artwork=_mockup_artwork_payload(artwork),
            source_path=source_path,
            output_folder=workspace / "03 Mockups",
            template_key=template_key,
        )
        for result in results:
            upsert_artwork_file(
                artwork_code=artwork_code,
                role=result["role"],
                relative_path=str(result["path"].relative_to(workspace)),
                stored_filename=result["stored_filename"],
                original_filename=result["original_filename"],
            )
        save_artwork_mockup_templates(
            artwork_code,
            {slot_key: template_key for slot_key in GENERATED_SLOTS},
        )
        set_artwork_production_flags(artwork_code, mockups_ready=False)
        invalidate_artwork_mockup_set_approval(artwork_code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=mockups&mockups_generated=8&template_pack={template_key}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/sets/{set_id}/generate")
async def generate_mockup_set_post(artwork_code: str, set_id: int, request: Request):
    artwork = get_artwork(artwork_code)
    mockup_set, items = get_mockup_set(set_id)
    if artwork is None or mockup_set is None:
        raise HTTPException(status_code=404, detail="Artwork or mockup set not found")
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload artwork before generating a set")
    try:
        form = await request.form()
        workspace = get_artwork_folder(artwork)
        source_path = resolve_assigned_file(artwork, source_assignment)
        production = get_artwork_production(artwork_code)
        selected_sources = {}
        for item in items:
            slot = item["slot_key"]
            candidates = _scene_candidates_for_item(item, production["orientation"])
            candidate_ids = {scene["id"] for scene in candidates}
            default_scene_id = item["scene_id"] if item["scene_id"] in candidate_ids else (
                candidates[0]["id"] if candidates else None
            )
            override = str(form.get(f"scene_{slot}") or default_scene_id or "")
            scene = get_mockup_scene(int(override)) if override.isdigit() and int(override) in candidate_ids else None
            if scene is not None:
                result = generate_scene_mockup(
                    artwork=dict(artwork), source_path=source_path,
                    scene_path=MOCKUP_SCENES_DIR / scene["image_path"],
                    scene=dict(scene), output_folder=workspace / "03 Mockups", slot_key=slot,
                )
                selected_sources[slot] = f"scene:{scene['id']}"
            else:
                result = generate_listing_image(
                    slot_key=item["template_slot"], artwork=_mockup_artwork_payload(artwork),
                    source_path=source_path, output_folder=workspace / "03 Mockups",
                    template_key=mockup_set["template_key"], output_slot_key=slot,
                )
                selected_sources[slot] = f"template:{item['template_slot']}"
            upsert_artwork_file(
                artwork_code=artwork_code, role=result["role"],
                relative_path=str(result["path"].relative_to(workspace)),
                stored_filename=result["stored_filename"],
                original_filename=result["original_filename"],
            )
        save_artwork_mockup_order(artwork_code, [item["slot_key"] for item in items])
        save_artwork_mockup_templates(artwork_code, selected_sources)
        record_artwork_mockup_set_generated(artwork_code, set_id)
        set_artwork_production_flags(artwork_code, mockups_ready=False)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=mockups&set_generated=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/sets/{set_id}/approve")
def approve_mockup_set_post(artwork_code: str, set_id: int, crop_reviewed: bool = Form(False)):
    if not crop_reviewed:
        raise HTTPException(status_code=400, detail="Review the Etsy cover crops before approval")
    _, items = get_mockup_set(set_id)
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    if any(f"mockup:{item['slot_key']}" not in assignments for item in items):
        raise HTTPException(status_code=400, detail="Generate every set image before approval")
    try:
        approve_artwork_mockup_set(artwork_code, set_id)
        set_artwork_production_flags(artwork_code, mockups_ready=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=mockups&set_approved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/{slot_key}/scene")
async def generate_scene_mockup_post(artwork_code: str, slot_key: str, request: Request):
    if slot_key not in {"room", "bedroom", "office"}:
        raise HTTPException(status_code=400, detail="Choose a lifestyle-image slot")
    form = await request.form()
    scene_value = str(form.get(f"scene_id_{slot_key}") or "")
    if not scene_value.isdigit():
        raise HTTPException(status_code=400, detail="Choose a reusable scene")
    scene_id = int(scene_value)
    artwork = get_artwork(artwork_code)
    scene = get_mockup_scene(scene_id)
    if artwork is None or scene is None or not scene["active"]:
        raise HTTPException(status_code=404, detail="Artwork or mockup scene not found")
    production = get_artwork_production(artwork_code)
    if scene["orientation"] not in {"any", production["orientation"]}:
        raise HTTPException(
            status_code=400, detail="Choose a scene matching the artwork orientation"
        )
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload artwork before generating a mockup")
    try:
        workspace = get_artwork_folder(artwork)
        result = generate_scene_mockup(
            artwork=_mockup_artwork_payload(artwork),
            source_path=resolve_assigned_file(artwork, source_assignment),
            scene_path=MOCKUP_SCENES_DIR / scene["image_path"],
            scene=dict(scene), output_folder=workspace / "03 Mockups", slot_key=slot_key,
        )
        upsert_artwork_file(
            artwork_code=artwork_code, role=result["role"],
            relative_path=str(result["path"].relative_to(workspace)),
            stored_filename=result["stored_filename"],
            original_filename=result["original_filename"],
        )
        save_artwork_mockup_template(artwork_code, slot_key, f"scene:{scene_id}")
        set_artwork_production_flags(artwork_code, mockups_ready=False)
        invalidate_artwork_mockup_set_approval(artwork_code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=mockups&scene_mockup_generated=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@app.post("/artworks/{artwork_code}/files/mockup")
def upload_mockup_file(
    artwork_code: str,
    slot_key: str = Form(...),
    upload: UploadFile = File(...),
    replacement_flow: bool = Form(False),
    mockup_flow: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    allowed_slots = set(GENERATED_SLOTS)
    if slot_key not in allowed_slots:
        raise HTTPException(status_code=400, detail="Invalid mockup slot")

    try:
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="mockup",
            ratio=slot_key,
        )
        upsert_artwork_file(artwork_code=artwork_code, **saved)
        set_artwork_production_flags(artwork_code, mockups_ready=False)
        invalidate_artwork_mockup_set_approval(artwork_code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    destination = (
        f"/artworks/{artwork_code.upper()}/replace-mockup?mockup_saved={slot_key}#mockup-review"
        if mockup_flow
        else
        f"/artworks/{artwork_code.upper()}/replace?mockup_saved={slot_key}#replacement-review"
        if replacement_flow
        else f"/artworks/{artwork_code.upper()}?step=mockups&mockup_saved={slot_key}"
    )
    return RedirectResponse(
        url=destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/{slot_key}/generate")
async def generate_one_listing_image_post(artwork_code: str, slot_key: str, request: Request):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    if slot_key not in GENERATED_SLOTS:
        raise HTTPException(status_code=400, detail="Invalid listing image slot")

    form = await request.form()
    template_key = str(form.get(f"{slot_key}_template_key") or DEFAULT_TEMPLATE_PACK)

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise HTTPException(
            status_code=400,
            detail="Upload an artwork file before generating listing images",
        )

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
        workspace = get_artwork_folder(artwork)
        result = generate_listing_image(
            slot_key=slot_key,
            artwork=_mockup_artwork_payload(artwork),
            source_path=source_path,
            output_folder=workspace / "03 Mockups",
            template_key=template_key,
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            role=result["role"],
            relative_path=str(result["path"].relative_to(workspace)),
            stored_filename=result["stored_filename"],
            original_filename=result["original_filename"],
        )
        save_artwork_mockup_template(artwork_code, slot_key, template_key)
        set_artwork_production_flags(artwork_code, mockups_ready=False)
        invalidate_artwork_mockup_set_approval(artwork_code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=mockups&listing_image_generated={slot_key}&template_pack={template_key}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/settings")
async def save_mockup_settings(artwork_code: str, request: Request):
    form = await request.form()
    positions = {}
    try:
        for slot_key in GENERATED_SLOTS:
            positions[slot_key] = int(form[f"{slot_key}_position"])
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Every listing image needs an Etsy position") from error

    expected = list(range(1, len(GENERATED_SLOTS) + 1))
    if sorted(positions.values()) != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Use each Etsy position from 1 through {len(GENERATED_SLOTS)} exactly once",
        )

    ordered_slots = [
        slot for slot, _ in sorted(positions.items(), key=lambda item: item[1])
    ]
    save_artwork_mockup_order(artwork_code, ordered_slots)

    context = _artwork_context(artwork_code)
    reviewed = form.get("reviewed") == "true"
    if reviewed and not context["production_summary"]["mockups_complete"]:
        raise HTTPException(
            status_code=400,
            detail="Generate or upload all eight listing images before marking them reviewed",
        )
    set_artwork_production_flags(artwork_code, mockups_ready=reviewed)
    mockup_state = get_artwork_mockup_set_state(artwork_code)
    if reviewed and mockup_state:
        approve_artwork_mockup_set(artwork_code, mockup_state["set_id"])
    elif not reviewed:
        invalidate_artwork_mockup_set_approval(artwork_code)

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=mockups&mockup_settings_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/artworks/{artwork_code}/files/view")
def view_assigned_file(
    artwork_code: str,
    role: str = Query(...),
    download: bool = Query(False),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    assignment = assignments.get(role)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assigned file not found")

    workspace = get_artwork_folder(artwork).resolve()
    file_path = (workspace / assignment["relative_path"]).resolve()
    try:
        file_path.relative_to(workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid file path") from error

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Assigned roles frequently point to newly regenerated files while their
    # public URL stays the same. Prevent the browser from showing the previous
    # mockup after a successful replacement.
    return FileResponse(
        file_path,
        filename=(
            assignment["original_filename"] or assignment["stored_filename"]
            if download else None
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/artworks/{artwork_code}/ratios/review")
def mark_ratio_review(
    artwork_code: str,
    reviewed: bool = Form(False),
):
    set_artwork_production_flags(
        artwork_code,
        ratio_exports_ready=reviewed,
    )
    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=print&ratio_review_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/validate")
def validate_artwork_production(artwork_code: str):
    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=details&validated=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/workspace/refresh")
def refresh_artwork_workspace(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    refresh_workspace(artwork)

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=source&workspace_refreshed=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/workspace/open")
def open_artwork_workspace(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        open_workspace(artwork)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/archive")
def archive_artwork_post(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    archive_artwork(artwork_code)

    return RedirectResponse(
        url=f"/collections/{artwork['collection_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/restore")
def restore_artwork_post(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    restore_artwork(artwork_code)

    return RedirectResponse(
        url=f"/collections/{artwork['collection_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
