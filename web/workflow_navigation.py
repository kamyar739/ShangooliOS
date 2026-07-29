"""Small, read-only navigation model for collection workflows."""

from web.collection_production import collection_production_overview
from web.collection_review import collection_review_overview
from web.db import get_listing
from web.publish_readiness import collection_publish_readiness


STAGES = (
    ("intake", "Intake"),
    ("production", "Produce"),
    ("review", "Review"),
    ("readiness", "Ready"),
    ("printify", "Printify"),
    ("etsy", "Etsy"),
)


def collection_workflow_navigation(collection_code, *, active_stage):
    """Describe workflow progress without owning any workflow behavior."""
    collection, production_items, latest_run = collection_production_overview(
        collection_code
    )
    _, _, review_complete = collection_review_overview(collection_code)
    _, readiness_items, counts, readiness_complete, _ = (
        collection_publish_readiness(collection_code)
    )

    total = len(readiness_items)
    production_attention = bool(
        latest_run
        and any(
            item["overall_status"] in {"blocked", "failed"}
            for item in production_items
        )
    )
    production_complete = bool(latest_run and not production_attention)
    printify_complete = bool(
        total
        and counts["printify_linked"] + counts["etsy_linked"] == total
    )
    etsy_complete = bool(total and counts["etsy_linked"] == total)
    submitted = False
    for item in readiness_items:
        if not item["listing_id"]:
            continue
        listing = get_listing(item["listing_id"])
        if (
            listing
            and listing["printify_publish_requested_at"]
            and not listing["external_listing_id"]
        ):
            submitted = True
            break

    completion = {
        "intake": bool(total),
        "production": production_complete,
        "review": review_complete,
        "readiness": readiness_complete,
        "printify": printify_complete,
        "etsy": etsy_complete,
    }
    attention = {
        "intake": not bool(total),
        "production": production_attention,
        "review": bool(latest_run and not review_complete),
        "readiness": bool(
            latest_run
            and (
                counts["blocked"]
                or counts["needs_review"]
                or not readiness_complete
            )
        ),
        "printify": bool(readiness_complete and not printify_complete),
        "etsy": bool(printify_complete and not etsy_complete),
    }
    urls = {
        "intake": "/fast-flow",
        "production": f"/collections/{collection['code']}/production",
        "review": f"/collections/{collection['code']}/review",
        "readiness": f"/collections/{collection['code']}/publish-readiness",
        "printify": f"/collections/{collection['code']}/printify",
        "etsy": f"/collections/{collection['code']}/publish",
    }

    if not latest_run:
        next_action = {
            "label": "Run safe production",
            "description": (
                "Confirm the imported originals and build the local "
                "production files."
            ),
            "url": urls["production"] + "#collection-workflow-action",
        }
    elif production_attention:
        next_action = {
            "label": "Review production exceptions",
            "description": (
                "Resolve the artwork that could not complete safe production."
            ),
            "url": urls["production"] + "#production-exceptions",
        }
    elif not review_complete:
        next_action = {
            "label": "Review generated files",
            "description": (
                "Approve the eligible ratio files and listing images together."
            ),
            "url": urls["review"] + "#collection-workflow-action",
        }
    elif not readiness_complete:
        next_action = {
            "label": "Finish publish readiness",
            "description": (
                "Prepare any missing local listings and resolve only the "
                "checks shown."
            ),
            "url": urls["readiness"] + "#collection-workflow-action",
        }
    elif not printify_complete:
        next_action = {
            "label": "Review Printify products",
            "description": (
                "Review sizes and prices before creating unpublished "
                "Printify drafts."
            ),
            "url": urls["printify"] + "#collection-workflow-action",
        }
    elif submitted:
        next_action = {
            "label": "Check Etsy status",
            "description": "Safely recover the Etsy listings already submitted by Printify.",
            "url": f"/collections/{collection['code']}/publish/recover",
        }
    elif not etsy_complete:
        next_action = {
            "label": "Review Etsy publication",
            "description": (
                "Choose which Printify products to send to the connected "
                "Etsy shop."
            ),
            "url": urls["etsy"] + "#collection-workflow-action",
        }
    else:
        next_action = {
            "label": "View completed collection",
            "description": "Every active artwork in this collection is linked to Etsy.",
            "url": f"/collections?collection={collection['code']}",
        }

    stages = []
    for key, label in STAGES:
        if completion[key]:
            state = "complete"
        elif attention[key]:
            state = "attention"
        else:
            state = "upcoming"
        stages.append({
            "key": key,
            "label": label,
            "url": urls[key],
            "state": state,
            "active": key == active_stage,
        })
    return {
        "kind": "collection",
        "title": collection["name"],
        "stages": stages,
        "next_action": next_action,
    }
