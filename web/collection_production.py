"""Collection-level orchestration over durable artwork production states."""

from web.db import (
    create_collection_production_run,
    finish_collection_production_run,
    get_artwork,
    get_artwork_certification,
    get_artwork_file_assignments,
    get_artwork_intelligence,
    get_artwork_listing_content,
    get_artwork_listings,
    get_artwork_production,
    get_collection,
    get_collection_production_run,
    get_collection_production_run_items,
    update_collection_production_run_item,
)
from web.local_listings import ensure_local_listing_draft
from web.production_tasks import (
    QUALITY_THRESHOLD,
    approve_certified_source,
    ensure_mockups,
    ensure_print_master,
    ensure_ratio_files,
    ensure_source_certification,
)
from web.ratio_generator import resolve_assigned_file


STATE_LABELS = {
    "complete": "Complete",
    "created": "Created",
    "pending": "Pending",
    "ready": "Ready",
    "needs_review": "Needs review",
    "blocked": "Blocked",
    "failed": "Failed",
    "skipped": "Skipped",
}


def _metadata_check(artwork_code):
    artwork = get_artwork(artwork_code)
    intelligence = get_artwork_intelligence(artwork_code)
    content = get_artwork_listing_content(artwork_code)
    required = {
        "artwork description": artwork["description"],
        "artwork prompt": artwork["prompt"],
        "theme": intelligence["theme"],
        "style": intelligence["style"],
        "mood": intelligence["mood"],
        "short story": content["short_story"],
        "long story": content["long_story"],
        "Etsy title": content["etsy_title"],
        "Etsy description": content["etsy_description"],
        "Etsy tags": content["etsy_tags"],
        "image alt text": content["alt_text"],
        "keywords": content["keywords"],
    }
    missing = [
        label for label, value in required.items()
        if not str(value or "").strip()
    ]
    return (not missing), missing, content


def _live_states(collection, artwork):
    code = artwork["artwork_code"]
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(code)
    }
    production = get_artwork_production(code)
    certification = get_artwork_certification(code)
    source_status = "complete" if assignments.get("source") else "blocked"
    certification_status = "pending"
    if certification:
        certification_status = (
            "complete"
            if certification["valid"]
            and (certification["score"] or 0) >= QUALITY_THRESHOLD
            else "needs_review"
        )
    print_master_status = (
        "complete" if assignments.get("print_master") else "pending"
    )
    required_ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]
    ratios_exist = bool(required_ratios) and all(
        f"ratio:{ratio}" in assignments for ratio in required_ratios
    )
    ratio_status = (
        "complete" if ratios_exist and production["ratio_exports_ready"]
        else "needs_review" if ratios_exist else "pending"
    )
    mockups_exist = all(
        f"mockup:{slot}" in assignments
        for slot in (
            "hero", "room", "bedroom", "office", "detail", "sizes",
            "how_it_works", "collection",
        )
    )
    mockup_status = (
        "complete" if mockups_exist and production["mockups_ready"]
        else "needs_review" if mockups_exist else "pending"
    )
    metadata_valid, missing_metadata, _ = _metadata_check(code)
    metadata_status = "complete" if metadata_valid else "blocked"
    listings = list(get_artwork_listings(code))
    if listings:
        listing_status = "complete"
    elif not collection["default_price_tier_1_cents"]:
        listing_status = "blocked"
    elif metadata_valid:
        listing_status = "ready"
    else:
        listing_status = "blocked"
    exceptions = []
    if source_status == "blocked":
        exceptions.append("Source image is missing")
    if certification_status == "needs_review":
        exceptions.append("Source quality requires review")
    if missing_metadata:
        exceptions.append("Missing metadata: " + ", ".join(missing_metadata))
    if not collection["default_price_tier_1_cents"]:
        exceptions.append("Collection base price is missing")
    overall = (
        "blocked" if source_status == "blocked" or listing_status == "blocked"
        else "needs_review"
        if "needs_review" in (certification_status, ratio_status, mockup_status)
        else "complete"
    )
    return {
        "artwork_code": code,
        "public_title": artwork["public_title"],
        "source_status": source_status,
        "certification_status": certification_status,
        "print_master_status": print_master_status,
        "ratio_status": ratio_status,
        "mockup_status": mockup_status,
        "metadata_status": metadata_status,
        "listing_status": listing_status,
        "overall_status": overall,
        "source_used": (
            "ai_upscale_4x"
            if assignments.get("source")
            and "_ai_upscaled_approved" in assignments["source"]["stored_filename"]
            else "original" if assignments.get("source") else None
        ),
        "error_message": " · ".join(exceptions) or None,
    }


def collection_production_overview(collection_code):
    collection, artworks, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    latest = get_collection_production_run(collection_code)
    states = [_live_states(collection, artwork) for artwork in artworks]
    if latest:
        persisted = {
            row["artwork_code"]: dict(row)
            for row in get_collection_production_run_items(latest["id"])
        }
        for item in states:
            saved = persisted.get(item["artwork_code"])
            if saved and saved["overall_status"] in {"failed", "blocked"}:
                item.update({
                    key: saved[key]
                    for key in (
                        "source_status", "certification_status",
                        "print_master_status", "ratio_status", "mockup_status",
                        "metadata_status", "listing_status", "overall_status",
                        "error_message",
                    )
                })
    return collection, states, latest


def _process_artwork(run_id, collection, artwork):
    code = artwork["artwork_code"]
    artwork = get_artwork(code)
    states = _live_states(collection, artwork)
    try:
        certification, source, source_path, source_used = (
            ensure_source_certification(artwork)
        )
        states["source_status"] = "complete"
        states["certification_status"] = "complete"
        states["source_used"] = source_used
        approve_certified_source(artwork, certification)

        states["print_master_status"] = ensure_print_master(
            artwork, source, source_path
        )
        states["ratio_status"] = ensure_ratio_files(artwork)
        states["mockup_status"] = ensure_mockups(artwork)

        metadata_valid, missing, content = _metadata_check(code)
        states["metadata_status"] = "complete" if metadata_valid else "blocked"
        listings = list(get_artwork_listings(code))
        if listings:
            states["listing_status"] = "complete"
        elif not collection["default_price_tier_1_cents"]:
            states["listing_status"] = "blocked"
            missing.append("collection base price")
        elif metadata_valid:
            ensure_local_listing_draft(collection, code, content)
            states["listing_status"] = "created"
        else:
            states["listing_status"] = "blocked"

        if missing:
            states["overall_status"] = "blocked"
            states["error_message"] = "Missing: " + ", ".join(missing)
        else:
            # Ratio and mockup files deliberately await the next sprint's
            # consolidated visual approval.
            states["ratio_status"] = (
                "complete"
                if get_artwork_production(code)["ratio_exports_ready"]
                else "needs_review"
            )
            states["mockup_status"] = (
                "complete"
                if get_artwork_production(code)["mockups_ready"]
                else "needs_review"
            )
            states["overall_status"] = (
                "needs_review"
                if "needs_review" in (
                    states["ratio_status"], states["mockup_status"]
                )
                else "complete"
            )
            states["error_message"] = (
                "Visual approval remains for ratio files and mockups."
                if states["overall_status"] == "needs_review" else None
            )
    except Exception as error:
        message = str(error)
        if "Source" in message or "quality" in message or "certification" in message:
            states["source_status"] = (
                "blocked" if "missing" in message else states["source_status"]
            )
            states["certification_status"] = "needs_review"
            states["overall_status"] = "blocked"
        else:
            states["overall_status"] = "failed"
        states["error_message"] = message
    update_collection_production_run_item(run_id, code, **{
        key: states[key] for key in (
            "source_status", "certification_status", "print_master_status",
            "ratio_status", "mockup_status", "metadata_status",
            "listing_status", "overall_status", "source_used", "error_message",
        )
    })
    return states


def run_collection_production(
    collection_code, *, source_approval_confirmed, retry_failed=False
):
    if not source_approval_confirmed:
        raise ValueError("Confirm the intended final source images first")
    collection, artworks, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    latest = get_collection_production_run(collection_code)
    if latest and (retry_failed or latest["status"] == "running"):
        run_id = latest["id"]
    else:
        run_id = create_collection_production_run(collection_code, True)
    prior = {
        row["artwork_code"]: row
        for row in get_collection_production_run_items(run_id)
    }
    results = []
    for artwork in artworks:
        previous = prior.get(artwork["artwork_code"])
        if retry_failed and previous and previous["overall_status"] != "failed":
            continue
        results.append(_process_artwork(run_id, collection, artwork))
    rows = get_collection_production_run_items(run_id)
    if any(row["overall_status"] == "failed" for row in rows):
        run_status = "failed"
    elif any(row["overall_status"] in {"blocked", "needs_review"} for row in rows):
        run_status = "needs_review"
    else:
        run_status = "complete"
    finish_collection_production_run(run_id, run_status)
    return run_id, results
