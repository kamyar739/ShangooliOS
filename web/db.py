from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "shangooli.db"


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_collections():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                c.code,
                c.name,
                COUNT(a.id) AS artwork_count
            FROM collections c
            LEFT JOIN artworks a
                ON a.collection_id = c.id
            GROUP BY c.id
            ORDER BY c.name
            """
        ).fetchall()

def get_collection(collection_code):
    with get_connection() as conn:
        collection = conn.execute(
            """
            SELECT
                code,
                name,
                status,
                target_artwork_count
            FROM collections
            WHERE code = ?
            """,
            (collection_code.upper(),),
        ).fetchone()

        if collection is None:
            return None, []

        artworks = conn.execute(
            """
            SELECT
                artwork_code,
                public_title,
                working_title,
                theme,
                status
            FROM artworks
            WHERE collection_id = (
                SELECT id
                FROM collections
                WHERE code = ?
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
                status.strip().lower(),
                artwork_code.upper(),
            ),
        )
        conn.commit()


def create_artwork(
    collection_code,
    public_title,
    working_title,
    theme,
):
    with get_connection() as conn:
        collection = conn.execute(
            """
            SELECT id
            FROM collections
            WHERE code = ?
            """,
            (collection_code.upper(),),
        ).fetchone()

        if collection is None:
            raise ValueError("Collection not found")

        next_number = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM artworks
            WHERE collection_id = ?
            """,
            (collection["id"],),
        ).fetchone()[0]

        artwork_code = f"{collection_code.upper()}-{next_number:03d}"

        conn.execute(
            """
            INSERT INTO artworks (
                artwork_code,
                collection_id,
                sequence_number,
                public_title,
                working_title,
                theme,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'idea')
            """,
            (
                artwork_code,
                collection["id"],
                next_number,
                public_title.strip(),
                working_title.strip() or None,
                theme.strip() or None,
            ),
        )
        conn.commit()

        return artwork_code



