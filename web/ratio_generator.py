from pathlib import Path

from PIL import Image, ImageOps

from app.database import get_artwork_folder
from web.file_intake import _ratio_slug


BACKGROUND_COLOR = (255, 255, 255)


def parse_ratio(ratio: str) -> tuple[int, int]:
    value = ratio.strip().replace(" ", "")

    if ":" not in value:
        raise ValueError(f"Invalid ratio: {ratio}")

    left, right = value.split(":", 1)

    try:
        width = int(left)
        height = int(right)
    except ValueError as error:
        raise ValueError(f"Invalid ratio: {ratio}") from error

    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid ratio: {ratio}")

    return width, height


def _target_dimensions(
    source_width: int,
    source_height: int,
    ratio_width: int,
    ratio_height: int,
) -> tuple[int, int]:
    source_area = source_width * source_height
    ratio_area = ratio_width * ratio_height
    scale = (source_area / ratio_area) ** 0.5

    target_width = max(1, round(ratio_width * scale))
    target_height = max(1, round(ratio_height * scale))

    return target_width, target_height


def generate_ratio_output(
    artwork,
    source_path: Path,
    ratio: str,
    mode: str,
    overwrite: bool,
) -> dict:
    ratio_width, ratio_height = parse_ratio(ratio)
    workspace = get_artwork_folder(artwork)
    destination_folder = workspace / "02 Print Files"
    destination_folder.mkdir(parents=True, exist_ok=True)

    ratio_slug = _ratio_slug(ratio)
    destination = (
        destination_folder
        / f"{artwork['artwork_code']}_ratio_{ratio_slug}.png"
    )

    if destination.exists() and not overwrite:
        return {
            "ratio": ratio,
            "status": "skipped",
            "message": "Existing output preserved",
            "relative_path": str(destination.relative_to(workspace)),
            "stored_filename": destination.name,
        }

    try:
        with Image.open(source_path) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            target_size = _target_dimensions(
                source.width,
                source.height,
                ratio_width,
                ratio_height,
            )

            if mode == "fit":
                output = ImageOps.pad(
                    source,
                    target_size,
                    method=Image.Resampling.LANCZOS,
                    color=BACKGROUND_COLOR,
                    centering=(0.5, 0.5),
                )
            elif mode == "crop":
                output = ImageOps.fit(
                    source,
                    target_size,
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
            else:
                raise ValueError("Unknown generation mode")

            output.save(
                destination,
                format="PNG",
                optimize=True,
            )

    except Exception as error:
        return {
            "ratio": ratio,
            "status": "failed",
            "message": str(error),
        }

    return {
        "ratio": ratio,
        "status": "created",
        "message": f"{target_size[0]} × {target_size[1]} px",
        "relative_path": str(destination.relative_to(workspace)),
        "stored_filename": destination.name,
    }


def resolve_assigned_file(artwork, assignment) -> Path:
    if assignment is None:
        raise ValueError("Print-ready file is not assigned")

    workspace = get_artwork_folder(artwork)
    candidate = (workspace / assignment["relative_path"]).resolve()

    try:
        candidate.relative_to(workspace.resolve())
    except ValueError as error:
        raise ValueError("Assigned file path is outside the workspace") from error

    if not candidate.is_file():
        raise ValueError("Assigned print-ready file is missing")

    return candidate
