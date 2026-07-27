"""Collection-level orchestration for creating unpublished Printify drafts."""

from app.database import get_artwork_folder
from web.db import (
    get_artwork_file_assignments,
    get_artwork_production,
    get_collection,
    get_listing,
    save_printify_product,
)
from web.printify_api import (
    PrintifyAPI,
    PrintifyAPIError,
    PrintifyProductCreationUnknown,
    create_printify_product,
    ratio_role_for_variant,
)
from web.publish_readiness import collection_publish_readiness


HORIZONTAL_PRINTIFY_PROFILE = {
    "orientation": "horizontal",
    "product_name": "Matte Horizontal Posters",
    "blueprint_id": 284,
    "provider_id": 99,
    "provider_name": "Printify Choice",
    "variants": (
        (43163, '14″ x 11″ / Matte', 2900),
        (43166, '18″ x 12″ / Matte', 3400),
        (43169, '20″ x 16″ / Matte', 3900),
        (43172, '24″ x 18″ / Matte', 4600),
        (43175, '30″ x 20″ / Matte', 5800),
        (43178, '36″ x 24″ / Matte', 7200),
    ),
}

VERTICAL_PRINTIFY_PROFILE = {
    "orientation": "vertical",
    "product_name": "Matte Vertical Posters",
    "blueprint_id": 282,
    "provider_id": 99,
    "provider_name": "Printify Choice",
    "variants": (
        (43135, '11″ x 14″ / Matte', 2900),
        (43138, '12″ x 18″ / Matte', 3400),
        (43141, '16″ x 20″ / Matte', 3900),
        (43144, '18″ x 24″ / Matte', 4600),
        (43147, '20″ x 30″ / Matte', 5800),
        (43150, '24″ x 36″ / Matte', 7200),
    ),
}


def automatic_printify_profile(collection, orientation):
    profile = {
        "horizontal": HORIZONTAL_PRINTIFY_PROFILE,
        "vertical": VERTICAL_PRINTIFY_PROFILE,
    }.get(str(orientation or "").strip().lower())
    if profile is None:
        return None
    prices = [
        collection[f"default_price_tier_{tier}_cents"]
        for tier in range(1, 7)
    ]
    return {
        **profile,
        "variants": tuple(
            (variant_id, title, prices[index])
            for index, (variant_id, title, _) in enumerate(profile["variants"])
        ),
    }


def printify_file_options(listing):
    workspace = get_artwork_folder(listing)
    options = []
    for assignment in get_artwork_file_assignments(listing["artwork_code"]):
        role = assignment["role"]
        if role == "print_master" or role.startswith("ratio:"):
            path = workspace / assignment["relative_path"]
            if path.is_file():
                options.append({
                    "role": role,
                    "label": (
                        role.replace("ratio:", "Ratio ")
                        .replace("print_master", "Print-ready file")
                    ),
                    "path": path,
                })
    return options


def _preview_item(collection, readiness):
    listing = get_listing(readiness["listing_id"])
    production = get_artwork_production(readiness["artwork_code"])
    orientation = production["orientation"] if production else ""
    profile = automatic_printify_profile(collection, orientation)
    variants = []
    if profile:
        variants = [
            {
                "id": variant_id,
                "title": title,
                "price_cents": price_cents,
                "ratio_role": ratio_role_for_variant(title),
            }
            for variant_id, title, price_cents in profile["variants"]
        ]
    return {
        **readiness,
        "listing": listing,
        "orientation": orientation,
        "profile": profile,
        "variants": variants,
    }


def collection_printify_overview(collection_code):
    collection, items, _, _, _ = collection_publish_readiness(collection_code)
    eligible = [
        _preview_item(collection, item)
        for item in items
        if item["primary_status"] == "ready"
    ]
    protected = [
        _preview_item(collection, item)
        for item in items
        if item["primary_status"] in {"printify_linked", "etsy_linked"}
    ]
    return collection, eligible, protected


def create_automatic_printify_draft(
    api, collection, listing, *, before_save=None
):
    """Create and immediately persist one unpublished Printify product."""
    production = get_artwork_production(listing["artwork_code"])
    profile = automatic_printify_profile(
        collection, production["orientation"] if production else ""
    )
    if profile is None:
        raise ValueError(
            "Automatic Printify setup requires a certified vertical or "
            "horizontal orientation"
        )

    file_options = {
        item["role"]: item for item in printify_file_options(listing)
    }
    providers = api.list_providers(profile["blueprint_id"])
    provider = next(
        (
            item for item in providers
            if item["id"] == profile["provider_id"]
            and item["title"] == profile["provider_name"]
        ),
        None,
    )
    if provider is None:
        raise ValueError("Printify changed or removed the configured provider")
    variants = {
        item["id"]: item
        for item in api.list_variants(profile["blueprint_id"], provider["id"])
    }
    selections = []
    for variant_id, expected_title, price_cents in profile["variants"]:
        variant = variants.get(variant_id)
        if not variant or variant.get("is_available") is False:
            raise ValueError(f"Printify size is unavailable: {expected_title}")
        if variant.get("title") != expected_title:
            raise ValueError(
                f"Printify changed the catalog size: {expected_title}"
            )
        role = ratio_role_for_variant(expected_title)
        if role not in file_options:
            raise ValueError(
                f"Missing prepared file for {expected_title}: {role}"
            )
        selections.append({
            "variant_id": variant_id,
            "title": expected_title,
            "cost_cents": (
                int(variant["cost"])
                if variant.get("cost") is not None else None
            ),
            "price_cents": price_cents,
            "path": file_options[role]["path"],
        })

    result = create_printify_product(
        api,
        listing=listing,
        blueprint_id=profile["blueprint_id"],
        provider_id=provider["id"],
        provider_name=provider["title"],
        selections=selections,
    )
    product = result["product"]
    if before_save is not None:
        before_save()
    save_printify_product(
        listing["id"],
        product_url=result["product_url"],
        product_id=str(product["id"]),
        provider=result["provider"],
        sizes=result["sizes"],
        base_cost_cents=result["base_cost_cents"],
    )
    return result


def create_selected_printify_drafts(
    collection_code, artwork_codes, *, confirmed, api=None
):
    if not confirmed:
        raise ValueError("Confirm creation of the unpublished Printify drafts")
    selected = list(dict.fromkeys(
        str(code).strip().upper() for code in artwork_codes if str(code).strip()
    ))
    if not selected:
        raise ValueError("Select at least one artwork")

    collection, _, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    printify_api = api or PrintifyAPI.from_env()
    if printify_api is None:
        raise ValueError("Printify API is not configured")

    results = []
    for code in selected:
        # Recompute local state before every external operation.
        _, current_items, _, _, _ = collection_publish_readiness(
            collection["code"]
        )
        current = next(
            (item for item in current_items if item["artwork_code"] == code),
            None,
        )
        if current is None:
            results.append({
                "artwork_code": code,
                "public_title": code,
                "outcome": "skipped",
                "label": "Skipped — not ready",
                "message": "Artwork is not an active member of this collection.",
            })
            continue
        listing = (
            get_listing(current["listing_id"])
            if current["listing_id"] else None
        )
        title = current["public_title"]
        if listing and str(listing["printify_product_id"] or "").strip():
            results.append({
                "artwork_code": code,
                "public_title": title,
                "outcome": "existing",
                "label": "Already on Printify",
                "message": "The existing Printify product was preserved.",
                "product_url": listing["printify_product_url"],
            })
            continue
        if current["primary_status"] != "ready" or listing is None:
            results.append({
                "artwork_code": code,
                "public_title": title,
                "outcome": "skipped",
                "label": "Skipped — not ready",
                "message": "The artwork no longer passes Publish Readiness.",
            })
            continue
        try:
            result = create_automatic_printify_draft(
                printify_api, collection, listing
            )
            results.append({
                "artwork_code": code,
                "public_title": title,
                "outcome": "created",
                "label": "Created",
                "message": "Unpublished Printify product created.",
                "product_url": result["product_url"],
            })
        except PrintifyProductCreationUnknown as error:
            results.append({
                "artwork_code": code,
                "public_title": title,
                "outcome": "unknown",
                "label": "Outcome unknown — manual reconciliation required",
                "message": str(error),
            })
        except (PrintifyAPIError, ValueError, KeyError) as error:
            results.append({
                "artwork_code": code,
                "public_title": title,
                "outcome": "failed",
                "label": "Failed safely",
                "message": str(error),
            })
    return collection, results
