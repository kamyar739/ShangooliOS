import re
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "shangooli.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
COLLECTIONS_DIR = PROJECT_ROOT / "assets" / "collections"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _column_exists(connection, table_name, column_name):
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(column["name"] == column_name for column in columns)


def initialize_database() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect() as connection:
        connection.executescript(schema)
        if (
            _column_exists(connection, "artworks", "id")
            and not _column_exists(connection, "artworks", "story")
        ):
            connection.execute("ALTER TABLE artworks ADD COLUMN story TEXT")
        connection.commit()


def seed_data() -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO brands (code, name, status, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                status = excluded.status,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            ("SHG", "ShangooliShop", "active", "Primary art brand and Etsy shop."),
        )

        brand = connection.execute(
            "SELECT id FROM brands WHERE code = ?", ("SHG",)
        ).fetchone()

        collection_rows = [
            (
                brand["id"], "CEL", "The Celebration Collection",
                "flagship_curated", "home_art", 8, "active",
                "Intentionally limited to 7–8 completed works.",
            ),
            (
                brand["id"], "DEN", "Dental Collection",
                "vertical_commercial", "dental", 20, "planned",
                "May grow beyond 20 works and be divided into mini-series.",
            ),
        ]

        connection.executemany(
            """
            INSERT INTO collections (
                brand_id, code, name, collection_type, vertical,
                target_artwork_count, status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                brand_id = excluded.brand_id,
                name = excluded.name,
                collection_type = excluded.collection_type,
                vertical = excluded.vertical,
                target_artwork_count = excluded.target_artwork_count,
                status = excluded.status,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            collection_rows,
        )
        connection.commit()


def list_brands():
    with connect() as connection:
        return connection.execute(
            "SELECT code, name, status FROM brands ORDER BY code"
        ).fetchall()


def list_collections():
    with connect() as connection:
        return connection.execute(
            """
            SELECT b.name AS brand_name, c.code, c.name, c.status,
                   c.target_artwork_count
            FROM collections AS c
            JOIN brands AS b ON b.id = c.brand_id
            ORDER BY b.name, c.code
            """
        ).fetchall()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip())
    return cleaned.strip("-") or "Untitled"


def next_artwork_number(connection, collection_id):
    row = connection.execute(
        """
        SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_number
        FROM artworks
        WHERE collection_id = ?
        """,
        (collection_id,),
    ).fetchone()
    return int(row["next_number"])


def get_artwork_folder(row) -> Path:
    collection_folder = COLLECTIONS_DIR / row["collection_code"]
    expected = collection_folder / f"{row['artwork_code']} {slugify(row['public_title'])}"
    if expected.exists():
        return expected

    # The artwork code is the permanent identity. Public titles may change after
    # files have been prepared, so preserve access to the existing workspace.
    existing = sorted(
        path for path in collection_folder.glob(f"{row['artwork_code']} *")
        if path.is_dir()
    )
    if len(existing) == 1:
        return existing[0]
    return expected


def initialize_artwork_workspace(row) -> Path:
    artwork_folder = get_artwork_folder(row)
    artwork_folder.mkdir(parents=True, exist_ok=True)

    for folder_name in (
        "01 Source Artwork",
        "02 Print Files",
        "03 Mockups",
        "04 Exports",
    ):
        (artwork_folder / folder_name).mkdir(exist_ok=True)

    artwork_md = artwork_folder / "artwork.md"
    if not artwork_md.exists():
        artwork_md.write_text(
            f"""# {row['artwork_code']} — {row['public_title']}

## Working Title

{row['working_title'] or ''}

## Theme

{row['theme'] or ''}

## Story

{row['story'] or ''}

## Notes


## Checklist

- [ ] Final artwork saved
- [ ] Print files prepared
- [ ] Mockups created
- [ ] Listing prepared
- [ ] Published
""",
            encoding="utf-8",
        )

    return artwork_folder


def create_artwork(collection_code, public_title, working_title, theme):
    collection_code = collection_code.strip().upper()
    public_title = public_title.strip()
    if not public_title:
        raise ValueError("Public title cannot be empty.")

    with connect() as connection:
        collection = connection.execute(
            "SELECT id, code, name FROM collections WHERE code = ?",
            (collection_code,),
        ).fetchone()
        if collection is None:
            raise ValueError(f"Unknown collection code: {collection_code}")

        sequence_number = next_artwork_number(connection, int(collection["id"]))
        artwork_code = f"{collection_code}-{sequence_number:03d}"

        artwork_row = {
            "collection_code": collection_code,
            "artwork_code": artwork_code,
            "public_title": public_title,
            "working_title": working_title,
            "theme": theme,
            "story": None,
        }
        artwork_folder = get_artwork_folder(artwork_row)

        if artwork_folder.exists():
            raise ValueError(f"Artwork folder already exists: {artwork_folder}")

        try:
            connection.execute(
                """
                INSERT INTO artworks (
                    artwork_code, collection_id, sequence_number,
                    public_title, working_title, theme, status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'idea')
                """,
                (
                    artwork_code, collection["id"], sequence_number,
                    public_title, working_title, theme,
                ),
            )
            connection.commit()
            initialize_artwork_workspace(artwork_row)
        except Exception:
            if artwork_folder.exists():
                for path in sorted(artwork_folder.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                artwork_folder.rmdir()
            raise

    return {"artwork_code": artwork_code, "folder_path": str(artwork_folder)}


def list_artworks():
    with connect() as connection:
        return connection.execute(
            """
            SELECT a.artwork_code, a.public_title, a.status,
                   c.code AS collection_code, c.name AS collection_name
            FROM artworks AS a
            JOIN collections AS c ON c.id = a.collection_id
            ORDER BY a.artwork_code
            """
        ).fetchall()


def get_artwork(artwork_code):
    with connect() as connection:
        return connection.execute(
            """
            SELECT a.artwork_code, a.public_title, a.working_title,
                   a.theme, a.story, a.status,
                   c.code AS collection_code, c.name AS collection_name
            FROM artworks AS a
            JOIN collections AS c ON c.id = a.collection_id
            WHERE a.artwork_code = ?
            """,
            (artwork_code.strip().upper(),),
        ).fetchone()


def update_artwork(
    artwork_code, public_title, working_title, theme, story, status
):
    allowed_statuses = {
        "idea", "creating", "review", "approved",
        "production", "listed", "paused", "retired",
    }
    normalized_status = status.strip().lower()
    if normalized_status not in allowed_statuses:
        valid = ", ".join(sorted(allowed_statuses))
        raise ValueError(f"Invalid status. Use one of: {valid}")

    with connect() as connection:
        existing = connection.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.strip().upper(),),
        ).fetchone()
        if existing is None:
            raise ValueError(f"Artwork not found: {artwork_code}")

        connection.execute(
            """
            UPDATE artworks
            SET public_title = ?, working_title = ?, theme = ?,
                story = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE artwork_code = ?
            """,
            (
                public_title.strip(), working_title, theme, story,
                normalized_status, artwork_code.strip().upper(),
            ),
        )
        connection.commit()
