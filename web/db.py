from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "shangooli.db"


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_collections():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.code, c.name, c.status, c.target_artwork_count,
                   COUNT(a.id) AS artwork_count
            FROM collections AS c
            LEFT JOIN artworks AS a ON a.collection_id = c.id
            GROUP BY c.id
            ORDER BY c.name
            """
        ).fetchall()


def get_collection(collection_code):
    with get_connection() as conn:
        collection = conn.execute(
            """
            SELECT code, name, status, target_artwork_count
            FROM collections
            WHERE code = ?
            """,
            (collection_code.upper(),),
        ).fetchone()

        if collection is None:
            return None, []

        artworks = conn.execute(
            """
            SELECT artwork_code, public_title, working_title, theme, status
            FROM artworks
            WHERE collection_id = (
                SELECT id FROM collections WHERE code = ?
            )
            ORDER BY sequence_number
            """,
            (collection_code.upper(),),
        ).fetchall()

        return collection, artworks


def get_artwork(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT a.artwork_code, a.public_title, a.working_title,
                   a.theme, a.story, a.status,
                   c.code AS collection_code,
                   c.name AS collection_name
            FROM artworks AS a
            JOIN collections AS c ON c.id = a.collection_id
            WHERE a.artwork_code = ?
            """,
            (artwork_code.upper(),),
        ).fetchone()


def update_artwork(
    artwork_code,
    public_title,
    working_title,
    theme,
    story,
    status,
):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE artworks
            SET public_title = ?, working_title = ?, theme = ?,
                story = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE artwork_code = ?
            """,
            (
                public_title.strip(),
                working_title.strip() or None,
                theme.strip() or None,
                story.strip() or None,
                status.strip().lower(),
                artwork_code.upper(),
            ),
        )
        conn.commit()


def create_collection(code, name, target_artwork_count, status):
    code = code.strip().upper()
    name = name.strip()
    normalized_status = status.strip().lower()

    if not code:
        raise ValueError("Collection code is required")
    if not name:
        raise ValueError("Collection name is required")
    if len(code) > 10:
        raise ValueError("Collection code must be 10 characters or fewer")
    if target_artwork_count < 0:
        raise ValueError("Target artwork count cannot be negative")

    allowed_statuses = {"planned", "active", "complete", "paused", "archived"}
    if normalized_status not in allowed_statuses:
        raise ValueError("Invalid collection status")

    with get_connection() as conn:
        brand = conn.execute(
            "SELECT id FROM brands WHERE code = 'SHG'"
        ).fetchone()
        if brand is None:
            raise ValueError("ShangooliShop brand was not found")

        duplicate = conn.execute(
            "SELECT 1 FROM collections WHERE code = ? OR name = ?",
            (code, name),
        ).fetchone()
        if duplicate is not None:
            raise ValueError("A collection with that code or name already exists")

        conn.execute(
            """
            INSERT INTO collections (
                brand_id, code, name, collection_type, vertical,
                target_artwork_count, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brand["id"],
                code,
                name,
                "standard",
                "general",
                target_artwork_count,
                normalized_status,
            ),
        )
        conn.commit()

    return code
