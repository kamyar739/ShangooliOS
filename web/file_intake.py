import re
import shutil
from pathlib import Path

from fastapi import UploadFile

from app.database import get_artwork_folder


ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
    ".pdf",
}


def _safe_extension(filename: str) -> str:
    extension = Path(filename or "").suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file type. Allowed extensions: {allowed}"
        )

    return extension


def _ratio_slug(ratio: str) -> str:
    value = ratio.strip()

    if not value:
        raise ValueError("Ratio is required")

    slug = re.sub(r"[^0-9A-Za-z]+", "x", value).strip("x").lower()

    if not slug:
        raise ValueError("Invalid ratio")

    return slug


def _replace_existing_role_file(
    destination_folder: Path,
    filename_prefix: str,
) -> None:
    if not destination_folder.exists():
        return

    for path in destination_folder.iterdir():
        if path.is_file() and path.stem.startswith(filename_prefix):
            path.unlink()


def save_uploaded_file(
    artwork,
    upload: UploadFile,
    role: str,
    ratio: str | None = None,
) -> dict:
    extension = _safe_extension(upload.filename or "")
    workspace = get_artwork_folder(artwork)

    if role == "source":
        folder = workspace / "01 Source Artwork"
        filename_prefix = f"{artwork['artwork_code']}_source"
        filename = f"{filename_prefix}{extension}"
        role_key = "source"

    elif role == "print_master":
        folder = workspace / "02 Print Files"
        filename_prefix = f"{artwork['artwork_code']}_master"
        filename = f"{filename_prefix}{extension}"
        role_key = "print_master"

    elif role == "ratio_output":
        ratio_value = (ratio or "").strip()
        ratio_slug = _ratio_slug(ratio_value)
        folder = workspace / "02 Print Files"
        filename_prefix = (
            f"{artwork['artwork_code']}_ratio_{ratio_slug}"
        )
        filename = f"{filename_prefix}{extension}"
        role_key = f"ratio:{ratio_value}"

    else:
        raise ValueError("Unknown file role")

    folder.mkdir(parents=True, exist_ok=True)
    _replace_existing_role_file(folder, filename_prefix)

    destination = folder / filename

    with destination.open("wb") as output:
        shutil.copyfileobj(upload.file, output)

    return {
        "role": role_key,
        "relative_path": str(destination.relative_to(workspace)),
        "stored_filename": filename,
        "original_filename": upload.filename or filename,
    }


def assigned_file_exists(artwork, relative_path: str | None) -> bool:
    if not relative_path:
        return False

    workspace = get_artwork_folder(artwork)
    candidate = (workspace / relative_path).resolve()

    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        return False

    return candidate.is_file()
