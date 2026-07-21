from pathlib import Path
import sqlite3

from app.database import initialize_database
from web.etsy_validation import validate_etsy_listing
from web.printify import validate_printify_product

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "shangooli.db"


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_production_schema():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_production (
                artwork_id INTEGER PRIMARY KEY,
                orientation TEXT DEFAULT 'horizontal',
                master_ratio TEXT DEFAULT '3:2',
                required_ratios TEXT DEFAULT '3:2, 4:3, 5:4, 14:11',
                original_approved INTEGER NOT NULL DEFAULT 0,
                print_master_ready INTEGER NOT NULL DEFAULT 0,
                ratio_exports_ready INTEGER NOT NULL DEFAULT 0,
                mockups_ready INTEGER NOT NULL DEFAULT 0,
                listing_content_ready INTEGER NOT NULL DEFAULT 0,
                ai_enhanced_at TEXT,
                ai_enhanced_original_width INTEGER,
                ai_enhanced_original_height INTEGER,
                ai_enhanced_width INTEGER,
                ai_enhanced_height INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id)
            )
            """
        )
        production_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(artwork_production)")
        }
        for column_name, column_type in (
            ("ai_enhanced_at", "TEXT"),
            ("ai_enhanced_original_width", "INTEGER"),
            ("ai_enhanced_original_height", "INTEGER"),
            ("ai_enhanced_width", "INTEGER"),
            ("ai_enhanced_height", "INTEGER"),
        ):
            if column_name not in production_columns:
                conn.execute(
                    f"ALTER TABLE artwork_production ADD COLUMN {column_name} {column_type}"
                )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_mockup_order (
                artwork_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                PRIMARY KEY (artwork_id, slot_key),
                UNIQUE (artwork_id, position)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_mockup_templates (
                artwork_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                template_key TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                PRIMARY KEY (artwork_id, slot_key)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mockup_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                room_type TEXT NOT NULL,
                orientation TEXT NOT NULL,
                image_path TEXT NOT NULL,
                placement_x REAL NOT NULL DEFAULT 25,
                placement_y REAL NOT NULL DEFAULT 15,
                placement_width REAL NOT NULL DEFAULT 50,
                placement_height REAL NOT NULL DEFAULT 50,
                source_url TEXT,
                creator TEXT,
                license_name TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        scene_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mockup_scenes)")
        }
        for column_name in ("source_url", "creator", "license_name"):
            if column_name not in scene_columns:
                conn.execute(f"ALTER TABLE mockup_scenes ADD COLUMN {column_name} TEXT")


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_intelligence (
                artwork_id INTEGER PRIMARY KEY,
                theme TEXT,
                style TEXT,
                mood TEXT,
                primary_colors TEXT,
                suggested_room TEXT,
                target_customer TEXT,
                generation_prompt TEXT,
                negative_prompt TEXT,
                ai_model TEXT,
                analysis_notes TEXT,
                analyzed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_listing_content (
                artwork_id INTEGER PRIMARY KEY,
                short_story TEXT,
                long_story TEXT,
                etsy_title TEXT,
                etsy_description TEXT,
                etsy_tags TEXT,
                alt_text TEXT,
                keywords TEXT,
                generated_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id)
            )
            """
        )


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_certification (
                artwork_id INTEGER PRIMARY KEY,
                valid INTEGER NOT NULL DEFAULT 0,
                width INTEGER,
                height INTEGER,
                mode TEXT,
                format TEXT,
                orientation TEXT,
                source_ratio REAL,
                closest_ratio TEXT,
                master_ratio TEXT,
                required_ratios TEXT,
                score INTEGER,
                status TEXT,
                largest_recommended_print TEXT,
                print_capability_json TEXT,
                warnings_json TEXT,
                certified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS print_master_certification (
                artwork_id INTEGER PRIMARY KEY,
                valid INTEGER NOT NULL DEFAULT 0,
                width INTEGER,
                height INTEGER,
                mode TEXT,
                format TEXT,
                orientation TEXT,
                source_ratio REAL,
                closest_ratio TEXT,
                master_ratio TEXT,
                required_ratios TEXT,
                score INTEGER,
                status TEXT,
                largest_recommended_print TEXT,
                print_capability_json TEXT,
                warnings_json TEXT,
                certified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id)
            )
            """
	)



        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artwork_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                original_filename TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                UNIQUE (artwork_id, role)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artwork_id INTEGER NOT NULL,
                marketplace TEXT NOT NULL DEFAULT 'Etsy',
                product TEXT NOT NULL DEFAULT 'Poster',
                title TEXT NOT NULL,
                description TEXT,
                tags TEXT,
                price_cents INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_listings_artwork_id ON listings(artwork_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)"
        )
        listing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(listings)").fetchall()
        }
        for column_name in (
            "marketplace_url",
            "external_listing_id",
            "published_at",
            "printify_product_url",
            "printify_product_id",
            "printify_provider",
            "printify_sizes",
            "printify_base_cost_cents",
            "printify_etsy_connected_at",
            "printify_publish_requested_at",
            "etsy_last_synced_at",
            "etsy_state",
            "etsy_inventory_quantity",
            "etsy_inventory_restore_quantity",
            "etsy_inventory_updated_at",
            "publishing_recovery_stage",
            "publishing_recovery_message",
            "publishing_recovery_checked_at",
        ):
            if column_name not in listing_columns:
                column_type = (
                    "INTEGER"
                    if column_name.endswith("_cents") or column_name.endswith("_quantity")
                    else "TEXT"
                )
                conn.execute(
                    f"ALTER TABLE listings ADD COLUMN {column_name} {column_type}"
                )

        collections_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'collections'"
        ).fetchone()
        if collections_table:
            collection_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(collections)").fetchall()
            }
            if "etsy_section_name" not in collection_columns:
                conn.execute("ALTER TABLE collections ADD COLUMN etsy_section_name TEXT")
            if "display_order" not in collection_columns:
                conn.execute("ALTER TABLE collections ADD COLUMN display_order INTEGER")
            conn.execute(
                """
                UPDATE collections
                SET etsy_section_name = CASE
                    WHEN name LIKE 'The %' THEN substr(name, 5, 24)
                    ELSE substr(name, 1, 24)
                END
                WHERE etsy_section_name IS NULL OR trim(etsy_section_name) = ''
                """
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO artwork_production (
                artwork_id, orientation, master_ratio, required_ratios
            )
            SELECT id, 'horizontal', '3:2', '3:2, 4:3, 5:4, 14:11'
            FROM artworks
            """
        )
        conn.execute(
            """
            UPDATE artwork_production
            SET
                orientation = COALESCE(NULLIF(orientation, ''), 'horizontal'),
                master_ratio = COALESCE(NULLIF(master_ratio, ''), '3:2'),
                required_ratios = COALESCE(
                    NULLIF(required_ratios, ''),
                    '3:2, 4:3, 5:4, 14:11'
                )
            """
        )
        conn.execute(
            """
            UPDATE artwork_production
            SET ai_enhanced_at = COALESCE(
                    (SELECT f.updated_at FROM artwork_files AS f
                     WHERE f.artwork_id = artwork_production.artwork_id
                       AND f.role = 'source'),
                    CURRENT_TIMESTAMP
                ),
                ai_enhanced_original_width = (
                    SELECT CAST(c.width / 4 AS INTEGER)
                    FROM artwork_certification AS c
                    WHERE c.artwork_id = artwork_production.artwork_id
                ),
                ai_enhanced_original_height = (
                    SELECT CAST(c.height / 4 AS INTEGER)
                    FROM artwork_certification AS c
                    WHERE c.artwork_id = artwork_production.artwork_id
                ),
                ai_enhanced_width = (
                    SELECT c.width FROM artwork_certification AS c
                    WHERE c.artwork_id = artwork_production.artwork_id
                ),
                ai_enhanced_height = (
                    SELECT c.height FROM artwork_certification AS c
                    WHERE c.artwork_id = artwork_production.artwork_id
                )
            WHERE ai_enhanced_at IS NULL
              AND EXISTS (
                  SELECT 1 FROM artwork_files AS f
                  WHERE f.artwork_id = artwork_production.artwork_id
                    AND f.role = 'source'
                    AND f.stored_filename LIKE '%_ai_upscaled_approved.png'
              )
            """
        )

        conn.commit()


initialize_database()
ensure_production_schema()


def get_collections():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.code,
                c.name,
                c.status,
                c.target_artwork_count,
                COUNT(DISTINCT CASE WHEN a.status != 'retired' THEN a.id END)
                    AS artwork_count,
                COUNT(DISTINCT CASE WHEN l.etsy_state = 'active' THEN l.id END)
                    AS live_etsy_count,
                COUNT(DISTINCT CASE WHEN l.status = 'ready' THEN l.id END)
                    AS ready_listing_count
            FROM collections AS c
            LEFT JOIN artworks AS a
                ON a.collection_id = c.id
            LEFT JOIN listings AS l
                ON l.artwork_id = a.id
            WHERE c.status != 'archived'
            GROUP BY c.id
            ORDER BY c.display_order IS NULL, c.display_order, c.name
            """
        ).fetchall()
    collections = []
    for row in rows:
        item = dict(row)
        if item["live_etsy_count"]:
            item["display_status"] = "Live on Etsy"
            item["display_status_class"] = "live"
        elif item["ready_listing_count"]:
            item["display_status"] = "Ready to publish"
            item["display_status_class"] = "ready"
        elif item["artwork_count"]:
            item["display_status"] = "In production"
            item["display_status_class"] = "production"
        else:
            item["display_status"] = "Planned"
            item["display_status_class"] = "planned"
        collections.append(item)
    return collections


def save_collection_order(collection_codes):
    codes = [str(code).strip().upper() for code in collection_codes]
    if not codes or len(codes) != len(set(codes)):
        raise ValueError("Collection order must contain each collection once")
    with get_connection() as conn:
        active_codes = {
            row["code"]
            for row in conn.execute(
                "SELECT code FROM collections WHERE status != 'archived'"
            ).fetchall()
        }
        if set(codes) != active_codes:
            raise ValueError("Collection order does not match the active collections")
        conn.executemany(
            "UPDATE collections SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE code = ?",
            [(position, code) for position, code in enumerate(codes, start=1)],
        )
        conn.commit()


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
                c.name AS collection_name,
                EXISTS (
                    SELECT 1
                    FROM artwork_files AS source_file
                    WHERE source_file.artwork_id = a.id
                      AND source_file.role = 'source'
                ) AS has_source_image
            FROM artworks AS a
            JOIN collections AS c
                ON c.id = a.collection_id
            WHERE a.status != 'retired'
              AND c.status != 'archived'
            ORDER BY a.updated_at DESC, a.id DESC
            LIMIT 6
            """
        ).fetchall()

    listing_rows = [dict(row) for row in list_listings()]
    work_queue = []
    ready_to_publish = []
    for listing in listing_rows:
        readiness = get_listing_readiness(listing["id"])
        listing["readiness"] = readiness
        if readiness["ready"]:
            if listing["status"] not in ("published", "archived"):
                ready_to_publish.append(listing)
        elif listing["status"] != "archived":
            listing["missing_labels"] = [
                item["label"] for item in readiness["items"] if not item["passed"]
            ]
            work_queue.append(listing)

    listing_counts = get_listing_status_counts()
    return {
        "collections": collections,
        "stats": stats,
        "recent_artworks": recent_artworks,
        "listing_stats": {
            "total": listing_counts["all"],
            "ready_to_publish": len(ready_to_publish),
            "needs_attention": len(work_queue),
            "published": listing_counts["published"],
        },
        "listing_work_queue": work_queue[:6],
        "ready_to_publish": ready_to_publish[:4],
        "dashboard_listings": listing_rows[:8],
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
                c.name AS collection_name,
                EXISTS (
                    SELECT 1
                    FROM artwork_files AS source_file
                    WHERE source_file.artwork_id = a.id
                      AND source_file.role = 'source'
                ) AS has_source_image
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
            SELECT code, name, status, target_artwork_count, etsy_section_name
            FROM collections
            WHERE code = ?
            """,
            (collection_code.upper(),),
        ).fetchone()

        if collection is None:
            return None, [], []

        artworks = conn.execute(
            """
            SELECT
                a.artwork_code,
                a.public_title,
                a.working_title,
                a.theme,
                a.status,
                p.orientation,
                p.master_ratio,
                p.original_approved,
                p.print_master_ready,
                p.ratio_exports_ready,
                p.mockups_ready,
                p.listing_content_ready,
                EXISTS (
                    SELECT 1
                    FROM artwork_files AS source_file
                    WHERE source_file.artwork_id = a.id
                      AND source_file.role = 'source'
                ) AS has_source_image
            FROM artworks AS a
            LEFT JOIN artwork_production AS p
                ON p.artwork_id = a.id
            WHERE a.collection_id = (
                SELECT id FROM collections WHERE code = ?
            )
              AND a.status != 'retired'
            ORDER BY
                CAST(SUBSTR(a.artwork_code, INSTR(a.artwork_code, '-') + 1) AS INTEGER),
                a.artwork_code
            """,
            (collection_code.upper(),),
        ).fetchall()

        archived_artworks = conn.execute(
            """
            SELECT
                a.artwork_code,
                a.public_title,
                a.working_title,
                a.theme,
                a.status,
                p.orientation,
                p.master_ratio,
                p.original_approved,
                p.print_master_ready,
                p.ratio_exports_ready,
                p.mockups_ready,
                p.listing_content_ready,
                EXISTS (
                    SELECT 1
                    FROM artwork_files AS source_file
                    WHERE source_file.artwork_id = a.id
                      AND source_file.role = 'source'
                ) AS has_source_image
            FROM artworks AS a
            LEFT JOIN artwork_production AS p
                ON p.artwork_id = a.id
            WHERE a.collection_id = (
                SELECT id FROM collections WHERE code = ?
            )
              AND a.status = 'retired'
            ORDER BY
                CAST(SUBSTR(a.artwork_code, INSTR(a.artwork_code, '-') + 1) AS INTEGER),
                a.artwork_code
            """,
            (collection_code.upper(),),
        ).fetchall()

        collection_item = dict(collection)
        listing_counts = conn.execute(
            """
            SELECT
                COUNT(DISTINCT CASE WHEN l.etsy_state = 'active' THEN l.id END) AS live_etsy_count,
                COUNT(DISTINCT CASE WHEN l.status = 'ready' THEN l.id END) AS ready_listing_count
            FROM artworks AS a
            LEFT JOIN listings AS l ON l.artwork_id = a.id
            WHERE a.collection_id = (SELECT id FROM collections WHERE code = ?)
              AND a.status != 'retired'
            """,
            (collection_code.upper(),),
        ).fetchone()
        collection_item["live_etsy_count"] = listing_counts["live_etsy_count"]
        if listing_counts["live_etsy_count"]:
            collection_item["display_status"] = "Live on Etsy"
        elif listing_counts["ready_listing_count"]:
            collection_item["display_status"] = "Ready to publish"
        elif artworks:
            collection_item["display_status"] = "In production"
        else:
            collection_item["display_status"] = "Planned"
        return collection_item, artworks, archived_artworks


def get_artwork(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                a.id,
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


def get_artwork_production(artwork_code):
    with get_connection() as conn:
        production = conn.execute(
            """
            SELECT
                p.orientation,
                p.master_ratio,
                p.required_ratios,
                p.original_approved,
                p.print_master_ready,
                p.ratio_exports_ready,
                p.mockups_ready,
                p.listing_content_ready,
                p.ai_enhanced_at,
                p.ai_enhanced_original_width,
                p.ai_enhanced_original_height,
                p.ai_enhanced_width,
                p.ai_enhanced_height,
                p.notes
            FROM artwork_production AS p
            JOIN artworks AS a
                ON a.id = p.artwork_id
            WHERE a.artwork_code = ?
            """,
            (artwork_code.upper(),),
        ).fetchone()

        if production is None:
            artwork = conn.execute(
                "SELECT id FROM artworks WHERE artwork_code = ?",
                (artwork_code.upper(),),
            ).fetchone()

            if artwork is None:
                return None

            conn.execute(
                """
                INSERT INTO artwork_production (
                    artwork_id, orientation, master_ratio, required_ratios
                ) VALUES (?, 'horizontal', '3:2', '3:2, 4:3, 5:4, 14:11')
                """,
                (artwork["id"],),
            )
            conn.commit()

            production = conn.execute(
                """
                SELECT
                    orientation,
                    master_ratio,
                    required_ratios,
                    original_approved,
                    print_master_ready,
                    ratio_exports_ready,
                    mockups_ready,
                    listing_content_ready,
                    ai_enhanced_at,
                    ai_enhanced_original_width,
                    ai_enhanced_original_height,
                    ai_enhanced_width,
                    ai_enhanced_height,
                    notes
                FROM artwork_production
                WHERE artwork_id = ?
                """,
                (artwork["id"],),
            ).fetchone()

        return production


def get_artwork_file_assignments(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                f.role,
                f.relative_path,
                f.stored_filename,
                f.original_filename,
                f.updated_at
            FROM artwork_files AS f
            JOIN artworks AS a
                ON a.id = f.artwork_id
            WHERE a.artwork_code = ?
            ORDER BY f.role
            """,
            (artwork_code.upper(),),
        ).fetchall()


def upsert_artwork_file(
    artwork_code,
    role,
    relative_path,
    stored_filename,
    original_filename,
):
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()

        if artwork is None:
            raise ValueError("Artwork not found")

        conn.execute(
            """
            INSERT INTO artwork_files (
                artwork_id,
                role,
                relative_path,
                stored_filename,
                original_filename
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(artwork_id, role) DO UPDATE SET
                relative_path = excluded.relative_path,
                stored_filename = excluded.stored_filename,
                original_filename = excluded.original_filename,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                artwork["id"],
                role,
                relative_path,
                stored_filename,
                original_filename,
            ),
        )
        conn.commit()



def set_artwork_production_flags(artwork_code, **flags):
    allowed = {
        "original_approved",
        "print_master_ready",
        "ratio_exports_ready",
        "mockups_ready",
        "listing_content_ready",
    }
    updates = {key: value for key, value in flags.items() if key in allowed}

    if not updates:
        return

    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [int(bool(value)) for value in updates.values()]
    values.append(artwork_code.upper())

    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            UPDATE artwork_production
            SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE artwork_id = (
                SELECT id FROM artworks WHERE artwork_code = ?
            )
            """,
            values,
        )
        if cursor.rowcount == 0:
            raise ValueError("Artwork production record not found")
        conn.commit()


def invalidate_artwork_after_source_change(artwork_code):
    """Keep generated files, but mark source-dependent work as out of date."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE artwork_production
            SET original_approved = 0,
                print_master_ready = 0,
                ratio_exports_ready = 0,
                mockups_ready = 0,
                listing_content_ready = 0,
                ai_enhanced_at = NULL,
                ai_enhanced_original_width = NULL,
                ai_enhanced_original_height = NULL,
                ai_enhanced_width = NULL,
                ai_enhanced_height = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_id = (
                SELECT id FROM artworks WHERE artwork_code = ?
            )
            """,
            (artwork_code.upper(),),
        )
        if cursor.rowcount == 0:
            raise ValueError("Artwork production record not found")
        conn.commit()


def record_ai_enhancement(
    artwork_code, *, original_width, original_height, enhanced_width, enhanced_height,
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE artwork_production
            SET ai_enhanced_at = CURRENT_TIMESTAMP,
                ai_enhanced_original_width = ?,
                ai_enhanced_original_height = ?,
                ai_enhanced_width = ?,
                ai_enhanced_height = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_id = (
                SELECT id FROM artworks WHERE artwork_code = ?
            )
            """,
            (
                original_width, original_height, enhanced_width, enhanced_height,
                artwork_code.upper(),
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Artwork production record not found")
        conn.commit()

def update_artwork_production(
    artwork_code,
    orientation,
    master_ratio,
    required_ratios,
    original_approved,
    print_master_ready,
    ratio_exports_ready,
    mockups_ready,
    listing_content_ready,
    notes,
):
    allowed_orientations = {"", "horizontal", "vertical", "square"}
    normalized_orientation = orientation.strip().lower()

    if normalized_orientation not in allowed_orientations:
        raise ValueError("Invalid orientation")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE artwork_production
            SET
                orientation = ?,
                master_ratio = ?,
                required_ratios = ?,
                original_approved = ?,
                print_master_ready = ?,
                ratio_exports_ready = ?,
                mockups_ready = ?,
                listing_content_ready = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_id = (
                SELECT id FROM artworks WHERE artwork_code = ?
            )
            """,
            (
                normalized_orientation or None,
                master_ratio.strip() or None,
                required_ratios.strip() or None,
                int(original_approved),
                int(print_master_ready),
                int(ratio_exports_ready),
                int(mockups_ready),
                int(listing_content_ready),
                notes.strip() or None,
                artwork_code.upper(),
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("Artwork production record not found")

        conn.commit()


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


def update_artwork_status(artwork_code, status):
    normalized_status = status.strip().lower()
    allowed_statuses = {
        "idea",
        "creating",
        "review",
        "approved",
        "production",
        "paused",
        "retired",
    }
    if normalized_status not in allowed_statuses:
        raise ValueError("Invalid artwork status")

    with get_connection() as conn:
        active_etsy_listing = conn.execute(
            """
            SELECT 1
            FROM listings AS l
            JOIN artworks AS a ON a.id = l.artwork_id
            WHERE a.artwork_code = ? AND l.etsy_state = 'active'
            LIMIT 1
            """,
            (artwork_code.upper(),),
        ).fetchone()
        if active_etsy_listing:
            raise ValueError(
                "This artwork is live on Etsy. Deactivate the Etsy listing before changing its artwork status."
            )
        cursor = conn.execute(
            "UPDATE artworks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE artwork_code = ?",
            (normalized_status, artwork_code.upper()),
        )
        if cursor.rowcount == 0:
            raise ValueError("Artwork not found")
        conn.commit()


def create_collection(code, name, target_artwork_count, status, etsy_section_name=None):
    code = code.strip().upper()
    name = name.strip()
    normalized_status = status.strip().lower()
    normalized_section = (etsy_section_name or name.removeprefix("The ")).strip()

    if not code:
        raise ValueError("Collection code is required")
    if not name:
        raise ValueError("Collection name is required")
    if len(code) > 10:
        raise ValueError("Collection code must be 10 characters or fewer")
    if target_artwork_count < 0:
        raise ValueError("Target artwork count cannot be negative")
    if not normalized_section or len(normalized_section) > 24:
        raise ValueError("Etsy section name must be between 1 and 24 characters")

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
                etsy_section_name,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brand["id"],
                code,
                name,
                "standard",
                "general",
                target_artwork_count,
                normalized_section,
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
    etsy_section_name=None,
):
    code = collection_code.strip().upper()
    name = name.strip()
    normalized_status = status.strip().lower()
    normalized_section = (etsy_section_name or name.removeprefix("The ")).strip()

    if not name:
        raise ValueError("Collection name is required")
    if target_artwork_count < 0:
        raise ValueError("Target artwork count cannot be negative")
    if not normalized_section or len(normalized_section) > 24:
        raise ValueError("Etsy section name must be between 1 and 24 characters")

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
                etsy_section_name = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
            """,
            (
                name,
                target_artwork_count,
                normalized_section,
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


def get_artwork_mockup_order(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT mo.slot_key, mo.position
            FROM artwork_mockup_order AS mo
            JOIN artworks AS a ON a.id = mo.artwork_id
            WHERE a.artwork_code = ?
            ORDER BY mo.position
            """,
            (artwork_code.upper(),),
        ).fetchall()


def get_artwork_mockup_templates(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT mt.slot_key, mt.template_key
            FROM artwork_mockup_templates AS mt
            JOIN artworks AS a ON a.id = mt.artwork_id
            WHERE a.artwork_code = ?
            ORDER BY mt.slot_key
            """,
            (artwork_code.upper(),),
        ).fetchall()


def save_artwork_mockup_template(artwork_code, slot_key, template_key):
    slot_key = slot_key.strip()
    template_key = template_key.strip()
    if not slot_key or not template_key:
        raise ValueError("Listing image slot and template are required")

    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")

        conn.execute(
            """
            INSERT INTO artwork_mockup_templates (artwork_id, slot_key, template_key)
            VALUES (?, ?, ?)
            ON CONFLICT(artwork_id, slot_key) DO UPDATE SET
                template_key = excluded.template_key,
                updated_at = CURRENT_TIMESTAMP
            """,
            (artwork["id"], slot_key, template_key),
        )
        conn.commit()


def save_artwork_mockup_templates(artwork_code, selections):
    normalized = {
        str(slot_key).strip(): str(template_key).strip()
        for slot_key, template_key in selections.items()
        if str(slot_key).strip() and str(template_key).strip()
    }
    if not normalized:
        return

    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")

        conn.executemany(
            """
            INSERT INTO artwork_mockup_templates (artwork_id, slot_key, template_key)
            VALUES (?, ?, ?)
            ON CONFLICT(artwork_id, slot_key) DO UPDATE SET
                template_key = excluded.template_key,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (artwork["id"], slot_key, template_key)
                for slot_key, template_key in normalized.items()
            ],
        )
        conn.commit()


def save_artwork_mockup_order(artwork_code, ordered_slot_keys):
    normalized = [value.strip() for value in ordered_slot_keys if value.strip()]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Mockup positions must be unique")

    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")

        conn.execute(
            "DELETE FROM artwork_mockup_order WHERE artwork_id = ?",
            (artwork["id"],),
        )
        conn.executemany(
            """
            INSERT INTO artwork_mockup_order (artwork_id, slot_key, position)
            VALUES (?, ?, ?)
            """,
            [
                (artwork["id"], slot_key, position)
                for position, slot_key in enumerate(normalized, start=1)
            ],
        )
        conn.commit()


def list_mockup_scenes(*, orientation=None):
    with get_connection() as conn:
        if orientation and orientation != "any":
            return conn.execute(
                """
                SELECT * FROM mockup_scenes
                WHERE active = 1 AND orientation IN (?, 'any')
                ORDER BY room_type, name
                """,
                (orientation,),
            ).fetchall()
        return conn.execute(
            """
            SELECT * FROM mockup_scenes
            WHERE active = 1
            ORDER BY room_type, name
            """
        ).fetchall()


def get_mockup_scene(scene_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM mockup_scenes WHERE id = ?",
            (scene_id,),
        ).fetchone()


def create_mockup_scene(
    *, name, room_type, orientation, image_path,
    placement_x, placement_y, placement_width, placement_height,
    source_url="", creator="", license_name="",
):
    values = [placement_x, placement_y, placement_width, placement_height]
    if any(value < 0 or value > 100 for value in values):
        raise ValueError("Scene placement values must be between 0 and 100")
    if placement_x + placement_width > 100 or placement_y + placement_height > 100:
        raise ValueError("The artwork placement must fit inside the scene")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO mockup_scenes (
                name, room_type, orientation, image_path,
                placement_x, placement_y, placement_width, placement_height,
                source_url, creator, license_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(), room_type.strip(), orientation.strip(), image_path,
                placement_x, placement_y, placement_width, placement_height,
                source_url.strip(), creator.strip(), license_name.strip(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_mockup_scene_placement(
    scene_id, *, placement_x, placement_y, placement_width, placement_height,
):
    values = [placement_x, placement_y, placement_width, placement_height]
    if any(value < 0 or value > 100 for value in values):
        raise ValueError("Scene placement values must be between 0 and 100")
    if placement_x + placement_width > 100 or placement_y + placement_height > 100:
        raise ValueError("The artwork placement must fit inside the scene")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mockup_scenes
            SET placement_x = ?, placement_y = ?, placement_width = ?,
                placement_height = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (placement_x, placement_y, placement_width, placement_height, scene_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Mockup scene not found")
        conn.commit()


def disable_mockup_scene(scene_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mockup_scenes
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (scene_id,),
        )
        if cursor.rowcount == 0:
            raise ValueError("Mockup scene not found")
        conn.commit()


def get_artwork_intelligence(artwork_code):
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id, theme FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            return None
        conn.execute(
            "INSERT OR IGNORE INTO artwork_intelligence (artwork_id, theme) VALUES (?, ?)",
            (artwork["id"], artwork["theme"] or ""),
        )
        conn.commit()
        return conn.execute(
            """
            SELECT theme, style, mood, primary_colors, suggested_room,
                   target_customer, generation_prompt, negative_prompt,
                   ai_model, analysis_notes, analyzed_at
            FROM artwork_intelligence
            WHERE artwork_id = ?
            """,
            (artwork["id"],),
        ).fetchone()


def update_artwork_intelligence(artwork_code, **values):
    allowed = {
        "theme", "style", "mood", "primary_colors", "suggested_room",
        "target_customer", "generation_prompt", "negative_prompt",
        "ai_model", "analysis_notes", "analyzed_at",
    }
    fields = [(key, values[key]) for key in values if key in allowed]
    if not fields:
        return
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")
        conn.execute(
            "INSERT OR IGNORE INTO artwork_intelligence (artwork_id) VALUES (?)",
            (artwork["id"],),
        )
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        params = [value for _, value in fields] + [artwork["id"]]
        conn.execute(
            f"UPDATE artwork_intelligence SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE artwork_id = ?",
            params,
        )
        conn.commit()


def get_artwork_listing_content(artwork_code):
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            return None
        conn.execute(
            "INSERT OR IGNORE INTO artwork_listing_content (artwork_id) VALUES (?)",
            (artwork["id"],),
        )
        conn.commit()
        return conn.execute(
            """
            SELECT short_story, long_story, etsy_title, etsy_description,
                   etsy_tags, alt_text, keywords, generated_at
            FROM artwork_listing_content WHERE artwork_id = ?
            """,
            (artwork["id"],),
        ).fetchone()


def update_artwork_listing_content(artwork_code, **values):
    allowed = {
        "short_story", "long_story", "etsy_title", "etsy_description",
        "etsy_tags", "alt_text", "keywords", "generated_at",
    }
    fields = [(key, values[key]) for key in values if key in allowed]
    if not fields:
        return
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")
        conn.execute(
            "INSERT OR IGNORE INTO artwork_listing_content (artwork_id) VALUES (?)",
            (artwork["id"],),
        )
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        params = [value for _, value in fields] + [artwork["id"]]
        conn.execute(
            f"UPDATE artwork_listing_content SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE artwork_id = ?",
            params,
        )
        conn.commit()


def upsert_artwork_certification(artwork_code, certification):
    import json
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")
        conn.execute(
            """
            INSERT INTO artwork_certification (
                artwork_id, valid, width, height, mode, format, orientation,
                source_ratio, closest_ratio, master_ratio, required_ratios,
                score, status, largest_recommended_print,
                print_capability_json, warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(artwork_id) DO UPDATE SET
                valid=excluded.valid, width=excluded.width, height=excluded.height,
                mode=excluded.mode, format=excluded.format,
                orientation=excluded.orientation, source_ratio=excluded.source_ratio,
                closest_ratio=excluded.closest_ratio, master_ratio=excluded.master_ratio,
                required_ratios=excluded.required_ratios, score=excluded.score,
                status=excluded.status,
                largest_recommended_print=excluded.largest_recommended_print,
                print_capability_json=excluded.print_capability_json,
                warnings_json=excluded.warnings_json,
                certified_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            """,
            (
                artwork["id"], int(certification["valid"]),
                certification["width"], certification["height"],
                certification["mode"], certification["format"],
                certification["orientation"], certification["source_ratio"],
                certification["closest_ratio"], certification["master_ratio"],
                ", ".join(certification["required_ratios"]),
                certification["score"], certification["status"],
                certification["largest_recommended_print"],
                json.dumps(certification["print_capability"]),
                json.dumps(certification["warnings"]),
            ),
        )
        conn.execute(
            """UPDATE artwork_production SET orientation=?, master_ratio=?,
            required_ratios=?, ratio_exports_ready=0, updated_at=CURRENT_TIMESTAMP
            WHERE artwork_id=?""",
            (certification["orientation"], certification["master_ratio"],
             ", ".join(certification["required_ratios"]), artwork["id"]),
        )
        conn.commit()


def get_artwork_certification(artwork_code):
    import json
    with get_connection() as conn:
        row = conn.execute(
            """SELECT c.* FROM artwork_certification c JOIN artworks a
            ON a.id=c.artwork_id WHERE a.artwork_code=?""",
            (artwork_code.upper(),),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["print_capability"] = json.loads(result.pop("print_capability_json") or "[]")
        result["warnings"] = json.loads(result.pop("warnings_json") or "[]")
        result["required_ratios"] = [x.strip() for x in (result["required_ratios"] or "").split(",") if x.strip()]
        return result


def upsert_print_master_certification(artwork_code, certification):
    import json

    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()

        if artwork is None:
            raise ValueError("Artwork not found")

        conn.execute(
            """
            INSERT INTO print_master_certification (
                artwork_id, valid, width, height, mode, format, orientation,
                source_ratio, closest_ratio, master_ratio, required_ratios,
                score, status, largest_recommended_print,
                print_capability_json, warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(artwork_id) DO UPDATE SET
                valid=excluded.valid,
                width=excluded.width,
                height=excluded.height,
                mode=excluded.mode,
                format=excluded.format,
                orientation=excluded.orientation,
                source_ratio=excluded.source_ratio,
                closest_ratio=excluded.closest_ratio,
                master_ratio=excluded.master_ratio,
                required_ratios=excluded.required_ratios,
                score=excluded.score,
                status=excluded.status,
                largest_recommended_print=excluded.largest_recommended_print,
                print_capability_json=excluded.print_capability_json,
                warnings_json=excluded.warnings_json,
                certified_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                artwork["id"],
                int(certification["valid"]),
                certification["width"],
                certification["height"],
                certification["mode"],
                certification["format"],
                certification["orientation"],
                certification["source_ratio"],
                certification["closest_ratio"],
                certification["master_ratio"],
                ", ".join(certification["required_ratios"]),
                certification["score"],
                certification["status"],
                certification["largest_recommended_print"],
                json.dumps(certification["print_capability"]),
                json.dumps(certification["warnings"]),
            ),
        )
        conn.execute(
            """
            UPDATE artwork_production
            SET orientation = ?, master_ratio = ?, required_ratios = ?,
                ratio_exports_ready = 0, mockups_ready = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_id = ?
            """,
            (
                certification["orientation"],
                certification["master_ratio"],
                ", ".join(certification["required_ratios"]),
                artwork["id"],
            ),
        )
        conn.commit()


def get_print_master_certification(artwork_code):
    import json

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.*
            FROM print_master_certification c
            JOIN artworks a ON a.id = c.artwork_id
            WHERE a.artwork_code = ?
            """,
            (artwork_code.upper(),),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["print_capability"] = json.loads(
            result.pop("print_capability_json") or "[]"
        )
        result["warnings"] = json.loads(
            result.pop("warnings_json") or "[]"
        )
        result["required_ratios"] = [
            value.strip()
            for value in (result["required_ratios"] or "").split(",")
            if value.strip()
        ]
        return result









LISTING_STATUSES = ("draft", "ready", "published", "archived")


def list_listings(status=None):
    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status not in LISTING_STATUSES:
        raise ValueError("Invalid listing status")

    query = """
        SELECT l.id, l.marketplace, l.product, l.title, l.price_cents,
               l.status, l.marketplace_url, l.external_listing_id,
               l.published_at, l.printify_product_url,
               l.printify_etsy_connected_at, l.updated_at,
               l.printify_publish_requested_at, l.etsy_last_synced_at,
               l.etsy_inventory_quantity, l.etsy_inventory_restore_quantity,
               l.etsy_inventory_updated_at,
               a.artwork_code, a.public_title,
               EXISTS (
                   SELECT 1 FROM artwork_files AS source_file
                   WHERE source_file.artwork_id = a.id
                     AND source_file.role = 'source'
               ) AS has_source_image,
               c.name AS collection_name
        FROM listings AS l
        JOIN artworks AS a ON a.id = l.artwork_id
        JOIN collections AS c ON c.id = a.collection_id
    """
    params = ()
    if normalized_status:
        query += " WHERE l.status = ?"
        params = (normalized_status,)
    query += " ORDER BY l.updated_at DESC, l.id DESC"

    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def get_listing_status_counts():
    counts = {status: 0 for status in LISTING_STATUSES}
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS total FROM listings GROUP BY status"
        ).fetchall()
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] = row["total"]
    counts["all"] = sum(counts.values())
    return counts


def get_artwork_listings(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT l.id, l.marketplace, l.product, l.title, l.description,
                   l.tags, l.price_cents, l.status, l.marketplace_url,
                   l.external_listing_id, l.published_at,
                   l.printify_product_url, l.printify_product_id,
                   l.printify_provider, l.printify_sizes,
                   l.printify_base_cost_cents,
                   l.printify_etsy_connected_at,
                   l.printify_publish_requested_at,
                   l.etsy_last_synced_at, l.etsy_state,
                   l.etsy_inventory_quantity, l.etsy_inventory_restore_quantity,
                   l.etsy_inventory_updated_at,
                   l.publishing_recovery_stage,
                   l.publishing_recovery_message,
                   l.publishing_recovery_checked_at,
                   l.created_at, l.updated_at
            FROM listings AS l
            JOIN artworks AS a ON a.id = l.artwork_id
            WHERE a.artwork_code = ?
            ORDER BY l.updated_at DESC, l.id DESC
            """,
            (artwork_code.upper(),),
        ).fetchall()


def get_listing(listing_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT l.id, l.marketplace, l.product, l.title, l.description,
                   l.tags, l.price_cents, l.status, l.marketplace_url,
                   l.external_listing_id, l.published_at,
                   l.printify_product_url, l.printify_product_id,
                   l.printify_provider, l.printify_sizes,
                   l.printify_base_cost_cents,
                   l.printify_etsy_connected_at,
                   l.printify_publish_requested_at,
                   l.etsy_last_synced_at, l.etsy_state,
                   l.etsy_inventory_quantity, l.etsy_inventory_restore_quantity,
                   l.etsy_inventory_updated_at,
                   l.publishing_recovery_stage,
                   l.publishing_recovery_message,
                   l.publishing_recovery_checked_at,
                   l.created_at, l.updated_at,
                   a.artwork_code, a.public_title, c.code AS collection_code,
                   EXISTS (
                       SELECT 1 FROM artwork_files AS source_file
                       WHERE source_file.artwork_id = a.id
                         AND source_file.role = 'source'
                   ) AS has_source_image,
                   c.name AS collection_name, c.etsy_section_name
            FROM listings AS l
            JOIN artworks AS a ON a.id = l.artwork_id
            JOIN collections AS c ON c.id = a.collection_id
            WHERE l.id = ?
            """,
            (listing_id,),
        ).fetchone()



def get_listing_readiness(listing_id):
    """Return the simple, user-facing checklist for publishing a listing."""
    with get_connection() as conn:
        listing = conn.execute(
            """
            SELECT l.id, l.title, l.description, l.tags, l.price_cents,
                   a.id AS artwork_id, a.artwork_code,
                   p.print_master_ready, p.ratio_exports_ready, p.mockups_ready
            FROM listings AS l
            JOIN artworks AS a ON a.id = l.artwork_id
            LEFT JOIN artwork_production AS p ON p.artwork_id = a.id
            WHERE l.id = ?
            """,
            (listing_id,),
        ).fetchone()
        if listing is None:
            return None

        roles = {
            row["role"]
            for row in conn.execute(
                "SELECT role FROM artwork_files WHERE artwork_id = ?",
                (listing["artwork_id"],),
            ).fetchall()
        }

    items = [
        {"key": "source", "label": "Source artwork", "passed": "source" in roles},
        {
            "key": "print_master",
            "label": "Print-ready file",
            "passed": "print_master" in roles or bool(listing["print_master_ready"]),
        },
        {
            "key": "ratios",
            "label": "Aspect-ratio exports",
            "passed": bool(listing["ratio_exports_ready"]),
        },
        {
            "key": "mockups",
            "label": "Listing images",
            "passed": bool(listing["mockups_ready"]),
        },
    ]
    items.extend(validate_etsy_listing(listing))
    completed = sum(1 for item in items if item["passed"])
    total = len(items)
    return {
        "items": items,
        "completed": completed,
        "total": total,
        "remaining": total - completed,
        "percentage": round((completed / total) * 100) if total else 0,
        "ready": completed == total,
    }

def create_listing(artwork_code, *, marketplace, product, title, description,
                   tags, price_cents, status="draft"):
    if status not in LISTING_STATUSES:
        raise ValueError("Invalid listing status")
    if price_cents < 0:
        raise ValueError("Price cannot be negative")
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")
        cursor = conn.execute(
            """
            INSERT INTO listings (
                artwork_id, marketplace, product, title, description, tags,
                price_cents, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (artwork["id"], marketplace, product, title, description, tags,
             price_cents, status),
        )
        conn.commit()
        return cursor.lastrowid


def update_listing(listing_id, *, marketplace, product, title, description,
                   tags, price_cents, status):
    if status not in LISTING_STATUSES:
        raise ValueError("Invalid listing status")
    if price_cents < 0:
        raise ValueError("Price cannot be negative")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET marketplace = ?, product = ?, title = ?, description = ?,
                tags = ?, price_cents = ?, status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (marketplace, product, title, description, tags, price_cents,
             status, listing_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        conn.commit()


def publish_listing(listing_id, *, marketplace_url, external_listing_id):
    from urllib.parse import urlparse

    normalized_url = (marketplace_url or "").strip()
    normalized_id = (external_listing_id or "").strip()
    parsed_url = urlparse(normalized_url)
    hostname = (parsed_url.hostname or "").lower()
    if parsed_url.scheme not in ("http", "https") or not (
        hostname == "etsy.com" or hostname.endswith(".etsy.com")
    ):
        raise ValueError("Enter a valid Etsy listing URL")
    if not normalized_id.isdigit():
        raise ValueError("Enter the numeric Etsy listing ID")

    readiness = get_listing_readiness(listing_id)
    if readiness is None:
        raise ValueError("Listing not found")
    if not readiness["ready"]:
        raise ValueError("Complete the listing readiness checklist before publishing")
    listing = get_listing(listing_id)
    printify = validate_printify_product(listing)
    if not printify["ready"]:
        raise ValueError(
            "Complete the Printify product details before publishing: "
            + ", ".join(printify["blockers"])
        )

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE listings
            SET marketplace_url = ?, external_listing_id = ?,
                published_at = CURRENT_TIMESTAMP, status = 'published',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_url, normalized_id, listing_id),
        )
        _mark_listing_artwork_listed(conn, listing_id)
        conn.commit()


def link_etsy_listing(listing_id, external_listing_id):
    normalized_id = str(external_listing_id or "").strip()
    if not normalized_id.isdigit():
        raise ValueError("Choose a valid Etsy listing")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET external_listing_id = ?, marketplace_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_id, f"https://www.etsy.com/listing/{normalized_id}", listing_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        conn.commit()


def clear_inactive_etsy_link(listing_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT etsy_state FROM listings WHERE id = ?", (listing_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Listing not found")
        if row["etsy_state"] == "active":
            raise ValueError("Cannot replace the link while this listing is live on Etsy")
        conn.execute(
            """
            UPDATE listings
            SET external_listing_id = NULL, marketplace_url = NULL,
                etsy_state = NULL, etsy_last_synced_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (listing_id,),
        )
        conn.commit()


def record_etsy_state(listing_id, etsy_state):
    normalized_state = str(etsy_state or "").strip().lower()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET etsy_state = ?,
                status = CASE
                    WHEN ? = 'active' THEN 'published'
                    WHEN status = 'published' AND ? != 'active' THEN 'ready'
                    ELSE status
                END,
                published_at = CASE
                    WHEN ? = 'active' THEN COALESCE(published_at, CURRENT_TIMESTAMP)
                    ELSE published_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_state, normalized_state, normalized_state, normalized_state, listing_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        if normalized_state == "active":
            _mark_listing_artwork_listed(conn, listing_id)
        conn.commit()


def mark_etsy_synced(listing_id, etsy_state=""):
    normalized_state = str(etsy_state or "").strip().lower()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET etsy_last_synced_at = CURRENT_TIMESTAMP,
                etsy_state = CASE WHEN ? != '' THEN ? ELSE etsy_state END,
                status = CASE
                    WHEN ? = 'active' THEN 'published'
                    WHEN status = 'published' AND ? != '' AND ? != 'active' THEN 'ready'
                    ELSE status
                END,
                published_at = CASE
                    WHEN ? = 'active' THEN COALESCE(published_at, CURRENT_TIMESTAMP)
                    ELSE published_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized_state, normalized_state, normalized_state,
                normalized_state, normalized_state, normalized_state, listing_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        if normalized_state == "active":
            _mark_listing_artwork_listed(conn, listing_id)
        conn.commit()


def record_etsy_inventory_quantity(listing_id, quantity):
    if quantity < 0 or quantity > 999:
        raise ValueError("Quantity must be between 0 and 999")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET etsy_inventory_quantity = ?,
                etsy_inventory_restore_quantity = CASE
                    WHEN ? > 0 THEN ?
                    ELSE COALESCE(etsy_inventory_restore_quantity, 2)
                END,
                etsy_inventory_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (quantity, quantity, quantity, listing_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        conn.commit()


def _mark_listing_artwork_listed(conn, listing_id):
    conn.execute(
        """
        UPDATE artworks
        SET status = 'listed', updated_at = CURRENT_TIMESTAMP
        WHERE id = (SELECT artwork_id FROM listings WHERE id = ?)
          AND status != 'retired'
        """,
        (listing_id,),
    )


def save_printify_product(
    listing_id, *, product_url, product_id, provider, sizes, base_cost_cents
):
    listing = get_listing(listing_id)
    if listing is None:
        raise ValueError("Listing not found")
    values = {
        "product": listing["product"],
        "printify_product_url": (product_url or "").strip(),
        "printify_product_id": (product_id or "").strip(),
        "printify_provider": (provider or "").strip(),
        "printify_sizes": (sizes or "").strip(),
        "printify_base_cost_cents": base_cost_cents,
    }
    validation = validate_printify_product(values)
    if not validation["ready"]:
        raise ValueError("Complete the Printify details: " + ", ".join(validation["blockers"]))

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE listings
            SET printify_product_url = ?, printify_product_id = ?,
                printify_provider = ?, printify_sizes = ?,
                printify_base_cost_cents = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                values["printify_product_url"], values["printify_product_id"],
                values["printify_provider"], values["printify_sizes"],
                values["printify_base_cost_cents"], listing_id,
            ),
        )
        conn.commit()


def mark_printify_etsy_connected(listing_id):
    listing = get_listing(listing_id)
    if listing is None:
        raise ValueError("Listing not found")
    printify = validate_printify_product(listing)
    if not printify["ready"]:
        raise ValueError("Complete the Printify product details first")
    if listing["status"] != "published" or not listing["marketplace_url"]:
        raise ValueError("Publish the Etsy listing before recording the connection")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE listings
            SET printify_etsy_connected_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (listing_id,),
        )
        conn.commit()


def mark_printify_publish_requested(listing_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET printify_publish_requested_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (listing_id,),
        )
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        conn.commit()


def record_publishing_recovery(listing_id, stage, message):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET publishing_recovery_stage = ?, publishing_recovery_message = ?,
                publishing_recovery_checked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            ((stage or "").strip(), (message or "").strip(), listing_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        conn.commit()


def duplicate_listing(listing_id):
    source = get_listing(listing_id)
    if source is None:
        raise ValueError("Listing not found")
    title = source["title"]
    copy_title = title if title.lower().endswith(" copy") else f"{title} Copy"
    return create_listing(
        source["artwork_code"],
        marketplace=source["marketplace"],
        product=source["product"],
        title=copy_title,
        description=source["description"] or "",
        tags=source["tags"] or "",
        price_cents=source["price_cents"],
        status="draft",
    )


def delete_listing(listing_id):
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        if cursor.rowcount == 0:
            raise ValueError("Listing not found")
        conn.commit()
