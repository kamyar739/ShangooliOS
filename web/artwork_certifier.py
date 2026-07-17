from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps

from web.product_catalog import product_sizes_for_ratio


RATIO_FAMILIES = {
    "horizontal": ("3:2", "4:3", "5:4", "14:11"),
    "vertical": ("2:3", "3:4", "4:5", "11:14"),
    "square": ("1:1",),
}

@dataclass(frozen=True)
class ArtworkCertification:
    valid: bool
    width: int
    height: int
    mode: str
    format: str
    orientation: str
    source_ratio: float
    closest_ratio: str
    master_ratio: str
    required_ratios: tuple[str, ...]
    score: int
    status: str
    largest_recommended_print: str | None
    print_capability: tuple[dict, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def detect_orientation(width: int, height: int, square_tolerance: float = 0.015) -> str:
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive")
    difference = abs(width - height) / max(width, height)
    if difference <= square_tolerance:
        return "square"
    return "horizontal" if width > height else "vertical"


def _ratio_value(label: str) -> float:
    left, right = label.split(":", 1)
    return int(left) / int(right)


def _closest_ratio(source_ratio: float, ratios: tuple[str, ...]) -> str:
    return min(ratios, key=lambda label: abs(source_ratio - _ratio_value(label)))


def _quality_for_ppi(ppi: float) -> tuple[str, bool]:
    if ppi >= 240:
        return "Excellent", True
    if ppi >= 180:
        return "Very good", True
    if ppi >= 150:
        return "Good for wall display", True
    if ppi >= 120:
        return "Marginal", False
    return "Not recommended", False


def certify_artwork(path: Path) -> ArtworkCertification:
    warnings: list[str] = []
    try:
        with Image.open(path) as opened:
            opened.verify()
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened)
            width, height = image.size
            mode = image.mode or "Unknown"
            image_format = image.format or path.suffix.lstrip(".").upper()
    except Exception as error:
        raise ValueError(f"Image quality check failed: {error}") from error

    orientation = detect_orientation(width, height)
    ratios = RATIO_FAMILIES[orientation]
    source_ratio = width / height
    closest = _closest_ratio(source_ratio, ratios)

    if mode not in {"RGB", "RGBA", "CMYK", "L", "LA", "I;16"}:
        warnings.append(f"Unusual color mode: {mode}")
    if width < 2400 or height < 2400:
        warnings.append("One image dimension is below 2400 pixels.")

    capability: list[dict] = []
    largest: str | None = None
    for print_width, print_height in product_sizes_for_ratio(closest, orientation):
        ppi = min(width / print_width, height / print_height)
        quality, recommended = _quality_for_ppi(ppi)
        label = f"{print_width}×{print_height}"
        capability.append(
            {
                "size": label,
                "ppi": round(ppi),
                "quality": quality,
                "recommended": recommended,
            }
        )
        if recommended:
            largest = label

    best_large_ppi = capability[-1]["ppi"] if capability else 0
    score = 100
    if warnings:
        score -= min(20, 8 * len(warnings))
    if largest is None:
        score -= 40
    elif best_large_ppi < 120:
        score -= 10
    score = max(0, min(100, score))

    status = "Certified for production" if score >= 80 and largest else "Needs attention"

    return ArtworkCertification(
        valid=True,
        width=width,
        height=height,
        mode=mode,
        format=image_format,
        orientation=orientation,
        source_ratio=round(source_ratio, 4),
        closest_ratio=closest,
        master_ratio=closest,
        required_ratios=ratios,
        score=score,
        status=status,
        largest_recommended_print=largest,
        print_capability=tuple(capability),
        warnings=tuple(warnings),
    )
