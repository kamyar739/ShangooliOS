"""Deterministic listing-image generation for ShangooliShop artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


CANVAS_SIZE = (2000, 2000)
GENERATED_SLOTS = ("hero", "detail", "sizes")
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


def _hero(artwork: Image.Image, title: str) -> Image.Image:
    canvas = Image.new("RGB", CANVAS_SIZE, "#f4f1eb")
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
        fill="#2d2b29",
    )
    mat = 22
    draw.rectangle(
        (frame_x + mat, frame_y + mat, frame_x + frame_w - mat, frame_y + frame_h - mat),
        fill="#fbfaf7",
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


def _detail(artwork: Image.Image, title: str) -> Image.Image:
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


def _sizes(artwork: Image.Image, title: str) -> Image.Image:
    canvas = Image.new("RGB", CANVAS_SIZE, "#fbfaf7")
    draw = ImageDraw.Draw(canvas)
    draw.text((120, 100), "AVAILABLE PRINT RATIOS", fill="#252321", font=_font(70, bold=True))
    draw.text((120, 205), "Choose the proportion that works best for your wall.", fill="#6c6760", font=_font(36))

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

    footer = (title.strip() or "ShangooliShop Artwork") + " • Horizontal ratio guide"
    draw.text((120, 1840), footer, fill="#77716a", font=_font(30))
    return canvas


def generate_mockups(*, artwork: dict, source_path: Path, output_folder: Path) -> list[dict]:
    """Generate the dependable v1 mockups and return assignment-ready metadata."""
    source = _load_artwork(source_path)
    title = artwork.get("public_title") or artwork.get("working_title") or ""
    code = artwork["artwork_code"]

    builders = {"hero": _hero, "detail": _detail, "sizes": _sizes}
    results: list[dict] = []
    for slot_key in GENERATED_SLOTS:
        filename = f"{code}_mockup_{slot_key}.jpg"
        destination = output_folder / filename
        _save(builders[slot_key](source, title), destination)
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
