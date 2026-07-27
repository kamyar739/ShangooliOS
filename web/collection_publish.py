"""Collection orchestration around the canonical single-listing engine."""

from web.db import get_artwork_listings, get_collection, get_listing
from web.listing_publication import (
    publication_protection,
    recover_listing_publication,
    request_listing_publication,
)
from web.publish_readiness import collection_publish_readiness


def _item_state(readiness):
    listing = (
        get_listing(readiness["listing_id"])
        if readiness["listing_id"] else None
    )
    if listing is None:
        return {
            **readiness,
            "listing": None,
            "selectable": False,
            "protection": "No local listing is available.",
            "display_icon": "⚠",
            "display_status": "Missing Printify draft",
            "display_class": "missing",
        }
    protected = publication_protection(listing)
    selectable = (
        protected is None
        and readiness["primary_status"] == "printify_linked"
    )
    message = ""
    if protected:
        message = protected["message"]
    elif not selectable:
        message = "The listing does not currently pass publication readiness."
    if protected and protected["outcome"] == "already_published":
        icon, status, css_class = "🌐", "Already published", "published"
    elif protected and protected["outcome"] in {"already_submitted", "unknown"}:
        icon, status, css_class = "⏳", (
            "Manual verification required"
            if protected["outcome"] == "unknown"
            else "Already submitted"
        ), "submitted"
    elif not str(listing["printify_product_id"] or "").strip():
        icon, status, css_class = "⚠", "Missing Printify draft", "missing"
    elif selectable:
        icon, status, css_class = "✓", "Ready", "ready"
    else:
        icon, status, css_class = "⚠", "Not ready", "missing"
    return {
        **readiness,
        "listing": listing,
        "selectable": selectable,
        "protection": message,
        "display_icon": icon,
        "display_status": status,
        "display_class": css_class,
    }


def collection_publication_overview(collection_code):
    collection, readiness, _, _, _ = collection_publish_readiness(
        collection_code
    )
    items = [_item_state(item) for item in readiness]
    _, _, retired = get_collection(collection_code)
    for artwork in retired:
        listings = list(get_artwork_listings(artwork["artwork_code"]))
        listing = next(
            (
                row for row in listings
                if str(row["printify_product_id"] or "").strip()
                or str(row["external_listing_id"] or "").strip()
            ),
            listings[0] if listings else None,
        )
        items.append({
            "artwork_code": artwork["artwork_code"],
            "public_title": artwork["public_title"],
            "artwork_status": "retired",
            "listing": listing,
            "listing_id": listing["id"] if listing else None,
            "printify_product_id": (
                str(listing["printify_product_id"] or "").strip()
                if listing else ""
            ),
            "etsy_listing_id": (
                str(listing["external_listing_id"] or "").strip()
                if listing else ""
            ),
            "selectable": False,
            "protection": "Retired artwork is never published.",
            "display_icon": "🚫",
            "display_status": "Retired",
            "display_class": "retired",
        })
    return collection, items


def publish_selected_listings(collection_code, listing_ids, *, confirmed, api=None):
    if not confirmed:
        raise ValueError("Confirm publication to the connected Etsy sales channel")
    selected = list(dict.fromkeys(
        int(value) for value in listing_ids if str(value).strip()
    ))
    if not selected:
        raise ValueError("Select at least one eligible product")
    collection, items = collection_publication_overview(collection_code)
    allowed = {
        item["listing"]["id"]
        for item in items
        if item["listing"] is not None and item["selectable"]
    }
    results = []
    for listing_id in selected:
        if listing_id not in allowed:
            listing = get_listing(listing_id)
            results.append({
                "listing_id": listing_id,
                "artwork_code": listing["artwork_code"] if listing else "",
                "title": listing["title"] if listing else str(listing_id),
                "outcome": "skipped",
                "label": "Skipped",
                "message": "The listing is not part of this active collection.",
            })
            continue
        results.append(
            request_listing_publication(listing_id, api=api)
        )
    return collection, results


def collection_recovery_overview(collection_code):
    collection, items = collection_publication_overview(collection_code)
    recoverable = [
        item for item in items
        if item["listing"] is not None
        and (
            item["listing"]["printify_publish_requested_at"]
            or item["listing"]["external_listing_id"]
            or item["listing"]["publishing_recovery_stage"]
        )
    ]
    return collection, recoverable


def recover_selected_listings(collection_code, listing_ids, *, api=None):
    selected = list(dict.fromkeys(
        int(value) for value in listing_ids if str(value).strip()
    ))
    if not selected:
        raise ValueError("Select at least one submitted product")
    collection, items = collection_recovery_overview(collection_code)
    allowed = {
        item["listing"]["id"]
        for item in items
        if item["listing"] is not None
    }
    results = []
    for listing_id in selected:
        if listing_id not in allowed:
            listing = get_listing(listing_id)
            results.append({
                "listing_id": listing_id,
                "artwork_code": listing["artwork_code"] if listing else "",
                "title": listing["title"] if listing else str(listing_id),
                "outcome": "skipped",
                "label": "Skipped",
                "message": "This listing is not eligible for collection recovery.",
            })
            continue
        results.append(
            recover_listing_publication(listing_id, api=api)
        )
    return collection, results
