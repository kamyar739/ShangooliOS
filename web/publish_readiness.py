"""Computed collection readiness for the future Printify handoff."""

from app.database import get_artwork_folder
from web.db import (
    find_artwork_listing_content,
    get_artwork,
    get_artwork_file_assignments,
    get_artwork_listings,
    get_artwork_mockup_set_state,
    get_artwork_production,
    get_collection,
    get_collection_production_run,
    get_collection_production_run_items,
)
from web.etsy_validation import validate_etsy_listing
from web.file_intake import assigned_file_exists
from web.local_listings import ensure_local_listing_draft
from web.production import MOCKUP_SLOTS, parse_required_ratios


PRIMARY_STATUS_LABELS = {
    "ready": "Ready",
    "blocked": "Blocked",
    "needs_review": "Needs Review",
    "printify_linked": "Already Sent to Printify",
    "etsy_linked": "Already Linked to Etsy",
}


def _assignment_exists(artwork, assignment):
    return bool(
        assignment
        and assigned_file_exists(artwork, assignment["relative_path"])
    )


def _listing_for_readiness(artwork_code):
    listings = list(get_artwork_listings(artwork_code))
    if not listings:
        return None
    current = [
        listing for listing in listings if listing["status"] != "archived"
    ]
    candidates = current or listings
    return next(
        (
            listing for listing in candidates
            if str(listing["external_listing_id"] or "").strip()
        ),
        next(
            (
                listing for listing in candidates
                if str(listing["printify_product_id"] or "").strip()
            ),
            candidates[0],
        ),
    )


def _run_item_map(collection_code):
    run = get_collection_production_run(collection_code)
    if run is None:
        return None, {}
    return run, {
        row["artwork_code"]: dict(row)
        for row in get_collection_production_run_items(run["id"])
    }


def artwork_publish_readiness(collection, artwork, run_item=None):
    code = artwork["artwork_code"]
    full_artwork = get_artwork(code)
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(code)
    }
    production = get_artwork_production(code)
    prepared = find_artwork_listing_content(code)
    listing = _listing_for_readiness(code)

    blockers = []
    review_items = []
    warnings = []

    source_exists = _assignment_exists(full_artwork, assignments.get("source"))
    master_exists = _assignment_exists(
        full_artwork, assignments.get("print_master")
    )
    source_approved = bool(production and production["original_approved"])
    master_approved = bool(production and production["print_master_ready"])
    if not source_exists:
        blockers.append("Source artwork file is missing")
    elif not source_approved:
        review_items.append("Source approval is outstanding")
    if not master_exists:
        blockers.append("Print-ready master file is missing")
    elif not master_approved:
        review_items.append("Print-ready master approval is outstanding")

    required_ratios = parse_required_ratios(
        production["required_ratios"] if production else None
    )
    ratio_files = [
        {
            "ratio": ratio,
            "exists": _assignment_exists(
                full_artwork, assignments.get(f"ratio:{ratio}")
            ),
        }
        for ratio in required_ratios
    ]
    ratios_exist = bool(ratio_files) and all(
        item["exists"] for item in ratio_files
    )
    ratios_approved = bool(production and production["ratio_exports_ready"])
    if not required_ratios:
        blockers.append("Required print ratios are not configured")
    elif not ratios_exist:
        blockers.append("Required ratio files are missing")
    elif not ratios_approved:
        review_items.append("Ratio-file approval is outstanding")

    mockup_files = [
        {
            "slot": slot,
            "exists": _assignment_exists(
                full_artwork, assignments.get(f"mockup:{slot}")
            ),
        }
        for slot, _, _ in MOCKUP_SLOTS
    ]
    mockups_exist = all(item["exists"] for item in mockup_files)
    mockup_set = get_artwork_mockup_set_state(code)
    mockups_approved = bool(
        production
        and production["mockups_ready"]
        and (mockup_set is None or mockup_set["approved_at"])
    )
    if not mockups_exist:
        blockers.append("Curated listing images are missing")
    elif not mockups_approved:
        review_items.append("Mockup approval is outstanding")

    content_source = listing or prepared
    title = str(
        content_source["title"] if listing
        else prepared["etsy_title"] if prepared else ""
    ).strip()
    description = str(
        content_source["description"] if listing
        else prepared["etsy_description"] if prepared else ""
    ).strip()
    tags = str(
        content_source["tags"] if listing
        else prepared["etsy_tags"] if prepared else ""
    ).strip()
    price_cents = (
        int(listing["price_cents"] or 0)
        if listing else int(collection["default_price_tier_1_cents"] or 0)
    )
    listing_validation = {
        item["key"]: item
        for item in validate_etsy_listing({
            "title": title,
            "description": description,
            "tags": tags,
            "price_cents": price_cents,
        })
    }
    for key in ("title", "description", "tags", "price"):
        check = listing_validation[key]
        if not check["passed"]:
            blockers.append(check["detail"] or f"{check['label']} is missing")

    alt_text = str(prepared["alt_text"] if prepared else "").strip()
    if not alt_text:
        blockers.append("Image alt text is missing")
    has_story = bool(
        prepared and (
            str(prepared["short_story"] or "").strip()
            or str(prepared["long_story"] or "").strip()
        )
    )
    if not has_story:
        warnings.append(
            "No separate story is saved; the listing description remains publishable."
        )
    if listing is None:
        blockers.append("Local listing draft is missing")

    if (
        run_item
        and run_item["overall_status"] in {"blocked", "failed"}
        and str(run_item["error_message"] or "").strip()
    ):
        blockers.append(str(run_item["error_message"]).strip())

    printify_id = str(
        (listing["printify_product_id"] or "") if listing else ""
    ).strip()
    etsy_id = str(
        (listing["external_listing_id"] or "") if listing else ""
    ).strip()
    if etsy_id:
        primary_status = "etsy_linked"
    elif printify_id:
        primary_status = "printify_linked"
    elif blockers:
        primary_status = "blocked"
    elif review_items:
        primary_status = "needs_review"
    else:
        primary_status = "ready"

    return {
        "artwork_code": code,
        "public_title": artwork["public_title"],
        "artwork_status": artwork["status"],
        "production_status": (
            run_item["overall_status"] if run_item
            else "No production run"
        ),
        "source_exists": source_exists,
        "source_approved": source_approved,
        "master_exists": master_exists,
        "master_approved": master_approved,
        "required_ratios": ratio_files,
        "ratios_exist": ratios_exist,
        "ratios_approved": ratios_approved,
        "mockup_files": mockup_files,
        "mockups_exist": mockups_exist,
        "mockups_approved": mockups_approved,
        "listing_exists": listing is not None,
        "listing_id": listing["id"] if listing else None,
        "listing_status": listing["status"] if listing else "missing",
        "title_ready": listing_validation["title"]["passed"],
        "description_ready": listing_validation["description"]["passed"],
        "tags_ready": listing_validation["tags"]["passed"],
        "alt_text_ready": bool(alt_text),
        "story_ready": has_story,
        "price_cents": price_cents,
        "price_ready": listing_validation["price"]["passed"],
        "printify_product_id": printify_id,
        "etsy_listing_id": etsy_id,
        "blockers": list(dict.fromkeys(blockers)),
        "review_items": list(dict.fromkeys(review_items)),
        "warnings": warnings,
        "primary_status": primary_status,
        "status_label": PRIMARY_STATUS_LABELS[primary_status],
    }


def collection_publish_readiness(collection_code):
    collection, artworks, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    run, run_items = _run_item_map(collection_code)
    items = [
        artwork_publish_readiness(
            collection, artwork, run_items.get(artwork["artwork_code"])
        )
        for artwork in artworks
    ]
    counts = {
        "total": len(items),
        "ready": 0,
        "blocked": 0,
        "needs_review": 0,
        "printify_linked": 0,
        "etsy_linked": 0,
    }
    for item in items:
        counts[item["primary_status"]] += 1
    acceptable = {"ready", "printify_linked", "etsy_linked"}
    collection_ready = bool(items) and all(
        item["primary_status"] in acceptable for item in items
    )
    return collection, items, counts, collection_ready, run


def prepare_missing_collection_drafts(collection_code):
    collection, artworks, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    results = {"created": [], "existing": [], "failed": []}
    for artwork in artworks:
        code = artwork["artwork_code"]
        try:
            result = ensure_local_listing_draft(collection, code)
            results[result["status"]].append(code)
        except Exception as error:
            results["failed"].append({
                "artwork_code": code,
                "message": str(error),
            })
    return results
