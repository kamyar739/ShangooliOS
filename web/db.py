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
            SELECT
                c.code,
                c.name,
                c.status,
                c.target_artwork_count,
                SUM(CASE WHEN a.status != 'retired' THEN 1 ELSE 0 END)
                    AS artwork_count
            FROM collections AS c
            LEFT JOIN artworks AS a
                ON a.collection_id = c.id
            WHERE c.status != 'archived'
            GROUP BY c.id
            ORDER BY c.name
            """
        ).fetchall()


def get_dashboard():
    with get_connection() as conn:
        collections = get_collections()

        stats = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status != 'retired' THEN 1 ELSE 0 END)
                    AS total_artworks,
                SUM(CASE WHEN status IN ('creating', 'review', 'production')
                    THEN 1 ELSE 0 END) AS in_progress,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END)
                    AS approved,
                SUM(CASE WHEN status = 'listed' THEN 1 ELSE 0 END)
                    AS listed
            FROM artworks
            """
        ).fetchone()

        recent_artworks = conn.execute(
            """
            SELECT
                a.artwork_code,
                a.public_title,
                a.theme,
                a.status,
                c.name AS collection_name
            FROM artworks AS a
            JOIN collections AS c
                ON c.id = a.collection_id
            WHERE a.status != 'retired'
              AND c.status != 'archived'
            ORDER BY a.updated_at DESC, a.id DESC
            LIMIT 6
            """
        ).fetchall()

        return {
            "collections": collections,
            "stats": stats,
            "recent_artworks": recent_artworks,
        }


def search_artworks(query):
    pattern = f"%{query.strip()}%"

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                a.artwork_code,
                a.public_title,
                a.working_title,
                a.theme,
                a.status,
                c.name AS collection_name
            FROM artworks AS a
            JOIN collections AS c
                ON c.id = a.collection_id
            WHERE a.status != 'retired'
              AND c.status != 'archived'
              AND (
                    a.artwork_code LIKE ?
                 OR a.public_title LIKE ?
                 OR COALESCE(a.working_title, '') LIKE ?
                 OR COALESCE(a.theme, '') LIKE ?
                 OR COALESCE(a.story, '') LIKE ?
              )
            ORDER BY a.artwork_code
            """,
            (pattern, pattern, pattern, pattern, pattern),
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
            return None, [], []

        artworks = conn.execute(
            """
            SELECT artwork_code, public_title, working_title, theme, status
            FROM artworks
            WHERE collection_id = (
                SELECT id FROM collections WHERE code = ?
            )
              AND status != 'retired'
            ORDER BY sequence_number
            """,
            (collection_code.upper(),),
        ).fetchall()

        archived_artworks = conn.execute(
            """
            SELECT artwork_code, public_title, working_title, theme, status
            FROM artworks
            WHERE collection_id = (
                SELECT id FROM collections WHERE code = ?
            )
              AND status = 'retired'
            ORDER BY sequence_number
            """,
            (collection_code.upper(),),
        ).fetchall()

        return collection, artworks, archived_artworks


def get_artwork(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                a.artwork_code,
                a.public_title,
                a.working_title,
                a.theme,
                a.story,
                a.status,
                c.code AS collection_code,
                c.name AS collection_name
            FROM artworks AS a
            JOIN collections AS c
                ON c.id = a.collection_id
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
    normalized_status = status.strip().lower()

    allowed_statuses = {
        "idea",
        "creating",
        "review",
        "approved",
        "production",
        "listed",
        "paused",
        "retired",
    }

    if normalized_status not in allowed_statuses:
        raise ValueError("Invalid artwork status")

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE artworks
            SET
                public_title = ?,
                working_title = ?,
                theme = ?,
                story = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_code = ?
            """,
            (
                public_title.strip(),
                working_title.strip() or None,
                theme.strip() or None,
                story.strip() or None,
                normalized_status,
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
            """
            SELECT 1
            FROM collections
            WHERE code = ? OR name = ?
            """,
            (code, name),
        ).fetchone()

        if duplicate is not None:
            raise ValueError(
                "A collection with that code or name already exists"
            )

        conn.execute(
            """
            INSERT INTO collections (
                brand_id,
                code,
                name,
                collection_type,
                vertical,
                target_artwork_count,
                status
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


def update_collection(
    collection_code,
    name,
    target_artwork_count,
    status,
):
    code = collection_code.strip().upper()
    name = name.strip()
    normalized_status = status.strip().lower()

    if not name:
        raise ValueError("Collection name is required")
    if target_artwork_count < 0:
        raise ValueError("Target artwork count cannot be negative")

    allowed_statuses = {"planned", "active", "complete", "paused"}

    if normalized_status not in allowed_statuses:
        raise ValueError("Invalid collection status")

    with get_connection() as conn:
        duplicate = conn.execute(
            """
            SELECT 1
            FROM collections
            WHERE name = ? AND code != ?
            """,
            (name, code),
        ).fetchone()

        if duplicate is not None:
            raise ValueError(
                "Another collection already uses that name"
            )

        cursor = conn.execute(
            """
            UPDATE collections
            SET
                name = ?,
                target_artwork_count = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
            """,
            (
                name,
                target_artwork_count,
                normalized_status,
                code,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("Collection not found")

        conn.commit()


def archive_collection(collection_code):
    code = collection_code.strip().upper()

    with get_connection() as conn:
        collection = conn.execute(
            "SELECT id FROM collections WHERE code = ?",
            (code,),
        ).fetchone()

        if collection is None:
            raise ValueError("Collection not found")

        artwork_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM artworks
            WHERE collection_id = ?
            """,
            (collection["id"],),
        ).fetchone()[0]

        if artwork_count > 0:
            raise ValueError(
                "A collection containing artworks cannot be archived"
            )

        conn.execute(
            """
            UPDATE collections
            SET
                status = 'archived',
                updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
            """,
            (code,),
        )
        conn.commit()


def archive_artwork(artwork_code):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE artworks
            SET
                status = 'retired',
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_code = ?
            """,
            (artwork_code.strip().upper(),),
        )

        if cursor.rowcount == 0:
            raise ValueError("Artwork not found")

        conn.commit()


def restore_artwork(artwork_code):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE artworks
            SET
                status = 'idea',
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_code = ?
              AND status = 'retired'
            """,
            (artwork_code.strip().upper(),),
        )

        if cursor.rowcount == 0:
            raise ValueError("Archived artwork not found")

        conn.commit()
