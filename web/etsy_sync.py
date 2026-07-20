from pathlib import Path
from datetime import datetime, timezone

from app.database import get_artwork_folder
from web.etsy_api import (
    create_etsy_shop_section,
    delete_etsy_listing_image,
    get_etsy_listing,
    get_etsy_listing_images,
    get_etsy_listing_inventory,
    list_etsy_shop_listings,
    list_etsy_shop_sections,
    update_etsy_listing,
    update_etsy_listing_inventory,
    update_etsy_listing_section,
    upload_etsy_listing_image,
)
from web.marketplace_export import _ordered_listing_images


def listing_tags(listing) -> list[str]:
    return [tag.strip() for tag in (listing["tags"] or "").split(",") if tag.strip()]


def find_etsy_candidates(listing) -> list[dict]:
    title = (listing["title"] or "").strip().casefold()
    candidates = {
        str(item.get("listing_id")): item
        for item in list_etsy_shop_listings()
        if item.get("listing_id")
    }
    return sorted(
        candidates.values(),
        key=lambda item: (
            0 if (item.get("title") or "").strip().casefold() == title else 1,
            -(item.get("updated_timestamp") or item.get("created_timestamp") or 0),
        ),
    )[:25]


def build_etsy_sync_preview(listing) -> dict:
    external_id = (listing["external_listing_id"] or "").strip()
    if not external_id:
        return {"linked": False, "candidates": find_etsy_candidates(listing)}
    remote = get_etsy_listing(external_id)
    remote_tags = remote.get("tags") or []
    local_tags = listing_tags(listing)
    workspace = get_artwork_folder(listing)
    images = _ordered_listing_images(workspace / "03 Mockups")[:10]
    remote_images = get_etsy_listing_images(external_id)
    inventory = get_etsy_listing_inventory(external_id)
    sections = list_etsy_shop_sections()
    desired_section = (listing["etsy_section_name"] or "").strip()
    current_section = next(
        (
            section.get("title", "")
            for section in sections
            if str(section.get("shop_section_id")) == str(remote.get("shop_section_id"))
        ),
        "Unassigned",
    )
    last_synced = listing["etsy_last_synced_at"] if "etsy_last_synced_at" in listing.keys() else None
    if last_synced:
        synced_at = datetime.fromisoformat(str(last_synced)).replace(tzinfo=timezone.utc).timestamp()
        local_images_changed = any(path.stat().st_mtime > synced_at for path in images)
    else:
        local_images_changed = True
    images_changed = local_images_changed or len(remote_images) != len(images)
    changes = [
        {"field": "Title", "before": remote.get("title", ""), "after": listing["title"],
         "changed": remote.get("title", "") != listing["title"]},
        {"field": "Description", "before": remote.get("description", ""), "after": listing["description"] or "",
         "changed": remote.get("description", "") != (listing["description"] or "")},
        {"field": "Tags / SEO", "before": ", ".join(remote_tags), "after": ", ".join(local_tags),
         "changed": remote_tags != local_tags},
        {"field": "Listing images", "before": f"{len(remote_images)} Etsy image(s)",
         "after": f"{len(images)} curated ShangooliOS image(s)", "changed": images_changed},
        {"field": "Shop section", "before": current_section, "after": desired_section or "Unassigned",
         "changed": bool(desired_section) and current_section.casefold() != desired_section.casefold()},
    ]
    return {
        "linked": True,
        "remote": remote,
        "changes": changes,
        "changed_count": sum(1 for item in changes if item["changed"]),
        "images": images,
        "remote_images": remote_images,
        "images_changed": images_changed,
        "inventory": inventory,
        "inventory_rows": inventory_rows(inventory),
        "sections": sections,
        "desired_section": desired_section,
    }


def sync_etsy_listing(listing) -> dict:
    preview = build_etsy_sync_preview(listing)
    if not preview["linked"]:
        raise ValueError("Link the Printify-created Etsy listing first")
    if not preview["images"]:
        raise ValueError("No curated listing images were found")
    listing_id = str(listing["external_listing_id"])
    desired_section = preview.get("desired_section", "")
    if desired_section:
        section = next(
            (
                item for item in preview.get("sections", [])
                if (item.get("title") or "").strip().casefold() == desired_section.casefold()
            ),
            None,
        )
        if section is None:
            section = create_etsy_shop_section(desired_section)
        section_id = section.get("shop_section_id")
        if not section_id:
            raise ValueError("Etsy did not confirm the shop section")
        if str(preview["remote"].get("shop_section_id")) != str(section_id):
            update_etsy_listing_section(listing_id, int(section_id))
            verified_listing = get_etsy_listing(listing_id)
            if str(verified_listing.get("shop_section_id")) != str(section_id):
                raise ValueError(f"Etsy did not confirm the {desired_section} section assignment")
    update_etsy_listing(
        listing_id,
        title=listing["title"],
        description=listing["description"] or "",
        tags=listing_tags(listing),
    )
    if not preview["images_changed"]:
        return {"listing_id": listing_id, "image_count": 0}
    uploaded_ids = set()
    for rank, image_path in enumerate(preview["images"], start=1):
        result = upload_etsy_listing_image(
            listing_id,
            Path(image_path),
            rank,
            f"{listing['title']} — listing image {rank}",
        )
        if not result.get("listing_image_id"):
            raise ValueError(f"Etsy did not confirm listing image {rank}; no older images were removed")
        uploaded_ids.add(int(result["listing_image_id"]))
    # The upload requests overwrite ranks 1..N. Remove any remaining Printify
    # images only after all curated images have uploaded successfully.
    current_images = get_etsy_listing_images(listing_id)
    for image in current_images:
        image_id = int(image["listing_image_id"])
        if image_id not in uploaded_ids:
            delete_etsy_listing_image(listing_id, image_id)
    return {"listing_id": listing_id, "image_count": len(uploaded_ids)}


def inventory_rows(inventory: dict) -> list[dict]:
    rows = []
    for product in inventory.get("products", []):
        offering = next((item for item in product.get("offerings", []) if item.get("is_enabled")), None)
        if not offering:
            continue
        labels = []
        for value in product.get("property_values", []):
            labels.extend(str(item) for item in value.get("values", []) if str(item).strip())
        price = offering.get("price") or {}
        divisor = int(price.get("divisor") or 100)
        rows.append({
            "product_id": product.get("product_id"),
            "label": " / ".join(labels) or product.get("sku") or "Default variant",
            "sku": product.get("sku") or "",
            "quantity": int(offering.get("quantity") or 0),
            "price": float(price.get("amount") or 0) / divisor,
        })
    return rows


def _inventory_update_payload(inventory: dict, quantity: int) -> dict:
    products = []
    for product in inventory.get("products", []):
        property_values = []
        for value in product.get("property_values", []):
            property_values.append({
                key: value[key]
                for key in ("property_id", "value_ids", "scale_id", "property_name", "values")
                if key in value and value[key] is not None
            })
        offerings = []
        for offering in product.get("offerings", []):
            price = offering.get("price") or {}
            divisor = int(price.get("divisor") or 100)
            normalized = {
                "price": float(price.get("amount") or 0) / divisor,
                "quantity": quantity if offering.get("is_enabled") else int(offering.get("quantity") or 0),
                "is_enabled": bool(offering.get("is_enabled")),
            }
            if offering.get("readiness_state_id") is not None:
                normalized["readiness_state_id"] = offering["readiness_state_id"]
            offerings.append(normalized)
        products.append({
            "sku": product.get("sku") or "",
            "property_values": property_values,
            "offerings": offerings,
        })
    payload = {"products": products}
    for key in (
        "price_on_property", "quantity_on_property", "sku_on_property",
        "readiness_state_on_property",
    ):
        if key in inventory and inventory[key] is not None:
            payload[key] = inventory[key]
    return payload


def set_etsy_inventory_quantity(listing, quantity: int) -> list[dict]:
    if quantity < 1 or quantity > 999:
        raise ValueError("Quantity must be between 1 and 999")
    listing_id = str(listing["external_listing_id"] or "").strip()
    if not listing_id:
        raise ValueError("Link the Etsy listing first")
    current = get_etsy_listing_inventory(listing_id)
    if not inventory_rows(current):
        raise ValueError("No enabled Etsy size variants were found")
    update_etsy_listing_inventory(listing_id, _inventory_update_payload(current, quantity))
    verified = get_etsy_listing_inventory(listing_id)
    rows = inventory_rows(verified)
    if not rows or any(row["quantity"] != quantity for row in rows):
        raise ValueError("Etsy did not confirm the requested quantity for every enabled size")
    return rows
