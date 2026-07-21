"""Deterministic listing-image generation for ShangooliShop artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from web.template_packs import DEFAULT_TEMPLATE_PACK, get_template_pack


CANVAS_SIZE = (2000, 2000)
GENERATED_SLOTS = ("hero", "room", "bedroom", "office", "detail", "sizes", "how_it_works", "collection")
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_artwork(source_path: Path) -> Image.Image:
    if source_path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError("Mockups require a JPG, PNG, TIFF, or WebP artwork file.")
    try:
        with Image.open(source_path) as source:
            return ImageOps.exif_transpose(source).convert("RGB")
    except OSError as error:
        raise ValueError("The assigned artwork file could not be opened as an image.") from error


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _save(canvas: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(destination, "JPEG", quality=94, optimize=True, progressive=True)


def _hero(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    profile = get_template_pack(template_key)
    canvas = Image.new("RGB", CANVAS_SIZE, profile["mat"])
    draw = ImageDraw.Draw(canvas)

    draw.ellipse((180, 1450, 1820, 1770), fill="#ded8cf")

    max_art = (1370, 1180)
    art = _fit(artwork, max_art)
    frame_padding = 44
    frame_w = art.width + frame_padding * 2
    frame_h = art.height + frame_padding * 2
    frame_x = (CANVAS_SIZE[0] - frame_w) // 2
    frame_y = 220 + (1180 - art.height) // 2

    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (frame_x + 30, frame_y + 34, frame_x + frame_w + 30, frame_y + frame_h + 34),
        radius=14,
        fill=(0, 0, 0, 82),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle(
        (frame_x, frame_y, frame_x + frame_w, frame_y + frame_h),
        radius=10,
        fill=profile["frame"],
    )
    mat = 22
    draw.rectangle(
        (frame_x + mat, frame_y + mat, frame_x + frame_w - mat, frame_y + frame_h - mat),
        fill=profile["mat"],
    )
    art_x = frame_x + frame_padding
    art_y = frame_y + frame_padding
    canvas.paste(art, (art_x, art_y))

    title_font = _font(66, bold=True)
    shop_font = _font(34)
    safe_title = title.strip() or "ShangooliShop Artwork"
    title_box = draw.textbbox((0, 0), safe_title, font=title_font)
    title_width = title_box[2] - title_box[0]
    if title_width > 1680:
        title_font = _font(48, bold=True)
        title_box = draw.textbbox((0, 0), safe_title, font=title_font)
        title_width = title_box[2] - title_box[0]
    draw.text(((2000 - title_width) / 2, 1640), safe_title, fill="#292724", font=title_font)
    shop_text = "ShangooliShop • Fine Art Print"
    shop_box = draw.textbbox((0, 0), shop_text, font=shop_font)
    draw.text(((2000 - (shop_box[2] - shop_box[0])) / 2, 1740), shop_text, fill="#6f6a63", font=shop_font)
    return canvas


def _detail(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    canvas = Image.new("RGB", CANVAS_SIZE, "#f7f5f1")
    detail = _cover(artwork, (1740, 1440))
    canvas.paste(detail, (130, 120))

    overlay = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((130, 1300, 1870, 1560), fill=(17, 17, 17, 132))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    label_font = _font(42, bold=True)
    title_font = _font(58, bold=True)
    body_font = _font(34)
    draw.text((205, 1340), "ARTWORK DETAIL", fill="white", font=label_font)
    display_title = title.strip() or "Original Artwork"
    draw.text((205, 1410), display_title[:48], fill="white", font=title_font)
    draw.text((205, 1492), "A closer look at the color, movement, and composition.", fill="#ece9e2", font=body_font)

    draw.text((140, 1685), "Printed from a high-resolution master", fill="#302e2b", font=_font(42, bold=True))
    draw.text((140, 1765), "Frame and decorative objects are not included.", fill="#706b64", font=_font(32))
    return canvas




def _artwork_orientation(artwork: Image.Image) -> str:
    difference = abs(artwork.width - artwork.height) / max(artwork.width, artwork.height)
    if difference <= 0.015:
        return "square"
    return "horizontal" if artwork.width > artwork.height else "vertical"


def _frame_box(artwork: Image.Image, center_x: int, top: int, max_width: int, max_height: int) -> tuple[int, int, int, int]:
    """Choose a frame footprint that matches horizontal, vertical, or square art."""
    orientation = _artwork_orientation(artwork)
    if orientation == "vertical":
        width, height = int(max_width * 0.68), max_height
    elif orientation == "square":
        side = min(max_width, max_height)
        width = height = side
    else:
        width, height = max_width, int(max_height * 0.78)
    left = center_x - width // 2
    return (left, top, left + width, top + height)

def _paste_framed_art(
    canvas: Image.Image,
    artwork: Image.Image,
    box: tuple[int, int, int, int],
    *,
    frame_color: str = "#2f2b28",
    mat_color: str = "#faf8f3",
    shadow_offset: tuple[int, int] = (24, 28),
) -> None:
    """Place artwork into a straight-on frame while preserving its proportions."""
    left, top, right, bottom = box
    frame_w = right - left
    frame_h = bottom - top
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    ox, oy = shadow_offset
    sd.rectangle((left + ox, top + oy, right + ox, bottom + oy), fill=(0, 0, 0, 72))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    canvas.alpha_composite(shadow) if canvas.mode == "RGBA" else canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB"))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle((left, top, right, bottom), fill=frame_color)
    outer = 28
    draw.rectangle((left + outer, top + outer, right - outer, bottom - outer), fill=mat_color)
    inner_pad = 55
    target = (max(1, frame_w - 2 * (outer + inner_pad)), max(1, frame_h - 2 * (outer + inner_pad)))
    art = _fit(artwork, target)
    art_x = left + (frame_w - art.width) // 2
    art_y = top + (frame_h - art.height) // 2
    canvas.paste(art, (art_x, art_y))


def _room(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    """Warm modern living-room mockup rendered without external template assets."""
    profile = get_template_pack(template_key)
    canvas = Image.new("RGB", CANVAS_SIZE, profile["wall"])
    draw = ImageDraw.Draw(canvas)
    # Wall and floor
    draw.rectangle((0, 0, 2000, 1450), fill=profile["wall"])
    draw.rectangle((0, 1450, 2000, 2000), fill=profile["floor"])
    for y in range(1460, 2000, 85):
        draw.line((0, y, 2000, y - 35), fill="#a87f61", width=5)
    # Window and curtains
    draw.rectangle((90, 180, 580, 1060), fill="#c7d8dd")
    draw.rectangle((120, 210, 550, 1030), fill="#edf4f5")
    draw.line((335, 210, 335, 1030), fill="#c2cccf", width=12)
    draw.line((120, 620, 550, 620), fill="#c2cccf", width=12)
    draw.polygon([(40, 120), (180, 120), (140, 1120), (0, 1120)], fill="#c8b29d")
    draw.polygon([(490, 120), (650, 120), (700, 1120), (560, 1120)], fill="#c8b29d")
    # Sofa
    draw.rounded_rectangle((230, 1260, 1740, 1790), radius=70, fill="#c9c0b2")
    draw.rounded_rectangle((300, 1120, 1670, 1530), radius=60, fill="#d7d0c5")
    draw.rounded_rectangle((340, 1220, 760, 1530), radius=45, fill="#b6a89a")
    draw.rounded_rectangle((1190, 1220, 1610, 1530), radius=45, fill="#8e9b8f")
    # Side table and plant
    draw.ellipse((1570, 1500, 1880, 1605), fill="#765b48")
    draw.rectangle((1705, 1580, 1740, 1870), fill="#765b48")
    draw.ellipse((1560, 1750, 1880, 1840), fill="#6d503e")
    draw.rectangle((90, 1300, 210, 1650), fill="#7b5f4a")
    draw.ellipse((35, 1180, 265, 1390), fill="#7e967d")
    draw.ellipse((50, 1080, 180, 1320), fill="#6f8d70")
    draw.ellipse((130, 1040, 260, 1330), fill="#86a184")

    _paste_framed_art(canvas, artwork, _frame_box(artwork, 1142, 180, 745, 835), frame_color=profile["frame"], mat_color=profile["mat"])
    draw.text((760, 1055), "IN-ROOM FRAMED MOCKUP", fill="#68615a", font=_font(28, bold=True))
    return canvas


def _bedroom(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    """Minimal bedroom lifestyle mockup rendered without external assets."""
    profile = get_template_pack(template_key)
    canvas = Image.new("RGB", CANVAS_SIZE, profile["wall"])
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 2000, 1420), fill=profile["wall"])
    draw.rectangle((0, 1420, 2000, 2000), fill=profile["floor"])
    # Bed
    draw.rounded_rectangle((260, 1170, 1760, 1860), radius=55, fill="#e5ded5")
    draw.rounded_rectangle((330, 1070, 1690, 1500), radius=50, fill="#faf8f3")
    draw.rounded_rectangle((390, 1140, 850, 1460), radius=45, fill="#d4c7bb")
    draw.rounded_rectangle((1110, 1140, 1570, 1460), radius=45, fill="#c8d0c8")
    draw.polygon([(340, 1480), (1650, 1480), (1760, 1900), (250, 1900)], fill="#b7a799")
    # Lamps and side tables
    for x in (140, 1700):
        draw.rectangle((x, 1430, x + 170, 1510), fill="#7a5d47")
        draw.rectangle((x + 65, 1220, x + 100, 1430), fill="#755e4f")
        draw.polygon([(x + 15, 1210), (x + 150, 1210), (x + 120, 1035), (x + 45, 1035)], fill="#d9cbb8")
    _paste_framed_art(canvas, artwork, _frame_box(artwork, 1000, 130, 820, 810), frame_color=profile["frame"], mat_color=profile["mat"])
    draw.text((120, 1885), "Styled bedroom presentation • Frame shown for display", fill="#6d665e", font=_font(30))
    return canvas



def _office(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    """Calm modern office mockup for an additional buyer context."""
    profile = get_template_pack(template_key)
    canvas = Image.new("RGB", CANVAS_SIZE, profile["wall"])
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 2000, 1450), fill=profile["wall"])
    draw.rectangle((0, 1450, 2000, 2000), fill=profile["floor"])
    # Desk and storage
    draw.rounded_rectangle((220, 1320, 1780, 1455), radius=24, fill="#765a45")
    draw.rectangle((300, 1450, 360, 1900), fill="#624936")
    draw.rectangle((1640, 1450, 1700, 1900), fill="#624936")
    draw.rectangle((260, 420, 650, 1230), fill="#d6cfc5")
    for y in (600, 800, 1000):
        draw.line((290, y, 620, y), fill="#a79e93", width=8)
    # Monitor, lamp, books and plant
    draw.rounded_rectangle((1130, 1190, 1570, 1430), radius=20, fill="#323438")
    draw.rectangle((1315, 1430, 1385, 1510), fill="#323438")
    draw.rectangle((1230, 1510, 1470, 1540), fill="#323438")
    draw.rectangle((760, 1280, 840, 1450), fill="#8d6c54")
    draw.polygon([(700, 1290), (900, 1290), (855, 1090), (745, 1090)], fill="#d6c7ae")
    draw.rectangle((455, 1235, 680, 1310), fill="#7c8d80")
    draw.rectangle((470, 1160, 665, 1235), fill="#b7775e")
    draw.ellipse((1570, 1100, 1830, 1320), fill="#7c977b")
    draw.rectangle((1665, 1280, 1735, 1450), fill="#84634c")
    _paste_framed_art(canvas, artwork, _frame_box(artwork, 1135, 180, 750, 840), frame_color=profile["frame"], mat_color=profile["mat"])
    draw.text((120, 1880), "MODERN OFFICE PRESENTATION • FRAME SHOWN FOR DISPLAY", fill="#68615a", font=_font(29))
    return canvas


def _how_it_works(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    """Clear ordering explainer that reduces common buyer questions."""
    canvas = Image.new("RGB", CANVAS_SIZE, "#f7f3ec")
    draw = ImageDraw.Draw(canvas)
    draw.text((120, 105), "HOW IT WORKS", fill="#282522", font=_font(78, bold=True))
    draw.text((120, 220), "From artwork selection to a finished wall display.", fill="#6b655e", font=_font(36))

    art = _fit(artwork, (650, 650))
    draw.rounded_rectangle((105, 390, 805, 1120), radius=28, fill="#ffffff", outline="#d9d2c8", width=5)
    canvas.paste(art, (455 - art.width // 2, 745 - art.height // 2))
    draw.text((180, 1160), "1  CHOOSE YOUR SIZE", fill="#282522", font=_font(42, bold=True))
    draw.text((180, 1230), "Select the ratio and dimensions that fit your wall.", fill="#6b655e", font=_font(30))

    steps = [
        ("2", "WE PRINT IT", "Your artwork is professionally produced to order."),
        ("3", "FRAME OR HANG", "Add your preferred frame and display it your way."),
        ("4", "ENJOY THE ROOM", "Bring color, movement, and personality into your space."),
    ]
    y = 440
    for number, heading, body in steps:
        draw.ellipse((970, y, 1100, y + 130), fill="#2d2b29")
        num_box = draw.textbbox((0, 0), number, font=_font(54, bold=True))
        draw.text((1035 - (num_box[2]-num_box[0])/2, y + 28), number, fill="#fffaf2", font=_font(54, bold=True))
        draw.text((1160, y + 5), heading, fill="#282522", font=_font(42, bold=True))
        draw.multiline_text((1160, y + 70), body, fill="#6b655e", font=_font(30), spacing=8)
        y += 360

    draw.line((120, 1735, 1880, 1735), fill="#d8d0c6", width=4)
    draw.text((120, 1790), "Artwork only • Frame and decorative objects are not included", fill="#6b655e", font=_font(31))
    draw.text((120, 1860), "SHANGOOLISHOP", fill="#282522", font=_font(38, bold=True))
    return canvas

def _collection(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    profile = get_template_pack(template_key)
    canvas = Image.new("RGB", CANVAS_SIZE, profile["text"])
    draw = ImageDraw.Draw(canvas)
    # Decorative celebration arcs
    draw.arc((80, 90, 850, 860), 195, 350, fill=profile["accent"], width=34)
    draw.arc((1200, 1180, 2050, 2030), 15, 170, fill=profile["accent"], width=38)
    art = _fit(artwork, (1180, 1050))
    frame_x = 410
    frame_y = 180
    frame_w = 1180
    frame_h = 1100
    draw.rectangle((frame_x, frame_y, frame_x + frame_w, frame_y + frame_h), fill="#f6f1e8")
    art_x = frame_x + (frame_w - art.width) // 2
    art_y = frame_y + (frame_h - art.height) // 2
    canvas.paste(art, (art_x, art_y))

    draw.text((160, 1370), "THE CELEBRATION COLLECTION", fill="#d6a764", font=_font(40, bold=True))
    display_title = (title.strip() or "Joyful Contemporary Art")[:46]
    draw.text((160, 1450), display_title, fill="#fffaf2", font=_font(72, bold=True))
    draw.text((160, 1570), "Art that brings movement, color, and joy into the room.", fill="#d8d0c7", font=_font(35))
    draw.line((160, 1690, 1840, 1690), fill="#645d57", width=3)
    draw.text((160, 1760), "SHANGOOLISHOP", fill="#fffaf2", font=_font(46, bold=True))
    draw.text((160, 1835), "Original artwork • Professionally printed", fill="#aaa29a", font=_font(30))
    return canvas

def _ratio_thumbnail(artwork: Image.Image, ratio: tuple[int, int], max_size: tuple[int, int]) -> Image.Image:
    width, height = ratio
    if artwork.width >= artwork.height:
        target_ratio = width / height
    else:
        target_ratio = height / width
    max_w, max_h = max_size
    if max_w / max_h > target_ratio:
        target_h = max_h
        target_w = int(target_h * target_ratio)
    else:
        target_w = max_w
        target_h = int(target_w / target_ratio)
    return _cover(artwork, (max(1, target_w), max(1, target_h)))


def _sizes(artwork: Image.Image, title: str, template_key: str = DEFAULT_TEMPLATE_PACK) -> Image.Image:
    canvas = Image.new("RGB", CANVAS_SIZE, "#fbfaf7")
    draw = ImageDraw.Draw(canvas)
    draw.text((120, 100), "AVAILABLE PRINT RATIOS", fill="#252321", font=_font(70, bold=True))
    draw.text((120, 205), "Choose the proportion that works best for your wall.", fill="#6c6760", font=_font(36))

    orientation = _artwork_orientation(artwork)
    if orientation == "vertical":
        ratios = (("2:3", (2, 3)), ("3:4", (3, 4)), ("4:5", (4, 5)), ("11:14", (11, 14)))
    elif orientation == "square":
        ratios = (("1:1", (1, 1)), ("Square", (1, 1)), ("Square", (1, 1)), ("Square", (1, 1)))
    else:
        ratios = (("3:2", (3, 2)), ("4:3", (4, 3)), ("5:4", (5, 4)), ("14:11", (14, 11)))
    positions = ((120, 390), (1040, 390), (120, 1040), (1040, 1040))
    for (label, ratio), (x, y) in zip(ratios, positions):
        thumb = _ratio_thumbnail(artwork, ratio, (700, 470))
        frame_w, frame_h = thumb.width + 42, thumb.height + 42
        frame_x = x + (760 - frame_w) // 2
        frame_y = y
        draw.rectangle((frame_x + 16, frame_y + 18, frame_x + frame_w + 16, frame_y + frame_h + 18), fill="#d8d4cd")
        draw.rectangle((frame_x, frame_y, frame_x + frame_w, frame_y + frame_h), fill="#302e2b")
        canvas.paste(thumb, (frame_x + 21, frame_y + 21))
        label_box = draw.textbbox((0, 0), label, font=_font(54, bold=True))
        draw.text((x + (760 - (label_box[2] - label_box[0])) / 2, y + 520), label, fill="#272522", font=_font(54, bold=True))

    footer = (title.strip() or "ShangooliShop Artwork") + f" • {orientation.title()} ratio guide"
    draw.text((120, 1840), footer, fill="#77716a", font=_font(30))
    return canvas


def generate_mockups(*, artwork: dict, source_path: Path, output_folder: Path, template_key: str = DEFAULT_TEMPLATE_PACK) -> list[dict]:
    """Generate all eight listing images and return assignment-ready metadata."""
    get_template_pack(template_key)
    source = _load_artwork(source_path)
    title = artwork.get("public_title") or artwork.get("working_title") or ""
    code = artwork["artwork_code"]

    builders = {
        "hero": _hero,
        "room": _room,
        "bedroom": _bedroom,
        "office": _office,
        "detail": _detail,
        "sizes": _sizes,
        "how_it_works": _how_it_works,
        "collection": _collection,
    }
    results: list[dict] = []
    for slot_key in GENERATED_SLOTS:
        filename = f"{code}_listing_{slot_key}_{template_key}.jpg"
        destination = output_folder / filename
        _save(builders[slot_key](source, title, template_key), destination)
        results.append(
            {
                "slot_key": slot_key,
                "role": f"mockup:{slot_key}",
                "path": destination,
                "stored_filename": filename,
                "original_filename": filename,
            }
        )
    return results


def generate_listing_image(*, slot_key: str, artwork: dict, source_path: Path, output_folder: Path, template_key: str = DEFAULT_TEMPLATE_PACK) -> dict:
    """Generate one listing image without replacing the other seven."""
    get_template_pack(template_key)
    if slot_key not in GENERATED_SLOTS:
        raise ValueError(f"Unknown listing image slot: {slot_key}")
    source = _load_artwork(source_path)
    title = artwork.get("public_title") or artwork.get("working_title") or ""
    builders = {
        "hero": _hero,
        "room": _room,
        "bedroom": _bedroom,
        "office": _office,
        "detail": _detail,
        "sizes": _sizes,
        "how_it_works": _how_it_works,
        "collection": _collection,
    }
    code = artwork["artwork_code"]
    filename = f"{code}_listing_{slot_key}_{template_key}.jpg"
    destination = output_folder / filename
    _save(builders[slot_key](source, title, template_key), destination)
    return {
        "slot_key": slot_key,
        "role": f"mockup:{slot_key}",
        "path": destination,
        "stored_filename": filename,
        "original_filename": filename,
    }


def generate_scene_mockup(
    *, artwork: dict, source_path: Path, scene_path: Path, scene: dict,
    output_folder: Path,
) -> dict:
    """Composite approved artwork into a reusable room scene placement."""
    artwork_image = _load_artwork(source_path)
    try:
        with Image.open(scene_path) as opened_scene:
            scene_image = ImageOps.exif_transpose(opened_scene).convert("RGB")
    except OSError as error:
        raise ValueError("The saved room scene could not be opened") from error
    canvas = _cover(scene_image, CANVAS_SIZE).filter(ImageFilter.GaussianBlur(28))
    foreground = _fit(scene_image, CANVAS_SIZE)
    scene_left = (CANVAS_SIZE[0] - foreground.width) // 2
    scene_top = (CANVAS_SIZE[1] - foreground.height) // 2
    canvas.paste(foreground, (scene_left, scene_top))

    left = scene_left + round(foreground.width * float(scene["placement_x"]) / 100)
    top = scene_top + round(foreground.height * float(scene["placement_y"]) / 100)
    width = round(foreground.width * float(scene["placement_width"]) / 100)
    height = round(foreground.height * float(scene["placement_height"]) / 100)
    frame = 20
    art = _fit(artwork_image, (max(1, width - frame * 2), max(1, height - frame * 2)))
    frame_width, frame_height = art.width + frame * 2, art.height + frame * 2
    frame_left = left + (width - frame_width) // 2
    frame_top = top + (height - frame_height) // 2
    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rectangle(
        (frame_left + 18, frame_top + 22, frame_left + frame_width + 18, frame_top + frame_height + 22),
        fill=(0, 0, 0, 75),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (frame_left, frame_top, frame_left + frame_width, frame_top + frame_height),
        fill="#2d2b29",
    )
    canvas.paste(art, (frame_left + frame, frame_top + frame))

    safe_scene_name = "".join(
        character.lower() if character.isalnum() else "-"
        for character in scene["name"]
    ).strip("-") or "scene"
    filename = f"{artwork['artwork_code']}_listing_room_{safe_scene_name}.jpg"
    destination = output_folder / filename
    _save(canvas, destination)
    return {
        "slot_key": "room",
        "role": "mockup:room",
        "path": destination,
        "stored_filename": filename,
        "original_filename": filename,
    }
