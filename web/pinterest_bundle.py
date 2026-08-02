"""Read-only Pinterest bundle generation for standalone products."""

import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from web import standalone_designs
from web.etsy_validation import parse_tags
from web.product_blueprints import get_product_blueprint


PINTEREST_IMAGE_SIZE = (1000, 1500)
PINTEREST_BOARD_DEFAULT = "Gift Ideas"
PINTEREST_BOARD_TEACHER = "Teacher Gift Ideas"
FONT_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def _font(path, size):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _clean(value):
    return " ".join(str(value or "").split()).strip()


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
    topics = ["Teacher gifts", "Coffee mugs"] if teacher else ["Gift ideas", "Coffee mugs"]
    return {
        "title": title,
        "description": description,
        "link": design["etsy_listing_url"] or "",
        "alt_text": alt_text,
        "board": PINTEREST_BOARD_TEACHER if teacher else PINTEREST_BOARD_DEFAULT,
        "topics": topics,
        "message": message,
        "product_label": product_label,
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


def render_pinterest_bundle(design, product_key):
    """Render one deterministic product-specific 2:3 Pinterest image."""
    copy = pinterest_bundle_copy(design, product_key)
    source = standalone_designs.product_asset_path(design)
    if source is None:
        raise ValueError("The prepared product graphic is missing")
    with Image.open(source) as opened:
        graphic = opened.convert("RGBA")

    accent = product_key == "mug_11oz_black_accent"
    canvas = Image.new("RGB", PINTEREST_IMAGE_SIZE, "#f7f0e5")
    draw = ImageDraw.Draw(canvas)

    # Warm, repeatable lifestyle setting that remains clearly product-specific.
    draw.rounded_rectangle((45, 45, 955, 1455), 42, fill="#fffaf3")
    draw.ellipse((-170, -210, 420, 380), fill="#dfe8df")
    draw.ellipse((730, -90, 1100, 280), fill="#d97b43")
    draw.rectangle((45, 1010, 955, 1455), fill="#d3b28d")
    draw.rectangle((45, 1010, 955, 1030), fill="#b38761")

    title_font = _font(FONT_BOLD, 58)
    subtitle_font = _font(FONT_BOLD, 30)
    brand_font = _font(FONT_BOLD, 28)
    message = copy["message"]
    words = message.split()
    lines = []
    current = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and draw.textbbox((0, 0), candidate, font=title_font)[2] > 780:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    lines = lines[:3]
    y = 120
    for line in lines:
        font = _fit_text(draw, line, FONT_BOLD, 780, 58)
        width = draw.textbbox((0, 0), line, font=font)[2]
        draw.text(((1000 - width) / 2, y), line, font=font, fill="#17213b")
        y += 68
    draw.text((110, y + 18), copy["product_label"], font=subtitle_font, fill="#5b4bd8")

    # Mug body and handle. The selected blueprint controls the accent treatment.
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

    draw.text((105, 1140), "A thoughtful gift for", font=brand_font, fill="#6d5b4e")
    audience = "remarkable teachers" if copy["board"] == PINTEREST_BOARD_TEACHER else "someone memorable"
    audience_font = _fit_text(draw, audience.title(), FONT_BOLD, 790, 54)
    draw.text((105, 1185), audience.title(), font=audience_font, fill="#17213b")
    draw.line((105, 1270, 895, 1270), fill="#d5c5ae", width=2)
    draw.text((105, 1310), "ShangooliShop", font=_font(FONT_BOLD, 34), fill="#17213b")
    draw.text((105, 1360), "Thoughtful gifts · memorable messages", font=_font(FONT_REGULAR, 25), fill="#6d5b4e")

    output = BytesIO()
    canvas.save(output, "PNG", optimize=True)
    return output.getvalue()


def pinterest_download_name(design, product_key):
    safe_name = re.sub(r"[^a-z0-9]+", "-", _clean(design["name"]).lower()).strip("-")
    return f"{safe_name or 'design'}-{product_key}-pinterest.png"
