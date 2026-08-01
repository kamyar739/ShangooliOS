"""Standalone message designs and their first Printify mug product."""

import re
import secrets
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from web.db import (
    get_standalone_design,
    record_standalone_marketplace_status,
    save_standalone_design_product,
    set_standalone_product_state,
)
from web.etsy_api import get_etsy_listing
from web.printify_api import (
    PrintifyAPI,
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

def mug_profile(blueprint_key=DEFAULT_MUG_BLUEPRINT_KEY):
    """Resolve one supported mug blueprint and its reusable placement rules."""
    key, blueprint = get_product_blueprint(blueprint_key)
    if blueprint["family"] != "mugs":
        raise ValueError("Choose a supported mug product")
    placement = placement_profile(blueprint["placement_profile"])
    return {
        "product_key": key,
        # Compatibility for existing callers and templates.
        "product_type": key,
        **blueprint,
        "placement_x": placement["x"],
        "placement_y": placement["y"],
        "placement_scale": placement["scale"],
        "right_hand_x": placement["right_hand_x"],
        "left_hand_x": placement["left_hand_x"],
    }


# Preserve the established import and existing white-mug behavior.
MUG_PROFILE = mug_profile()


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
        "audience": (
            f"{subject} teachers, educators, coworkers, or students looking "
            "for a memorable teacher gift"
            if subject
            else "teachers, educators, coworkers, or students looking for a memorable gift"
        ),
        "tags": _etsy_safe_tags(candidates),
    }


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


def render_quick_text_design(message: str):
    """Render the fixed Shangooli quick-text style as a transparent PNG."""
    normalized = "\n".join(
        " ".join(line.split()) for line in str(message or "").splitlines()
        if line.strip()
    ).strip()
    if not normalized:
        raise ValueError("Enter the message for the design")
    if len(normalized) > 180:
        raise ValueError("Keep the quick design message under 180 characters")
    canvas = Image.new("RGBA", QUICK_TEXT_CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    max_width = 2720
    selected = None
    for size in range(270, 109, -10):
        font = ImageFont.truetype(str(QUICK_TEXT_FONT), size)
        lines = _wrap_quick_text(draw, normalized, font, max_width)
        line_height = round(size * 1.08)
        total_height = line_height * len(lines)
        widest_line = max(
            draw.textlength(line, font=font) for line in lines
        )
        if (
            len(lines) <= 4
            and total_height <= 900
            and widest_line <= max_width
        ):
            selected = (font, lines, line_height, total_height)
            break
    if selected is None:
        raise ValueError(
            "This message is too long for the quick design. Shorten it or "
            "upload a finished graphic."
        )
    font, lines, line_height, total_height = selected
    y = (QUICK_TEXT_CANVAS[1] - total_height) / 2
    space_width = draw.textlength(" ", font=font)
    for line in lines:
        words = line.split()
        if len(words) == 1:
            segments = [(words[0], QUICK_TEXT_BLUE)]
        else:
            segments = [
                (" ".join(words[:-1]), QUICK_TEXT_NAVY),
                (words[-1], QUICK_TEXT_BLUE),
            ]
        widths = [draw.textlength(text, font=font) for text, _ in segments]
        total_width = sum(widths) + space_width * (len(segments) - 1)
        x = (QUICK_TEXT_CANVAS[0] - total_width) / 2
        for index, ((text, color), width) in enumerate(zip(segments, widths)):
            draw.text((x, y), text, font=font, fill=color)
            x += width + (space_width if index < len(segments) - 1 else 0)
        y += line_height
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
    save_standalone_design_product(
        design_id,
        product_key=blueprint_key,
        blueprint_version=profile["version"],
        production_asset_filename=design["source_filename"],
        title=normalized_title,
        description=(description or "").strip(),
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
        result = create_printify_product(
            printify_api,
            listing={
                "title": design["product_title"],
                "description": design["product_description"] or "",
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
        payload = {
            "title": design["product_title"],
            "description": design["product_description"] or "",
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
