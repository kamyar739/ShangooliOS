"""Read-only Pinterest bundle generation for standalone products."""

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

from web import standalone_designs
from web.etsy_validation import parse_tags
from web.printify_api import PrintifyAPI, PrintifyAPIError
from web.product_blueprints import get_product_blueprint
from web.mug_scene_profiles import (
    BLACK_ACCENT_PINTEREST_SCENE,
    composite_design_on_scene,
)


PINTEREST_IMAGE_SIZE = (1000, 1500)
PINTEREST_BOARD_DEFAULT = "Gift Ideas"
PINTEREST_BOARD_TEACHER = "Teacher Gift Ideas"
TEACHER_SUBJECTS = (
    "biology",
    "chemistry",
    "math",
    "history",
    "english",
    "science",
    "art",
    "music",
    "elementary",
)
FONT_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def _font(path, size):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _clean(value):
    return " ".join(str(value or "").split()).strip()


def _placement_claim(placement_mode):
    return {
        "front": "Right-handed placement · faces outward in the right hand",
        "reverse": "Left-handed placement · faces outward in the left hand",
        "both": "Printed on both sides · easy to see from either hand",
        "different": "A different design is printed on each side",
    }.get(_clean(placement_mode), "Right-handed placement")


def _shorten(text, maximum):
    text = _clean(text)
    if len(text) <= maximum:
        return text
    shortened = text[: maximum - 1].rsplit(" ", 1)[0].rstrip(" ,.-")
    return f"{shortened}…"


def pinterest_bundle_copy(design, product_key):
    """Build editable Pinterest copy from the selected saved product row."""
    _, blueprint = get_product_blueprint(product_key)
    message = _clean(design["message"] or design["name"])
    product_label = blueprint["label"]
    tags = parse_tags(design["tags"] or "")
    teacher = any(
        word in " ".join([message, *tags]).lower()
        for word in ("teacher", "classroom", "lesson", "educator", "biology", "math")
    )
    title = _shorten(
        design["product_title"]
        or f"{message} — {product_label}",
        100,
    )
    searchable = ", ".join(tags[:8])
    description = _clean(design["product_description"] or design["description"])
    if searchable:
        description = f"{description} Great for shoppers looking for {searchable}."
    description = _shorten(description, 500)
    color_detail = (
        "a white mug with a black handle and black interior"
        if product_key == "mug_11oz_black_accent"
        else "a white ceramic mug"
    )
    alt_text = _shorten(
        f'{color_detail.capitalize()} featuring the message “{message}” '
        "in a styled gift presentation.",
        500,
    )
    tag_text = " ".join(tags).lower()
    subject = next(
        (candidate for candidate in TEACHER_SUBJECTS if candidate in tag_text),
        "",
    )
    topics = []
    if teacher:
        topics.append("Teacher gifts")
    else:
        topics.append("Gift ideas")
    if subject:
        topics.append(subject.title())
    topics.append("Coffee mugs")
    audience_label = (
        f"{subject.upper()} TEACHER GIFT"
        if subject
        else "TEACHER GIFT"
        if teacher
        else "THOUGHTFUL GIFT"
    )
    return {
        "title": title,
        "description": description,
        "link": design["etsy_listing_url"] or "",
        "alt_text": alt_text,
        "board": PINTEREST_BOARD_TEACHER if teacher else PINTEREST_BOARD_DEFAULT,
        "topics": topics,
        "message": message,
        "product_label": product_label,
        "audience_label": audience_label,
    }


def _fit_text(draw, text, font_path, max_width, start_size, minimum=30):
    for size in range(start_size, minimum - 1, -2):
        font = _font(font_path, size)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
    return _font(font_path, minimum)


def _contain(image, size):
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def _cover(image, size):
    """Fill a fixed area without distorting the product photograph."""
    target_width, target_height = size
    scale = max(target_width / image.width, target_height / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - target_width) // 2)
    top = max(0, (resized.height - target_height) // 2)
    return resized.crop((left, top, left + target_width, top + target_height))


def select_printify_context_mockup(product):
    """Prefer the selected product's lifestyle image, then its default mockup."""
    images = product.get("images") or []
    for image in images:
        source = str(image.get("src") or "")
        camera = parse_qs(urlparse(source).query).get("camera_label", [""])[0]
        if camera == "context":
            return source
    for image in images:
        if image.get("is_default") and image.get("src"):
            return str(image["src"])
    return str(images[0].get("src") or "") if images else ""


def load_printify_product_mockup(design, api=None):
    """Read the exact connected product mockup without changing external state."""
    product_id = _clean(design["printify_product_id"])
    if not product_id:
        return None
    printify_api = api or PrintifyAPI.from_env()
    if printify_api is None:
        return None
    try:
        product = printify_api.get_product(product_id)
        source = select_printify_context_mockup(product)
        parsed = urlparse(source)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(
            ".printify.com"
        ):
            return None
        request = Request(source, headers={"User-Agent": "ShangooliOS/1.0"})
        with urlopen(request, timeout=20) as response:
            contents = response.read()
        with Image.open(BytesIO(contents)) as opened:
            return opened.convert("RGB")
    except (OSError, PrintifyAPIError, ValueError):
        return None


def render_pinterest_bundle(design, product_key, *, product_mockup=None):
    """Render one deterministic product-specific 2:3 Pinterest image."""
    copy = pinterest_bundle_copy(design, product_key)
    source = standalone_designs.product_asset_path(design)
    if source is None:
        raise ValueError("The prepared product graphic is missing")
    with Image.open(source) as opened:
        graphic = opened.convert("RGBA")
    if product_key == "mug_11oz_black_accent" and BLACK_ACCENT_PINTEREST_SCENE.path.is_file():
        with Image.open(BLACK_ACCENT_PINTEREST_SCENE.path) as opened:
            approved_scene = composite_design_on_scene(
                opened, graphic, BLACK_ACCENT_PINTEREST_SCENE
            )
        product_mockup = approved_scene
    elif product_mockup is None:
        product_mockup = load_printify_product_mockup(design)

    accent = product_key == "mug_11oz_black_accent"
    canvas = Image.new("RGB", PINTEREST_IMAGE_SIZE, "#f8f5ef")
    draw = ImageDraw.Draw(canvas)

    # Keep the surrounding treatment quiet so the real product remains the hero.
    draw.rectangle((0, 1250, 1000, 1500), fill="#17213b")

    title_font = _font(FONT_BOLD, 36)
    product_font = _font(FONT_BOLD, 29)
    brand_font = _font(FONT_BOLD, 28)
    message = copy["message"]

    if product_mockup is not None:
        # The real Printify context mockup accurately reflects the chosen mug variant.
        photo = _cover(product_mockup.convert("RGB"), (1000, 1250))
        canvas.paste(photo, (0, 0))
    else:
        # Offline/legacy fallback: accurate but intentionally simple product rendering.
        mug_left, mug_top, mug_right, mug_bottom = 235, 500, 765, 1085
        handle_fill = "#17191e" if accent else "#f4f4f2"
        handle_outline = "#050607" if accent else "#c9c7c1"
        draw.ellipse((680, 635, 900, 920), fill=handle_fill, outline=handle_outline, width=12)
        draw.ellipse((722, 681, 846, 868), fill="#fffaf3")
        draw.rounded_rectangle(
            (mug_left, mug_top, mug_right, mug_bottom),
            70,
            fill="#fdfdfb",
            outline="#c9c7c1",
            width=4,
        )
        rim_fill = "#111318" if accent else "#dddcd7"
        draw.ellipse((mug_left, mug_top - 18, mug_right, mug_top + 85), fill=rim_fill)
        draw.ellipse((mug_left + 24, mug_top + 4, mug_right - 24, mug_top + 58), fill="#4b2d21")

        graphic = _contain(graphic, (390, 250))
        gx = int((mug_left + mug_right - graphic.width) / 2)
        gy = int(mug_top + 230 - graphic.height / 2)
        canvas.paste(graphic, (gx, gy), graphic)

    # A compact subject cue adds search context without competing with the photo.
    label_font = _font(FONT_BOLD, 23)
    label_width = draw.textbbox((0, 0), copy["audience_label"], font=label_font)[2]
    draw.rounded_rectangle(
        (38, 38, 82 + label_width, 92),
        24,
        fill="#fbfaf7",
    )
    draw.text((60, 54), copy["audience_label"], font=label_font, fill="#17213b")

    message_font = _fit_text(draw, message, FONT_BOLD, 860, 36, minimum=26)
    draw.text((70, 1280), message, font=message_font, fill="#ffffff")
    draw.text((70, 1330), copy["product_label"], font=product_font, fill="#a99df7")
    draw.line((70, 1380, 930, 1380), fill="#46506a", width=2)
    draw.text((70, 1402), "ShangooliShop", font=brand_font, fill="#ffffff")
    draw.text(
        (70, 1445),
        _placement_claim(design["placement_mode"]),
        font=_font(FONT_REGULAR, 24),
        fill="#c9cddd",
    )

    output = BytesIO()
    canvas.save(output, "PNG", optimize=True)
    return output.getvalue()


def pinterest_download_name(design, product_key):
    safe_name = re.sub(r"[^a-z0-9]+", "-", _clean(design["name"]).lower()).strip("-")
    return f"{safe_name or 'design'}-{product_key}-pinterest.png"
