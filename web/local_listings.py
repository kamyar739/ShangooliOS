"""Shared, idempotent creation of local marketplace listing drafts."""

from web.db import (
    create_listing,
    find_artwork_listing_content,
    get_artwork_listings,
)


def ensure_local_listing_draft(collection, artwork_code, content=None):
    """Return an existing listing unchanged or create one from prepared content."""
    existing = list(get_artwork_listings(artwork_code))
    if existing:
        return {
            "status": "existing",
            "listing_id": existing[0]["id"],
            "listing": existing[0],
        }

    prepared = content or find_artwork_listing_content(artwork_code)
    if prepared is None:
        raise ValueError("Prepared listing content is missing")
    required = {
        "Etsy title": prepared["etsy_title"],
        "Etsy description": prepared["etsy_description"],
        "Etsy tags": prepared["etsy_tags"],
    }
    missing = [
        label for label, value in required.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise ValueError("Missing prepared content: " + ", ".join(missing))

    price_cents = int(collection["default_price_tier_1_cents"] or 0)
    if price_cents <= 0:
        raise ValueError("Collection base price is missing")

    listing_id = create_listing(
        artwork_code,
        marketplace="Etsy",
        product="Poster",
        title=str(prepared["etsy_title"]).strip(),
        description=str(prepared["etsy_description"]).strip(),
        tags=str(prepared["etsy_tags"]).strip(),
        price_cents=price_cents,
        status="draft",
    )
    return {
        "status": "created",
        "listing_id": listing_id,
        "listing": None,
    }
