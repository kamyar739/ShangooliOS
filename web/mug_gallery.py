"""Product-specific mug gallery preparation and safe Etsy synchronization."""

import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

from web.db import (
    get_standalone_design,
    save_standalone_product_gallery,
    update_standalone_product_gallery_state,
)
from web.etsy_api import (
    delete_etsy_listing_image,
    get_etsy_listing_images,
    upload_etsy_listing_image,
)
from web.printify_api import PrintifyAPI, PrintifyAPIError


GALLERY_ROOT = Path(__file__).resolve().parents[1] / "assets" / "designs" / "galleries"
GALLERY_SIZE = (2000, 2000)
GALLERY_SLOTS = (
    ("hero", "Hero product image"),
    ("lifestyle", "Lifestyle scene"),
    ("gift", "Gift presentation"),
    ("both_sides", "Placement proof"),
)
FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
FONT_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial.ttf")


def _font(path, size):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _safe_manifest(product):
    try:
        value = json.loads(product["gallery_manifest"] or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def gallery_items(product):
    return _safe_manifest(product)


def gallery_path(filename):
    candidate = GALLERY_ROOT / str(filename or "")
    try:
        candidate.resolve().relative_to(GALLERY_ROOT.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _download_image(source):
    parsed = urlparse(str(source or ""))
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(
        ".printify.com"
    ):
        raise ValueError("Printify returned an unsupported mockup address")
    request = Request(source, headers={"User-Agent": "ShangooliOS/1.0"})
    with urlopen(request, timeout=60) as response:
        contents = response.read()
    with Image.open(BytesIO(contents)) as opened:
        return opened.convert("RGB")


def _cover(image, size):
    width, height = size
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _contain(image, size):
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def _render_gallery_image(slot, images, product):
    primary = images[0]
    context = images[min(1, len(images) - 1)]
    alternate = images[min(2, len(images) - 1)]
    title = " ".join(str(product["product_title"] or product["name"] or "Mug gift").split())
    if slot == "hero":
        return _cover(primary, GALLERY_SIZE)
    if slot == "lifestyle":
        return _cover(context, GALLERY_SIZE)

    canvas = Image.new("RGB", GALLERY_SIZE, "#f7f0e5")
    draw = ImageDraw.Draw(canvas)
    if slot == "gift":
        photo = _cover(context, (2000, 1540))
        canvas.paste(photo, (0, 0))
        draw.rectangle((0, 1540, 2000, 2000), fill="#17213b")
        draw.text((110, 1625), "A THOUGHTFUL EVERYDAY GIFT", font=_font(FONT_BOLD, 43), fill="#aaa0ff")
        draw.text((110, 1710), title[:70], font=_font(FONT_BOLD, 58), fill="white")
        draw.text((110, 1880), "ShangooliShop · printed to order", font=_font(FONT_REGULAR, 36), fill="#d8dced")
        return canvas

    placement_mode = str(product["placement_mode"] or "both")
    proof_copy = {
        "front": (
            "DESIGN PRINTED ON ONE SIDE",
            "Positioned for clear visibility when held in the right hand.",
        ),
        "reverse": (
            "DESIGN PRINTED ON ONE SIDE",
            "Positioned for clear visibility when held in the left hand.",
        ),
        "different": (
            "A DIFFERENT DESIGN ON EACH SIDE",
            "Each side of the mug has its own approved artwork.",
        ),
        "both": (
            "THE DESIGN IS PRINTED ON BOTH SIDES",
            "Easy to see whether the mug is held in the left or right hand.",
        ),
    }
    headline, supporting_copy = proof_copy.get(placement_mode, proof_copy["both"])
    draw.text((100, 85), headline, font=_font(FONT_BOLD, 46), fill="#17213b")
    draw.text((100, 155), supporting_copy, font=_font(FONT_REGULAR, 34), fill="#536078")
    for image, left in ((primary, 80), (alternate, 1030)):
        placed = _contain(image, (890, 1480))
        x = left + (890 - placed.width) // 2
        y = 340 + (1480 - placed.height) // 2
        canvas.paste(placed, (x, y))
    draw.line((1000, 300, 1000, 1840), fill="#d7d0c6", width=4)
    draw.text((100, 1890), "ShangooliShop", font=_font(FONT_BOLD, 42), fill="#17213b")
    return canvas


def prepare_mug_gallery(design_id, product_key, *, api=None):
    """Create a deterministic gallery from the exact Printify product renders.

    Printify remains responsible for mug geometry, placement, perspective, and
    lighting.  ShangooliOS deliberately does not paint the flat design onto a
    photographed mug here; doing so produces visually inaccurate mockups.
    """
    product = get_standalone_design(design_id, product_key)
    if product is None or not product["product_id"]:
        raise ValueError("Save the mug setup first")
    if not product["printify_product_id"]:
        raise ValueError("Create the Printify product before preparing its gallery")
    client = api or PrintifyAPI.from_env()
    if client is None:
        raise ValueError("Connect Printify before preparing the gallery")
    remote = client.get_product(product["printify_product_id"])
    sources = [item.get("src") for item in (remote.get("images") or []) if item.get("src")]
    if not sources:
        raise ValueError("Printify has not generated product images yet")
    try:
        images = [_download_image(source) for source in sources[:4]]
    except OSError as error:
        raise ValueError("A Printify product image could not be downloaded") from error

    folder_name = f"product-{product['product_id']}"
    folder = GALLERY_ROOT / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    for position, (slot, label) in enumerate(GALLERY_SLOTS, start=1):
        rendered = _render_gallery_image(slot, images, product)
        filename = f"{folder_name}/{position:02d}-{slot}.jpg"
        path = GALLERY_ROOT / filename
        rendered.save(path, "JPEG", quality=94, optimize=True)
        if slot == "both_sides":
            placement_mode = str(product["placement_mode"] or "both")
            label = {
                "front": "Right-handed placement proof",
                "reverse": "Left-handed placement proof",
                "different": "Different-design placement proof",
                "both": "Both-sides proof",
            }.get(placement_mode, "Placement proof")
        manifest.append(
            {
                "slot": slot,
                "label": label,
                "position": position,
                "filename": filename,
                "source": "printify_render",
            }
        )
    save_standalone_product_gallery(
        design_id,
        product_key,
        manifest=json.dumps(manifest),
        state="prepared",
        message=(
            "Four accurate product renders from Printify are ready for review. "
            "If they show older artwork, update this product in Printify first, "
            "then refresh the renders here."
        ),
    )
    return manifest


def reorder_mug_gallery(design_id, product_key, ordered_slots):
    product = get_standalone_design(design_id, product_key)
    current = {item["slot"]: item for item in gallery_items(product)}
    ordered = [current[slot] for slot in ordered_slots if slot in current]
    ordered.extend(item for slot, item in current.items() if slot not in ordered_slots)
    for position, item in enumerate(ordered, start=1):
        item["position"] = position
    save_standalone_product_gallery(
        design_id,
        product_key,
        manifest=json.dumps(ordered),
        state="prepared",
        message="Gallery order saved. Review and approve it before Etsy synchronization.",
    )
    return ordered


def replace_mug_gallery_item(design_id, product_key, slot, contents, original_name):
    product = get_standalone_design(design_id, product_key)
    items = gallery_items(product)
    item = next((entry for entry in items if entry["slot"] == slot), None)
    if item is None:
        raise ValueError("Prepare the gallery before replacing an image")
    try:
        with Image.open(BytesIO(contents)) as opened:
            image = opened.convert("RGB")
    except OSError as error:
        raise ValueError("Choose a readable PNG or JPEG image") from error
    safe_name = re.sub(r"[^a-z0-9]+", "-", Path(original_name).stem.lower()).strip("-")
    filename = f"product-{product['product_id']}/{item['position']:02d}-{slot}-{safe_name or 'custom'}.jpg"
    path = GALLERY_ROOT / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    _cover(image, GALLERY_SIZE).save(path, "JPEG", quality=94, optimize=True)
    item["filename"] = filename
    item["source"] = "uploaded"
    save_standalone_product_gallery(
        design_id,
        product_key,
        manifest=json.dumps(items),
        state="prepared",
        message="Custom image saved. Review and approve the complete gallery.",
    )
    return items


def upload_mug_gallery(design_id, product_key, uploads):
    """Replace the local review set with four finished images in upload order."""
    if len(uploads) != len(GALLERY_SLOTS):
        raise ValueError("Choose exactly four finished mockups")
    product = get_standalone_design(design_id, product_key)
    if product is None or not product["product_id"]:
        raise ValueError("Save the mug setup first")
    folder_name = f"product-{product['product_id']}"
    manifest = []
    for position, ((slot, label), (contents, original_name)) in enumerate(
        zip(GALLERY_SLOTS, uploads), start=1
    ):
        try:
            with Image.open(BytesIO(contents)) as opened:
                image = opened.convert("RGB")
        except OSError as error:
            raise ValueError(f"Mockup {position} is not a readable PNG or JPEG") from error
        filename = f"{folder_name}/{position:02d}-{slot}-uploaded.jpg"
        path = GALLERY_ROOT / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        _cover(image, GALLERY_SIZE).save(path, "JPEG", quality=94, optimize=True)
        manifest.append(
            {
                "slot": slot,
                "label": label,
                "position": position,
                "filename": filename,
                "source": "uploaded",
                "original_name": Path(original_name).name,
            }
        )
    save_standalone_product_gallery(
        design_id,
        product_key,
        manifest=json.dumps(manifest),
        state="prepared",
        message="Four finished mockups uploaded. Review and approve the set.",
    )
    return manifest


def approve_mug_gallery(design_id, product_key):
    product = get_standalone_design(design_id, product_key)
    items = gallery_items(product)
    if len(items) < len(GALLERY_SLOTS) or any(gallery_path(item["filename"]) is None for item in items):
        raise ValueError("Prepare the complete gallery before approval")
    update_standalone_product_gallery_state(
        design_id, product_key, state="approved", message="Gallery approved and ready for Etsy."
    )


def sync_mug_gallery_to_etsy(design_id, product_key, *, confirmed):
    if not confirmed:
        raise ValueError("Confirm Etsy gallery synchronization")
    product = get_standalone_design(design_id, product_key)
    if product is None or not product["etsy_listing_id"]:
        raise ValueError("Find and link the Etsy listing first")
    if product["gallery_state"] != "approved":
        raise ValueError("Approve the gallery before Etsy synchronization")
    items = sorted(gallery_items(product), key=lambda item: item["position"])
    paths = [gallery_path(item["filename"]) for item in items]
    if any(path is None for path in paths):
        raise ValueError("One or more approved gallery files is missing")

    listing_id = str(product["etsy_listing_id"])
    uploaded_ids = set()
    try:
        for rank, (item, path) in enumerate(zip(items, paths), start=1):
            result = upload_etsy_listing_image(
                listing_id, path, rank, f"{product['product_title']} — {item['label']}"
            )
            if not result.get("listing_image_id"):
                raise ValueError(f"Etsy did not confirm image {rank}")
            uploaded_ids.add(int(result["listing_image_id"]))
    except Exception:
        update_standalone_product_gallery_state(
            design_id,
            product_key,
            state="needs_review",
            message="Etsy gallery synchronization stopped. Existing images were preserved; retry safely.",
        )
        raise

    for image in get_etsy_listing_images(listing_id):
        image_id = int(image["listing_image_id"])
        if image_id not in uploaded_ids:
            delete_etsy_listing_image(listing_id, image_id)
    update_standalone_product_gallery_state(
        design_id,
        product_key,
        state="synced",
        message=f"{len(uploaded_ids)} approved gallery images synchronized to Etsy.",
    )
    return {"image_count": len(uploaded_ids), "listing_id": listing_id}
