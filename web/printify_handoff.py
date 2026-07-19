import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_artwork_folder
from web.printify import validate_printify_product


PRINT_FILE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".tif", ".tiff"}


def _print_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    candidates = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in PRINT_FILE_EXTENSIONS
    )
    ratio_files = [path for path in candidates if "ratio" in path.stem.lower()]
    return ratio_files or candidates


def inspect_printify_handoff(listing, readiness: dict) -> dict:
    workspace = get_artwork_folder(listing)
    files = _print_files(workspace / "02 Print Files")
    printify = validate_printify_product(listing)
    blockers = list(printify["blockers"])
    readiness_by_key = {item["key"]: item for item in readiness["items"]}
    for key in ("print_master", "ratios"):
        item = readiness_by_key[key]
        if not item["passed"]:
            blockers.append(item["label"])
    if not files:
        blockers.append("Print files in the artwork workspace")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "files": files,
        "file_count": len(files),
        "export_folder": workspace / "04 Exports",
    }


def build_printify_handoff(listing, readiness: dict) -> dict:
    state = inspect_printify_handoff(listing, readiness)
    if not state["ready"]:
        raise ValueError("Complete the Printify handoff first: " + ", ".join(state["blockers"]))

    export_folder = state["export_folder"]
    export_folder.mkdir(parents=True, exist_ok=True)
    filename = f"{listing['artwork_code']}_listing_{listing['id']}_printify.zip"
    archive_path = export_folder / filename
    sizes = [size.strip() for size in listing["printify_sizes"].split(",") if size.strip()]
    created_at = datetime.now(timezone.utc).isoformat()
    file_entries = [
        {"filename": f"print-files/{path.name}", "source_filename": path.name}
        for path in state["files"]
    ]
    manifest = {
        "schema_version": 1,
        "created_at": created_at,
        "artwork_code": listing["artwork_code"],
        "listing_id": listing["id"],
        "printify": {
            "product_url": listing["printify_product_url"],
            "product_id": listing["printify_product_id"],
            "provider": listing["printify_provider"],
            "sizes": sizes,
            "base_cost_cents": listing["printify_base_cost_cents"],
        },
        "print_files": file_entries,
    }
    checklist = """PRINTIFY SETUP CHECKLIST

[ ] Open the saved Printify product
[ ] Upload the matching print file for each selected size
[ ] Confirm placement and cropping in the product editor
[ ] Confirm provider, variants, base cost, and retail pricing
[ ] Save or publish the product in Printify
[ ] Connect the Printify product to the Etsy listing
[ ] Return to ShangooliOS and mark the connection complete
"""
    temporary_path = archive_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("printify.json", json.dumps(manifest, indent=2))
        archive.writestr("printify-setup-checklist.txt", checklist)
        for entry, path in zip(file_entries, state["files"]):
            archive.write(path, entry["filename"])
    temporary_path.replace(archive_path)
    return {"path": archive_path, "filename": filename, "file_count": len(file_entries)}
