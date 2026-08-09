"""Approved, reusable scene profiles for deterministic mug mockups."""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


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
    "pinterest-high-school-classroom-right-handed-v1.png",
    # Keep the larger Printify-matched scale, but sit the artwork comfortably
    # below the rim on this particular photographed mug.
    (0.39, 0.52, 0.63, 0.63),
    1.45,
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
