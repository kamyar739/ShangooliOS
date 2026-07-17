"""Deterministic print-master preparation for ShangooliOS.

This module does not pretend to perform AI restoration. It normalizes the source,
uses high-quality Lanczos resampling when enlargement is needed, and records a
manifest so the operator can see exactly what changed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from PIL import Image, ImageOps

from app.database import get_artwork_folder
from web.artwork_certifier import certify_artwork
from web.product_catalog import product_sizes_for_ratio


DEFAULT_TARGET_PPI = 180
DEFAULT_MAX_LONG_EDGE = 7200
DEFAULT_MAX_SCALE = 4.0


@dataclass(frozen=True)
class PrintMasterResult:
    source_filename: str
    master_filename: str
    source_width: int
    source_height: int
    master_width: int
    master_height: int
    scale_factor: float
    resized: bool
    target_ppi: int
    target_product_size: str | None
    color_mode: str
    method: str
    created_at: str
    relative_path: str
    manifest_relative_path: str

    def to_dict(self) -> dict:
        return asdict(self)


def _target_dimensions(
    width: int,
    height: int,
    *,
    target_long_edge: int,
    max_scale: float,
) -> tuple[int, int, float]:
    current_long_edge = max(width, height)
    if current_long_edge >= target_long_edge:
        return width, height, 1.0

    scale = min(target_long_edge / current_long_edge, max_scale)
    return max(1, round(width * scale)), max(1, round(height * scale)), scale


def build_print_master(
    artwork,
    source_path: Path,
    *,
    target_ppi: int = DEFAULT_TARGET_PPI,
    max_long_edge: int = DEFAULT_MAX_LONG_EDGE,
    max_scale: float = DEFAULT_MAX_SCALE,
) -> PrintMasterResult:
    if target_ppi <= 0 or max_long_edge <= 0 or max_scale < 1:
        raise ValueError("Invalid print-master settings")

    certification = certify_artwork(source_path)
    product_sizes = product_sizes_for_ratio(
        certification.closest_ratio,
        certification.orientation,
    )
    target_product = product_sizes[-1] if product_sizes else None

    if target_product:
        product_long_edge = max(target_product)
        requested_long_edge = round(product_long_edge * target_ppi)
        target_long_edge = min(max_long_edge, requested_long_edge)
        target_product_label = f"{target_product[0]}×{target_product[1]}"
    else:
        target_long_edge = max_long_edge
        target_product_label = None

    workspace = get_artwork_folder(artwork)
    destination_folder = workspace / "02 Print Files"
    destination_folder.mkdir(parents=True, exist_ok=True)
    destination = destination_folder / f"{artwork['artwork_code']}_master.png"
    manifest_path = destination_folder / f"{artwork['artwork_code']}_master.json"

    try:
        with Image.open(source_path) as opened:
            source = ImageOps.exif_transpose(opened)
            source_width, source_height = source.size

            # Flatten transparency against white and normalize all output to RGB.
            if source.mode in {"RGBA", "LA"} or "transparency" in source.info:
                rgba = source.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                normalized = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                normalized = source.convert("RGB")

            target_width, target_height, scale = _target_dimensions(
                source_width,
                source_height,
                target_long_edge=target_long_edge,
                max_scale=max_scale,
            )
            resized = (target_width, target_height) != (source_width, source_height)
            if resized:
                normalized = normalized.resize(
                    (target_width, target_height),
                    Image.Resampling.LANCZOS,
                )

            normalized.save(destination, format="PNG", optimize=True)
    except Exception as error:
        raise ValueError(f"Unable to create print master: {error}") from error

    method = "Lanczos upscale" if resized else "Normalized without enlargement"
    result = PrintMasterResult(
        source_filename=source_path.name,
        master_filename=destination.name,
        source_width=source_width,
        source_height=source_height,
        master_width=target_width,
        master_height=target_height,
        scale_factor=round(scale, 3),
        resized=resized,
        target_ppi=target_ppi,
        target_product_size=target_product_label,
        color_mode="RGB",
        method=method,
        created_at=datetime.now(timezone.utc).isoformat(),
        relative_path=str(destination.relative_to(workspace)),
        manifest_relative_path=str(manifest_path.relative_to(workspace)),
    )
    manifest_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return result


def load_print_master_manifest(artwork) -> dict | None:
    workspace = get_artwork_folder(artwork)
    path = workspace / "02 Print Files" / f"{artwork['artwork_code']}_master.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
