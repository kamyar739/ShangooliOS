#!/usr/bin/env python3
"""Export active Black Accent mugs and exact local images to shangooli.com."""

from __future__ import annotations

import json
import hashlib
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "shangooli.db"
GALLERY_ROOT = ROOT / "assets" / "designs" / "galleries"
SITE_ROOT = ROOT / "marketing-site"
SITE_IMAGES = SITE_ROOT / "public" / "images" / "mugs"
INVENTORY_PATH = SITE_ROOT / "app" / "storefront-inventory.json"
COLLECTIONS_PATH = SITE_ROOT / "app" / "storefront-collections.json"
AUDIT_PATH = SITE_ROOT / "storefront-image-audit.json"


def export_storefront_inventory():
    try:
        previous_inventory = {
            int(item["id"]): item for item in json.loads(INVENTORY_PATH.read_text())
        }
    except (OSError, ValueError, KeyError, TypeError):
        previous_inventory = {}
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT d.id, d.name, d.message, d.display_order,
               LOWER(COALESCE(c.code, 'EVERYDAY')) AS collection_code,
               COALESCE(c.name, 'Everyday Mugs') AS collection_name,
               p.etsy_listing_id, p.price_cents,
               p.product_thumbnail_filename
        FROM standalone_designs AS d
        LEFT JOIN mug_collections AS c ON c.id = d.mug_collection_id
        JOIN standalone_design_products AS p ON p.design_id = d.id
        WHERE p.product_type = 'mug_11oz_black_accent'
          AND LOWER(COALESCE(p.etsy_state, '')) = 'active'
          AND p.etsy_paused_at IS NULL
        ORDER BY CASE WHEN d.display_order = 0 THEN 1 ELSE 0 END,
                 d.display_order, d.id
        """
    ).fetchall()
    collection_rows = connection.execute(
        """
        SELECT LOWER(code) AS code, name, profession, description, status
        FROM mug_collections
        WHERE status IN ('active', 'planning')
        ORDER BY display_order, name COLLATE NOCASE
        """
    ).fetchall()
    connection.close()

    products = []
    missing = []
    seen_listings = set()
    SITE_IMAGES.mkdir(parents=True, exist_ok=True)
    for row in rows:
        listing_id = str(row["etsy_listing_id"] or "").strip()
        filename = str(row["product_thumbnail_filename"] or "").strip()
        source = GALLERY_ROOT / filename
        problems = []
        if not listing_id:
            problems.append("missing Etsy listing ID")
        elif listing_id in seen_listings:
            problems.append("duplicate Etsy listing ID")
        if not filename or not source.is_file():
            problems.append("missing local right-side image")
        if problems:
            missing.append(
                {"design_id": row["id"], "name": row["name"], "problems": problems}
            )
            continue
        seen_listings.add(listing_id)
        legacy_filename = f"design-{row['id']}-black-accent-right-side.jpg"
        previous_image = str(previous_inventory.get(int(row["id"]), {}).get("image") or "")
        previous_filename = Path(previous_image).name if previous_image.startswith("/images/mugs/") else ""
        previous_path = SITE_IMAGES / previous_filename if previous_filename else None
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        previous_matches = (
            previous_path is not None
            and previous_path.is_file()
            and hashlib.sha256(previous_path.read_bytes()).hexdigest() == source_digest
        )
        # Preserve stable URLs while an image is unchanged. When a corrected
        # Printify render replaces an existing file, use a content-versioned
        # URL so the public custom-domain cache cannot serve the former image.
        if previous_matches and not (
            previous_filename == legacy_filename and "corrected" in source.stem
        ):
            storefront_filename = previous_filename
        elif previous_filename:
            storefront_filename = (
                f"design-{row['id']}-black-accent-right-side-{source_digest[:10]}.jpg"
            )
        else:
            storefront_filename = legacy_filename
        shutil.copy2(source, SITE_IMAGES / storefront_filename)
        products.append(
            {
                "id": row["id"],
                "message": row["message"] or row["name"],
                "listingId": listing_id,
                "image": f"/images/mugs/{storefront_filename}",
                "price": f"{int(row['price_cents']) / 100:.2f}",
                "collection": row["collection_code"],
                "collectionName": row["collection_name"],
            }
        )

    audit = {
        "active_black_accent_count": len(rows),
        "exported_count": len(products),
        "missing_or_invalid": missing,
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2) + "\n")
    if missing or len(products) != len(rows):
        raise ValueError(json.dumps(audit, indent=2))
    INVENTORY_PATH.write_text(json.dumps(products, indent=2) + "\n")
    COLLECTIONS_PATH.write_text(
        json.dumps([dict(row) for row in collection_rows], indent=2) + "\n"
    )
    return audit


def main():
    audit = export_storefront_inventory()
    print(json.dumps(audit))


if __name__ == "__main__":
    main()
