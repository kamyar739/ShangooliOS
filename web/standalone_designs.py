"""Standalone message designs and their first Printify mug product."""

import hashlib
import re
import secrets
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from web.db import (
    get_standalone_product_placement_default,
    get_standalone_design,
    record_standalone_marketplace_status,
    save_standalone_design_product,
    save_standalone_product_placement_default,
    set_standalone_product_state,
)
from web.etsy_api import get_etsy_listing
from web.printify_api import (
    PrintifyAPI,
    PrintifyAPIConnectionError,
    PrintifyAPIError,
    PrintifyProductCreationUnknown,
    create_printify_product,
)
from web.product_blueprints import (
    DEFAULT_MUG_BLUEPRINT_KEY,
    PRODUCT_BLUEPRINTS,
    get_product_blueprint,
    placement_profile,
    product_readiness,
    resolve_artwork_treatment,
)


DESIGN_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets" / "designs"
QUICK_TEXT_FONT = Path(
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
)
QUICK_TEXT_CANVAS = (3200, 1312)
QUICK_TEXT_NAVY = (7, 14, 48, 255)
QUICK_TEXT_BLUE = (41, 36, 190, 255)
TEMPLATE_CANVAS = (2400, 2400)
TEMPLATE_INK = (39, 38, 38, 255)
TEMPLATE_TEAL = (28, 112, 104, 255)
TEMPLATE_MEDICAL_BLUE = (53, 109, 154, 255)
TEMPLATE_GOLD = (232, 171, 42, 255)
TEMPLATE_SERIF_FONT = Path("/System/Library/Fonts/Supplemental/Didot.ttc")
TEMPLATE_SCRIPT_FONT = Path("/System/Library/Fonts/Supplemental/SignPainter.ttc")
TEMPLATE_BLOCK_FONT = Path("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf")


_MARKETPLACE_PUNCTUATION = str.maketrans({
    "–": "-",
    "—": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    " ": " ",
})


def printify_safe_marketplace_copy(title, description):
    """Normalize listing copy without ever changing the printed artwork."""
    def normalize(value, *, multiline):
        value = str(value or "").translate(_MARKETPLACE_PUNCTUATION)
        value = re.sub(r"(?<=\d)\s*%", " Percent", value)
        value = value.replace("%", " Percent")
        value = "".join(
            character
            for character in value
            if character in "\n\t" or ord(character) >= 32
        )
        if multiline:
            return "\n".join(
                re.sub(r"[ \t]+", " ", line).strip()
                for line in value.splitlines()
            ).strip()
        return re.sub(r"\s+", " ", value).strip()

    safe_title = normalize(title, multiline=False)
    safe_description = normalize(description, multiline=True)
    if not safe_title:
        raise ValueError("Enter the Etsy title")
    if len(safe_title) > 140:
        raise ValueError("Keep the Etsy title at 140 characters or fewer")
    if not safe_description:
        raise ValueError("Enter the Etsy description")
    return safe_title, safe_description


def mug_profile(blueprint_key=DEFAULT_MUG_BLUEPRINT_KEY):
    """Resolve one supported mug blueprint and its reusable placement rules."""
    key, blueprint = get_product_blueprint(blueprint_key)
    if blueprint["family"] != "mugs":
        raise ValueError("Choose a supported mug product")
    placement = placement_profile(blueprint["placement_profile"])
    saved = get_standalone_product_placement_default(key)
    return {
        "product_key": key,
        # Compatibility for existing callers and templates.
        "product_type": key,
        **blueprint,
        "placement_x": saved["placement_x"] if saved else placement["x"],
        "placement_y": saved["placement_y"] if saved else placement["y"],
        "placement_scale": saved["placement_scale"] if saved else placement["scale"],
        "placement_mode": saved["placement_mode"] if saved else "front",
        "right_hand_x": placement["right_hand_x"],
        "left_hand_x": placement["left_hand_x"],
    }


def capture_printify_placement_default(
    design_id,
    blueprint_key,
    *,
    confirmed,
    api=None,
):
    """Store a linked product's current Printify placement for future products."""
    if not confirmed:
        raise ValueError("Confirm using the current Printify placement as the future default")
    profile = mug_profile(blueprint_key)
    design = get_standalone_design(design_id, blueprint_key)
    if design is None or not design["printify_product_id"]:
        raise ValueError("Create and review this product in Printify first")
    client = api or PrintifyAPI.from_env()
    if client is None:
        raise ValueError("Connect Printify before capturing its placement")
    remote = client.get_product(design["printify_product_id"])
    areas = remote.get("print_areas") or []
    matching = [
        area for area in areas
        if profile["variant_id"] in (area.get("variant_ids") or [])
    ]
    if len(matching) != 1:
        raise ValueError("Printify returned an ambiguous print area; no default was changed")
    placeholders = matching[0].get("placeholders") or []
    if len(placeholders) != 1 or placeholders[0].get("position") != "front":
        raise ValueError("Printify returned an unexpected mug placeholder; no default was changed")
    images = placeholders[0].get("images") or []
    if not images:
        raise ValueError("Printify did not return a placed design")
    mode = design["placement_mode"] or "front"
    placed = max(images, key=lambda item: float(item.get("scale") or 0))
    remote_x = float(placed["x"])
    remote_y = float(placed["y"])
    remote_scale = float(placed["scale"])
    base_x = profile["left_hand_x"] if mode == "reverse" else profile["right_hand_x"]
    normalized_x = 0.5 + ((remote_x - base_x) / 0.3)
    if not (0.0 <= normalized_x <= 1.0 and 0.0 <= remote_y <= 1.0 and 0.05 <= remote_scale <= 2.0):
        raise ValueError("Printify returned placement values outside the safe range")
    save_standalone_product_placement_default(
        blueprint_key,
        placement_x=normalized_x,
        placement_y=remote_y,
        placement_scale=remote_scale,
        placement_mode=mode,
        source_printify_product_id=design["printify_product_id"],
    )
    return {
        "placement_x": normalized_x,
        "placement_y": remote_y,
        "placement_scale": remote_scale,
        "placement_mode": mode,
    }


# Preserve the established import and existing white-mug behavior.
MUG_PROFILE = mug_profile()


def publish_standalone_product(
    design_id,
    blueprint_key=DEFAULT_MUG_BLUEPRINT_KEY,
    *,
    confirmed,
    api=None,
):
    """Safely submit one existing Printify product to its sales channel."""
    if not confirmed:
        raise ValueError("Confirm publishing through Printify")
    design = get_standalone_design(design_id, blueprint_key)
    if design is None:
        raise ValueError("Design not found")
    if not design["printify_product_id"]:
        raise ValueError("Create the Printify mug draft first")
    if design["etsy_listing_id"]:
        return {"product_key": blueprint_key, "outcome": "already_published"}
    if design["external_state"] in {
        "publish_requested",
        "publish_outcome_unknown",
    }:
        return {
            "product_key": blueprint_key,
            "outcome": design["external_state"],
        }

    client = api or PrintifyAPI.from_env()
    if client is None:
        raise ValueError("Connect Printify before publishing")
    try:
        client.get_product(design["printify_product_id"])
        client.publish_product(design["printify_product_id"], include_images=True)
    except PrintifyAPIConnectionError:
        message = (
            "Printify may have accepted the request. Check status; do not "
            "publish again yet."
        )
        set_standalone_product_state(
            design_id,
            "publish_outcome_unknown",
            message,
            product_key=blueprint_key,
        )
        return {
            "product_key": blueprint_key,
            "outcome": "publish_outcome_unknown",
            "message": message,
        }
    except PrintifyAPIError as error:
        set_standalone_product_state(
            design_id,
            "publish_failed",
            str(error),
            product_key=blueprint_key,
        )
        return {
            "product_key": blueprint_key,
            "outcome": "publish_failed",
            "message": str(error),
        }

    message = (
        "Printify accepted the publication request. Check status to finish "
        "Etsy synchronization."
    )
    set_standalone_product_state(
        design_id,
        "publish_requested",
        message,
        product_key=blueprint_key,
    )
    return {
        "product_key": blueprint_key,
        "outcome": "publish_requested",
        "message": message,
    }


TEACHER_SUBJECTS = (
    (
        "biology",
        ("biology", "cell", "cells", "dna", "genetic", "organism"),
        "science teacher",
    ),
    (
        "chemistry",
        ("chemistry", "chemical", "reaction", "periodic", "element", "molecule", "atom"),
        "science teacher",
    ),
    (
        "physics",
        ("physics", "gravity", "force", "quantum"),
        "science teacher",
    ),
    (
        "science",
        ("science", "curiosity"),
        "science teacher",
    ),
    (
        "math",
        (
            "math",
            "mathematics",
            "algebra",
            "geometry",
            "calculus",
            "equation",
            "solve problems",
            "solving problems",
        ),
        "math teacher",
    ),
    (
        "english",
        ("english", "grammar", "literature", "reading", "writing", "punctuation"),
        "english teacher",
    ),
    (
        "history",
        ("history", "historical", "the past"),
        "history teacher",
    ),
    (
        "music",
        ("music", "musical", "rhythm"),
        "music teacher",
    ),
    (
        "art",
        (
            "art teacher",
            "art class",
            "painting class",
            "creativity",
            "creative curriculum",
        ),
        "art teacher",
    ),
    (
        "elementary",
        ("elementary", "tiny humans", "little learners"),
        "elementary teacher",
    ),
)


def _etsy_safe_tags(candidates):
    """Return unique Etsy-sized tags in the supplied priority order."""
    tags = []
    seen = set()
    for candidate in candidates:
        tag = " ".join(str(candidate or "").lower().split()).strip(" ,")
        key = tag.casefold()
        if not tag or len(tag) > 20 or key in seen:
            continue
        tags.append(tag)
        seen.add(key)
        if len(tags) == 13:
            break
    return tags


def _teacher_metadata(message: str):
    lower_message = message.lower()
    subject = ""
    broader_teacher = ""
    for name, signals, broad_tag in TEACHER_SUBJECTS:
        if any(signal in lower_message for signal in signals):
            subject = name
            broader_teacher = broad_tag
            break

    teacher_signals = (
        "teacher",
        "teaching",
        "i teach",
        "classroom",
        "lesson",
        "student",
        "brilliant minds",
        "find their spark",
        "grading",
        "educator",
        "masters degree in patience",
    )
    teacher_audience = bool(subject) or any(
        signal in lower_message for signal in teacher_signals
    )
    if not teacher_audience:
        return None

    humorous_signals = (
        "coffee",
        "silently",
        "correcting",
        "problem",
        "reaction",
        "cell",
        "gravity",
        "periodic",
        "masters degree",
        "past present",
    )
    inspirational_signals = (
        "superpower",
        "inspire",
        "believe",
        "difference",
        "future",
        "dream",
    )
    appreciation_signals = ("thank", "best teacher", "amazing teacher")
    if any(signal in lower_message for signal in humorous_signals):
        tone = "humor"
    elif any(signal in lower_message for signal in inspirational_signals):
        tone = "inspirational"
    elif any(signal in lower_message for signal in appreciation_signals):
        tone = "appreciation"
    else:
        tone = ""

    subject_teacher = f"{subject} teacher" if subject else ""
    subject_mug = f"{subject} mug" if subject else ""
    subject_gift = f"{subject} gift" if subject else ""
    candidates = [
        "teacher",
        subject,
        tone,
        subject_teacher,
        broader_teacher,
        "teacher gift",
        subject_mug,
        "classroom humor" if tone == "humor" else "classroom inspiration",
        "teacher coffee mug",
        subject_gift,
        "educator gift",
        "school gift",
        "funny teacher mug" if tone == "humor" else "inspiring teacher",
        "quote mug",
        "typography mug",
    ]
    return {
        "subject": subject,
        "audience": (
            f"{subject} teachers, educators, coworkers, or students looking "
            "for a memorable teacher gift"
            if subject
            else "teachers, educators, coworkers, or students looking for a memorable gift"
        ),
        "tags": _etsy_safe_tags(candidates),
    }


def suggested_mug_title(
    message: str, blueprint_key: str = DEFAULT_MUG_BLUEPRINT_KEY
):
    """Create concise search-oriented copy for one specific mug blueprint."""
    exact_message = " ".join(str(message or "").split()).strip()
    if not exact_message:
        return ""
    _, blueprint = get_product_blueprint(blueprint_key)
    product_label = blueprint["marketplace_title_product"]
    display_message = exact_message.rstrip(" .!?")
    teacher_metadata = _teacher_metadata(exact_message)
    if teacher_metadata:
        subject = teacher_metadata.get("subject") or ""
        prefix = (
            f"{subject.title()} Teacher {product_label}"
            if subject
            else f"Teacher {product_label}"
        )
        return f"{prefix} – {display_message}"
    return f"{product_label} – {display_message}"


def design_metadata_from_message(message: str):
    """Build editable starter copy from text already present in a design."""
    exact_message = " ".join(str(message or "").split()).strip()
    if not exact_message:
        return {"name": "", "description": "", "tags": ""}
    name = exact_message.rstrip(" .!?")[:120]
    lower_message = exact_message.lower()
    teacher_metadata = _teacher_metadata(exact_message)
    if teacher_metadata:
        audience = teacher_metadata["audience"]
    elif "coffee" in lower_message or "espresso" in lower_message:
        audience = "coffee lovers, coworkers, friends, or anyone who enjoys a memorable quote"
    else:
        audience = "friends, coworkers, or anyone who enjoys a memorable quote"
    description = (
        f'A clean typographic mug featuring “{exact_message}” '
        f"It is an easy everyday gift for {audience}."
    )
    if teacher_metadata:
        tags = teacher_metadata["tags"]
    else:
        candidates = [
            (
                "coffee mug"
                if "coffee" in lower_message or "espresso" in lower_message
                else ""
            ),
            "wine lover gift" if "wine" in lower_message else "",
            "quote mug",
            "typography mug",
            "message mug",
            "unique gift",
            "coworker gift",
            "desk mug",
        ]
        tags = _etsy_safe_tags(candidates)
    return {
        "name": name,
        "description": description,
        "tags": ", ".join(tags),
    }


def _wrap_quick_text(draw, message, font, max_width):
    explicit_lines = [
        " ".join(line.split()) for line in message.splitlines() if line.strip()
    ]
    if len(explicit_lines) > 1:
        return explicit_lines
    words = " ".join(message.split()).split()
    lines = []
    current = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def render_quick_text_design(
    message: str,
    style_variant: int | None = None,
    *,
    accent_graphics: bool = False,
):
    """Render the approved Shangooli mixed-typography template as a transparent PNG."""
    normalized = "\n".join(
        " ".join(line.split()) for line in str(message or "").splitlines()
        if line.strip()
    ).strip()
    if not normalized:
        raise ValueError("Enter the message for the design")
    if len(normalized) > 180:
        raise ValueError("Keep the quick design message under 180 characters")
    return render_mixed_typography_design(
        normalized,
        style_variant=style_variant,
        accent_graphics=accent_graphics,
    )


def _balanced_template_lines(message, target_lines=4):
    explicit = [" ".join(line.split()) for line in message.splitlines() if line.strip()]
    if len(explicit) > 1:
        return explicit[:5]
    words = " ".join(message.split()).split()
    if len(words) <= 3:
        return [" ".join(words)]
    line_count = min(target_lines, max(2, (len(words) + 1) // 2))
    lines = []
    start = 0
    for index in range(line_count):
        remaining_words = len(words) - start
        remaining_lines = line_count - index
        take = max(1, round(remaining_words / remaining_lines))
        lines.append(" ".join(words[start:start + take]))
        start += take
    if start < len(words):
        lines[-1] = f"{lines[-1]} {' '.join(words[start:])}"
    return lines


def _fit_template_font(draw, text, font_path, max_width, preferred_size):
    for size in range(preferred_size, 79, -8):
        font = ImageFont.truetype(str(font_path), size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
    return ImageFont.truetype(str(font_path), 80)


def _mixed_word_segments(text, primary, accent, selector):
    """Occasionally split one substantial word between two coordinated colors."""
    matches = list(re.finditer(r"[A-Za-z]{5,}", text))
    if not matches:
        return [(text, primary)]
    match = matches[selector % len(matches)]
    word = match.group(0)
    split = max(2, min(len(word) - 2, len(word) // 2))
    return [
        (text[:match.start()], primary),
        (word[:split], primary),
        (word[split:], accent),
        (text[match.end():], primary),
    ]


def _draw_centered_segments(draw, y, segments, font):
    widths = [draw.textlength(text, font=font) for text, _color in segments]
    x = (TEMPLATE_CANVAS[0] - sum(widths)) / 2
    for (text, color), width in zip(segments, widths):
        draw.text((x, y), text, font=font, fill=color, stroke_width=1)
        x += width


def _draw_accent_graphics(draw, variant):
    """Draw restrained, clearly visible abstract shapes around the typography."""
    palettes = (
        (TEMPLATE_MEDICAL_BLUE, TEMPLATE_TEAL),
        (TEMPLATE_TEAL, TEMPLATE_GOLD),
        (TEMPLATE_MEDICAL_BLUE, TEMPLATE_GOLD),
    )
    primary, secondary = palettes[variant % len(palettes)]
    # Keep the center clear for wording while making the selected format
    # unmistakably different from Text Only.
    draw.ellipse((120, 250, 390, 520), fill=primary)
    draw.ellipse((245, 390, 455, 600), fill=TEMPLATE_GOLD)
    draw.polygon(((1940, 190), (2260, 315), (2130, 610), (1835, 440)), fill=secondary)
    draw.rounded_rectangle((115, 1840, 500, 1970), radius=65, fill=secondary)
    draw.rounded_rectangle((180, 2020, 625, 2140), radius=60, fill=primary)
    draw.ellipse((1930, 1830, 2280, 2180), outline=primary, width=48)
    draw.ellipse((2025, 1925, 2185, 2085), fill=TEMPLATE_GOLD)


def render_mixed_typography_design(
    message: str,
    style_variant: int | None = None,
    *,
    accent_graphics: bool = False,
):
    """Render editable phrases with the approved colorful teacher-mug recipe."""
    normalized = "\n".join(
        " ".join(line.split()) for line in str(message or "").splitlines()
        if line.strip()
    ).strip()
    if not normalized:
        raise ValueError("Enter the message for the design")
    if len(normalized) > 180:
        raise ValueError("Keep the quick design message under 180 characters")

    canvas = Image.new("RGBA", TEMPLATE_CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    lines = _balanced_template_lines(normalized)
    digest = hashlib.sha256(normalized.casefold().encode("utf-8")).digest()
    style_recipes = [
        [
            (TEMPLATE_SERIF_FONT, TEMPLATE_INK, 285, True),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_TEAL, 390, False),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_MEDICAL_BLUE, 390, True),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_INK, 300, False),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_TEAL, 270, True),
        ],
        [
            (TEMPLATE_BLOCK_FONT, TEMPLATE_TEAL, 330, True),
            (TEMPLATE_SERIF_FONT, TEMPLATE_INK, 300, False),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_MEDICAL_BLUE, 380, False),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_INK, 310, True),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_TEAL, 310, False),
        ],
        [
            (TEMPLATE_SERIF_FONT, TEMPLATE_MEDICAL_BLUE, 300, True),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_INK, 380, False),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_TEAL, 375, True),
            (TEMPLATE_SERIF_FONT, TEMPLATE_INK, 285, False),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_MEDICAL_BLUE, 300, False),
        ],
        [
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_TEAL, 360, False),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_INK, 350, True),
            (TEMPLATE_SERIF_FONT, TEMPLATE_MEDICAL_BLUE, 310, True),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_INK, 320, False),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_TEAL, 285, True),
        ],
        [
            (TEMPLATE_BLOCK_FONT, TEMPLATE_INK, 345, True),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_MEDICAL_BLUE, 390, False),
            (TEMPLATE_SERIF_FONT, TEMPLATE_TEAL, 315, True),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_INK, 300, False),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_MEDICAL_BLUE, 300, False),
        ],
        [
            (TEMPLATE_SERIF_FONT, TEMPLATE_TEAL, 300, True),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_MEDICAL_BLUE, 365, True),
            (TEMPLATE_SCRIPT_FONT, TEMPLATE_INK, 390, False),
            (TEMPLATE_SERIF_FONT, TEMPLATE_MEDICAL_BLUE, 285, False),
            (TEMPLATE_BLOCK_FONT, TEMPLATE_TEAL, 285, True),
        ],
    ]
    recipe_index = (
        digest[0] % len(style_recipes)
        if style_variant is None
        else int(style_variant) % len(style_recipes)
    )
    if accent_graphics:
        _draw_accent_graphics(draw, recipe_index)
    recipes = style_recipes[recipe_index]
    accents = [TEMPLATE_TEAL, TEMPLATE_MEDICAL_BLUE, TEMPLATE_GOLD, TEMPLATE_INK]
    mixed_line = digest[1] % len(lines) if digest[2] % 3 else -1
    rendered = []
    max_width = 1980
    for index, line in enumerate(lines):
        font_path, color, preferred, uppercase = recipes[index % len(recipes)]
        if len(lines) == 3 and index == 1:
            # The middle line normally acts as the connector between the setup
            # and payoff, so keep it visibly quieter in every style option.
            preferred = max(220, round(preferred * 0.74))
        elif len(lines) == 3 and index == 2:
            # Give the punchline a reliable bold finish while retaining each
            # recipe's color variation.
            font_path = TEMPLATE_BLOCK_FONT
            preferred = max(390, preferred)
            uppercase = True
        display = line.upper() if uppercase else line
        font = _fit_template_font(draw, display, font_path, max_width, preferred)
        box = draw.textbbox((0, 0), display, font=font)
        segments = [(display, color)]
        if index == mixed_line:
            accent = accents[digest[3] % len(accents)]
            if accent == color:
                accent = accents[(digest[3] + 1) % len(accents)]
            segments = _mixed_word_segments(display, color, accent, digest[4])
        rendered.append(
            (
                display,
                font,
                color,
                segments,
                box[2] - box[0],
                box[3] - box[1],
                box[1],
            )
        )
    # Mixed script, serif, and condensed faces have very different ascenders
    # and descenders. Three-line phrases need deliberate breathing room or the
    # visual lines appear to collide even when their measured boxes do not.
    gap = 112 if len(rendered) == 3 else 96 if len(rendered) == 2 else 48
    total_height = sum(item[5] for item in rendered) + gap * (len(rendered) - 1)
    y = (TEMPLATE_CANVAS[1] - total_height) / 2
    for index, (text, font, color, segments, width, height, bbox_top) in enumerate(rendered):
        x = (TEMPLATE_CANVAS[0] - width) / 2
        # Pillow fonts carry different invisible offsets above their visible
        # glyphs. Draw against the measured visible top so serif, script, and
        # condensed lines all receive the same actual gap.
        _draw_centered_segments(draw, y - bbox_top, segments, font)
        if index == 0 and len(rendered) > 1:
            ray_y = y + height / 2
            for offset in (-42, 0, 42):
                draw.line((x - 115, ray_y + offset, x - 45, ray_y + offset / 2), fill=TEMPLATE_GOLD, width=18)
                draw.line((x + width + 45, ray_y + offset / 2, x + width + 115, ray_y + offset), fill=TEMPLATE_GOLD, width=18)
        y += height + gap
    if len(rendered) > 1:
        ornament_y = min(TEMPLATE_CANVAS[1] - 150, y + 40)
        center = TEMPLATE_CANVAS[0] / 2
        draw.line((center - 260, ornament_y, center - 70, ornament_y), fill=TEMPLATE_GOLD, width=14)
        draw.line((center + 70, ornament_y, center + 260, ornament_y), fill=TEMPLATE_GOLD, width=14)
        # Draw the small heart directly so it is reliable across local font versions.
        heart_x = center
        heart_y = ornament_y - 4
        draw.ellipse((heart_x - 31, heart_y - 34, heart_x - 1, heart_y - 4), fill=TEMPLATE_GOLD)
        draw.ellipse((heart_x + 1, heart_y - 34, heart_x + 31, heart_y - 4), fill=TEMPLATE_GOLD)
        draw.polygon(
            ((heart_x - 31, heart_y - 17), (heart_x + 31, heart_y - 17), (heart_x, heart_y + 27)),
            fill=TEMPLATE_GOLD,
        )
    output = BytesIO()
    canvas.save(output, "PNG", optimize=True)
    return output.getvalue()


def analyze_design_image(contents: bytes, original_filename: str = ""):
    """Read visible design text locally when Tesseract is available."""
    if not contents:
        raise ValueError("Choose a completed design image")
    executable = shutil.which("tesseract")
    if executable is None:
        return {
            "message": "",
            **design_metadata_from_message(""),
            "analysis_available": False,
        }
    suffix = Path(original_filename or "design.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        suffix = ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
        temporary.write(contents)
        temporary.flush()
        try:
            result = subprocess.run(
                [executable, temporary.name, "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
    message = " ".join((result.stdout if result else "").split()).strip()
    return {
        "message": message,
        **design_metadata_from_message(message),
        "analysis_available": True,
    }


def _printify_etsy_listing_id(product):
    external = product.get("external") or {}
    candidates = [
        external.get("id") if isinstance(external, dict) else None,
        external.get("handle") if isinstance(external, dict) else None,
    ]
    for candidate in candidates:
        match = re.search(r"(?:listing/)?(\d{6,})", str(candidate or ""))
        if match:
            return match.group(1)
    return None


def check_design_marketplace_status(
    design_id,
    *,
    printify_api=None,
    product_key=DEFAULT_MUG_BLUEPRINT_KEY,
):
    design = get_standalone_design(design_id, product_key)
    if design is None:
        raise ValueError("Design not found")
    if not design["printify_product_id"]:
        raise ValueError("Create the Printify product first")
    api = printify_api or PrintifyAPI.from_env()
    if api is None:
        raise ValueError("Printify API is not configured")
    product = api.get_product(design["printify_product_id"])
    etsy_id = _printify_etsy_listing_id(product)
    if not etsy_id:
        record_standalone_marketplace_status(
            design_id,
            message=(
                "Printify has not reported a connected Etsy listing yet. "
                "If you just published it, wait briefly and check again."
            ),
            product_key=product_key,
        )
        return {"linked": False}
    remote = get_etsy_listing(etsy_id)
    state = str(remote.get("state") or "").strip().lower()
    paused = state != "active"
    etsy_url = f"https://www.etsy.com/listing/{etsy_id}"
    record_standalone_marketplace_status(
        design_id,
        etsy_listing_id=etsy_id,
        etsy_listing_url=etsy_url,
        etsy_state=state,
        paused=paused,
        message=(
            "Etsy listing found and active."
            if state == "active"
            else f"Etsy listing found with status: {state or 'unknown'}."
        ),
        product_key=product_key,
    )
    return {"linked": True, "listing_id": etsy_id, "state": state}


def save_design_source(contents: bytes, original_filename: str):
    if not contents:
        raise ValueError("Choose a completed design image")
    DESIGN_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = DESIGN_ASSETS_DIR / f".upload-{secrets.token_hex(8)}"
    temporary.write_bytes(contents)
    try:
        with Image.open(temporary) as image:
            image.verify()
        with Image.open(temporary) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
            rgba = image.convert("RGBA")
            has_transparency = rgba.getchannel("A").getextrema()[0] < 255
    except (UnidentifiedImageError, OSError) as error:
        temporary.unlink(missing_ok=True)
        raise ValueError("Upload a valid PNG or JPEG design image") from error
    if image_format not in {"PNG", "JPEG"}:
        temporary.unlink(missing_ok=True)
        raise ValueError("Upload the completed design as a PNG or JPEG")
    extension = ".png" if image_format == "PNG" else ".jpg"
    filename = f"design-{secrets.token_hex(12)}{extension}"
    destination = DESIGN_ASSETS_DIR / filename
    temporary.replace(destination)
    return {
        "filename": filename,
        "original_filename": Path(original_filename or filename).name,
        "width": width,
        "height": height,
        "has_transparency": has_transparency,
    }


def design_source_path(design):
    if design is None:
        return None
    candidate = DESIGN_ASSETS_DIR / str(design["source_filename"] or "")
    try:
        candidate.resolve().relative_to(DESIGN_ASSETS_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def product_asset_path(design):
    """Return the product row's prepared asset, with a legacy-safe fallback."""
    if design is None:
        return None
    filename = design["production_asset_filename"] or design["source_filename"]
    candidate = DESIGN_ASSETS_DIR / str(filename or "")
    try:
        candidate.resolve().relative_to(DESIGN_ASSETS_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def removable_background_preview(design):
    """Return a safe transparent preview for a uniform, light edge background."""
    source = design_source_path(design)
    if source is None:
        return None
    with Image.open(source) as opened:
        rgba = opened.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] < 255:
        return None
    width, height = rgba.size
    sample_points = (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
    )
    samples = [rgba.getpixel(point)[:3] for point in sample_points]
    background = tuple(
        round(sum(sample[channel] for sample in samples) / len(samples))
        for channel in range(3)
    )
    if min(background) < 220:
        return None
    if any(
        max(abs(sample[channel] - background[channel]) for channel in range(3))
        > 18
        for sample in samples
    ):
        return None
    flood_points = (
        *sample_points,
        (width // 2, 0),
        (width // 2, height - 1),
        (0, height // 2),
        (width - 1, height // 2),
    )
    for point in flood_points:
        if rgba.getpixel(point)[3] == 255:
            ImageDraw.floodfill(
                rgba,
                point,
                (*background, 0),
                thresh=32,
            )
    alpha_histogram = rgba.getchannel("A").histogram()
    transparent_pixels = alpha_histogram[0]
    if (
        transparent_pixels < width * height * 0.02
        or transparent_pixels > width * height * 0.98
    ):
        return None
    output = BytesIO()
    rgba.save(output, "PNG", optimize=True)
    return output.getvalue()


def design_opposite_source_path(design):
    if design is None or not design["opposite_source_filename"]:
        return None
    candidate = DESIGN_ASSETS_DIR / str(design["opposite_source_filename"])
    try:
        candidate.resolve().relative_to(DESIGN_ASSETS_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


_MUG_PLACEMENT_DESCRIPTIONS = {
    "front": (
        "The design is printed on the right-handed side of the mug, so it "
        "faces outward when held in the right hand."
    ),
    "reverse": (
        "The design is printed on the left-handed side of the mug, so it "
        "faces outward when held in the left hand."
    ),
    "both": (
        "The design is printed on both sides for clear visibility when held "
        "in either hand."
    ),
    "different": (
        "The mug features a different design on each side for a distinct "
        "view from either direction."
    ),
}


def mug_description_for_placement(description, placement_mode):
    """Keep customer-facing mug copy accurate when its side setup changes."""
    normalized = " ".join(str(description or "").split()).strip()
    for placement_copy in _MUG_PLACEMENT_DESCRIPTIONS.values():
        normalized = normalized.replace(placement_copy, "").strip()
    normalized = normalized.rstrip()
    if normalized and normalized[-1] not in ".!?":
        normalized += "."
    placement_copy = _MUG_PLACEMENT_DESCRIPTIONS[placement_mode]
    return f"{normalized} {placement_copy}".strip()


def suggested_mug_description(description, blueprint_key, placement_mode):
    """Add only the selected blueprint's product facts and saved side setup."""
    normalized = " ".join(str(description or "").split()).strip()
    for blueprint in PRODUCT_BLUEPRINTS.values():
        detail = blueprint.get("marketplace_description_detail") or ""
        if detail:
            normalized = normalized.replace(detail, "").strip()
    _, blueprint = get_product_blueprint(blueprint_key)
    detail = blueprint.get("marketplace_description_detail") or ""
    if detail:
        normalized = f"{normalized.rstrip()} {detail}".strip()
    return mug_description_for_placement(normalized, placement_mode)


def save_mug_setup(
    design_id,
    *,
    blueprint_key=DEFAULT_MUG_BLUEPRINT_KEY,
    title,
    description,
    price_cents,
    placement_scale,
    placement_x=None,
    placement_y=None,
    placement_mode="front",
    opposite_source_filename=None,
    allow_existing_update=False,
):
    profile = mug_profile(blueprint_key)
    if placement_x is None:
        placement_x = profile["placement_x"]
    if placement_y is None:
        placement_y = profile["placement_y"]
    design = get_standalone_design(design_id, blueprint_key)
    if design is None:
        raise ValueError("Design not found")
    if (
        design["printify_product_id"]
        and design["external_state"] != "needs_update"
        and not allow_existing_update
    ):
        raise ValueError("The existing Printify mug is protected")
    if design["external_state"] in {"creating", "outcome_unknown"}:
        raise ValueError(
            "Verify the previous Printify attempt before changing this setup"
        )
    normalized_title = (title or "").strip()
    if not normalized_title:
        raise ValueError("Enter a product title")
    if not 0.25 <= placement_scale <= 0.9:
        raise ValueError("Choose a placement size between 25% and 90%")
    if not 0.1 <= placement_x <= 0.9:
        raise ValueError("Choose a horizontal position between 10% and 90%")
    if not 0.1 <= placement_y <= 0.9:
        raise ValueError("Choose a vertical position between 10% and 90%")
    if placement_mode not in {"front", "reverse", "both", "different"}:
        raise ValueError("Choose one side or both sides of the mug")
    existing_opposite = design["opposite_source_filename"]
    if placement_mode == "different" and not (
        opposite_source_filename or existing_opposite
    ):
        raise ValueError("Upload the graphic for the opposite side")
    if design["printify_product_id"] and allow_existing_update:
        set_standalone_product_state(
            design_id,
            "needs_update",
            "Mug setup changed. Update the existing Printify product.",
            product_key=blueprint_key,
        )
    save_standalone_design_product(
        design_id,
        product_key=blueprint_key,
        blueprint_version=profile["version"],
        # Editing placement must keep using this product's prepared artwork;
        # a newer design source is adopted only through the explicit prepare flow.
        production_asset_filename=(
            design["production_asset_filename"] or design["source_filename"]
        ),
        title=normalized_title,
        description=mug_description_for_placement(
            description, placement_mode
        ),
        price_cents=price_cents,
        blueprint_id=profile["blueprint_id"],
        provider_id=profile["provider_id"],
        provider_name=profile["provider_name"],
        variant_id=profile["variant_id"],
        variant_title=profile["variant_title"],
        placement_x=placement_x,
        placement_y=placement_y,
        placement_scale=placement_scale,
        placement_mode=placement_mode,
        opposite_source_filename=opposite_source_filename,
    )


def _mug_image_placements(design, source, profile=MUG_PROFILE):
    """Return saved mug graphics mapped onto the two physical mug faces."""
    placement_mode = design["placement_mode"] or "front"
    horizontal_offset = (design["placement_x"] - 0.5) * 0.3
    right_hand_x = profile["right_hand_x"] + horizontal_offset
    left_hand_x = profile["left_hand_x"] + horizontal_offset
    common = {
        "y": design["placement_y"],
        "scale": design["placement_scale"],
    }
    if placement_mode == "reverse":
        return [{"path": source, "x": left_hand_x, **common}]
    if placement_mode == "both":
        return [
            {"path": source, "x": right_hand_x, **common},
            {"path": source, "x": left_hand_x, **common},
        ]
    if placement_mode == "different":
        opposite_source = design_opposite_source_path(design)
        if opposite_source is None:
            raise ValueError("The opposite-side graphic is missing")
        return [
            {"path": source, "x": right_hand_x, **common},
            {"path": opposite_source, "x": left_hand_x, **common},
        ]
    return [{"path": source, "x": right_hand_x, **common}]


def create_mug_draft(
    design_id,
    *,
    confirmed,
    api=None,
    blueprint_key=DEFAULT_MUG_BLUEPRINT_KEY,
):
    if not confirmed:
        raise ValueError("Confirm creation of the unpublished Printify mug")
    profile = mug_profile(blueprint_key)
    design = get_standalone_design(design_id, blueprint_key)
    if design is None:
        raise ValueError("Design not found")
    if design["printify_product_id"]:
        return {
            "outcome": "existing",
            "message": "The existing Printify mug was preserved.",
            "product_url": design["printify_product_url"],
        }
    if design["external_state"] in {"creating", "outcome_unknown"}:
        raise ValueError(
            "The previous result is uncertain. Check Printify before trying again."
        )
    if not design["product_id"]:
        raise ValueError("Review and save the mug setup first")
    source = product_asset_path(design)
    if source is None:
        raise ValueError("The approved design image is missing")
    readiness = product_readiness(
        product=design if design["product_id"] else None,
        source_exists=True,
        blueprint=PRODUCT_BLUEPRINTS[blueprint_key],
    )
    if not readiness["ready"]:
        raise ValueError("; ".join(readiness["blockers"]))
    source = resolve_artwork_treatment(source, profile["artwork_treatment"])

    printify_api = api or PrintifyAPI.from_env()
    if printify_api is None:
        raise ValueError("Printify API is not configured")
    try:
        providers = printify_api.list_providers(design["blueprint_id"])
        provider = next(
            (
                item
                for item in providers
                if item["id"] == design["provider_id"]
                and item["title"] == design["provider_name"]
            ),
            None,
        )
        if provider is None:
            raise ValueError(
                "Printify changed or removed the configured mug provider"
            )
        variants = {
            item["id"]: item
            for item in printify_api.list_variants(
                design["blueprint_id"], provider["id"]
            )
        }
    except PrintifyAPIError as error:
        raise ValueError(
            f"Could not verify the current Printify mug catalog: {error}"
        ) from error
    variant = variants.get(design["variant_id"])
    if not variant or variant.get("is_available") is False:
        raise ValueError("The configured 11 oz mug is unavailable")
    if variant.get("title") != design["variant_title"]:
        raise ValueError("Printify changed the configured mug variant")
    placeholders = variant.get("placeholders") or []
    expected_area = profile["print_area"]
    if len(placeholders) != 1 or any(
        placeholders[0].get(field) != expected_area[field]
        for field in ("position", "width", "height")
    ):
        raise ValueError("Printify changed the configured mug print area")

    set_standalone_product_state(
        design_id,
        "creating",
        "Creating the unpublished Printify draft.",
        product_key=blueprint_key,
    )
    try:
        image_placements = _mug_image_placements(design, source, profile)
        safe_title, safe_description = printify_safe_marketplace_copy(
            design["product_title"], design["product_description"] or ""
        )
        result = create_printify_product(
            printify_api,
            listing={
                "title": safe_title,
                "description": safe_description,
            },
            blueprint_id=design["blueprint_id"],
            provider_id=design["provider_id"],
            provider_name=design["provider_name"],
            selections=[
                {
                    "variant_id": design["variant_id"],
                    "title": design["variant_title"],
                    "cost_cents": (
                        int(variant["cost"])
                        if variant.get("cost") is not None
                        else None
                    ),
                    "price_cents": design["price_cents"],
                    "path": source,
                }
            ],
            image_x=design["placement_x"],
            image_y=design["placement_y"],
            image_scale=design["placement_scale"],
            image_placements=image_placements,
        )
    except PrintifyProductCreationUnknown as error:
        set_standalone_product_state(
            design_id,
            "outcome_unknown",
            str(error),
            product_key=blueprint_key,
        )
        return {"outcome": "outcome_unknown", "message": str(error)}
    except (PrintifyAPIError, ValueError) as error:
        set_standalone_product_state(
            design_id, "failed", str(error), product_key=blueprint_key
        )
        return {"outcome": "failed", "message": str(error)}

    product = result["product"]
    set_standalone_product_state(
        design_id,
        "created",
        "Unpublished mug draft created in Printify.",
        product_key=blueprint_key,
        printify_product_id=str(product["id"]),
        printify_product_url=result["product_url"],
        base_cost_cents=result["base_cost_cents"],
    )
    return {
        "outcome": "created",
        "message": "Unpublished mug draft created in Printify.",
        "product_url": result["product_url"],
    }


def update_mug_draft_graphics(
    design_id,
    *,
    confirmed,
    api=None,
    blueprint_key=DEFAULT_MUG_BLUEPRINT_KEY,
    source_filename=None,
):
    """Refresh the existing mug product from current ShangooliOS content."""
    if not confirmed:
        raise ValueError("Confirm the update to the existing Printify draft")
    profile = mug_profile(blueprint_key)
    design = get_standalone_design(design_id, blueprint_key)
    if design is None:
        raise ValueError("Design not found")
    if not design["printify_product_id"]:
        raise ValueError("Create the Printify mug draft first")
    if design["external_state"] == "update_outcome_unknown":
        raise ValueError(
            "The previous update result is uncertain. Check Printify before retrying."
        )
    if source_filename:
        source = DESIGN_ASSETS_DIR / Path(source_filename).name
        if not source.is_file():
            source = None
    else:
        source = product_asset_path(design)
    if source is None:
        raise ValueError("The corrected design graphic is missing")
    source = resolve_artwork_treatment(source, profile["artwork_treatment"])
    printify_api = api or PrintifyAPI.from_env()
    set_standalone_product_state(
        design_id,
        "updating",
        "Updating the existing Printify mug draft.",
        product_key=blueprint_key,
    )
    try:
        product = printify_api.get_product(design["printify_product_id"])
        variants = product.get("variants") or []
        if not variants:
            raise ValueError("The existing Printify mug has no variants")
        placements = _mug_image_placements(design, source, profile)
        uploaded = {}
        for placement in placements:
            path = placement["path"]
            if path not in uploaded:
                uploaded[path] = printify_api.upload_image(path)["id"]
        images = [
            {
                "id": uploaded[item["path"]],
                "x": item["x"],
                "y": item["y"],
                "scale": item["scale"],
                "angle": 0,
            }
            for item in placements
        ]
        safe_title, safe_description = printify_safe_marketplace_copy(
            design["product_title"], design["product_description"] or ""
        )
        payload = {
            "title": safe_title,
            "description": safe_description,
            "variants": [
                {
                    "id": variant["id"],
                    "price": variant["price"],
                    "is_enabled": variant.get("is_enabled", False),
                }
                for variant in variants
            ],
            "print_areas": [
                {
                    "variant_ids": [variant["id"] for variant in variants],
                    "placeholders": [
                        {"position": "front", "images": images}
                    ],
                }
            ],
        }
        printify_api.update_product(design["printify_product_id"], payload)
    except PrintifyAPIConnectionError:
        message = (
            "Printify did not confirm the artwork update. Check the existing "
            "draft before trying again."
        )
        set_standalone_product_state(
            design_id,
            "update_outcome_unknown",
            message,
            product_key=blueprint_key,
        )
        return {"outcome": "outcome_unknown", "message": message}
    except (PrintifyAPIError, ValueError, KeyError) as error:
        set_standalone_product_state(
            design_id, "needs_update", str(error), product_key=blueprint_key
        )
        return {"outcome": "failed", "message": str(error)}
    set_standalone_product_state(
        design_id,
        "created",
        "The Printify mug artwork, title, and description were updated.",
        product_key=blueprint_key,
    )
    return {
        "outcome": "updated",
        "message": "The existing Printify mug draft was updated.",
        "product_url": design["printify_product_url"],
    }


def update_mug_draft_copy(
    design_id,
    *,
    confirmed,
    api=None,
    blueprint_key=DEFAULT_MUG_BLUEPRINT_KEY,
):
    """Update only a connected Printify product's title and description."""
    if not confirmed:
        raise ValueError(
            "Confirm the wording update to the existing Printify product"
        )
    design = get_standalone_design(design_id, blueprint_key)
    if design is None:
        raise ValueError("Design not found")
    if not design["printify_product_id"]:
        raise ValueError("Create the Printify mug draft first")
    if design["external_state"] == "update_outcome_unknown":
        raise ValueError(
            "The previous update result is uncertain. Check Printify before retrying."
        )

    printify_api = api or PrintifyAPI.from_env()
    set_standalone_product_state(
        design_id,
        "updating",
        "Updating the Printify product wording.",
        product_key=blueprint_key,
    )
    try:
        safe_title, safe_description = printify_safe_marketplace_copy(
            design["product_title"], design["product_description"] or ""
        )
        printify_api.update_product(
            design["printify_product_id"],
            {
                "title": safe_title,
                "description": safe_description,
            },
        )
    except PrintifyAPIConnectionError:
        message = (
            "Printify did not confirm the wording update. Check the existing "
            "product before trying again."
        )
        set_standalone_product_state(
            design_id,
            "update_outcome_unknown",
            message,
            product_key=blueprint_key,
        )
        return {"outcome": "outcome_unknown", "message": message}
    except (PrintifyAPIError, ValueError, KeyError) as error:
        set_standalone_product_state(
            design_id, "needs_update", str(error), product_key=blueprint_key
        )
        return {"outcome": "failed", "message": str(error)}

    set_standalone_product_state(
        design_id,
        "created",
        "The Printify product title and description were updated.",
        product_key=blueprint_key,
    )
    return {
        "outcome": "updated",
        "message": "The existing Printify product wording was updated.",
        "product_url": design["printify_product_url"],
    }
