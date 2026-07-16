from app.database import get_artwork_folder
from web.file_intake import assigned_file_exists


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


def parse_required_ratios(required_ratios: str | None) -> list[str]:
    return [
        value.strip()
        for value in (required_ratios or "").split(",")
        if value.strip()
    ]


def build_production_summary(
    artwork,
    production,
    files,
    assignments,
) -> dict:
    category_counts = {
        "source": 0,
        "print": 0,
        "mockups": 0,
        "exports": 0,
    }

    for file_record in files:
        category_counts[file_record["category"]] += 1

    assignment_map = {
        record["role"]: record
        for record in assignments
    }

    source_assignment = assignment_map.get("source")
    master_assignment = assignment_map.get("print_master")

    source_ready = bool(
        source_assignment
        and assigned_file_exists(
            artwork,
            source_assignment["relative_path"],
        )
    )

    master_ready = bool(
        master_assignment
        and assigned_file_exists(
            artwork,
            master_assignment["relative_path"],
        )
    )

    required_ratios = parse_required_ratios(
        production["required_ratios"]
    )

    ratio_status = []

    for ratio in required_ratios:
        assignment = assignment_map.get(f"ratio:{ratio}")
        exists = bool(
            assignment
            and assigned_file_exists(
                artwork,
                assignment["relative_path"],
            )
        )

        ratio_status.append(
            {
                "ratio": ratio,
                "assigned": assignment,
                "exists": exists,
            }
        )

    missing_ratios = [
        record["ratio"]
        for record in ratio_status
        if not record["exists"]
    ]

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

    validation_items = [
        {
            "label": "Orientation selected",
            "passed": bool(production["orientation"]),
        },
        {
            "label": "Master aspect ratio set",
            "passed": bool(production["master_ratio"]),
        },
        {
            "label": "Required output ratios defined",
            "passed": bool(required_ratios),
        },
        {
            "label": "Approved source file assigned",
            "passed": source_ready,
        },
        {
            "label": "Original artwork approved",
            "passed": bool(production["original_approved"]),
        },
        {
            "label": "Print master file assigned",
            "passed": master_ready,
        },
        {
            "label": "Print master marked ready",
            "passed": bool(production["print_master_ready"]),
        },
        {
            "label": "All required ratio files assigned",
            "passed": bool(required_ratios) and not missing_ratios,
        },
        {
            "label": "Ratio exports marked complete",
            "passed": bool(production["ratio_exports_ready"]),
        },
        {
            "label": "Mockups marked complete",
            "passed": bool(production["mockups_ready"]),
        },
        {
            "label": "Listing content marked ready",
            "passed": bool(production["listing_content_ready"]),
        },
    ]

    validation_passed = all(
        item["passed"]
        for item in validation_items
    )

    if validation_passed:
        readiness = "ready"
        readiness_label = "Ready for listing"
    elif (
        source_ready
        or master_ready
        or checklist_complete >= 2
    ):
        readiness = "in-progress"
        readiness_label = "In production"
    else:
        readiness = "not-started"
        readiness_label = "Setup needed"

    return {
        "assignment_map": assignment_map,
        "category_counts": category_counts,
        "checklist_complete": checklist_complete,
        "checklist_total": len(checklist_fields),
        "required_ratios": required_ratios,
        "ratio_status": ratio_status,
        "missing_ratios": missing_ratios,
        "source_assignment": source_assignment,
        "source_ready": source_ready,
        "master_assignment": master_assignment,
        "master_ready": master_ready,
        "validation_items": validation_items,
        "validation_passed": validation_passed,
        "readiness": readiness,
        "readiness_label": readiness_label,
    }
