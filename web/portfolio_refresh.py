"""Guided orchestration for refreshing existing standalone product slots."""

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import Request, urlopen

from web.db import (
    get_standalone_design,
    list_standalone_design_products,
    replace_standalone_design_source,
    set_standalone_design_refresh_state,
    store_standalone_product_asset_reference,
    update_standalone_design,
    update_standalone_product_copy,
)
from web.printify_api import PrintifyAPI, PrintifyAPIError
from web.product_blueprints import PRODUCT_BLUEPRINTS
from web.etsy_api import (
    delete_etsy_listing_image,
    get_etsy_listing_images,
    upload_etsy_listing_image,
)
from web.standalone_designs import (
    design_metadata_from_message,
    render_quick_text_design,
    save_design_source,
    publish_standalone_product,
    suggested_mug_description,
    suggested_mug_title,
    update_mug_draft_graphics,
)


def refresh_preview(message):
    normalized = "\n".join(
        " ".join(line.split())
        for line in str(message or "").splitlines()
        if line.strip()
    ).strip()
    image = render_quick_text_design(normalized)
    return {
        "message": normalized,
        "metadata": design_metadata_from_message(normalized),
        "image": image,
    }


def refresh_eligibility(design_id):
    products = list_standalone_design_products(design_id)
    supported = set(PRODUCT_BLUEPRINTS)
    eligible = [item for item in products if item["product_type"] in supported]
    blockers = []
    for product in eligible:
        if not product["printify_product_id"]:
            blockers.append(
                f"{PRODUCT_BLUEPRINTS[product['product_type']]['label']} has no Printify product."
            )
        if product["external_state"] in {
            "creating",
            "outcome_unknown",
            "updating",
            "update_outcome_unknown",
        }:
            blockers.append(
                f"{PRODUCT_BLUEPRINTS[product['product_type']]['label']} has an unresolved operation."
            )
    if len(eligible) < 2:
        blockers.append(
            "Portfolio Refresh requires the existing white and Black Accent mug products."
        )
    return {"products": eligible, "blockers": blockers}


def apply_portfolio_refresh(design_id, message, *, confirmed, update_printify=None):
    """Adopt one generated design and update each existing product independently."""
    if not confirmed:
        raise ValueError("Confirm the Portfolio Refresh")
    design = get_standalone_design(design_id)
    if design is None:
        raise ValueError("Design not found")
    eligibility = refresh_eligibility(design_id)
    if eligibility["blockers"]:
        raise ValueError(" ".join(eligibility["blockers"]))
    preview = refresh_preview(message)
    saved = save_design_source(preview["image"], "portfolio-refresh.png")
    metadata = preview["metadata"]
    replace_standalone_design_source(
        design_id,
        source_filename=saved["filename"],
        source_original_filename=saved["original_filename"],
        image_width=saved["width"],
        image_height=saved["height"],
    )
    update_standalone_design(
        design_id,
        name=metadata["name"],
        message=preview["message"],
        description=metadata["description"],
        tags=metadata["tags"],
    )

    results = []
    updater = update_printify or update_mug_draft_graphics
    for product in eligibility["products"]:
        key = product["product_type"]
        try:
            title = suggested_mug_title(preview["message"], key)
            description = suggested_mug_description(
                metadata["description"], key, product["placement_mode"] or "front"
            )
            update_standalone_product_copy(
                design_id, key, title=title, description=description
            )
            result = updater(
                design_id,
                confirmed=True,
                blueprint_key=key,
                source_filename=saved["filename"],
            )
            if result["outcome"] == "updated":
                store_standalone_product_asset_reference(
                    design_id, key, saved["filename"]
                )
            results.append({"product_key": key, **result})
        except ValueError as error:
            results.append(
                {"product_key": key, "outcome": "failed", "message": str(error)}
            )

    failures = [item for item in results if item["outcome"] != "updated"]
    if failures:
        set_standalone_design_refresh_state(
            design_id,
            "needs_review",
            "One or more Printify products needs attention before continuing.",
        )
    else:
        set_standalone_design_refresh_state(
            design_id,
            "awaiting_printify",
            "Review and publish both updated products in Printify, then return here.",
        )
    return results


def publish_portfolio_refresh(design_id, *, confirmed, api=None):
    """Submit each refreshed product through Printify without unsafe retries."""
    if not confirmed:
        raise ValueError("Confirm publishing through Printify")
    eligibility = refresh_eligibility(design_id)
    if eligibility["blockers"]:
        raise ValueError(" ".join(eligibility["blockers"]))
    client = api or PrintifyAPI.from_env()
    if client is None:
        raise ValueError("Connect Printify before publishing")

    results = []
    for product in eligibility["products"]:
        key = product["product_type"]
        results.append(
            publish_standalone_product(
                design_id,
                key,
                confirmed=True,
                api=client,
            )
        )

    if any(item["outcome"] in {"publish_failed", "publish_outcome_unknown"} for item in results):
        set_standalone_design_refresh_state(
            design_id, "needs_review", "One product needs attention. Check each result before retrying."
        )
    else:
        set_standalone_design_refresh_state(
            design_id,
            "awaiting_etsy",
            "Printify accepted both publication requests. Check status to finish Etsy synchronization.",
        )
    return results


def sync_portfolio_refresh_mockups(design_id, product_key, *, api=None):
    """Replace the Etsy gallery with this product's current Printify mockups."""
    product = next(
        (
            item
            for item in list_standalone_design_products(design_id)
            if item["product_type"] == product_key
        ),
        None,
    )
    if product is None or not product["printify_product_id"]:
        raise ValueError("The Printify product is missing")
    if not product["etsy_listing_id"]:
        raise ValueError("Find and link the Etsy listing first")
    client = api or PrintifyAPI.from_env()
    if client is None:
        raise ValueError("Connect Printify before synchronizing mockups")
    remote = client.get_product(product["printify_product_id"])
    images = [item for item in (remote.get("images") or []) if item.get("src")][:10]
    if not images:
        raise ValueError("Printify has not generated the refreshed mockups yet")

    listing_id = str(product["etsy_listing_id"])
    uploaded_ids = set()
    try:
        with TemporaryDirectory(prefix="shangooli-mug-mockups-") as folder:
            for rank, image in enumerate(images, start=1):
                path = Path(folder) / f"mockup-{rank}.jpg"
                request = Request(image["src"], headers={"User-Agent": "ShangooliOS/1.0"})
                with urlopen(request, timeout=60) as response:
                    path.write_bytes(response.read())
                result = upload_etsy_listing_image(
                    listing_id,
                    path,
                    rank,
                    f"{product['title']} — product mockup {rank}",
                )
                if not result.get("listing_image_id"):
                    raise ValueError(f"Etsy did not confirm mockup {rank}")
                uploaded_ids.add(int(result["listing_image_id"]))
    except URLError as error:
        raise ValueError("A refreshed Printify mockup could not be downloaded") from error

    for image in get_etsy_listing_images(listing_id):
        image_id = int(image["listing_image_id"])
        if image_id not in uploaded_ids:
            delete_etsy_listing_image(listing_id, image_id)
    return {"listing_id": listing_id, "image_count": len(uploaded_ids)}
