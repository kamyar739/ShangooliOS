"""Collection-level visual review over existing artwork production state."""

from web.db import (
    approve_artwork_mockup_set,
    create_collection_production_run,
    get_artwork,
    get_artwork_certification,
    get_artwork_file_assignments,
    get_artwork_listing_content,
    get_artwork_listings,
    get_artwork_mockup_order,
    get_artwork_mockup_set_state,
    get_artwork_production,
    get_collection,
    get_collection_production_run,
    get_collection_production_run_items,
    invalidate_artwork_mockup_set_approval,
    finish_collection_production_run,
    list_mockup_sets,
    record_artwork_mockup_set_generated,
    set_artwork_production_flags,
    update_collection_production_run_item,
)
from web.local_listings import ensure_local_listing_draft
from web.etsy_validation import (
    ETSY_TAG_MAX_COUNT,
    ETSY_TAG_MAX_LENGTH,
    ETSY_TITLE_MAX_LENGTH,
    parse_tags,
)
from web.mockup_generator import GENERATED_SLOTS
from web.production_tasks import QUALITY_THRESHOLD
from web.production_tasks import regenerate_ratio_set


def _metadata_validation(content):
    blockers = []
    title = str(content["etsy_title"] or "").strip()
    description = str(content["etsy_description"] or "").strip()
    tags = parse_tags(content["etsy_tags"])
    alt_text = str(content["alt_text"] or "").strip()
    if not title:
        blockers.append("Etsy title is missing")
    elif len(title) > ETSY_TITLE_MAX_LENGTH:
        blockers.append(
            f"Etsy title exceeds {ETSY_TITLE_MAX_LENGTH} characters"
        )
    if not description:
        blockers.append("Etsy description is missing")
    if not tags:
        blockers.append("Etsy tags are missing")
    elif len(tags) > ETSY_TAG_MAX_COUNT:
        blockers.append(f"Etsy allows no more than {ETSY_TAG_MAX_COUNT} tags")
    long_tags = [tag for tag in tags if len(tag) > ETSY_TAG_MAX_LENGTH]
    if long_tags:
        blockers.append(
            f"Etsy tags exceed {ETSY_TAG_MAX_LENGTH} characters: "
            + ", ".join(long_tags)
        )
    if not alt_text:
        blockers.append("Image alt text is missing")
    if not str(content["short_story"] or "").strip():
        blockers.append("Short story is missing")
    if not str(content["long_story"] or "").strip():
        blockers.append("Long story is missing")
    return blockers


def _default_mockup_set():
    return next(
        (row for row in list_mockup_sets() if row["name"] == "Etsy Standard"),
        None,
    )


def _production_exception_map(collection_code):
    latest = get_collection_production_run(collection_code)
    if not latest:
        return {}
    return {
        row["artwork_code"]: dict(row)
        for row in get_collection_production_run_items(latest["id"])
    }


def artwork_review_state(collection, artwork, run_item=None):
    code = artwork["artwork_code"]
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(code)
    }
    production = get_artwork_production(code)
    certification = get_artwork_certification(code)
    content = get_artwork_listing_content(code)
    metadata_blockers = _metadata_validation(content)
    required_ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]
    ratio_items = [
        {
            "ratio": ratio,
            "role": f"ratio:{ratio}",
            "exists": f"ratio:{ratio}" in assignments,
        }
        for ratio in required_ratios
    ]
    order = [
        row["slot_key"] for row in get_artwork_mockup_order(code)
    ] or list(GENERATED_SLOTS)
    mockup_items = [
        {
            "slot": slot,
            "role": f"mockup:{slot}",
            "exists": f"mockup:{slot}" in assignments,
        }
        for slot in order
    ]
    all_ratios = bool(ratio_items) and all(item["exists"] for item in ratio_items)
    all_mockups = len(mockup_items) == len(GENERATED_SLOTS) and all(
        item["exists"] for item in mockup_items
    )
    mockup_set = get_artwork_mockup_set_state(code)
    source_passes = bool(
        certification
        and certification["valid"]
        and (certification["score"] or 0) >= QUALITY_THRESHOLD
        and production["original_approved"]
    )
    warnings = list(certification["warnings"] if certification else [])
    production_error = None
    if run_item and run_item["overall_status"] in {"blocked", "failed"}:
        production_error = run_item["error_message"]
    blockers = []
    if not assignments.get("source"):
        blockers.append("Source image is missing")
    elif not source_passes:
        blockers.append("Production source is not approved at passing quality")
    if not production["print_master_ready"] or not assignments.get("print_master"):
        blockers.append("Approved print master is missing")
    if not all_ratios:
        blockers.append("Required ratio files are incomplete")
    if not all_mockups:
        blockers.append("Mockup set is incomplete")
    blockers.extend(metadata_blockers)
    if not collection["default_price_tier_1_cents"]:
        blockers.append("Collection base price is missing")
    if production_error:
        blockers.append(production_error)
    visually_approved = bool(
        production["ratio_exports_ready"]
        and production["mockups_ready"]
        and mockup_set
        and mockup_set["approved_at"]
    )
    approved = bool(
        visually_approved
        and not blockers
    )
    if run_item and run_item["overall_status"] == "needs_correction":
        display_state = "needs_correction"
    elif approved:
        display_state = "approved"
    elif run_item and run_item["overall_status"] == "failed":
        display_state = "failed"
    elif not all_ratios or not all_mockups:
        display_state = "not_generated"
    elif blockers:
        display_state = "blocked"
    else:
        display_state = "ready"
    listings = list(get_artwork_listings(code))
    return {
        "artwork_code": code,
        "public_title": artwork["public_title"],
        "source_status": "Passing" if source_passes else "Needs review",
        "source_warnings": warnings,
        "quality_exception": production_error,
        "ratio_items": ratio_items,
        "mockup_items": mockup_items,
        "all_ratios": all_ratios,
        "all_mockups": all_mockups,
        "metadata_blockers": metadata_blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": warnings,
        "review_status": (
            "needs_correction"
            if run_item and run_item["overall_status"] == "needs_correction"
            else "approved" if approved else "pending"
        ),
        "correction_note": (
            run_item["error_message"]
            if run_item and run_item["overall_status"] == "needs_correction"
            else None
        ),
        "display_state": display_state,
        "visually_approved": visually_approved,
        "approved": approved,
        "listing_exists": bool(listings),
        "listing_id": listings[0]["id"] if listings else None,
        "eligible": not blockers,
    }


def collection_review_overview(collection_code):
    collection, artworks, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    run_items = _production_exception_map(collection_code)
    items = [
        artwork_review_state(
            collection, artwork, run_items.get(artwork["artwork_code"])
        )
        for artwork in artworks
    ]
    ready = bool(items) and all(item["approved"] and item["listing_exists"] for item in items)
    return collection, items, ready


def approve_artwork_for_collection(collection_code, artwork_code):
    collection, artworks, _ = get_collection(collection_code)
    artwork = next(
        (item for item in artworks if item["artwork_code"] == artwork_code.upper()),
        None,
    )
    if collection is None or artwork is None:
        raise ValueError("Artwork is not part of this collection")
    run_item = _production_exception_map(collection_code).get(artwork_code.upper())
    state = artwork_review_state(collection, artwork, run_item)
    if not state["eligible"]:
        raise ValueError("; ".join(state["blockers"]))
    if not state["visually_approved"]:
        mockup_state = get_artwork_mockup_set_state(artwork_code)
        if mockup_state is None:
            default_set = _default_mockup_set()
            if default_set is None:
                raise ValueError("Etsy Standard mockup set is not configured")
            record_artwork_mockup_set_generated(artwork_code, default_set["id"])
            mockup_state = get_artwork_mockup_set_state(artwork_code)
        approve_artwork_mockup_set(artwork_code, mockup_state["set_id"])
        set_artwork_production_flags(
            artwork_code,
            ratio_exports_ready=True,
            mockups_ready=True,
            listing_content_ready=True,
        )
    listings = list(get_artwork_listings(artwork_code))
    if not listings:
        content = get_artwork_listing_content(artwork_code)
        ensure_local_listing_draft(collection, artwork_code, content)
    latest = get_collection_production_run(collection_code)
    if latest:
        update_collection_production_run_item(
            latest["id"], artwork_code,
            ratio_status="complete", mockup_status="complete",
            metadata_status="complete", listing_status="complete",
            overall_status="complete", error_message=None,
        )
    return artwork_review_state(collection, artwork, run_item)


def send_artwork_back(artwork_code, correction_note=""):
    set_artwork_production_flags(
        artwork_code, ratio_exports_ready=False, mockups_ready=False
    )
    invalidate_artwork_mockup_set_approval(artwork_code)
    artwork = get_artwork(artwork_code)
    if artwork:
        latest = get_collection_production_run(artwork["collection_code"])
        if latest is None:
            run_id = create_collection_production_run(
                artwork["collection_code"], True
            )
            finish_collection_production_run(run_id, "needs_review")
        else:
            run_id = latest["id"]
        update_collection_production_run_item(
            run_id, artwork_code,
            ratio_status="needs_review", mockup_status="needs_review",
            overall_status="needs_correction",
            error_message=correction_note.strip() or "Sent back for correction",
        )


def approve_many(collection_code, artwork_codes):
    collection, items, _ = collection_review_overview(collection_code)
    requested = {code.strip().upper() for code in artwork_codes}
    approved, skipped, failed = [], [], []
    for item in items:
        if requested and item["artwork_code"] not in requested:
            continue
        if not item["eligible"]:
            skipped.append(item["artwork_code"])
            continue
        try:
            approve_artwork_for_collection(
                collection["code"], item["artwork_code"]
            )
            approved.append(item["artwork_code"])
        except Exception:
            failed.append(item["artwork_code"])
    return {"approved": approved, "skipped": skipped, "failed": failed}


def regenerate_selected_ratio_sets(collection_code, artwork_codes):
    collection, artworks, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    requested = {code.strip().upper() for code in artwork_codes}
    artwork_map = {row["artwork_code"]: row for row in artworks}
    latest = get_collection_production_run(collection_code)
    successes, failures = [], []
    for code in requested:
        artwork = artwork_map.get(code)
        if artwork is None:
            failures.append({"artwork_code": code, "message": "Artwork not found"})
            continue
        try:
            regenerate_ratio_set(get_artwork(code))
            if latest:
                update_collection_production_run_item(
                    latest["id"], code,
                    ratio_status="needs_review",
                    overall_status="needs_review",
                    error_message="Replacement ratio set generated; visual review remains.",
                )
            successes.append(code)
        except Exception as error:
            failures.append({"artwork_code": code, "message": str(error)})
    return {"successes": sorted(successes), "failures": failures}
