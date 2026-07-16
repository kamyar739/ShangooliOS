from pathlib import Path

from app.database import get_artwork_folder


WORKSPACE_CATEGORIES = (
    ("source", "Source Artwork", "01 Source Artwork"),
    ("print", "Print Files", "02 Print Files"),
    ("mockups", "Mockups", "03 Mockups"),
    ("exports", "Exports", "04 Exports"),
)


def list_workspace_files(artwork) -> list[dict]:
    workspace = get_artwork_folder(artwork)
    results = []

    for category_key, category_label, folder_name in WORKSPACE_CATEGORIES:
        folder = workspace / folder_name

        if not folder.exists():
            continue

        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue

            stat = path.stat()

            results.append(
                {
                    "category": category_key,
                    "category_label": category_label,
                    "name": path.name,
                    "relative_path": str(path.relative_to(workspace)),
                    "size_bytes": stat.st_size,
                    "size_label": format_file_size(stat.st_size),
                    "extension": path.suffix.lower().lstrip(".") or "file",
                }
            )

    return results


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"

    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"

    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def build_production_summary(artwork, production, files) -> dict:
    category_counts = {
        "source": 0,
        "print": 0,
        "mockups": 0,
        "exports": 0,
    }

    for file_record in files:
        category_counts[file_record["category"]] += 1

    checklist_fields = (
        "original_approved",
        "print_master_ready",
        "ratio_exports_ready",
        "mockups_ready",
        "listing_content_ready",
    )

    checklist_complete = sum(
        1 for field in checklist_fields if production[field]
    )

    required_ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]

    missing = []

    if not production["orientation"]:
        missing.append("Orientation")
    if not production["master_ratio"]:
        missing.append("Master ratio")
    if not required_ratios:
        missing.append("Required output ratios")
    if category_counts["source"] == 0:
        missing.append("Source artwork file")
    if not production["original_approved"]:
        missing.append("Original approval")
    if not production["print_master_ready"]:
        missing.append("Print master")
    if not production["ratio_exports_ready"]:
        missing.append("Ratio exports")
    if not production["mockups_ready"]:
        missing.append("Mockups")
    if not production["listing_content_ready"]:
        missing.append("Listing content")

    if not missing:
        readiness = "ready"
        readiness_label = "Ready for listing"
    elif checklist_complete >= 3 or category_counts["print"] > 0:
        readiness = "in-progress"
        readiness_label = "In production"
    else:
        readiness = "not-started"
        readiness_label = "Setup needed"

    return {
        "category_counts": category_counts,
        "checklist_complete": checklist_complete,
        "checklist_total": len(checklist_fields),
        "required_ratios": required_ratios,
        "missing": missing,
        "readiness": readiness,
        "readiness_label": readiness_label,
    }
