"""One-time Pinterest catalog launch preparation."""

import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from web.db import (
    get_standalone_design,
    list_pinterest_launch_states,
    list_standalone_design_products,
    list_standalone_designs,
)
from web.pinterest_bundle import (
    DEFAULT_DOCTOR_PINTEREST_STYLE,
    DEFAULT_PINTEREST_STYLE,
    normalize_pinterest_style,
    pinterest_bundle_copy,
    pinterest_download_name,
    render_pinterest_bundle,
)


PUBLIC_PIN_DIR = (
    Path(__file__).resolve().parents[1]
    / "marketing-site"
    / "public"
    / "images"
    / "pinterest-launch"
)
PUBLIC_PIN_BASE_URL = "https://shangooli.com/images/pinterest-launch"


def live_pinterest_launch_items(collection_code=None):
    """Return active, unpaused products and their saved review choices."""
    requested_collection = str(collection_code or "").strip().upper()
    states = {
        (row["design_id"], row["product_type"]): row
        for row in list_pinterest_launch_states()
    }
    items = []
    for design_row in list_standalone_designs():
        if design_row["status"] == "archived":
            continue
        if requested_collection and str(
            design_row["mug_collection_code"] or ""
        ).upper() != requested_collection:
            continue
        for product in list_standalone_design_products(design_row["id"]):
            if (
                str(product["etsy_state"] or "").lower() != "active"
                or product["etsy_paused_at"]
                or not product["etsy_listing_url"]
            ):
                continue
            design = get_standalone_design(design_row["id"], product["product_type"])
            state = states.get((design_row["id"], product["product_type"]))
            default_style = (
                DEFAULT_DOCTOR_PINTEREST_STYLE
                if requested_collection == "DOCTOR"
                else DEFAULT_PINTEREST_STYLE
            )
            try:
                style = normalize_pinterest_style(
                    state["selected_style"] if state else default_style,
                    requested_collection,
                )
            except ValueError:
                # A collection may predate its own scene set. Never leak a
                # teacher classroom into the Doctor launch when that happens.
                style = default_style
            items.append(
                {
                    "design": design,
                    "design_id": design_row["id"],
                    "product_key": product["product_type"],
                    "style": style,
                    "approved": bool(state["approved"]) if state else False,
                    "bundle": pinterest_bundle_copy(design, product["product_type"]),
                    "filename": pinterest_download_name(design, product["product_type"]),
                }
            )
    return items


def staged_pin_path(item):
    return PUBLIC_PIN_DIR / item["filename"]


def verify_public_pin_urls(items):
    """Confirm Pinterest can fetch every approved image from Shangooli.com."""
    approved = [item for item in items if item["approved"]]

    def check(item):
        url = f"{PUBLIC_PIN_BASE_URL}/{item['filename']}"
        request = Request(
            url,
            headers={
                "User-Agent": "ShangooliOS-Pinterest-Preflight/1.0",
                "Range": "bytes=0-0",
            },
        )
        try:
            with urlopen(request, timeout=12) as response:
                content_type = str(response.headers.get("Content-Type") or "")
                ok = response.status in {200, 206} and content_type.startswith("image/")
                return url, ok
        except (HTTPError, URLError, TimeoutError, OSError):
            return url, False

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(approved)))) as executor:
        checked = list(executor.map(check, approved))
    return {
        "checked_count": len(checked),
        "verified_count": sum(ok for _, ok in checked),
        "failed_urls": [url for url, ok in checked if not ok],
    }


def stage_approved_launch_assets(items):
    """Render approved pins into the public storefront source directory."""
    PUBLIC_PIN_DIR.mkdir(parents=True, exist_ok=True)
    staged = []
    for item in items:
        if not item["approved"]:
            continue
        output = staged_pin_path(item)
        output.write_bytes(
            render_pinterest_bundle(
                item["design"], item["product_key"], style=item["style"]
            )
        )
        staged.append(output)
    return staged


def launch_csv(items, *, start_date, pins_per_day=2):
    """Build Pinterest's official bulk-upload columns for approved pins."""
    start = date.fromisoformat(str(start_date))
    requested_per_day = int(pins_per_day)
    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "Title",
            "Media URL",
            "Pinterest board",
            "Thumbnail",
            "Description",
            "Link",
            "Publish date",
            "Keywords",
        ],
    )
    writer.writeheader()
    approved = [item for item in items if item["approved"]]
    per_day = len(approved) if requested_per_day == 0 else max(
        1, min(requested_per_day, 10)
    )
    per_day = max(per_day, 1)
    for index, item in enumerate(approved):
        bundle = item["bundle"]
        writer.writerow(
            {
                "Title": bundle["title"],
                "Media URL": f"{PUBLIC_PIN_BASE_URL}/{item['filename']}",
                "Pinterest board": bundle["board"],
                "Thumbnail": "",
                "Description": bundle["description"],
                "Link": bundle["link"],
                "Publish date": (start + timedelta(days=index // per_day)).isoformat(),
                "Keywords": ", ".join(bundle["topics"]),
            }
        )
    return output.getvalue().encode("utf-8-sig")
