"""Guarded restart of a collection after final source artwork replacement."""

from datetime import datetime
from pathlib import Path
import shutil

from PIL import Image

from app.database import get_artwork_folder
from web.db import (
    get_artwork,
    get_artwork_file_assignments,
    get_artwork_listings,
    get_collection,
    restart_collection_records_for_replacement,
)


GENERATED_FOLDERS = ("02 Print Files", "03 Mockups")


def replacement_restart_overview(collection_code):
    collection, artworks, _ = get_collection(collection_code)
    if collection is None:
        raise ValueError("Collection not found")
    items = []
    for summary in artworks:
        artwork = get_artwork(summary["artwork_code"])
        assignments = {
            row["role"]: row
            for row in get_artwork_file_assignments(summary["artwork_code"])
        }
        source = assignments.get("source")
        source_path = (
            get_artwork_folder(artwork) / source["relative_path"]
            if source else None
        )
        source_ok = bool(source_path and source_path.is_file())
        if source_ok:
            try:
                with Image.open(source_path) as image:
                    image.verify()
            except Exception:
                source_ok = False
        listings = list(get_artwork_listings(summary["artwork_code"]))
        current = next(
            (row for row in listings if row["status"] != "archived"),
            listings[0] if listings else None,
        )
        items.append({
            "artwork_code": summary["artwork_code"],
            "public_title": summary["public_title"],
            "source_filename": source["original_filename"] if source else None,
            "source_ok": source_ok,
            "listing": current,
        })
    blockers = []
    for item in items:
        if not item["source_ok"]:
            blockers.append(f"{item['artwork_code']}: readable source is missing")
        if item["listing"] is None:
            blockers.append(f"{item['artwork_code']}: local listing is missing")
    return collection, items, blockers


def restart_collection_with_replacement_sources(
    collection_code, *, sources_confirmed, archive_confirmed
):
    if not sources_confirmed:
        raise ValueError(
            "Confirm that the replacement images are the intended final originals"
        )
    if not archive_confirmed:
        raise ValueError(
            "Confirm that current publication records should be archived"
        )
    collection, items, blockers = replacement_restart_overview(collection_code)
    if blockers:
        raise ValueError("Cannot restart: " + "; ".join(blockers))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    moved = []
    try:
        for item in items:
            artwork = get_artwork(item["artwork_code"])
            workspace = get_artwork_folder(artwork)
            archive_root = workspace / "99 Archive" / f"Replacement Restart {stamp}"
            for folder_name in GENERATED_FOLDERS:
                source_dir = workspace / folder_name
                if not source_dir.exists():
                    continue
                destination = archive_root / folder_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source_dir), str(destination))
                moved.append((source_dir, destination))

        records = restart_collection_records_for_replacement(collection["code"])
    except Exception:
        for original, archived in reversed(moved):
            if archived.exists() and not original.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(archived), str(original))
        raise

    archive_roots = {}
    for original, archived in moved:
        original.mkdir(parents=True, exist_ok=True)
        archive_roots[str(original.parent)] = str(archived.parent)
    return {
        "collection_code": collection["code"],
        "items": records,
        "archive_roots": list(archive_roots.values()),
    }
