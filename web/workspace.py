import subprocess
from pathlib import Path

from app.database import get_artwork_folder, initialize_artwork_workspace


WORKSPACE_SECTIONS = (
    ("source", "01 Source Artwork"),
    ("print", "02 Print Files"),
    ("mockups", "03 Mockups"),
    ("exports", "04 Exports"),
)


def _file_count(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(1 for path in folder.rglob("*") if path.is_file())


def inspect_workspace(artwork) -> dict:
    folder = get_artwork_folder(artwork)

    sections = []
    for key, folder_name in WORKSPACE_SECTIONS:
        section_folder = folder / folder_name
        sections.append(
            {
                "key": key,
                "name": folder_name,
                "path": section_folder,
                "exists": section_folder.is_dir(),
                "file_count": _file_count(section_folder),
            }
        )

    artwork_md = folder / "artwork.md"

    return {
        "path": folder,
        "exists": folder.is_dir(),
        "artwork_md_exists": artwork_md.is_file(),
        "artwork_md_path": artwork_md,
        "sections": sections,
        "total_files": _file_count(folder),
        "complete_structure": (
            folder.is_dir()
            and artwork_md.is_file()
            and all(section["exists"] for section in sections)
        ),
    }


def refresh_workspace(artwork) -> Path:
    return initialize_artwork_workspace(artwork)


def open_workspace(artwork) -> Path:
    folder = initialize_artwork_workspace(artwork)

    try:
        subprocess.run(
            ["open", str(folder)],
            check=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "The macOS 'open' command is unavailable."
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Finder could not open the workspace: {folder}"
        ) from error

    return folder
