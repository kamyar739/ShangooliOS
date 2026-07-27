"""Shared, state-safe publication and recovery for one local listing."""

from web.db import (
    get_artwork,
    get_artwork_listings,
    get_listing,
    link_etsy_listing,
    mark_etsy_synced,
    mark_printify_publish_requested,
    record_etsy_state,
    record_publishing_recovery,
)
from web.etsy_api import EtsyAPIError, etsy_config, get_etsy_listing
from web.etsy_sync import (
    build_etsy_sync_preview,
    find_etsy_candidates,
    sync_etsy_listing,
)
from web.printify import validate_printify_product
from web.printify_api import (
    PrintifyAPI,
    PrintifyAPIConnectionError,
    PrintifyAPIError,
)
from web.db import get_listing_readiness


UNKNOWN_STAGE = "publish_outcome_unknown"


def _archived_etsy_ids(artwork_code):
    return {
        str(item["external_listing_id"]).strip()
        for item in get_artwork_listings(artwork_code)
        if item["status"] == "archived"
        and str(item["external_listing_id"] or "").strip()
    }


def _result(listing, outcome, label, message):
    return {
        "listing_id": listing["id"] if listing else None,
        "artwork_code": listing["artwork_code"] if listing else "",
        "title": listing["title"] if listing else "",
        "outcome": outcome,
        "label": label,
        "message": message,
    }


def publication_protection(listing):
    """Return a protected outcome, or None when a new request is allowed."""
    if listing is None:
        return {
            "outcome": "skipped",
            "label": "Skipped",
            "message": "Listing not found.",
        }
    artwork = get_artwork(listing["artwork_code"])
    if artwork is None or artwork["status"] == "retired":
        return {
            "outcome": "skipped",
            "label": "Skipped",
            "message": "The artwork is retired or unavailable.",
        }
    if listing["status"] == "archived":
        return {
            "outcome": "skipped",
            "label": "Skipped",
            "message": "The local listing is archived.",
        }
    if (
        str(listing["external_listing_id"] or "").strip()
        or str(listing["etsy_state"] or "").strip().lower() == "active"
        or listing["status"] == "published"
    ):
        return {
            "outcome": "already_published",
            "label": "Already published",
            "message": "The existing Etsy publication was preserved.",
        }
    if listing["publishing_recovery_stage"] == UNKNOWN_STAGE:
        return {
            "outcome": "unknown",
            "label": "Outcome unknown — manual verification required",
            "message": (
                "A previous request may have reached Printify. Verify Printify "
                "and Etsy before taking any further action."
            ),
        }
    if listing["printify_publish_requested_at"]:
        return {
            "outcome": "already_submitted",
            "label": "Already submitted",
            "message": (
                "A publication request already exists. Use recovery instead of "
                "sending it again."
            ),
        }
    if not str(listing["printify_product_id"] or "").strip():
        return {
            "outcome": "skipped",
            "label": "Skipped",
            "message": "No usable Printify product is attached.",
        }
    return None


def request_listing_publication(listing_id, *, api=None):
    """Submit one existing Printify product using the canonical safe path."""
    listing = get_listing(listing_id)
    protected = publication_protection(listing)
    if protected:
        return _result(
            listing, protected["outcome"], protected["label"], protected["message"]
        )
    readiness = get_listing_readiness(listing_id)
    if not readiness["ready"]:
        return _result(
            listing,
            "failed",
            "Failed safely",
            "Complete the listing readiness checklist before publishing.",
        )
    if not validate_printify_product(listing)["ready"]:
        return _result(
            listing,
            "failed",
            "Failed safely",
            "Create or save the Printify product before publishing.",
        )
    printify_api = api or PrintifyAPI.from_env()
    if printify_api is None:
        return _result(
            listing,
            "failed",
            "Failed safely",
            "Printify API is not configured.",
        )
    try:
        # Confirm that the protected product still exists immediately before
        # the irreversible publish request.
        if hasattr(printify_api, "get_product"):
            printify_api.get_product(listing["printify_product_id"])
        printify_api.publish_product(listing["printify_product_id"])
        mark_printify_publish_requested(listing_id)
        record_publishing_recovery(
            listing_id,
            "waiting_for_etsy",
            (
                "Printify accepted the publication request. Etsy listing "
                "creation may take time; check status and recover next."
            ),
        )
        return _result(
            get_listing(listing_id),
            "requested",
            "Publish requested",
            (
                "Printify accepted the request. Etsy may still be creating the "
                "listing."
            ),
        )
    except PrintifyAPIConnectionError as error:
        message = (
            "The connection ended before Printify's response was confirmed. "
            "Verify the product in Printify and Etsy before retrying. "
            f"Details: {error}"
        )
        record_publishing_recovery(listing_id, UNKNOWN_STAGE, message)
        return _result(
            get_listing(listing_id),
            "unknown",
            "Outcome unknown — manual verification required",
            message,
        )
    except (PrintifyAPIError, ValueError, KeyError) as error:
        return _result(
            listing, "failed", "Failed safely", str(error)
        )


def recover_listing_publication(
    listing_id,
    *,
    api=None,
    find_candidates=find_etsy_candidates,
    get_remote_listing=get_etsy_listing,
    get_config=etsy_config,
    build_preview=build_etsy_sync_preview,
    sync_listing=sync_etsy_listing,
):
    """Advance one submitted listing without repeating Printify publication."""
    listing = get_listing(listing_id)
    if listing is None:
        return _result(None, "failed", "Recovery failed safely", "Listing not found.")
    if not validate_printify_product(listing)["ready"]:
        return _result(
            listing,
            "failed",
            "Recovery failed safely",
            "Create the Printify draft first.",
        )
    if listing["publishing_recovery_stage"] == UNKNOWN_STAGE:
        return _result(
            listing,
            "unknown",
            "Outcome unknown — manual verification required",
            listing["publishing_recovery_message"],
        )
    printify_api = api or PrintifyAPI.from_env()
    if printify_api is None:
        return _result(
            listing,
            "failed",
            "Recovery failed safely",
            "Printify API is not configured.",
        )

    try:
        product = printify_api.get_product(listing["printify_product_id"])
        product_title = (product.get("title") or listing["title"] or "").strip().casefold()
        external_id = str(listing["external_listing_id"] or "").strip()
        if not external_id:
            candidates = find_candidates(listing)
            exact = [
                item
                for item in candidates
                if (item.get("title") or "").strip().casefold()
                in {product_title, (listing["title"] or "").strip().casefold()}
                and str(item.get("listing_id") or "").strip()
                not in _archived_etsy_ids(listing["artwork_code"])
            ]
            if len(exact) == 1:
                external_id = str(exact[0]["listing_id"])
                link_etsy_listing(listing_id, external_id)
                record_etsy_state(listing_id, exact[0].get("state", ""))
                listing = get_listing(listing_id)
            elif len(exact) > 1:
                message = (
                    "More than one Etsy listing matches. Choose the correct "
                    "listing on the Etsy publishing page."
                )
                record_publishing_recovery(listing_id, "needs_review", message)
                return _result(
                    get_listing(listing_id),
                    "needs_review",
                    "Ambiguous Etsy matches — manual review required",
                    message,
                )
            else:
                if listing["printify_publish_requested_at"]:
                    message = (
                        "Printify is confirmed; Etsy has not returned a matching "
                        "listing yet. Wait briefly, then check again."
                    )
                    stage = "waiting_for_etsy"
                    label = "Waiting for Etsy"
                    outcome = "waiting"
                else:
                    message = (
                        "The Printify draft is confirmed. It has not been sent "
                        "to Etsy, so no publish action was repeated."
                    )
                    stage = "printify_draft_confirmed"
                    label = "Skipped"
                    outcome = "skipped"
                record_publishing_recovery(listing_id, stage, message)
                return _result(
                    get_listing(listing_id), outcome, label, message
                )

        listing = get_listing(listing_id)
        remote = get_remote_listing(external_id)
        if str(remote.get("shop_id", "")) != str(get_config()["shop_id"]):
            raise ValueError("The linked Etsy listing belongs to a different shop")
        record_etsy_state(listing_id, remote.get("state", ""))
        preview = build_preview(get_listing(listing_id))
        if preview.get("changed_count"):
            result = sync_listing(get_listing(listing_id))
            mark_etsy_synced(listing_id, result.get("state", ""))
            message = (
                "Recovered the Etsy link and synchronized the ShangooliOS title, "
                "description, tags, images, and section. Final Etsy review remains."
            )
        else:
            mark_etsy_synced(listing_id, remote.get("state", ""))
            message = (
                "Printify and Etsy are linked and already synchronized. Final "
                "Etsy review remains."
            )
        record_publishing_recovery(listing_id, "etsy_ready_for_review", message)
        return _result(
            get_listing(listing_id),
            "recovered",
            "Etsy listing linked and synchronized",
            message,
        )
    except (EtsyAPIError, PrintifyAPIError, KeyError, ValueError) as failure:
        failure_text = str(failure)
        normalized = failure_text.casefold()
        if "http 409" in normalized and "being edited by another process" in normalized:
            message = (
                "The Etsy listing was found and linked, but Printify is still "
                "finishing its setup. Nothing needs to be repeated. Wait briefly, "
                "then check status again."
            )
            record_publishing_recovery(listing_id, "waiting_for_etsy", message)
            return _result(
                get_listing(listing_id),
                "waiting",
                "Temporary Etsy edit lock",
                message,
            )
        message = f"Recovery stopped safely: {failure_text}"
        record_publishing_recovery(listing_id, "recovery_failed", message)
        return _result(
            get_listing(listing_id),
            "failed",
            "Recovery failed safely",
            message,
        )
