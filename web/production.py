from dataclasses import dataclass

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


@dataclass(frozen=True)
class WorkflowStatus:
    steps: list[dict]
    completed_steps: int
    total_steps: int
    progress_percent: int
    current_step: dict | None
    current_stage: str
    next_action: dict
    readiness: str
    readiness_label: str


def build_workflow_status(
    artwork,
    production,
    *,
    source_ready: bool,
    master_ready: bool,
    required_ratios: list[str],
    missing_ratios: list[str],
) -> WorkflowStatus:
    ratios_generated = bool(required_ratios) and not missing_ratios
    is_listed = artwork["status"] == "listed"

    steps = [
        {
            "key": "created",
            "stage": "Artwork Setup",
            "label": "Artwork created",
            "complete": True,
        },
        {
            "key": "source",
            "stage": "Source Artwork",
            "label": "Source artwork uploaded",
            "complete": source_ready,
        },
        {
            "key": "approved",
            "stage": "Source Artwork",
            "label": "Source artwork approved",
            "complete": bool(production["original_approved"]),
        },
        {
            "key": "master",
            "stage": "Print Production",
            "label": "Print master uploaded",
            "complete": master_ready,
        },
        {
            "key": "ratios",
            "stage": "Print Production",
            "label": "Required ratios generated",
            "complete": ratios_generated,
        },
        {
            "key": "ratio_review",
            "stage": "Print Production",
            "label": "Ratio files reviewed",
            "complete": bool(production["ratio_exports_ready"]),
        },
        {
            "key": "mockups",
            "stage": "Marketing Assets",
            "label": "Mockups created and approved",
            "complete": bool(production["mockups_ready"]),
        },
        {
            "key": "listing",
            "stage": "Etsy Listing",
            "label": "Listing content ready",
            "complete": bool(production["listing_content_ready"]),
        },
        {
            "key": "published",
            "stage": "Publishing",
            "label": "Published",
            "complete": is_listed,
        },
    ]

    completed_steps = sum(1 for step in steps if step["complete"])
    total_steps = len(steps)
    progress_percent = round((completed_steps / total_steps) * 100)

    current_step = next(
        (step for step in steps if not step["complete"]),
        None,
    )

    action_map = {
        "source": {
            "title": "Upload the source artwork",
            "description": (
                "Add the approved source image to the artwork workspace "
                "to begin production."
            ),
            "label": "Upload Source",
            "href": "#file-intake",
        },
        "approved": {
            "title": "Approve the source artwork",
            "description": (
                "Review the source image and confirm that it is the final "
                "version to use for production."
            ),
            "label": "Review Source",
            "href": "#production-setup",
        },
        "master": {
            "title": "Upload the print master",
            "description": (
                "Add the high-resolution print master used to generate "
                "the required print ratios."
            ),
            "label": "Upload Print Master",
            "href": "#file-intake",
        },
        "ratios": {
            "title": (
                f"Generate {', '.join(missing_ratios)}"
                if missing_ratios
                else "Set up the required print ratios"
            ),
            "description": (
                "Create the missing ratio files from the approved print master."
                if missing_ratios
                else "Choose the required print ratios before generating files."
            ),
            "label": "Open Ratio Generator",
            "href": "#production-setup",
        },
        "ratio_review": {
            "title": "Review the generated ratio files",
            "description": (
                "Check each crop and confirm that all required exports are ready."
            ),
            "label": "Review Ratios",
            "href": "#production-setup",
        },
        "mockups": {
            "title": "Create and approve the mockups",
            "description": (
                "Prepare the listing images that show the artwork clearly "
                "and in context."
            ),
            "label": "Open Mockup Files",
            "href": "#file-intake",
        },
        "listing": {
            "title": "Finish the Etsy listing content",
            "description": (
                "Complete the title, description, tags, pricing, and listing details."
            ),
            "label": "Edit Artwork Details",
            "href": "#artwork-details",
        },
        "published": {
            "title": "Publish the artwork",
            "description": (
                "The production package is complete. Review and publish the listing."
            ),
            "label": "Review Listing Readiness",
            "href": "#validation",
        },
    }

    if current_step:
        current_stage = current_step["stage"]
        next_action = action_map[current_step["key"]]
    else:
        current_stage = "Complete"
        next_action = {
            "title": "Workflow complete",
            "description": "This artwork has completed every production step.",
            "label": "View Artwork Details",
            "href": "#artwork-details",
        }

    if current_step is None or current_step["key"] == "published":
        readiness = "ready"
        readiness_label = "Ready for listing"
    elif completed_steps >= 2:
        readiness = "in-progress"
        readiness_label = "In production"
    else:
        readiness = "not-started"
        readiness_label = "Setup needed"

    return WorkflowStatus(
        steps=steps,
        completed_steps=completed_steps,
        total_steps=total_steps,
        progress_percent=progress_percent,
        current_step=current_step,
        current_stage=current_stage,
        next_action=next_action,
        readiness=readiness,
        readiness_label=readiness_label,
    )


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

    workflow = build_workflow_status(
        artwork,
        production,
        source_ready=source_ready,
        master_ready=master_ready,
        required_ratios=required_ratios,
        missing_ratios=missing_ratios,
    )

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
        "readiness": workflow.readiness,
        "readiness_label": workflow.readiness_label,
        "workflow_steps": workflow.steps,
        "completed_steps": workflow.completed_steps,
        "total_steps": workflow.total_steps,
        "progress_percent": workflow.progress_percent,
        "current_step": workflow.current_step,
        "next_action": workflow.next_action,
        "workflow": workflow,
    }
