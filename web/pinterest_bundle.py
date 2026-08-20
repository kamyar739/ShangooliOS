"""Read-only Pinterest bundle generation for standalone products."""

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from web import standalone_designs
from web import mug_gallery
from web.etsy_validation import parse_tags
from web.printify_api import PrintifyAPI, PrintifyAPIError
from web.product_blueprints import get_product_blueprint
from web.mug_scene_profiles import (
    BLACK_ACCENT_PINTEREST_SCENE,
    MugSceneProfile,
    composite_design_on_scene,
    composite_product_render_on_scene,
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
TEACHER_PINTEREST_STYLES = (
    {
        "key": "classroom_story",
        "label": "High-school classroom",
        "description": "An energetic classroom scene with older students.",
        "filename": "pinterest-high-school-classroom-empty-table-v1.png",
    },
    {
        "key": "elementary_classroom",
        "label": "Elementary classroom",
        "description": "A warm collaborative classroom with grade-school students.",
        "filename": "pinterest-elementary-collaboration-v1.png",
    },
    {
        "key": "middle_school_science",
        "label": "Middle-school science",
        "description": "A bright science lesson with older students.",
        "filename": "pinterest-middle-school-science-v1.png",
    },
    {
        "key": "kindergarten_art",
        "label": "Kindergarten art",
        "description": "Younger children creating colorful classroom art.",
        "filename": "pinterest-kindergarten-art-v1.png",
    },
    {
        "key": "kindergarten_reading",
        "label": "Kindergarten reading",
        "description": "A cozy story-time scene with younger children.",
        "filename": "pinterest-kindergarten-reading-v1.png",
    },
    {
        "key": "kindergarten_learning",
        "label": "Kindergarten learning",
        "description": "Younger children learning through colorful hands-on play.",
        "filename": "pinterest-kindergarten-learning-v1.png",
    },
)
DOCTOR_PINTEREST_STYLES = (
    {
        "key": "doctor_consultation",
        "label": "Doctor consultation office",
        "description": "A warm, welcoming physician consultation room.",
        "filename": "pinterest-doctor-consultation-office-v1.png",
    },
    {
        "key": "doctor_workroom",
        "label": "Hospital physician workroom",
        "description": "A bright clinical workroom with a clean foreground.",
        "filename": "pinterest-doctor-workroom-v1.png",
    },
    {
        "key": "doctor_specialist",
        "label": "Medical specialist office",
        "description": "A refined specialist office with medical details.",
        "filename": "pinterest-doctor-specialist-office-v1.png",
    },
    {
        "key": "doctor_private_office",
        "label": "Private doctor office",
        "description": "A premium private physician office in deep medical blue.",
        "filename": "pinterest-doctor-private-office-v1.png",
    },
    {
        "key": "doctor_lounge",
        "label": "Doctors' lounge",
        "description": "A fresh hospital staff workspace and break area.",
        "filename": "pinterest-doctor-lounge-v1.png",
    },
    {
        "key": "doctor_exam_room",
        "label": "Modern exam room",
        "description": "A clean, calm outpatient exam room.",
        "filename": "pinterest-doctor-exam-room-v1.png",
    },
)
PINTEREST_STYLES = TEACHER_PINTEREST_STYLES + DOCTOR_PINTEREST_STYLES
DEFAULT_PINTEREST_STYLE = "classroom_story"
DEFAULT_DOCTOR_PINTEREST_STYLE = "doctor_consultation"


def _font(path, size):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _clean(value):
    return " ".join(str(value or "").split()).strip()


def pinterest_style_options(collection_code=None):
    if _clean(collection_code).upper() == "DOCTOR":
        return DOCTOR_PINTEREST_STYLES
    return TEACHER_PINTEREST_STYLES


def normalize_pinterest_style(style, collection_code=None):
    options = (
        pinterest_style_options(collection_code)
        if collection_code
        else PINTEREST_STYLES
    )
    default = (
        DEFAULT_DOCTOR_PINTEREST_STYLE
        if _clean(collection_code).upper() == "DOCTOR"
        else DEFAULT_PINTEREST_STYLE
    )
    selected = _clean(style) or default
    if selected not in {item["key"] for item in options}:
        raise ValueError("Choose a supported Pinterest ad style")
    return selected


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


def _storefront_slug(message):
    slug = re.sub(r"[^a-z0-9]+", "-", _clean(message).lower()).strip("-")
    return slug or "teacher-mug"


def pinterest_bundle_copy(design, product_key):
    """Build editable Pinterest copy from the selected saved product row."""
    _, blueprint = get_product_blueprint(product_key)
    message = _clean(design["message"] or design["name"])
    product_label = blueprint["label"]
    tags = parse_tags(design["tags"] or "")
    collection_code = _clean(
        design["mug_collection_code"]
        if "mug_collection_code" in design.keys()
        else ""
    ).upper()
    searchable_identity = " ".join(
        [message, *tags, _clean(design["description"])]
    ).lower()
    doctor = collection_code == "DOCTOR" or any(
        term in searchable_identity
        for term in ("doctor", "physician", "medical mug", "resident gift")
    )
    teacher = collection_code == "TEACHER" or any(
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
    if doctor:
        topics.append("Doctor gifts")
    elif teacher:
        topics.append("Teacher gifts")
    else:
        topics.append("Gift ideas")
    if subject:
        topics.append(subject.title())
    topics.append("Coffee mugs")
    audience_label = (
        "DOCTOR GIFT"
        if doctor
        else
        f"{subject.upper()} TEACHER GIFT"
        if subject
        else "TEACHER GIFT"
        if teacher
        else "THOUGHTFUL GIFT"
    )
    collection_slug = _storefront_slug(
        collection_code
        or ("DOCTOR" if doctor else "TEACHER" if teacher else "EVERYDAY")
    )
    campaign = f"{collection_slug.replace('-', '_')}_mugs"
    creative_slug = _storefront_slug(message)
    return {
        "title": title,
        "description": description,
        "link": (
            f"https://shangooli.com/collections/{collection_slug}"
            f"?utm_source=pinterest&utm_medium=social&utm_campaign={campaign}"
            f"&utm_content={creative_slug}"
        ),
        "alt_text": alt_text,
        "board": (
            "Doctor Gift Ideas"
            if doctor
            else PINTEREST_BOARD_TEACHER if teacher else PINTEREST_BOARD_DEFAULT
        ),
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


def select_printify_camera_mockup(product, camera_label):
    """Select one exact Printify camera angle, with the normal fallback."""
    for image in product.get("images") or []:
        source = str(image.get("src") or "")
        camera = parse_qs(urlparse(source).query).get("camera_label", [""])[0]
        if camera == camera_label:
            return source
    return select_printify_context_mockup(product)


def load_printify_product_mockup(design, api=None, *, camera_label=None):
    """Read the exact connected product mockup without changing external state."""
    product_id = _clean(design["printify_product_id"])
    if not product_id:
        return None
    printify_api = api or PrintifyAPI.from_env()
    if printify_api is None:
        return None
    try:
        product = printify_api.get_product(product_id)
        source = (
            select_printify_camera_mockup(product, camera_label)
            if camera_label
            else select_printify_context_mockup(product)
        )
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


def load_local_product_mockup(design):
    """Load the exact locally approved side-view product image when present."""
    try:
        filename = design["product_thumbnail_filename"]
    except (KeyError, TypeError, IndexError):
        filename = ""
    path = mug_gallery.gallery_path(filename)
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            return opened.convert("RGB")
    except OSError:
        return None


def _wrapped_lines(draw, text, font, max_width, maximum_lines=3):
    words = _clean(text).split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
            if len(lines) == maximum_lines - 1:
                break
        else:
            current = candidate
    consumed = sum(len(line.split()) for line in lines)
    remaining = words[consumed:]
    if remaining:
        current = " ".join(remaining)
        while draw.textbbox((0, 0), current, font=font)[2] > max_width and " " in current:
            current = current.rsplit(" ", 1)[0]
        if consumed + len(current.split()) < len(words):
            current = current.rstrip(" ,.-") + "…"
    if current and len(lines) < maximum_lines:
        lines.append(current)
    return lines


def _draw_headline(draw, message, box, *, fill, start_size=58, maximum_lines=3):
    left, top, right, bottom = box
    for size in range(start_size, 29, -2):
        font = _font(FONT_BOLD, size)
        lines = _wrapped_lines(draw, message.upper(), font, right - left, maximum_lines)
        line_height = round(size * 1.02)
        if len(lines) * line_height <= bottom - top:
            break
    y = top
    for line in lines:
        draw.text((left, y), line, font=font, fill=fill)
        y += line_height


def _draw_benefit_strip(draw, y, *, dark=True):
    background = "#123d3d" if dark else "#f5e8d4"
    foreground = "#ffffff" if dark else "#173f3f"
    muted = "#cce1d9" if dark else "#8b4a2e"
    draw.rectangle((0, y, 1000, 1500), fill=background)
    benefits = (
        ("01", "EXACT MUG"),
        ("02", "READY TO GIFT"),
        ("03", "SHOP ON ETSY"),
    )
    width = 1000 // len(benefits)
    for index, (number, title) in enumerate(benefits):
        x = index * width + 42
        if index:
            draw.line((index * width, y + 42, index * width, 1460), fill=muted, width=2)
        draw.text((x, y + 28), number, font=_font(FONT_BOLD, 34), fill=muted)
        draw.text((x, y + 84), title, font=_font(FONT_BOLD, 33), fill=foreground)


def _pinterest_headline(message):
    """Use a stronger curiosity hook when a proven message benefits from it."""
    if _clean(message).casefold() == "they think i know everything":
        return "Every Student Thinks I Know Everything"
    return message


def _pinterest_scene_profile(style):
    option = next(item for item in PINTEREST_STYLES if item["key"] == style)
    return MugSceneProfile(
        style,
        option["label"],
        option["filename"],
        BLACK_ACCENT_PINTEREST_SCENE.artwork_box,
        BLACK_ACCENT_PINTEREST_SCENE.artwork_scale,
        # Make the product the first read. This is about 18% larger than the
        # prior 56%-wide treatment while preserving the visual center.
        (0.17, 0.40, 0.83, 0.85),
        BLACK_ACCENT_PINTEREST_SCENE.product_width_scale,
        BLACK_ACCENT_PINTEREST_SCENE.handle_width_scale,
        BLACK_ACCENT_PINTEREST_SCENE.handle_height_scale,
    )


def _approved_product_scene(
    design, product_key, graphic, *, style, product_mockup=None
):
    """Build the lifestyle scene around the exact saved product photograph."""
    if product_mockup is None:
        product_mockup = load_local_product_mockup(design)
    if product_mockup is None:
        product_mockup = load_printify_product_mockup(design, camera_label="left")
    profile = _pinterest_scene_profile(style)
    with Image.open(profile.path) as opened:
        # Keep the people gently in the background while the exact saved mug
        # and typography remain crisp.
        softened = opened.convert("RGB").filter(ImageFilter.GaussianBlur(3.0))
        if product_mockup is not None:
            return composite_product_render_on_scene(
                softened, product_mockup, profile
            )
        return composite_design_on_scene(
            softened, graphic, profile
        )


def _render_classroom_story(scene, copy):
    canvas = _cover(scene, PINTEREST_IMAGE_SIZE)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1000, 286), fill="#f7efdf")
    draw.rectangle((0, 280, 1000, 288), fill="#dc9d16")
    _draw_headline(
        draw,
        _pinterest_headline(copy["message"]),
        (54, 38, 720, 258),
        fill="#123d3d",
        start_size=64,
    )
    # A large, high-contrast audience badge remains legible during a fast
    # Pinterest scroll without competing with the product itself.
    draw.ellipse((748, 36, 958, 246), fill="#e85d24", outline="#ffd166", width=8)
    badge_lines = copy["audience_label"].replace(" GIFT", "\nGIFT")
    draw.multiline_text(
        (853, 90), badge_lines,
        font=_font(FONT_BOLD, 41), fill="#ffffff", anchor="ma", align="center", spacing=2,
    )
    draw.rounded_rectangle(
        (630, 1184, 950, 1288), 48, fill="#e85d24", outline="#ffd166", width=5
    )
    draw.text(
        (790, 1207), "SHOP ON ETSY", font=_font(FONT_BOLD, 38),
        fill="#ffffff", anchor="ma",
    )
    _draw_benefit_strip(draw, 1320, dark=True)
    return canvas


def _render_gift_guide(scene, copy):
    canvas = Image.new("RGB", PINTEREST_IMAGE_SIZE, "#f6ead7")
    draw = ImageDraw.Draw(canvas)
    photo = _cover(scene, (910, 925))
    canvas.paste(photo, (45, 350))
    draw.rounded_rectangle((45, 40, 955, 310), 28, fill="#fffaf0", outline="#d8b98c", width=3)
    draw.text((78, 70), "THE GIFT THEY'LL ACTUALLY USE", font=_font(FONT_BOLD, 25), fill="#b9502e")
    _draw_headline(draw, copy["message"], (78, 112, 915, 286), fill="#173f3f", start_size=48)
    draw.rounded_rectangle((84, 1095, 540, 1295), 24, fill="#fffaf0", outline="#d8b98c", width=2)
    for index, text in enumerate(("Classroom-ready humor", "Black handle + interior", "Ships from Etsy")):
        y = 1130 + index * 48
        draw.ellipse((112, y + 3, 130, y + 21), fill="#d99a18")
        draw.text((148, y), text, font=_font(FONT_BOLD, 22), fill="#263c3c")
    _draw_benefit_strip(draw, 1320, dark=False)
    return canvas


def _render_bold_product(scene, copy):
    canvas = Image.new("RGB", PINTEREST_IMAGE_SIZE, "#143f3d")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((42, 365, 958, 1245), 32, fill="#f7efdf")
    photo = _cover(scene, (880, 840))
    canvas.paste(photo, (60, 385))
    draw.text((56, 48), "A LITTLE CLASSROOM HUMOR", font=_font(FONT_BOLD, 24), fill="#efaa27")
    _draw_headline(draw, copy["message"], (56, 98, 930, 325), fill="#ffffff", start_size=58)
    draw.rounded_rectangle((690, 1160, 930, 1218), 29, fill="#b94d2c")
    draw.text((810, 1176), "SHOP ON ETSY", font=_font(FONT_BOLD, 19), fill="#ffffff", anchor="ma")
    _draw_benefit_strip(draw, 1280, dark=True)
    return canvas


def render_pinterest_bundle(
    design, product_key, *, product_mockup=None, style=DEFAULT_PINTEREST_STYLE
):
    """Render one deterministic product-specific 2:3 Pinterest image."""
    copy = pinterest_bundle_copy(design, product_key)
    source = standalone_designs.product_asset_path(design)
    if source is None:
        raise ValueError("The prepared product graphic is missing")
    with Image.open(source) as opened:
        graphic = opened.convert("RGBA")
    selected_style = normalize_pinterest_style(style)
    selected_profile = _pinterest_scene_profile(selected_style)
    if selected_profile.path.is_file() and (
        product_key == "mug_11oz_black_accent"
        or load_local_product_mockup(design) is not None
    ):
        approved_scene = _approved_product_scene(
            design,
            product_key,
            graphic,
            style=selected_style,
            product_mockup=product_mockup,
        )
        canvas = _render_classroom_story(approved_scene, copy)
        output = BytesIO()
        canvas.save(output, "PNG", optimize=True)
        return output.getvalue()
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
