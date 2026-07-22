import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_artwork_folder
from web.production import MOCKUP_SLOTS
from web.db import get_artwork_file_assignments, get_artwork_mockup_order


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return cleaned.strip("-") or "marketplace"


def _ordered_listing_images(mockup_folder: Path) -> list[Path]:
    if not mockup_folder.is_dir():
        return []

    images = [
        path
        for path in mockup_folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    slot_positions = {slot: position for position, (slot, _, _) in enumerate(MOCKUP_SLOTS)}

    def image_slot(path: Path) -> str | None:
        stem = path.stem.lower()
        return next(
            (
                slot for slot in slot_positions
                if f"_listing_{slot}_" in stem or stem.endswith(f"_listing_{slot}")
            ),
            None,
        )

    def sort_key(path: Path):
        slot = image_slot(path)
        return (slot_positions.get(slot, len(slot_positions)), path.name.lower())

    # Old template variants can remain on disk after a style is changed. Keep
    # only the newest file for each listing slot so obsolete duplicates do not
    # accumulate on Etsy.
    selected_by_slot: dict[str, Path] = {}
    unassigned: list[Path] = []
    for path in images:
        slot = image_slot(path)
        if slot is None:
            unassigned.append(path)
            continue
        current = selected_by_slot.get(slot)
        if current is None or (path.stat().st_mtime, path.name.lower()) > (
            current.stat().st_mtime,
            current.name.lower(),
        ):
            selected_by_slot[slot] = path

    # Once slot-based listing images exist, loose legacy mockups are archival
    # workspace files rather than customer-facing Etsy images.
    selected = list(selected_by_slot.values()) if selected_by_slot else unassigned
    return sorted(selected, key=sort_key)


def ordered_listing_images_for_artwork(artwork) -> list[Path]:
    """Resolve the eight active assignments in the artwork's saved Etsy order."""
    workspace = get_artwork_folder(artwork)
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork["artwork_code"])
    }
    saved_order = [row["slot_key"] for row in get_artwork_mockup_order(artwork["artwork_code"])]
    default_order = [slot for slot, _, _ in MOCKUP_SLOTS]
    ordered_slots = saved_order or default_order
    images = []
    for slot in ordered_slots:
        assignment = assignments.get(f"mockup:{slot}")
        if assignment is None:
            continue
        path = workspace / assignment["relative_path"]
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(path)
    return images or _ordered_listing_images(workspace / "03 Mockups")


def inspect_listing_export(listing, readiness: dict) -> dict:
    workspace = get_artwork_folder(listing)
    images = ordered_listing_images_for_artwork(listing)
    blockers = [
        item.get("detail") or item["label"]
        for item in readiness["items"]
        if not item["passed"]
    ]
    if not images and "Listing images" not in blockers:
        blockers.append("Listing image files")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "images": images,
        "image_count": len(images),
        "export_folder": workspace / "04 Exports",
    }


def build_listing_export(listing, readiness: dict) -> dict:
    export_state = inspect_listing_export(listing, readiness)
    if not export_state["ready"]:
        raise ValueError(
            "Complete the publishing checklist first: "
            + ", ".join(export_state["blockers"])
        )

    export_folder = export_state["export_folder"]
    export_folder.mkdir(parents=True, exist_ok=True)
    marketplace_slug = _slug(listing["marketplace"])
    archive_name = (
        f"{listing['artwork_code']}_listing_{listing['id']}_{marketplace_slug}.zip"
    )
    archive_path = export_folder / archive_name
    created_at = datetime.now(timezone.utc).isoformat()
    tags = [tag.strip() for tag in (listing["tags"] or "").split(",") if tag.strip()]

    image_entries = []
    for position, image_path in enumerate(export_state["images"], start=1):
        packaged_name = f"images/{position:02d}_{image_path.name}"
        image_entries.append(
            {
                "position": position,
                "filename": packaged_name,
                "source_filename": image_path.name,
            }
        )

    manifest = {
        "schema_version": 1,
        "created_at": created_at,
        "listing": {
            "id": listing["id"],
            "artwork_code": listing["artwork_code"],
            "artwork_title": listing["public_title"],
            "collection": listing["collection_name"],
            "marketplace": listing["marketplace"],
            "product": listing["product"],
            "title": listing["title"],
            "description": listing["description"] or "",
            "tags": tags,
            "price_cents": listing["price_cents"],
            "price_usd": f"{listing['price_cents'] / 100:.2f}",
            "status": listing["status"],
        },
        "images": image_entries,
        "checklist": readiness["items"],
    }

    listing_text = (
        f"TITLE\n{listing['title']}\n\n"
        f"PRICE (USD)\n${listing['price_cents'] / 100:.2f}\n\n"
        f"PRODUCT\n{listing['product']}\n\n"
        f"DESCRIPTION\n{listing['description'] or ''}\n\n"
        f"TAGS\n{', '.join(tags)}\n"
    )
    checklist_text = "PUBLISH CHECKLIST\n\n" + "\n".join(
        f"[{'x' if item['passed'] else ' '}] {item['label']}"
        for item in readiness["items"]
    )

    temporary_path = archive_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("listing.txt", listing_text)
        archive.writestr("listing.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        archive.writestr("publish-checklist.txt", checklist_text + "\n")
        for entry, image_path in zip(image_entries, export_state["images"]):
            archive.write(image_path, entry["filename"])
    temporary_path.replace(archive_path)

    return {
        "path": archive_path,
        "filename": archive_name,
        "image_count": len(image_entries),
        "created_at": created_at,
    }
