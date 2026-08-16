"""Approved, reusable scene profiles for deterministic mug mockups."""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENE_ROOT = PROJECT_ROOT / "data" / "mockup_scenes" / "mugs" / "black_accent"


@dataclass(frozen=True)
class MugSceneProfile:
    key: str
    label: str
    filename: str
    # Normalized printable face area within the approved 1024 x 1536 scene.
    artwork_box: tuple[float, float, float, float]
    artwork_scale: float = 1.0
    # Optional normalized area occupied by a complete rendered product. This
    # lets marketing images use Printify's exact mug render instead of
    # approximating the artwork placement on a blank scene mug.
    product_box: tuple[float, float, float, float] | None = None
    # Some Printify studio renders make the complete mug look broader than it
    # does in a natural lifestyle photograph. Keep this profile-specific so
    # the correction applies consistently without changing the source render.
    product_width_scale: float = 1.0
    # Printify's isolated studio angle can exaggerate the handle. Lifestyle
    # scenes can correct it independently without distorting the mug body.
    handle_width_scale: float = 1.0
    handle_height_scale: float = 1.0

    @property
    def path(self):
        return SCENE_ROOT / self.filename


BLACK_ACCENT_GALLERY_SCENES = (
    MugSceneProfile("teacher_desk", "Teacher desk", "teacher-desk-right-handed-v1.png", (0.38, 0.45, 0.68, 0.59), 1.45),
    MugSceneProfile("bright_classroom", "Bright classroom", "bright-classroom-right-handed-v1.png", (0.42, 0.49, 0.63, 0.58), 1.45),
    # These four boxes describe the same physical print position on differently
    # framed mugs: centered on the visible face and roughly one-third of its
    # height. Keep them calibrated together so a gallery does not appear to use
    # four different print sizes.
    MugSceneProfile("cozy_reading", "Cozy reading corner", "cozy-reading-right-handed-v1.png", (0.49, 0.52, 0.67, 0.63), 1.45),
    MugSceneProfile("teacher_appreciation", "Teacher appreciation", "teacher-appreciation-right-handed-v1.png", (0.47, 0.61, 0.69, 0.71), 1.45),
    MugSceneProfile("staff_room", "Staff room", "staff-room-right-handed-v1.png", (0.47, 0.55, 0.67, 0.66), 1.45),
    MugSceneProfile("premium_hero", "Premium dark hero", "dark-premium-hero-right-handed-v1.png", (0.47, 0.52, 0.69, 0.63), 1.45),
)

BLACK_ACCENT_PINTEREST_SCENE = MugSceneProfile(
    "pinterest_high_school",
    "High-school classroom Pinterest master",
    "pinterest-high-school-classroom-empty-table-v1.png",
    # Keep the larger Printify-matched scale, but sit the artwork comfortably
    # below the rim on this particular photographed mug.
    (0.39, 0.52, 0.63, 0.63),
    1.45,
    (0.27, 0.45, 0.73, 0.75),
    0.82,
    0.72,
    0.84,
)


def composite_design_on_scene(scene, graphic, profile):
    """Place the exact prepared design into one approved blank mug face."""
    canvas = scene.convert("RGBA")
    design = graphic.convert("RGBA")
    # Prepared mug graphics use a wide transparent production canvas. Fitting
    # that full canvas into a scene makes the visible lettering look much
    # smaller than it does on the Printify mug, so size the visible artwork
    # instead while preserving the original product asset unchanged.
    visible_bounds = design.getchannel("A").getbbox()
    if visible_bounds:
        design = design.crop(visible_bounds)
    left, top, right, bottom = profile.artwork_box
    box = (
        round(left * canvas.width),
        round(top * canvas.height),
        round(right * canvas.width),
        round(bottom * canvas.height),
    )
    maximum = (
        max(1, round((box[2] - box[0]) * profile.artwork_scale)),
        max(1, round((box[3] - box[1]) * profile.artwork_scale)),
    )
    design.thumbnail(maximum, Image.Resampling.LANCZOS)
    x = box[0] + (maximum[0] - design.width) // 2
    y = box[1] + (maximum[1] - design.height) // 2
    canvas.alpha_composite(design, (x, y))
    return canvas.convert("RGB")


def composite_product_render_on_scene(scene, product_render, profile):
    """Cut the exact Printify mug from white and place it in an empty scene."""
    if profile.product_box is None:
        return scene.convert("RGB")
    canvas = scene.convert("RGBA")
    product = product_render.convert("RGB")

    # Printify renders the white mug on a nearly white background. A plain
    # color threshold cannot distinguish the white ceramic from the
    # white studio floor. Locate the dark rim, then explicitly retain the mug
    # body below it. This avoids both failure modes: a missing ceramic body and
    # the square/white halo seen around earlier cutouts.
    grayscale = product.convert("L")
    dark = grayscale.point(lambda value: 255 if value <= 165 else 0)

    def longest_run(row):
        best_start = best_end = run_start = None
        for x, value in enumerate(row):
            if value and run_start is None:
                run_start = x
            if run_start is not None and (not value or x == len(row) - 1):
                run_end = x if value and x == len(row) - 1 else x - 1
                if best_start is None or run_end - run_start > best_end - best_start:
                    best_start, best_end = run_start, run_end
                run_start = None
        return best_start, best_end

    rim = None
    dark_pixels = dark.load()
    # The rim is the longest nearly horizontal dark run in the upper 60%.
    for y in range(round(product.height * 0.08), round(product.height * 0.62)):
        run = longest_run([dark_pixels[x, y] for x in range(product.width)])
        if run[0] is None:
            continue
        length = run[1] - run[0] + 1
        if rim is None or length > rim[0]:
            rim = (length, run[0], run[1], y)

    body = Image.new("L", product.size, 0)
    if rim:
        rim_width, rim_left, rim_right, rim_y = rim
        body_bottom = min(
            product.height - 1,
            rim_y + round(rim_width * 1.18),
        )
        curve = max(7, round(rim_width * 0.14))
        body_draw = ImageDraw.Draw(body)
        body_draw.ellipse(
            (rim_left, rim_y - curve, rim_right, rim_y + curve), fill=255
        )
        body_draw.rectangle(
            (rim_left, rim_y, rim_right, body_bottom - curve), fill=255
        )
        body_draw.ellipse(
            (rim_left, body_bottom - curve * 2, rim_right, body_bottom), fill=255
        )

    # Keep only genuinely dark rendered details outside the reconstructed white
    # ceramic body. Using the general background difference here also captured
    # pale studio-floor compression and produced a rectangular white shelf at
    # the bottom of the composited mug.
    foreground = dark.filter(ImageFilter.MaxFilter(5))
    # Keep the handle, rim, and lettering, but clip away any remaining studio
    # shadow beneath the reconstructed ceramic body.
    if rim:
        allowed = Image.new("L", product.size, 0)
        margin = round(rim_width * 0.72)
        ImageDraw.Draw(allowed).rectangle(
            (
                max(0, rim_left - margin),
                max(0, rim_y - round(rim_width * 0.22)),
                min(product.width - 1, rim_right + margin),
                min(product.height - 1, body_bottom + curve),
            ),
            fill=255,
        )
        foreground = ImageChops.multiply(foreground, allowed)
    mask = ImageChops.lighter(foreground, body)
    # Close the tiny antialiased seam where Printify's dark handle joins the
    # pale ceramic body, then soften only the outside edge. This also restores
    # the complete rounded foot instead of leaving a clipped-looking base.
    mask = mask.filter(ImageFilter.MaxFilter(5))
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))

    bounds = mask.getbbox()
    if bounds is None:
        return scene.convert("RGB")
    product = product.crop(bounds).convert("RGBA")
    product.putalpha(mask.crop(bounds))
    if rim and (
        profile.handle_width_scale != 1.0
        or profile.handle_height_scale != 1.0
    ):
        # The handle is the portion left of the detected ceramic rim. Scale it
        # separately, keep a small overlap behind the body, and preserve the
        # body at full height. This prevents both the oversized-loop look and
        # the detached-handle seam.
        rim_width, rim_left, _rim_right, _rim_y = rim
        split_x = max(1, min(product.width - 1, rim_left - bounds[0]))
        overlap = max(3, round(rim_width * 0.045))
        handle_limit = min(product.width, split_x + overlap)
        handle_layer = product.crop((0, 0, handle_limit, product.height))
        handle_bounds = handle_layer.getchannel("A").getbbox()
        if handle_bounds:
            handle_piece = handle_layer.crop(handle_bounds)
            handle_piece = handle_piece.resize(
                (
                    max(1, round(handle_piece.width * profile.handle_width_scale)),
                    max(1, round(handle_piece.height * profile.handle_height_scale)),
                ),
                Image.Resampling.LANCZOS,
            )
            body_layer = product.copy()
            body_alpha = body_layer.getchannel("A")
            ImageDraw.Draw(body_alpha).rectangle(
                (0, 0, split_x - 1, product.height), fill=0
            )
            body_layer.putalpha(body_alpha)
            rebuilt = Image.new("RGBA", product.size, (0, 0, 0, 0))
            handle_center_y = (handle_bounds[1] + handle_bounds[3]) // 2
            handle_x = split_x + overlap - handle_piece.width
            handle_y = handle_center_y - handle_piece.height // 2
            rebuilt.alpha_composite(handle_piece, (handle_x, handle_y))
            rebuilt.alpha_composite(body_layer)
            product = rebuilt
    left, top, right, bottom = profile.product_box
    box = (
        round(left * canvas.width),
        round(top * canvas.height),
        round(right * canvas.width),
        round(bottom * canvas.height),
    )
    maximum = (box[2] - box[0], box[3] - box[1])
    product.thumbnail(maximum, Image.Resampling.LANCZOS)
    if profile.product_width_scale != 1.0:
        product = product.resize(
            (
                max(1, round(product.width * profile.product_width_scale)),
                product.height,
            ),
            Image.Resampling.LANCZOS,
        )
    x = box[0] + (maximum[0] - product.width) // 2
    y = box[3] - product.height

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_width = round(product.width * 0.62)
    shadow_height = max(10, round(product.height * 0.05))
    shadow_draw.ellipse(
        (
            x + (product.width - shadow_width) // 2,
            box[3] - round(shadow_height * 0.35),
            x + (product.width + shadow_width) // 2,
            box[3] + round(shadow_height * 0.65),
        ),
        fill=(35, 25, 18, 90),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(8, shadow_height // 2)))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(product, (x, y))
    return canvas.convert("RGB")
