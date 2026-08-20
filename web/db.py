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
        collection_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(collections)")
        }
        for column_name, column_type in (
            ("prompt", "TEXT"),
            ("cover_image_path", "TEXT"),
            ("cover_approved", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if collection_columns and column_name not in collection_columns:
                conn.execute(f"ALTER TABLE collections ADD COLUMN {column_name} {column_type}")
        artwork_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(artworks)")
        }
        if artwork_columns and "description" not in artwork_columns:
            conn.execute("ALTER TABLE artworks ADD COLUMN description TEXT")
        if artwork_columns and "prompt" not in artwork_columns:
            conn.execute("ALTER TABLE artworks ADD COLUMN prompt TEXT")
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
            CREATE TABLE IF NOT EXISTS mockup_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                template_key TEXT NOT NULL DEFAULT 'modern_minimal',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mockup_set_items (
                set_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                label TEXT,
                source_kind TEXT NOT NULL DEFAULT 'template',
                template_slot TEXT,
                position INTEGER NOT NULL,
                scene_id INTEGER,
                is_lead INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (set_id) REFERENCES mockup_sets(id) ON DELETE CASCADE,
                FOREIGN KEY (scene_id) REFERENCES mockup_scenes(id),
                PRIMARY KEY (set_id, slot_key),
                UNIQUE (set_id, position)
            )
            """
        )
        set_item_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mockup_set_items)")
        }
        for column_name, declaration in {
            "label": "TEXT",
            "source_kind": "TEXT NOT NULL DEFAULT 'template'",
            "template_slot": "TEXT",
        }.items():
            if column_name not in set_item_columns:
                conn.execute(
                    f"ALTER TABLE mockup_set_items ADD COLUMN {column_name} {declaration}"
                )
        conn.execute(
            """UPDATE mockup_set_items
               SET label=COALESCE(label, replace(slot_key, '_', ' ')),
                   template_slot=COALESCE(template_slot, slot_key),
                   source_kind=CASE WHEN scene_id IS NOT NULL THEN 'scene' ELSE source_kind END"""
        )
        for slot, label in {
            "hero": "Hero", "room": "Lifestyle Scene", "bedroom": "Bedroom",
            "office": "Office", "detail": "Detail", "sizes": "Sizes",
            "how_it_works": "How It Works", "collection": "Collection",
        }.items():
            conn.execute(
                """UPDATE mockup_set_items SET label=?
                   WHERE slot_key=? AND (label IS NULL OR lower(label)=replace(?, '_', ' '))""",
                (label, slot, slot),
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork_mockup_sets (
                artwork_id INTEGER PRIMARY KEY,
                set_id INTEGER NOT NULL,
                generated_at TEXT,
                approved_at TEXT,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                FOREIGN KEY (set_id) REFERENCES mockup_sets(id)
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
        scene_presentation_columns = {
            "frame_color": "TEXT NOT NULL DEFAULT '#2d2b29'",
            "frame_width": "REAL NOT NULL DEFAULT 2",
            "mat_color": "TEXT NOT NULL DEFAULT '#faf8f3'",
            "mat_width": "REAL NOT NULL DEFAULT 1.2",
            "shadow_strength": "REAL NOT NULL DEFAULT 35",
        }
        for column_name, declaration in scene_presentation_columns.items():
            if column_name not in scene_columns:
                conn.execute(
                    f"ALTER TABLE mockup_scenes ADD COLUMN {column_name} {declaration}"
                )

        default_set = conn.execute(
            "SELECT id FROM mockup_sets WHERE name = 'Etsy Standard'"
        ).fetchone()
        if default_set is None:
            cursor = conn.execute(
                "INSERT INTO mockup_sets (name, description) VALUES (?, ?)",
                ("Etsy Standard", "Eight-image curated Etsy listing set"),
            )
            default_set_id = cursor.lastrowid
            slots = ("hero", "room", "bedroom", "office", "detail", "sizes", "how_it_works", "collection")
            conn.executemany(
                """INSERT INTO mockup_set_items
                   (set_id, slot_key, label, source_kind, template_slot, position, is_lead)
                   VALUES (?, ?, ?, 'template', ?, ?, ?)""",
                [(default_set_id, slot, slot.replace("_", " ").title(), slot,
                  position, int(slot == "hero")) for position, slot in enumerate(slots, 1)],
            )


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
                ai_model TEXT,
                analysis_notes TEXT,
                analyzed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id)
            )
            """
        )
        if "creative_direction" in collection_columns:
            conn.execute(
                "UPDATE collections SET prompt = COALESCE(prompt, creative_direction)"
            )
        intelligence_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(artwork_intelligence)")
        }
        if "generation_prompt" in intelligence_columns:
            conn.execute(
                """
                UPDATE artworks
                SET prompt = COALESCE(
                    prompt,
                    (SELECT generation_prompt FROM artwork_intelligence
                     WHERE artwork_intelligence.artwork_id = artworks.id)
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_production_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                source_approval_confirmed INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (collection_id) REFERENCES collections(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_production_run_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                artwork_id INTEGER NOT NULL,
                source_status TEXT NOT NULL DEFAULT 'pending',
                certification_status TEXT NOT NULL DEFAULT 'pending',
                print_master_status TEXT NOT NULL DEFAULT 'pending',
                ratio_status TEXT NOT NULL DEFAULT 'pending',
                mockup_status TEXT NOT NULL DEFAULT 'pending',
                metadata_status TEXT NOT NULL DEFAULT 'pending',
                listing_status TEXT NOT NULL DEFAULT 'pending',
                overall_status TEXT NOT NULL DEFAULT 'pending',
                source_used TEXT,
                error_message TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES collection_production_runs(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                UNIQUE (run_id, artwork_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_collection_production_runs_collection "
            "ON collection_production_runs(collection_id, id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mug_collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL COLLATE NOCASE UNIQUE,
                name TEXT NOT NULL,
                profession TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                default_product_key TEXT NOT NULL DEFAULT 'mug_11oz_black_accent',
                default_price_cents INTEGER NOT NULL DEFAULT 2200,
                placement_x REAL NOT NULL DEFAULT 0.5,
                placement_y REAL NOT NULL DEFAULT 0.25,
                placement_scale REAL NOT NULL DEFAULT 0.45,
                placement_mode TEXT NOT NULL DEFAULT 'front',
                pinterest_style TEXT NOT NULL DEFAULT 'classroom_story',
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS standalone_designs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mug_collection_id INTEGER,
                name TEXT NOT NULL,
                message TEXT,
                description TEXT,
                tags TEXT,
                source_filename TEXT NOT NULL,
                source_original_filename TEXT,
                image_width INTEGER,
                image_height INTEGER,
                status TEXT NOT NULL DEFAULT 'draft',
                tshirt_candidate INTEGER NOT NULL DEFAULT 0 CHECK (tshirt_candidate IN (0, 1)),
                display_order INTEGER NOT NULL DEFAULT 0,
                refresh_state TEXT,
                refresh_message TEXT,
                refresh_updated_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (mug_collection_id) REFERENCES mug_collections(id)
            )
            """
        )
        collection_profile_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mug_collections)")
        }
        for column_name, definition in (
            ("default_price_cents", "INTEGER NOT NULL DEFAULT 2200"),
            ("placement_x", "REAL NOT NULL DEFAULT 0.5"),
            ("placement_y", "REAL NOT NULL DEFAULT 0.25"),
            ("placement_scale", "REAL NOT NULL DEFAULT 0.45"),
            ("placement_mode", "TEXT NOT NULL DEFAULT 'front'"),
            ("pinterest_style", "TEXT NOT NULL DEFAULT 'classroom_story'"),
        ):
            if column_name not in collection_profile_columns:
                conn.execute(
                    f"ALTER TABLE mug_collections ADD COLUMN {column_name} {definition}"
                )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS standalone_design_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                design_id INTEGER NOT NULL,
                product_type TEXT NOT NULL DEFAULT 'mug_11oz',
                blueprint_version INTEGER NOT NULL DEFAULT 1,
                title TEXT NOT NULL,
                description TEXT,
                price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
                blueprint_id INTEGER NOT NULL,
                provider_id INTEGER NOT NULL,
                provider_name TEXT NOT NULL,
                variant_id INTEGER NOT NULL,
                variant_title TEXT NOT NULL,
                placement_x REAL NOT NULL DEFAULT 0.5,
                placement_y REAL NOT NULL DEFAULT 0.5,
                placement_scale REAL NOT NULL DEFAULT 0.45,
                placement_mode TEXT NOT NULL DEFAULT 'front',
                opposite_source_filename TEXT,
                production_asset_filename TEXT,
                printify_product_id TEXT,
                printify_product_url TEXT,
                printify_base_cost_cents INTEGER,
                external_state TEXT NOT NULL DEFAULT 'not_sent',
                external_message TEXT,
                etsy_listing_id TEXT,
                etsy_listing_url TEXT,
                etsy_state TEXT,
                etsy_paused_at TEXT,
                marketplace_checked_at TEXT,
                etsy_last_synced_at TEXT,
                gallery_manifest TEXT,
                gallery_state TEXT NOT NULL DEFAULT 'not_prepared',
                gallery_approved_at TEXT,
                gallery_synced_at TEXT,
                gallery_message TEXT,
                product_thumbnail_filename TEXT,
                pinterest_ad_rating INTEGER NOT NULL DEFAULT 0 CHECK (pinterest_ad_rating BETWEEN 0 AND 3),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (design_id) REFERENCES standalone_designs(id)
                    ON DELETE CASCADE,
                UNIQUE (design_id, product_type)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_standalone_design_products_design "
            "ON standalone_design_products(design_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pinterest_launch_items (
                design_id INTEGER NOT NULL,
                product_type TEXT NOT NULL,
                selected_style TEXT NOT NULL DEFAULT 'classroom_story',
                approved INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1)),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (design_id, product_type),
                FOREIGN KEY (design_id) REFERENCES standalone_designs(id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS standalone_product_placement_defaults (
                product_key TEXT PRIMARY KEY,
                placement_x REAL NOT NULL,
                placement_y REAL NOT NULL,
                placement_scale REAL NOT NULL,
                placement_mode TEXT NOT NULL DEFAULT 'front',
                source_printify_product_id TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mug_text_ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                text TEXT NOT NULL COLLATE NOCASE UNIQUE,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5),
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        idea_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mug_text_ideas)")
        }
        if "rating" not in idea_columns:
            conn.execute(
                "ALTER TABLE mug_text_ideas ADD COLUMN rating INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "UPDATE mug_text_ideas SET rating = 5 WHERE is_favorite = 1"
            )
        if "mug_collection_id" not in idea_columns:
            conn.execute(
                "ALTER TABLE mug_text_ideas ADD COLUMN mug_collection_id INTEGER"
            )
        if "deleted_at" not in idea_columns:
            conn.execute("ALTER TABLE mug_text_ideas ADD COLUMN deleted_at TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mug_text_ideas_order "
            "ON mug_text_ideas(display_order, id)"
        )
        idea_count = conn.execute(
            "SELECT COUNT(*) AS count FROM mug_text_ideas"
        ).fetchone()["count"]
        if idea_count == 0:
            ideas = [
                ("Classroom Reality", "I Had a Plan. Then the Bell Rang."),
                ("Classroom Reality", "I Have Graded Things You Can't Even Imagine."),
                ("Classroom Reality", "Somewhere, Someone Is Sharpening a Pencil."),
                ("Classroom Reality", "Ask Again After Coffee."),
                ("Classroom Reality", "Today's Lesson: Flexibility."),
                ("Classroom Reality", "That's Going in Tomorrow's Lesson."),
                ("Classroom Reality", "This Wasn't in the Lesson Plan."),
                ("Classroom Reality", "I Teach Future Adults. Pray for Me."),
                ("Classroom Reality", "My Job Is Explaining Google."),
                ("Classroom Reality", "I Run on Curiosity and Deadlines."),
                ("Classroom Reality", "Classroom Chaos Coordinator."),
                ("Classroom Reality", "I Make Confusion Temporary."),
                ("Classroom Reality", "Raising Tomorrow's Smart People."),
                ("Classroom Reality", "It's Not Magic. It's Teaching."),
                ("Classroom Reality", 'I Turn "Huh?" into "Ohhh..."'),
                ("Things Teachers Think", "That's Actually a Great Question."),
                ("Things Teachers Think", "I'm Pretending I Didn't Hear That."),
                ("Things Teachers Think", "Somebody's About to Learn Something."),
                ("Biology", "I Know What Your Mitochondria Are Doing."),
                ("Biology", "Cells Before Bells."),
                ("Biology", "Everything Is Related Somehow."),
                ("Biology", "Biology Never Sleeps."),
                ("Biology", "Life Is Complicated. I Teach It Anyway."),
                ("Science", "Gravity Is Having Another Great Day."),
                ("Science", "The Evidence Disagrees."),
                ("Science", "Evolution Never Takes a Day Off."),
                ("Science", "Science Doesn't Care About Opinions."),
                ("Science", "I Make Molecules Interesting."),
                ("Science", "Ask Me About Weird Animals."),
                ("Science", "Powered by Experiments."),
                ("Science", "I Break Things... Scientifically."),
                ("History", "Every Century Has Issues."),
                ("History", "Today's Drama Happened 500 Years Ago."),
                ("History", "The Past Is Still Talking."),
                ("History", "I Grade Yesterday for a Living."),
                ("History", "I Already Know How This Ends."),
                ("History", "I've Seen This Before."),
                ("Math", "I Solve Problems for Fun."),
                ("Math", "Variables Build Character."),
                ("Math", "Math Is Just Organized Thinking."),
                ("Math", "I Know Where X Went."),
                ("The Inner Monologue", "I Was Not Prepared for That Answer."),
                ("The Veteran Teacher", "I've Learned Not to Ask Why First."),
                ("The Veteran Teacher", "Nothing Surprises Me Before Lunch."),
                ("The Veteran Teacher", "I've Seen This Lesson Before."),
                ("Student Logic", "That Made Perfect Sense... To Somebody."),
                ("Student Logic", "That's Creative. Not Correct, But Creative."),
                ("Student Logic", "You Connected Some Dots."),
                ("Student Logic", "That's an Impressive Guess."),
                ("Student Logic", "I Respect the Confidence."),
                ("Classroom Reality", "Somebody Just Learned by Accident."),
                ("Classroom Reality", "Deep Breath... Everyone."),
                ("Classroom Reality", "The Whiteboard Is Judging Me."),
                ("Classroom Reality", "We Were So Close."),
                ("Classroom Reality", "That Marker Is Definitely Empty."),
                ("The Honest Ones", "They Think I Know Everything."),
                ("The Honest Ones", "I Hope This Works."),
                ("The Honest Ones", "I Wonder If They'll Remember This."),
                ("Dry Humor", "That's Tomorrow's Problem."),
                ("Dry Humor", "Future Me Will Figure It Out."),
                ("Dry Humor", "That Was Unexpectedly Educational."),
                ("Dry Humor", "Good Enough for First Period."),
                ("Dry Humor", "Somehow This Became a Life Lesson."),
                ("Dry Humor", "I Wasn't Expecting That Plot Twist."),
                ("Dry Humor", "We Call This a Learning Opportunity."),
                ("The Ones That Feel Real", "Please Let This Marker Last."),
                ("The Ones That Feel Real", "I Just Sat Down."),
                ("The Ones That Feel Real", "I Can Explain That."),
                ("The Ones That Feel Real", "Please Don't Tell the Next Class."),
                ("The Ones That Feel Real", "I Need More Whiteboard."),
                ("The Ones That Feel Real", "That's Going to Be on the Test."),
                ("My Favorites", "We Took the Scenic Route."),
            ]
            favorites = {
                "that's creative. not correct, but creative.",
                "nothing surprises me before lunch.",
                "i respect the confidence.",
                "we took the scenic route.",
                "somebody just learned by accident.",
                "the whiteboard is judging me.",
                "please let this marker last.",
                "they think i know everything.",
                "that was unexpectedly educational.",
                "i was not prepared for that answer.",
            }
            conn.executemany(
                """
                INSERT OR IGNORE INTO mug_text_ideas (
                    category, text, is_favorite, rating, display_order
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        category,
                        text,
                        int(text.casefold() in favorites),
                        5 if text.casefold() in favorites else 0,
                        order,
                    )
                    for order, (category, text) in enumerate(ideas, start=1)
                ],
            )
        design_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(standalone_designs)")
        }
        if "mug_collection_id" not in design_columns:
            conn.execute(
                "ALTER TABLE standalone_designs ADD COLUMN mug_collection_id INTEGER"
            )
        if "tshirt_candidate" not in design_columns:
            conn.execute(
                "ALTER TABLE standalone_designs ADD COLUMN tshirt_candidate INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commerce_metrics_daily (
                metric_date TEXT NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('etsy', 'pinterest')),
                orders INTEGER NOT NULL DEFAULT 0,
                items_sold INTEGER NOT NULL DEFAULT 0,
                revenue_cents INTEGER NOT NULL DEFAULT 0,
                ad_spend_cents INTEGER NOT NULL DEFAULT 0,
                impressions INTEGER NOT NULL DEFAULT 0,
                paid_clicks INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (metric_date, source)
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO mug_collections (
                code, name, profession, description, status,
                default_product_key, display_order
            ) VALUES (
                'TEACHER', 'Teacher Mugs', 'Teacher',
                'Humorous and thoughtful mugs for teachers and educators.',
                'active', 'mug_11oz_black_accent', 10
            )
            """
        )
        conn.execute(
            """
            UPDATE mug_collections
            SET code = 'EVERYDAY', name = 'Everyday Mugs',
                profession = 'General',
                description = 'Everyday humor, quotes, and giftable mug ideas outside profession collections.'
            WHERE code IN ('ONE_OFF', 'ORIGINALS')
              AND NOT EXISTS (
                  SELECT 1 FROM mug_collections WHERE code = 'EVERYDAY'
              )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO mug_collections (
                code, name, profession, description, status,
                default_product_key, default_price_cents,
                placement_x, placement_y, placement_scale, placement_mode,
                pinterest_style, display_order
            ) VALUES (
                'EVERYDAY', 'Everyday Mugs', 'General',
                'Everyday humor, quotes, and giftable mug ideas outside profession collections.',
                'active', 'mug_11oz_black_accent', 2200,
                0.5, 0.25, 0.45, 'front', 'classroom_story', 30
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO mug_collections (
                code, name, profession, description, status,
                default_product_key, default_price_cents,
                placement_x, placement_y, placement_scale, placement_mode,
                pinterest_style, display_order
            ) VALUES (
                'DOCTOR', 'Doctor Mugs', 'Doctor',
                'Humorous, appreciative, and profession-focused mugs for doctors.',
                'planning', 'mug_11oz_black_accent', 2200,
                0.5, 0.25, 0.45, 'front', 'medical_story', 20
            )
            """
        )
        conn.execute(
            """
            UPDATE mug_text_ideas
            SET mug_collection_id = (
                SELECT id FROM mug_collections WHERE code = 'TEACHER'
            )
            WHERE mug_collection_id IS NULL
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mug_collection_launches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mug_collection_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ideas',
                target_count INTEGER NOT NULL DEFAULT 20,
                current_step TEXT NOT NULL DEFAULT 'ideas',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (mug_collection_id) REFERENCES mug_collections(id),
                UNIQUE (mug_collection_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mug_collection_launch_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                launch_id INTEGER NOT NULL,
                text_idea_id INTEGER,
                message TEXT NOT NULL,
                display_order INTEGER NOT NULL,
                artwork_mode TEXT NOT NULL DEFAULT 'text_only',
                artwork_message TEXT,
                artwork_state TEXT NOT NULL DEFAULT 'waiting',
                artwork_style_variant INTEGER,
                artwork_filename TEXT,
                standalone_design_id INTEGER,
                artwork_approved_at TEXT,
                printify_state TEXT NOT NULL DEFAULT 'waiting',
                placement_state TEXT NOT NULL DEFAULT 'waiting',
                mockup_state TEXT NOT NULL DEFAULT 'waiting',
                listing_state TEXT NOT NULL DEFAULT 'waiting',
                publish_state TEXT NOT NULL DEFAULT 'waiting',
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (launch_id) REFERENCES mug_collection_launches(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (text_idea_id) REFERENCES mug_text_ideas(id),
                UNIQUE (launch_id, text_idea_id)
            )
            """
        )
        launch_item_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(mug_collection_launch_items)")
        }
        if "artwork_mode" not in launch_item_columns:
            conn.execute(
                "ALTER TABLE mug_collection_launch_items "
                "ADD COLUMN artwork_mode TEXT NOT NULL DEFAULT 'text_only'"
            )
        for column_name, column_type in (
            ("artwork_message", "TEXT"),
            ("artwork_style_variant", "INTEGER"),
            ("artwork_filename", "TEXT"),
            ("standalone_design_id", "INTEGER"),
            ("artwork_approved_at", "TEXT"),
        ):
            if column_name not in launch_item_columns:
                conn.execute(
                    f"ALTER TABLE mug_collection_launch_items "
                    f"ADD COLUMN {column_name} {column_type}"
                )
        conn.execute(
            """
            UPDATE standalone_designs
            SET mug_collection_id = (
                SELECT id FROM mug_collections WHERE code = 'TEACHER'
            )
            WHERE mug_collection_id IS NULL AND status != 'archived'
            """
        )
        for column_name in (
            "refresh_state",
            "refresh_message",
            "refresh_updated_at",
        ):
            if column_name not in design_columns:
                conn.execute(
                    f"ALTER TABLE standalone_designs ADD COLUMN {column_name} TEXT"
                )
        if "display_order" not in design_columns:
            conn.execute(
                "ALTER TABLE standalone_designs ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "UPDATE standalone_designs SET display_order = id WHERE display_order = 0"
            )
        design_product_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(standalone_design_products)"
            )
        }
        if "placement_mode" not in design_product_columns:
            conn.execute(
                "ALTER TABLE standalone_design_products "
                "ADD COLUMN placement_mode TEXT NOT NULL DEFAULT 'front'"
            )
        if "opposite_source_filename" not in design_product_columns:
            conn.execute(
                "ALTER TABLE standalone_design_products "
                "ADD COLUMN opposite_source_filename TEXT"
            )
        if "blueprint_version" not in design_product_columns:
            conn.execute(
                "ALTER TABLE standalone_design_products "
                "ADD COLUMN blueprint_version INTEGER NOT NULL DEFAULT 1"
            )
        if "production_asset_filename" not in design_product_columns:
            conn.execute(
                "ALTER TABLE standalone_design_products "
                "ADD COLUMN production_asset_filename TEXT"
            )
        if "pinterest_ad_rating" not in design_product_columns:
            conn.execute(
                "ALTER TABLE standalone_design_products "
                "ADD COLUMN pinterest_ad_rating INTEGER NOT NULL DEFAULT 0"
            )
        if "product_thumbnail_filename" not in design_product_columns:
            conn.execute(
                "ALTER TABLE standalone_design_products "
                "ADD COLUMN product_thumbnail_filename TEXT"
            )
        for column_name in (
            "etsy_listing_id",
            "etsy_listing_url",
            "etsy_state",
            "etsy_paused_at",
            "marketplace_checked_at",
            "etsy_last_synced_at",
        ):
            if column_name not in design_product_columns:
                conn.execute(
                    f"ALTER TABLE standalone_design_products ADD COLUMN {column_name} TEXT"
                )
        gallery_columns = {
            "gallery_manifest": "TEXT",
            "gallery_state": "TEXT NOT NULL DEFAULT 'not_prepared'",
            "gallery_approved_at": "TEXT",
            "gallery_synced_at": "TEXT",
            "gallery_message": "TEXT",
        }
        for column_name, definition in gallery_columns.items():
            if column_name not in design_product_columns:
                conn.execute(
                    f"ALTER TABLE standalone_design_products ADD COLUMN {column_name} {definition}"
                )
        conn.execute(
            """
            UPDATE standalone_design_products
            SET etsy_last_synced_at = COALESCE(
                    marketplace_checked_at, updated_at, CURRENT_TIMESTAMP
                )
            WHERE etsy_last_synced_at IS NULL
              AND etsy_listing_id IS NOT NULL
              AND LOWER(COALESCE(external_message, '')) LIKE '%etsy%'
              AND LOWER(COALESCE(external_message, '')) LIKE '%synchroniz%'
            """
        )
        run_item_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(collection_production_run_items)"
            )
        }
        if "source_used" not in run_item_columns:
            conn.execute(
                "ALTER TABLE collection_production_run_items ADD COLUMN source_used TEXT"
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
            "etsy_paused_at",
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
            default_collection_prices = (2900, 3400, 3900, 4600, 5800, 7200)
            for tier, default_price in enumerate(default_collection_prices, start=1):
                column_name = f"default_price_tier_{tier}_cents"
                if column_name not in collection_columns:
                    conn.execute(
                        f"ALTER TABLE collections ADD COLUMN {column_name} "
                        f"INTEGER NOT NULL DEFAULT {default_price}"
                    )
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
                UPDATE collections
                SET name = 'Duende – A Flamenco Collection',
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = 'DUE' AND name = 'The Duende Collection'
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
                c.cover_image_path,
                c.cover_approved,
                (
                    SELECT cover_artwork.artwork_code
                    FROM artworks AS cover_artwork
                    WHERE cover_artwork.collection_id = c.id
                      AND cover_artwork.status != 'retired'
                      AND EXISTS (
                        SELECT 1 FROM artwork_files AS cover_file
                        WHERE cover_file.artwork_id = cover_artwork.id
                          AND cover_file.role = 'source'
                      )
                    ORDER BY cover_artwork.sequence_number, cover_artwork.id
                    LIMIT 1
                ) AS representative_artwork_code,
                COUNT(DISTINCT CASE WHEN a.status != 'retired' THEN a.id END)
                    AS artwork_count,
                COUNT(DISTINCT CASE WHEN l.etsy_state = 'active' THEN l.id END)
                    AS live_etsy_count,
                COUNT(DISTINCT CASE
                    WHEN l.etsy_paused_at IS NOT NULL
                     AND l.external_listing_id IS NOT NULL
                    THEN l.id END
                ) AS paused_etsy_count,
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
        if item["status"] == "paused":
            item["display_status"] = "Paused"
            item["display_status_class"] = "paused"
        elif item["paused_etsy_count"] and not item["live_etsy_count"]:
            item["display_status"] = "Paused on Etsy"
            item["display_status_class"] = "paused"
        elif item["live_etsy_count"]:
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
                a.sequence_number,
                a.public_title,
                a.theme,
                a.status,
                c.name AS collection_name,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_paused_at IS NOT NULL
                ) AS etsy_paused,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_state = 'active'
                ) AS etsy_live,
                (
                    SELECT marketplace_listing.marketplace_url
                    FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.marketplace_url IS NOT NULL
                    ORDER BY marketplace_listing.etsy_paused_at IS NULL,
                             marketplace_listing.updated_at DESC
                    LIMIT 1
                ) AS etsy_url,
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
        recent_collection_codes = [
            row["code"]
            for row in conn.execute(
                """
                SELECT c.code
                FROM collections AS c
                JOIN artworks AS a ON a.collection_id = c.id
                WHERE a.status != 'retired'
                  AND c.status != 'archived'
                GROUP BY c.id
                ORDER BY MAX(a.updated_at) DESC, MAX(a.id) DESC
                """
            ).fetchall()
        ]

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
        "recent_collection_codes": recent_collection_codes,
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
                a.sequence_number,
                a.public_title,
                a.working_title,
                a.theme,
                a.status,
                c.name AS collection_name,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_paused_at IS NOT NULL
                ) AS etsy_paused,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_state = 'active'
                ) AS etsy_live,
                (
                    SELECT marketplace_listing.marketplace_url
                    FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.marketplace_url IS NOT NULL
                    ORDER BY marketplace_listing.etsy_paused_at IS NULL,
                             marketplace_listing.updated_at DESC
                    LIMIT 1
                ) AS etsy_url,
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
            SELECT code, name, status, target_artwork_count, etsy_section_name,
                   cover_image_path, cover_approved,
                   notes AS description, prompt,
                   default_price_tier_1_cents,
                   default_price_tier_2_cents,
                   default_price_tier_3_cents,
                   default_price_tier_4_cents,
                   default_price_tier_5_cents,
                   default_price_tier_6_cents,
                   (SELECT COUNT(*) FROM artworks
                    WHERE collection_id = collections.id) AS artwork_count
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
                a.sequence_number,
                a.public_title,
                a.working_title,
                a.theme,
                a.description,
                a.prompt,
                a.status,
                p.orientation,
                p.master_ratio,
                p.original_approved,
                p.print_master_ready,
                p.ratio_exports_ready,
                p.mockups_ready,
                p.listing_content_ready,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_paused_at IS NOT NULL
                ) AS etsy_paused,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_state = 'active'
                ) AS etsy_live,
                (
                    SELECT marketplace_listing.marketplace_url
                    FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.marketplace_url IS NOT NULL
                    ORDER BY marketplace_listing.etsy_paused_at IS NULL,
                             marketplace_listing.updated_at DESC
                    LIMIT 1
                ) AS etsy_url,
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
                a.sequence_number,
                a.public_title,
                a.working_title,
                a.theme,
                a.description,
                a.prompt,
                a.status,
                p.orientation,
                p.master_ratio,
                p.original_approved,
                p.print_master_ready,
                p.ratio_exports_ready,
                p.mockups_ready,
                p.listing_content_ready,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_paused_at IS NOT NULL
                ) AS etsy_paused,
                EXISTS (
                    SELECT 1 FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.etsy_state = 'active'
                ) AS etsy_live,
                (
                    SELECT marketplace_listing.marketplace_url
                    FROM listings AS marketplace_listing
                    WHERE marketplace_listing.artwork_id = a.id
                      AND marketplace_listing.marketplace_url IS NOT NULL
                    ORDER BY marketplace_listing.etsy_paused_at IS NULL,
                             marketplace_listing.updated_at DESC
                    LIMIT 1
                ) AS etsy_url,
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
                a.sequence_number,
                a.public_title,
                a.working_title,
                a.theme,
                a.description,
                a.story,
                a.prompt,
                a.status,
                c.code AS collection_code,
                c.name AS collection_name,
                c.notes AS collection_description
            FROM artworks AS a
            JOIN collections AS c
                ON c.id = a.collection_id
            WHERE a.artwork_code = ?
            """,
            (artwork_code.upper(),),
        ).fetchone()


def create_collection_production_run(collection_code, source_approval_confirmed):
    with get_connection() as conn:
        collection = conn.execute(
            "SELECT id FROM collections WHERE code = ?",
            (collection_code.strip().upper(),),
        ).fetchone()
        if collection is None:
            raise ValueError("Collection not found")
        cursor = conn.execute(
            """
            INSERT INTO collection_production_runs (
                collection_id, status, source_approval_confirmed
            ) VALUES (?, 'running', ?)
            """,
            (collection["id"], int(bool(source_approval_confirmed))),
        )
        run_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO collection_production_run_items (run_id, artwork_id)
            SELECT ?, id FROM artworks
            WHERE collection_id = ? AND status != 'retired'
            """,
            (run_id, collection["id"]),
        )
        conn.commit()
        return run_id


def get_collection_production_run(collection_code):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT r.*
            FROM collection_production_runs AS r
            JOIN collections AS c ON c.id = r.collection_id
            WHERE c.code = ?
            ORDER BY r.id DESC
            LIMIT 1
            """,
            (collection_code.strip().upper(),),
        ).fetchone()


def get_collection_production_run_items(run_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT i.*, a.artwork_code, a.public_title
            FROM collection_production_run_items AS i
            JOIN artworks AS a ON a.id = i.artwork_id
            WHERE i.run_id = ?
            ORDER BY a.sequence_number, a.artwork_code
            """,
            (run_id,),
        ).fetchall()


def update_collection_production_run_item(run_id, artwork_code, **states):
    allowed = {
        "source_status", "certification_status", "print_master_status",
        "ratio_status", "mockup_status", "metadata_status", "listing_status",
        "overall_status", "error_message",
        "source_used",
    }
    updates = {key: value for key, value in states.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            UPDATE collection_production_run_items
            SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE run_id = ? AND artwork_id = (
                SELECT id FROM artworks WHERE artwork_code = ?
            )
            """,
            (*updates.values(), run_id, artwork_code.strip().upper()),
        )
        if cursor.rowcount == 0:
            raise ValueError("Production run item not found")
        conn.commit()


def finish_collection_production_run(run_id, status):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE collection_production_runs
            SET status = ?, updated_at = CURRENT_TIMESTAMP,
                completed_at = CASE
                    WHEN ? IN ('complete', 'needs_review', 'failed')
                    THEN CURRENT_TIMESTAMP ELSE completed_at END
            WHERE id = ?
            """,
            (status, status, run_id),
        )
        conn.commit()


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


def get_collection_branding_revision(collection_code):
    """Return the newest collection identity/source change timestamp."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(changed_at) AS changed_at
            FROM (
                SELECT updated_at AS changed_at
                FROM collections
                WHERE code = ?
                UNION ALL
                SELECT a.updated_at
                FROM artworks AS a
                JOIN collections AS c ON c.id = a.collection_id
                WHERE c.code = ?
                UNION ALL
                SELECT f.updated_at
                FROM artwork_files AS f
                JOIN artworks AS a ON a.id = f.artwork_id
                JOIN collections AS c ON c.id = a.collection_id
                WHERE c.code = ? AND f.role = 'source'
            )
            """,
            (
                collection_code.upper(),
                collection_code.upper(),
                collection_code.upper(),
            ),
        ).fetchone()
        return row["changed_at"] if row else None


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


def replace_artwork_ratio_assignments(artwork_code, assignments):
    """Atomically point every required ratio role at a completed replacement set."""
    rows = list(assignments)
    with get_connection() as conn:
        artwork = conn.execute(
            "SELECT id FROM artworks WHERE artwork_code = ?",
            (artwork_code.strip().upper(),),
        ).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")
        conn.executemany(
            """
            INSERT INTO artwork_files (
                artwork_id, role, relative_path, stored_filename,
                original_filename
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(artwork_id, role) DO UPDATE SET
                relative_path = excluded.relative_path,
                stored_filename = excluded.stored_filename,
                original_filename = excluded.original_filename,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    artwork["id"], row["role"], row["relative_path"],
                    row["stored_filename"], row["original_filename"],
                )
                for row in rows
            ],
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
        conn.execute(
            """UPDATE artwork_mockup_sets SET approved_at=NULL
               WHERE artwork_id=(SELECT id FROM artworks WHERE artwork_code=?)""",
            (artwork_code.upper(),),
        )
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
    prompt,
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
                prompt = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_code = ?
            """,
            (
                public_title.strip(),
                working_title.strip() or None,
                theme.strip() or None,
                story.strip() or None,
                prompt.strip() or None,
                normalized_status,
                artwork_code.upper(),
            ),
        )
        conn.commit()


def update_artwork_details(
    artwork_code,
    *,
    public_title,
    description,
    prompt,
    status,
):
    normalized_status = status.strip().lower()
    allowed_statuses = {
        "idea", "creating", "review", "approved", "production",
        "listed", "paused", "retired",
    }
    if normalized_status not in allowed_statuses:
        raise ValueError("Invalid artwork status")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE artworks
            SET public_title = ?, description = ?, prompt = ?, status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE artwork_code = ?
            """,
            (
                public_title.strip(),
                description.strip() or None,
                prompt.strip() or None,
                normalized_status,
                artwork_code.upper(),
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Artwork not found")
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


def create_collection(
    code, name, target_artwork_count, status, etsy_section_name=None,
    description="", prompt="", default_prices=None,
):
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
    prices = tuple(default_prices or (2900, 3400, 3900, 4600, 5800, 7200))
    if len(prices) != 6 or any(int(price) <= 0 for price in prices):
        raise ValueError("Enter a positive default price for every poster size")

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
                notes,
                prompt,
                default_price_tier_1_cents,
                default_price_tier_2_cents,
                default_price_tier_3_cents,
                default_price_tier_4_cents,
                default_price_tier_5_cents,
                default_price_tier_6_cents,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brand["id"],
                code,
                name,
                "standard",
                "general",
                target_artwork_count,
                normalized_section,
                description.strip() or None,
                prompt.strip() or None,
                *prices,
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
    description="",
    prompt="",
    new_code=None,
    default_prices=None,
):
    code = collection_code.strip().upper()
    requested_code = (new_code or code).strip().upper()
    name = name.strip()
    normalized_status = status.strip().lower()
    normalized_section = (etsy_section_name or name.removeprefix("The ")).strip()

    if not name:
        raise ValueError("Collection name is required")
    if not requested_code:
        raise ValueError("Collection code is required")
    if len(requested_code) > 10:
        raise ValueError("Collection code must be 10 characters or fewer")
    if target_artwork_count < 0:
        raise ValueError("Target artwork count cannot be negative")
    if not normalized_section or len(normalized_section) > 24:
        raise ValueError("Etsy section name must be between 1 and 24 characters")
    prices = tuple(default_prices or (2900, 3400, 3900, 4600, 5800, 7200))
    if len(prices) != 6 or any(int(price) <= 0 for price in prices):
        raise ValueError("Enter a positive default price for every poster size")

    allowed_statuses = {"planned", "active", "complete", "paused"}

    if normalized_status not in allowed_statuses:
        raise ValueError("Invalid collection status")

    with get_connection() as conn:
        collection = conn.execute(
            """
            SELECT c.id, COUNT(a.id) AS artwork_count
            FROM collections AS c
            LEFT JOIN artworks AS a ON a.collection_id = c.id
            WHERE c.code = ?
            GROUP BY c.id
            """,
            (code,),
        ).fetchone()
        if collection is None:
            raise ValueError("Collection not found")
        if requested_code != code and collection["artwork_count"]:
            raise ValueError(
                "Collection code cannot change after artwork has been created"
            )
        duplicate = conn.execute(
            """
            SELECT 1
            FROM collections
            WHERE (name = ? OR code = ?) AND code != ?
            """,
            (name, requested_code, code),
        ).fetchone()

        if duplicate is not None:
            raise ValueError(
                "Another collection already uses that name"
            )

        cursor = conn.execute(
            """
            UPDATE collections
            SET
                code = ?,
                name = ?,
                target_artwork_count = ?,
                etsy_section_name = ?,
                notes = ?,
                prompt = ?,
                default_price_tier_1_cents = ?,
                default_price_tier_2_cents = ?,
                default_price_tier_3_cents = ?,
                default_price_tier_4_cents = ?,
                default_price_tier_5_cents = ?,
                default_price_tier_6_cents = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
            """,
            (
                requested_code,
                name,
                target_artwork_count,
                normalized_section,
                description.strip() or None,
                prompt.strip() or None,
                *prices,
                normalized_status,
                code,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("Collection not found")

        conn.commit()
    return requested_code


def set_collection_cover(collection_code, relative_path, approved=False):
    with get_connection() as conn:
        result = conn.execute(
            """
            UPDATE collections
            SET cover_image_path = ?, cover_approved = ?, updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
            """,
            (relative_path, int(bool(approved)), collection_code.upper()),
        )
        if not result.rowcount:
            raise ValueError("Collection not found")
        conn.commit()


def approve_collection_cover(collection_code):
    with get_connection() as conn:
        result = conn.execute(
            """
            UPDATE collections
            SET cover_approved = 1, updated_at = CURRENT_TIMESTAMP
            WHERE code = ? AND cover_image_path IS NOT NULL
            """,
            (collection_code.upper(),),
        )
        if not result.rowcount:
            raise ValueError("Upload a collection cover first")
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


MOCKUP_SET_SLOTS = (
    "hero", "room", "bedroom", "office", "detail", "sizes",
    "how_it_works", "collection",
)


def list_mockup_sets():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT ms.*, COUNT(msi.slot_key) AS item_count,
                   MAX(CASE WHEN msi.is_lead = 1 THEN msi.slot_key END) AS lead_slot
            FROM mockup_sets AS ms
            LEFT JOIN mockup_set_items AS msi ON msi.set_id = ms.id
            WHERE ms.active = 1
            GROUP BY ms.id
            ORDER BY ms.name
            """
        ).fetchall()


def get_mockup_set(set_id):
    with get_connection() as conn:
        mockup_set = conn.execute(
            "SELECT * FROM mockup_sets WHERE id = ? AND active = 1", (set_id,)
        ).fetchone()
        if mockup_set is None:
            return None, []
        items = conn.execute(
            """
            SELECT msi.*, ms.name AS scene_name, ms.room_type
            FROM mockup_set_items AS msi
            LEFT JOIN mockup_scenes AS ms ON ms.id = msi.scene_id
            WHERE msi.set_id = ?
            ORDER BY msi.position
            """,
            (set_id,),
        ).fetchall()
        return mockup_set, items


def create_mockup_set(name, description="", template_key="modern_minimal", scene_id=None):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO mockup_sets (name, description, template_key) VALUES (?, ?, ?)",
            (name.strip(), description.strip(), template_key.strip()),
        )
        set_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO mockup_set_items
            (set_id, slot_key, label, source_kind, template_slot, position, scene_id, is_lead)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (set_id, slot, slot.replace("_", " ").title(),
                 "scene" if slot == "room" and scene_id else "template", slot,
                 position, scene_id if slot == "room" else None, int(slot == "hero"))
                for position, slot in enumerate(MOCKUP_SET_SLOTS, 1)
            ],
        )
        conn.commit()
        return set_id


def update_mockup_set(set_id, *, name, description, template_key, ordered_slots=None,
                      lead_slot="hero", scene_id=None, items=None):
    if items is not None:
        ordered_slots = [item["slot_key"] for item in sorted(items, key=lambda item: item["position"])]
        if len(ordered_slots) != len(set(ordered_slots)) or not ordered_slots:
            raise ValueError("Every marketplace image needs a unique slot")
        if lead_slot not in ordered_slots:
            raise ValueError("Choose a valid cover image")
    else:
        items = [
            {
                "slot_key": slot, "label": slot.replace("_", " ").title(),
                "source_kind": "scene" if slot == "room" and scene_id else "template",
                "template_slot": slot, "scene_id": scene_id if slot == "room" else None,
                "position": position,
            }
            for position, slot in enumerate(ordered_slots or (), 1)
        ]
    ordered_slots = [str(slot).strip() for slot in ordered_slots]
    if items is None or not ordered_slots:
        raise ValueError("Add at least one marketplace image")
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE mockup_sets SET name=?, description=?, template_key=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=? AND active=1""",
            (name.strip(), description.strip(), template_key.strip(), set_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Mockup set not found")
        conn.execute("DELETE FROM mockup_set_items WHERE set_id = ?", (set_id,))
        conn.executemany(
            """INSERT INTO mockup_set_items
               (set_id, slot_key, label, source_kind, template_slot,
                position, scene_id, is_lead)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (set_id, item["slot_key"], item.get("label") or "Listing image",
                 item.get("source_kind") or "template", item.get("template_slot"),
                 position, item.get("scene_id"), int(item["slot_key"] == lead_slot))
                for position, item in enumerate(sorted(items, key=lambda item: item["position"]), 1)
            ],
        )
        conn.commit()


def add_mockup_set_item(set_id):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT slot_key, position FROM mockup_set_items WHERE set_id=? ORDER BY position",
            (set_id,),
        ).fetchall()
        used = {row["slot_key"] for row in existing}
        number = 1
        while f"extra_{number}" in used:
            number += 1
        scene = conn.execute(
            "SELECT id, name FROM mockup_scenes WHERE active=1 ORDER BY room_type, name LIMIT 1"
        ).fetchone()
        slot_key = f"extra_{number}"
        conn.execute(
            """INSERT INTO mockup_set_items
               (set_id, slot_key, label, source_kind, template_slot, position, scene_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (set_id, slot_key, f"Additional image {number}",
             "scene" if scene else "template", None if scene else "hero",
             len(existing) + 1, scene["id"] if scene else None),
        )
        conn.commit()


def remove_mockup_set_item(set_id, slot_key):
    with get_connection() as conn:
        item = conn.execute(
            "SELECT is_lead FROM mockup_set_items WHERE set_id=? AND slot_key=?",
            (set_id, slot_key),
        ).fetchone()
        if item is None:
            raise ValueError("Marketplace image not found")
        if item["is_lead"]:
            raise ValueError("Choose another cover image before removing this one")
        conn.execute(
            "DELETE FROM mockup_set_items WHERE set_id=? AND slot_key=?", (set_id, slot_key)
        )
        remaining = conn.execute(
            "SELECT slot_key FROM mockup_set_items WHERE set_id=? ORDER BY position", (set_id,)
        ).fetchall()
        for position, row in enumerate(remaining, 1):
            conn.execute(
                "UPDATE mockup_set_items SET position=? WHERE set_id=? AND slot_key=?",
                (position, set_id, row["slot_key"]),
            )
        conn.commit()


def record_artwork_mockup_set_generated(artwork_code, set_id):
    with get_connection() as conn:
        artwork = conn.execute("SELECT id FROM artworks WHERE artwork_code=?", (artwork_code.upper(),)).fetchone()
        if artwork is None:
            raise ValueError("Artwork not found")
        conn.execute(
            """INSERT INTO artwork_mockup_sets (artwork_id, set_id, generated_at, approved_at)
               VALUES (?, ?, CURRENT_TIMESTAMP, NULL)
               ON CONFLICT(artwork_id) DO UPDATE SET set_id=excluded.set_id,
               generated_at=CURRENT_TIMESTAMP, approved_at=NULL""",
            (artwork["id"], set_id),
        )
        conn.commit()


def approve_artwork_mockup_set(artwork_code, set_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE artwork_mockup_sets SET approved_at=CURRENT_TIMESTAMP
               WHERE artwork_id=(SELECT id FROM artworks WHERE artwork_code=?)
                 AND set_id=? AND generated_at IS NOT NULL""",
            (artwork_code.upper(), set_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Generate this mockup set before approving it")
        conn.commit()


def get_artwork_mockup_set_state(artwork_code):
    with get_connection() as conn:
        return conn.execute(
            """SELECT ams.*, ms.name, ms.template_key,
               (SELECT slot_key FROM mockup_set_items WHERE set_id=ms.id AND is_lead=1) AS lead_slot
               FROM artwork_mockup_sets AS ams
               JOIN artworks AS a ON a.id=ams.artwork_id
               JOIN mockup_sets AS ms ON ms.id=ams.set_id
               WHERE a.artwork_code=?""",
            (artwork_code.upper(),),
        ).fetchone()


def invalidate_artwork_mockup_set_approval(artwork_code):
    with get_connection() as conn:
        conn.execute(
            """UPDATE artwork_mockup_sets SET approved_at=NULL
               WHERE artwork_id=(SELECT id FROM artworks WHERE artwork_code=?)""",
            (artwork_code.upper(),),
        )
        conn.commit()


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
                ORDER BY room_type,
                         CASE WHEN name LIKE 'Shangooli Default · %' THEN 0 ELSE 1 END,
                         name
                """,
                (orientation,),
            ).fetchall()
        return conn.execute(
            """
            SELECT * FROM mockup_scenes
            WHERE active = 1
            ORDER BY room_type,
                     CASE WHEN name LIKE 'Shangooli Default · %' THEN 0 ELSE 1 END,
                     name
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
    source_url="", creator="", license_name="", frame_color="#2d2b29",
    frame_width=2, mat_color="#faf8f3", mat_width=1.2, shadow_strength=35,
):
    values = [placement_x, placement_y, placement_width, placement_height]
    if any(value < 0 or value > 100 for value in values):
        raise ValueError("Scene placement values must be between 0 and 100")
    if placement_x + placement_width > 100 or placement_y + placement_height > 100:
        raise ValueError("The artwork placement must fit inside the scene")
    if frame_width < 0 or frame_width > 12 or mat_width < 0 or mat_width > 12:
        raise ValueError("Frame and mat widths must be between 0 and 12")
    if shadow_strength < 0 or shadow_strength > 100:
        raise ValueError("Shadow strength must be between 0 and 100")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO mockup_scenes (
                name, room_type, orientation, image_path,
                placement_x, placement_y, placement_width, placement_height,
                source_url, creator, license_name, frame_color, frame_width,
                mat_color, mat_width, shadow_strength
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(), room_type.strip(), orientation.strip(), image_path,
                placement_x, placement_y, placement_width, placement_height,
                source_url.strip(), creator.strip(), license_name.strip(),
                frame_color.strip(), frame_width, mat_color.strip(), mat_width,
                shadow_strength,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_mockup_scene_placement(
    scene_id, *, placement_x, placement_y, placement_width, placement_height,
    frame_color="#2d2b29", frame_width=2, mat_color="#faf8f3",
    mat_width=1.2, shadow_strength=35,
):
    values = [placement_x, placement_y, placement_width, placement_height]
    if any(value < 0 or value > 100 for value in values):
        raise ValueError("Scene placement values must be between 0 and 100")
    if placement_x + placement_width > 100 or placement_y + placement_height > 100:
        raise ValueError("The artwork placement must fit inside the scene")
    if frame_width < 0 or frame_width > 12 or mat_width < 0 or mat_width > 12:
        raise ValueError("Frame and mat widths must be between 0 and 12")
    if shadow_strength < 0 or shadow_strength > 100:
        raise ValueError("Shadow strength must be between 0 and 100")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mockup_scenes
            SET placement_x = ?, placement_y = ?, placement_width = ?,
                placement_height = ?, frame_color = ?, frame_width = ?,
                mat_color = ?, mat_width = ?, shadow_strength = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (placement_x, placement_y, placement_width, placement_height,
             frame_color, frame_width, mat_color, mat_width, shadow_strength,
             scene_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Mockup scene not found")
        conn.commit()


def update_mockup_scene_background(
    scene_id, *, image_path, source_url="", creator="", license_name="",
):
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE mockup_scenes
               SET image_path=?, source_url=?, creator=?, license_name=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND active=1""",
            (
                image_path, source_url.strip(), creator.strip(),
                license_name.strip(), scene_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Reusable scene not found")
        scene_key = f"scene:{scene_id}"
        conn.execute(
            """UPDATE artwork_mockup_sets SET approved_at=NULL
               WHERE artwork_id IN (
                   SELECT artwork_id FROM artwork_mockup_templates
                   WHERE template_key=?
               )""",
            (scene_key,),
        )
        conn.execute(
            """UPDATE artwork_production SET mockups_ready=0,
                   updated_at=CURRENT_TIMESTAMP
               WHERE artwork_id IN (
                   SELECT artwork_id FROM artwork_mockup_templates
                   WHERE template_key=?
               )""",
            (scene_key,),
        )
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
                   target_customer, ai_model, analysis_notes, analyzed_at
            FROM artwork_intelligence
            WHERE artwork_id = ?
            """,
            (artwork["id"],),
        ).fetchone()


def update_artwork_intelligence(artwork_code, **values):
    allowed = {
        "theme", "style", "mood", "primary_colors", "suggested_room",
        "target_customer", "ai_model", "analysis_notes", "analyzed_at",
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


def find_artwork_listing_content(artwork_code):
    """Read prepared listing content without creating a placeholder row."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT lc.short_story, lc.long_story, lc.etsy_title,
                   lc.etsy_description, lc.etsy_tags, lc.alt_text,
                   lc.keywords, lc.generated_at
            FROM artwork_listing_content AS lc
            JOIN artworks AS a ON a.id = lc.artwork_id
            WHERE a.artwork_code = ?
            """,
            (artwork_code.upper(),),
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


def list_listings(status=None, collection_code=None):
    normalized_status = (status or "").strip().lower()
    normalized_collection = (collection_code or "").strip().upper()
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
               l.etsy_paused_at,
               a.artwork_code, a.public_title, a.sequence_number,
               a.status AS artwork_status,
               EXISTS (
                   SELECT 1 FROM artwork_files AS source_file
                   WHERE source_file.artwork_id = a.id
                     AND source_file.role = 'source'
               ) AS has_source_image,
               c.code AS collection_code, c.name AS collection_name,
               c.status AS collection_status
        FROM listings AS l
        JOIN artworks AS a ON a.id = l.artwork_id
        JOIN collections AS c ON c.id = a.collection_id
    """
    clauses = []
    params = []
    if normalized_status:
        clauses.append("l.status = ?")
        params.append(normalized_status)
    if normalized_collection:
        clauses.append("c.code = ?")
        params.append(normalized_collection)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += (
        " ORDER BY c.display_order IS NULL, c.display_order, c.code, "
        "a.sequence_number, l.id"
    )

    with get_connection() as conn:
        return conn.execute(query, tuple(params)).fetchall()


def get_listing_status_counts(collection_status=None, artwork_state="current"):
    counts = {status: 0 for status in LISTING_STATUSES}
    normalized_collection_status = (collection_status or "").strip().lower()
    normalized_artwork_state = (artwork_state or "current").strip().lower()
    if normalized_collection_status and normalized_collection_status not in (
        "active", "paused",
    ):
        raise ValueError("Invalid collection status")
    if normalized_artwork_state not in ("current", "retired", "all"):
        raise ValueError("Invalid artwork state")
    query = """
        SELECT l.status, COUNT(*) AS total
        FROM listings AS l
        JOIN artworks AS a ON a.id = l.artwork_id
        JOIN collections AS c ON c.id = a.collection_id
    """
    clauses = []
    params = []
    if normalized_collection_status:
        clauses.append("c.status = ?")
        params.append(normalized_collection_status)
    if normalized_artwork_state == "current":
        clauses.append("a.status != 'retired'")
    elif normalized_artwork_state == "retired":
        clauses.append("a.status = 'retired'")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " GROUP BY l.status"
    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] = row["total"]
    counts["all"] = sum(
        counts[status] for status in LISTING_STATUSES if status != "archived"
    )
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
                   l.etsy_paused_at,
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


def restart_collection_records_for_replacement(collection_code):
    """Archive current listings and clear source-derived production records.

    Creative metadata and source assignments are intentionally preserved.
    A fresh local draft is created from the newest current listing so edited
    copy and pricing survive without carrying external publication identity.
    """
    with get_connection() as conn:
        collection = conn.execute(
            "SELECT id FROM collections WHERE code = ? AND status != 'archived'",
            (collection_code.upper(),),
        ).fetchone()
        if collection is None:
            raise ValueError("Collection not found")
        artworks = conn.execute(
            """
            SELECT id, artwork_code
            FROM artworks
            WHERE collection_id = ? AND status != 'retired'
            ORDER BY sequence_number, artwork_code
            """,
            (collection["id"],),
        ).fetchall()
        results = []
        for artwork in artworks:
            listings = conn.execute(
                """
                SELECT *
                FROM listings
                WHERE artwork_id = ?
                ORDER BY status = 'archived', updated_at DESC, id DESC
                """,
                (artwork["id"],),
            ).fetchall()
            current = next(
                (row for row in listings if row["status"] != "archived"),
                listings[0] if listings else None,
            )
            if current is None:
                raise ValueError(
                    f"{artwork['artwork_code']} has no local listing to preserve"
                )
            archived_ids = []
            for listing in listings:
                if listing["status"] != "archived":
                    conn.execute(
                        """
                        UPDATE listings
                        SET status = 'archived', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (listing["id"],),
                    )
                    archived_ids.append(listing["id"])
            cursor = conn.execute(
                """
                INSERT INTO listings (
                    artwork_id, marketplace, product, title, description, tags,
                    price_cents, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft')
                """,
                (
                    artwork["id"], current["marketplace"], current["product"],
                    current["title"], current["description"], current["tags"],
                    current["price_cents"],
                ),
            )
            conn.execute(
                """
                DELETE FROM artwork_files
                WHERE artwork_id = ?
                  AND (role = 'print_master' OR role LIKE 'ratio:%'
                       OR role LIKE 'mockup:%')
                """,
                (artwork["id"],),
            )
            conn.execute(
                "DELETE FROM artwork_certification WHERE artwork_id = ?",
                (artwork["id"],),
            )
            conn.execute(
                "DELETE FROM print_master_certification WHERE artwork_id = ?",
                (artwork["id"],),
            )
            conn.execute(
                """
                UPDATE artwork_production
                SET original_approved = 0, print_master_ready = 0,
                    ratio_exports_ready = 0, mockups_ready = 0,
                    ai_enhanced_at = NULL,
                    ai_enhanced_original_width = NULL,
                    ai_enhanced_original_height = NULL,
                    ai_enhanced_width = NULL, ai_enhanced_height = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE artwork_id = ?
                """,
                (artwork["id"],),
            )
            conn.execute(
                """
                UPDATE artwork_mockup_sets
                SET generated_at = NULL, approved_at = NULL
                WHERE artwork_id = ?
                """,
                (artwork["id"],),
            )
            conn.execute(
                """
                UPDATE artworks
                SET status = CASE WHEN status = 'listed' THEN 'production'
                                  ELSE status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (artwork["id"],),
            )
            results.append({
                "artwork_code": artwork["artwork_code"],
                "archived_listing_ids": archived_ids,
                "new_listing_id": cursor.lastrowid,
            })
        conn.commit()
        return results


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
                   l.etsy_paused_at,
                   l.publishing_recovery_stage,
                   l.publishing_recovery_message,
                   l.publishing_recovery_checked_at,
                   l.created_at, l.updated_at,
                   a.artwork_code, a.sequence_number, a.public_title, c.code AS collection_code,
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


def record_etsy_paused(listing_id, paused):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE listings
            SET etsy_paused_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                etsy_state = CASE WHEN ? THEN 'inactive' ELSE 'active' END,
                status = CASE WHEN ? THEN 'ready' ELSE 'published' END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(bool(paused)), int(bool(paused)), int(bool(paused)), listing_id),
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


def create_standalone_design(
    *,
    name,
    message,
    description,
    tags,
    source_filename,
    source_original_filename,
    image_width,
    image_height,
    collection_code="TEACHER",
):
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("Enter a design name")
    with get_connection() as conn:
        collection = conn.execute(
            "SELECT id FROM mug_collections WHERE UPPER(code) = UPPER(?)",
            ((collection_code or "").strip(),),
        ).fetchone()
        if collection is None:
            raise ValueError("Choose a valid mug collection")
        cursor = conn.execute(
            """
            INSERT INTO standalone_designs (
                mug_collection_id, name, message, description, tags, source_filename,
                source_original_filename, image_width, image_height
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection["id"],
                normalized_name,
                (message or "").strip(),
                (description or "").strip(),
                (tags or "").strip(),
                source_filename,
                source_original_filename,
                image_width,
                image_height,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_standalone_design(design_id, product_key="mug_11oz"):
    """Return a design joined to one product blueprint instance.

    ``standalone_design_products.product_type`` is retained as the database
    column name for compatibility. New code treats its value as a stable
    product blueprint key.
    """
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT d.*, p.id AS product_id, p.product_type, p.title AS product_title,
                   p.blueprint_version, p.production_asset_filename,
                   p.description AS product_description, p.price_cents,
                   p.blueprint_id, p.provider_id, p.provider_name,
                   p.variant_id, p.variant_title, p.placement_x, p.placement_y,
                   p.placement_scale, p.placement_mode,
                   p.opposite_source_filename, p.printify_product_id,
                   p.printify_product_url, p.printify_base_cost_cents,
                   p.external_state, p.external_message, p.etsy_listing_id,
                   p.etsy_listing_url, p.etsy_state, p.etsy_paused_at,
                   p.marketplace_checked_at, p.etsy_last_synced_at
                   , p.gallery_manifest, p.gallery_state,
                   p.gallery_approved_at, p.gallery_synced_at,
                   p.gallery_message, p.product_thumbnail_filename
            FROM standalone_designs AS d
            LEFT JOIN standalone_design_products AS p
              ON p.design_id = d.id AND p.product_type = ?
            WHERE d.id = ?
            """,
            (product_key, design_id),
        ).fetchone()


def list_standalone_design_products(design_id):
    """List independent product instances belonging to one creative source."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM standalone_design_products
            WHERE design_id = ?
            ORDER BY created_at, id
            """,
            (design_id,),
        ).fetchall()


def save_standalone_product_gallery(
    design_id, product_key, *, manifest, state, message=""
):
    """Persist one product's exact gallery without affecting sibling products."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET gallery_manifest = ?, gallery_state = ?, gallery_message = ?,
                gallery_approved_at = CASE
                    WHEN ? = 'approved' THEN CURRENT_TIMESTAMP ELSE NULL END,
                gallery_synced_at = CASE
                    WHEN ? = 'synced' THEN CURRENT_TIMESTAMP ELSE gallery_synced_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (manifest, state, (message or "").strip(), state, state, design_id, product_key),
        )
        if cursor.rowcount == 0:
            raise ValueError("Product setup not found")
        conn.commit()


def update_standalone_product_gallery_state(
    design_id, product_key, *, state, message=""
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET gallery_state = ?, gallery_message = ?,
                gallery_approved_at = CASE
                    WHEN ? = 'approved' THEN CURRENT_TIMESTAMP
                    WHEN ? = 'prepared' THEN NULL ELSE gallery_approved_at END,
                gallery_synced_at = CASE
                    WHEN ? = 'synced' THEN CURRENT_TIMESTAMP ELSE gallery_synced_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (state, (message or "").strip(), state, state, state, design_id, product_key),
        )
        if cursor.rowcount == 0:
            raise ValueError("Product setup not found")
        conn.commit()


def list_standalone_product_summaries():
    """Return all product rows used to summarize and filter design cards."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT design_id, product_type, title, description,
                   printify_product_id, external_state, etsy_listing_id,
                   etsy_listing_url, etsy_state, etsy_paused_at,
                   etsy_last_synced_at, pinterest_ad_rating,
                   product_thumbnail_filename
            FROM standalone_design_products
            ORDER BY design_id, created_at, id
            """
        ).fetchall()


def save_standalone_product_thumbnail(design_id, product_key, filename):
    """Save one local, product-specific catalog and website reference image."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET product_thumbnail_filename = ?, updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (filename, design_id, product_key),
        )
        if cursor.rowcount == 0:
            raise ValueError("Product setup not found")
        conn.commit()


def list_standalone_designs():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT d.*, c.code AS mug_collection_code,
                   c.name AS mug_collection_name,
                   c.profession AS mug_collection_profession,
                   p.product_type, p.title AS product_title,
                   p.description AS product_description,
                   p.printify_product_id, p.printify_product_url,
                   p.external_state, p.external_message, p.price_cents,
                   p.etsy_listing_id, p.etsy_listing_url, p.etsy_state,
                   p.etsy_paused_at, p.marketplace_checked_at
            FROM standalone_designs AS d
            LEFT JOIN mug_collections AS c ON c.id = d.mug_collection_id
            LEFT JOIN standalone_design_products AS p
              ON p.design_id = d.id AND p.product_type = 'mug_11oz'
            ORDER BY CASE WHEN d.display_order = 0 THEN 1 ELSE 0 END,
                     d.display_order, d.id DESC
            """
        ).fetchall()


def list_mug_collections():
    """List mug catalog collections separately from poster collections."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.*,
                   COUNT(d.id) AS design_count,
                   SUM(CASE WHEN d.status != 'archived' THEN 1 ELSE 0 END)
                       AS active_design_count,
                   SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM standalone_design_products p
                       WHERE p.design_id = d.id
                         AND LOWER(COALESCE(p.etsy_state, '')) = 'active'
                         AND p.etsy_paused_at IS NULL
                   ) THEN 1 ELSE 0 END) AS live_design_count
            FROM mug_collections c
            LEFT JOIN standalone_designs d ON d.mug_collection_id = c.id
            GROUP BY c.id
            ORDER BY c.display_order, c.name COLLATE NOCASE
            """
        ).fetchall()


def create_mug_collection(*, code, name, profession, description=""):
    normalized_code = "".join(
        character for character in (code or "").strip().upper()
        if character.isalnum() or character in {"_", "-"}
    )
    normalized_name = (name or "").strip()
    normalized_profession = (profession or "").strip()
    if not normalized_code or not normalized_name or not normalized_profession:
        raise ValueError("Enter a code, collection name, and profession")
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO mug_collections (
                    code, name, profession, description, default_product_key,
                    display_order
                ) VALUES (?, ?, ?, ?, 'mug_11oz_black_accent',
                    COALESCE((SELECT MAX(display_order) + 10 FROM mug_collections), 10))
                """,
                (
                    normalized_code,
                    normalized_name,
                    normalized_profession,
                    (description or "").strip(),
                ),
            )
        except sqlite3.IntegrityError as error:
            existing = conn.execute(
                "SELECT id, status FROM mug_collections WHERE code = ?",
                (normalized_code,),
            ).fetchone()
            if existing is None or existing["status"] != "planning":
                raise ValueError("That mug collection code already exists") from error
            conn.execute(
                """
                UPDATE mug_collections
                SET name = ?, profession = ?, description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    normalized_name,
                    normalized_profession,
                    (description or "").strip(),
                    existing["id"],
                ),
            )
            conn.commit()
            return existing["id"]
        conn.commit()
        return cursor.lastrowid


def get_mug_collection_profile_for_design(design_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.* FROM mug_collections c
            JOIN standalone_designs d ON d.mug_collection_id = c.id
            WHERE d.id = ?
            """,
            (design_id,),
        ).fetchone()


def mug_catalog_integrity():
    """Return non-destructive catalog checks used before adding professions."""
    with get_connection() as conn:
        return {
            "unassigned_active": conn.execute(
                "SELECT COUNT(*) FROM standalone_designs "
                "WHERE status != 'archived' AND mug_collection_id IS NULL"
            ).fetchone()[0],
            "active_white_products": conn.execute(
                """
                SELECT COUNT(*) FROM standalone_design_products
                WHERE product_type = 'mug_11oz'
                  AND LOWER(COALESCE(etsy_state, '')) = 'active'
                  AND etsy_paused_at IS NULL
                """
            ).fetchone()[0],
            "paused_white_products": conn.execute(
                """
                SELECT COUNT(*) FROM standalone_design_products
                WHERE product_type = 'mug_11oz' AND etsy_paused_at IS NOT NULL
                """
            ).fetchone()[0],
            "active_black_products": conn.execute(
                """
                SELECT COUNT(*) FROM standalone_design_products
                WHERE product_type = 'mug_11oz_black_accent'
                  AND LOWER(COALESCE(etsy_state, '')) = 'active'
                  AND etsy_paused_at IS NULL
                """
            ).fetchone()[0],
            "missing_black_thumbnails": conn.execute(
                """
                SELECT COUNT(*) FROM standalone_design_products
                WHERE product_type = 'mug_11oz_black_accent'
                  AND product_thumbnail_filename IS NULL
                """
            ).fetchone()[0],
            "black_product_overrides": conn.execute(
                """
                SELECT COUNT(*) FROM standalone_design_products p
                JOIN standalone_designs d ON d.id = p.design_id
                JOIN mug_collections c ON c.id = d.mug_collection_id
                WHERE p.product_type = c.default_product_key
                  AND (
                    p.price_cents != c.default_price_cents OR
                    p.placement_x != c.placement_x OR
                    p.placement_y != c.placement_y OR
                    p.placement_scale != c.placement_scale OR
                    p.placement_mode != c.placement_mode
                  )
                """
            ).fetchone()[0],
        }


def rate_standalone_product_pinterest_ad(design_id, product_key, rating):
    normalized_rating = int(rating)
    if normalized_rating < 0 or normalized_rating > 3:
        raise ValueError("Pinterest ad rating must be between zero and three stars")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET pinterest_ad_rating = ?, updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (normalized_rating, design_id, product_key),
        )
        if cursor.rowcount == 0:
            raise ValueError("Product setup not found")
        conn.commit()


def list_pinterest_launch_states():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT design_id, product_type, selected_style, approved, updated_at
            FROM pinterest_launch_items
            ORDER BY design_id, product_type
            """
        ).fetchall()


def save_pinterest_launch_state(
    design_id, product_key, *, selected_style=None, approved=None
):
    """Persist review choices without changing the underlying product record."""
    current = {
        (row["design_id"], row["product_type"]): row
        for row in list_pinterest_launch_states()
    }.get((int(design_id), product_key))
    style = selected_style or (
        current["selected_style"] if current else "classroom_story"
    )
    approval = (
        int(bool(approved))
        if approved is not None
        else int(current["approved"] if current else 0)
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pinterest_launch_items (
                design_id, product_type, selected_style, approved
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(design_id, product_type) DO UPDATE SET
                selected_style = excluded.selected_style,
                approved = excluded.approved,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(design_id), product_key, style, approval),
        )
        conn.commit()


def approve_all_pinterest_launch_items(items, approved=True):
    for design_id, product_key in items:
        save_pinterest_launch_state(
            design_id, product_key, approved=approved
        )


def reorder_standalone_designs(design_ids):
    """Reorder the supplied visible designs while preserving all other positions."""
    normalized_ids = [int(design_id) for design_id in design_ids]
    if len(normalized_ids) != len(set(normalized_ids)):
        raise ValueError("Each design can appear only once")
    with get_connection() as conn:
        existing = {
            row["id"]: row["display_order"]
            for row in conn.execute(
                "SELECT id, display_order FROM standalone_designs WHERE id IN (%s)"
                % ",".join("?" for _ in normalized_ids),
                normalized_ids,
            )
        } if normalized_ids else {}
        if set(normalized_ids) != set(existing):
            raise ValueError("The design list changed. Reload and try again")
        occupied_orders = sorted(
            order or design_id for design_id, order in existing.items()
        )
        conn.executemany(
            """
            UPDATE standalone_designs
            SET display_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            zip(occupied_orders, normalized_ids),
        )
        conn.commit()


def update_standalone_design(
    design_id, *, name, message, description, tags, tshirt_candidate=False
):
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("Enter a design name")
    with get_connection() as conn:
        previous = conn.execute(
            "SELECT tags FROM standalone_designs WHERE id = ?", (design_id,)
        ).fetchone()
        cursor = conn.execute(
            """
            UPDATE standalone_designs
            SET name = ?, message = ?, description = ?, tags = ?, tshirt_candidate = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized_name,
                (message or "").strip(),
                (description or "").strip(),
                (tags or "").strip(),
                int(bool(tshirt_candidate)),
                design_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Design not found")
        if previous and (previous["tags"] or "").strip() != (tags or "").strip():
            conn.execute(
                """
                UPDATE standalone_design_products
                SET etsy_last_synced_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE design_id = ? AND etsy_listing_id IS NOT NULL
                """,
                (design_id,),
            )
        conn.commit()


def set_standalone_design_archived(design_id, archived):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_designs
            SET status = CASE WHEN ? THEN 'archived'
                              WHEN status = 'archived' AND EXISTS (
                                  SELECT 1 FROM standalone_design_products
                                  WHERE design_id = standalone_designs.id
                                    AND printify_product_id IS NOT NULL
                              ) THEN 'on_printify'
                              WHEN status = 'archived' THEN 'draft'
                              ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (bool(archived), design_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Design not found")
        conn.commit()


def set_standalone_design_refresh_state(design_id, state, message=""):
    """Persist only the resume point for the guided portfolio refresh."""
    allowed = {
        "awaiting_printify",
        "awaiting_etsy",
        "awaiting_gallery",
        "needs_review",
        "complete",
    }
    if state not in allowed:
        raise ValueError("Unknown portfolio refresh state")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_designs
            SET refresh_state = ?, refresh_message = ?,
                refresh_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (state, (message or "").strip(), design_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Design not found")
        conn.commit()


def record_standalone_marketplace_status(
    design_id,
    *,
    etsy_listing_id=None,
    etsy_listing_url=None,
    etsy_state=None,
    paused=None,
    message="",
    product_key="mug_11oz",
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET etsy_listing_id = COALESCE(?, etsy_listing_id),
                etsy_listing_url = COALESCE(?, etsy_listing_url),
                etsy_state = COALESCE(?, etsy_state),
                etsy_paused_at = CASE
                    WHEN ? = 1 THEN COALESCE(etsy_paused_at, CURRENT_TIMESTAMP)
                    WHEN ? = 0 THEN NULL
                    ELSE etsy_paused_at
                END,
                external_message = ?,
                marketplace_checked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (
                str(etsy_listing_id).strip() if etsy_listing_id else None,
                (etsy_listing_url or "").strip() or None,
                (etsy_state or "").strip().lower() or None,
                1 if paused is True else None,
                0 if paused is False else None,
                (message or "").strip(),
                design_id,
                product_key,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Save the mug setup first")
        conn.commit()


def mark_standalone_etsy_synced(design_id, *, product_key="mug_11oz"):
    """Record that one product's saved copy was successfully sent to Etsy."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET etsy_last_synced_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (design_id, product_key),
        )
        if cursor.rowcount == 0:
            raise ValueError("Save the mug setup first")
        conn.commit()


def replace_standalone_design_source(
    design_id,
    *,
    source_filename,
    source_original_filename,
    image_width,
    image_height,
):
    """Point a design at a corrected source while preserving the old file."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_designs
            SET source_filename = ?, source_original_filename = ?,
                image_width = ?, image_height = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                source_filename,
                source_original_filename,
                image_width,
                image_height,
                design_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Design not found")
        conn.execute(
            """
            UPDATE standalone_design_products
            SET external_state = CASE
                    WHEN printify_product_id IS NOT NULL THEN 'needs_update'
                    ELSE external_state
                END,
                external_message = CASE
                    WHEN printify_product_id IS NOT NULL
                    THEN 'The saved graphic changed. Update the existing Printify draft.'
                    ELSE external_message
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = 'mug_11oz'
            """,
            (design_id,),
        )
        conn.commit()


def save_standalone_design_product(
    design_id,
    *,
    product_key="mug_11oz",
    blueprint_version=1,
    production_asset_filename=None,
    title,
    description,
    price_cents,
    blueprint_id,
    provider_id,
    provider_name,
    variant_id,
    variant_title,
    placement_x,
    placement_y,
    placement_scale,
    placement_mode="front",
    opposite_source_filename=None,
):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO standalone_design_products (
                design_id, product_type, blueprint_version,
                production_asset_filename, title, description, price_cents,
                blueprint_id, provider_id, provider_name, variant_id,
                variant_title, placement_x, placement_y, placement_scale
                , placement_mode, opposite_source_filename
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(design_id, product_type) DO UPDATE SET
                title = excluded.title,
                blueprint_version = excluded.blueprint_version,
                production_asset_filename = COALESCE(
                    excluded.production_asset_filename,
                    standalone_design_products.production_asset_filename
                ),
                description = excluded.description,
                price_cents = excluded.price_cents,
                blueprint_id = excluded.blueprint_id,
                provider_id = excluded.provider_id,
                provider_name = excluded.provider_name,
                variant_id = excluded.variant_id,
                variant_title = excluded.variant_title,
                placement_x = excluded.placement_x,
                placement_y = excluded.placement_y,
                placement_scale = excluded.placement_scale,
                placement_mode = excluded.placement_mode,
                opposite_source_filename = COALESCE(
                    excluded.opposite_source_filename,
                    standalone_design_products.opposite_source_filename
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE (
                    standalone_design_products.printify_product_id IS NULL
                    OR standalone_design_products.external_state = 'needs_update'
                  )
              AND standalone_design_products.external_state NOT IN (
                  'creating', 'outcome_unknown'
              )
            """,
            (
                design_id,
                product_key,
                blueprint_version,
                production_asset_filename,
                (title or "").strip(),
                (description or "").strip(),
                price_cents,
                blueprint_id,
                provider_id,
                (provider_name or "").strip(),
                variant_id,
                (variant_title or "").strip(),
                placement_x,
                placement_y,
                placement_scale,
                placement_mode,
                opposite_source_filename,
            ),
        )
        conn.commit()


def update_standalone_product_copy(
    design_id, product_key, *, title, description
):
    """Stage copy changes for one connected product without touching setup."""
    normalized_title = (title or "").strip()
    if not normalized_title:
        raise ValueError("Enter a product title")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET title = ?, description = ?,
                etsy_last_synced_at = CASE
                    WHEN etsy_listing_id IS NOT NULL THEN NULL
                    ELSE etsy_last_synced_at
                END,
                external_state = CASE
                    WHEN printify_product_id IS NOT NULL THEN 'needs_update'
                    ELSE external_state
                END,
                external_message = CASE
                    WHEN printify_product_id IS NOT NULL
                    THEN 'Product copy changed. Update the existing Printify draft.'
                    ELSE external_message
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
              AND external_state NOT IN (
                  'creating', 'outcome_unknown', 'updating',
                  'update_outcome_unknown'
              )
            """,
            (
                normalized_title,
                (description or "").strip(),
                design_id,
                product_key,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError(
                "Save the product setup or resolve its current operation first"
            )
        conn.commit()


def prepare_standalone_product_asset(
    design_id, product_key, production_asset_filename
):
    """Explicitly adopt a design asset for exactly one product blueprint."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET production_asset_filename = ?,
                external_state = CASE
                    WHEN printify_product_id IS NOT NULL THEN 'needs_update'
                    ELSE external_state
                END,
                external_message = CASE
                    WHEN printify_product_id IS NOT NULL
                    THEN 'A newer graphic was prepared for this product. Update the existing Printify draft when ready.'
                    ELSE external_message
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
              AND external_state NOT IN (
                  'creating', 'outcome_unknown', 'updating',
                  'update_outcome_unknown'
              )
            """,
            (production_asset_filename, design_id, product_key),
        )
        if cursor.rowcount == 0:
            raise ValueError(
                "Save the product setup or resolve its current operation first"
            )
        conn.commit()


def store_standalone_product_asset_reference(
    design_id, product_key, production_asset_filename
):
    """Record the exact asset used by one successfully updated product."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET production_asset_filename = ?, updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (production_asset_filename, design_id, product_key),
        )
        if cursor.rowcount == 0:
            raise ValueError("Product setup not found")
        conn.commit()


def set_standalone_product_state(
    design_id,
    state,
    message="",
    *,
    product_key="mug_11oz",
    printify_product_id=None,
    printify_product_url=None,
    base_cost_cents=None,
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE standalone_design_products
            SET external_state = ?, external_message = ?,
                printify_product_id = COALESCE(?, printify_product_id),
                printify_product_url = COALESCE(?, printify_product_url),
                printify_base_cost_cents = COALESCE(?, printify_base_cost_cents),
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = ?
            """,
            (
                state,
                (message or "").strip(),
                printify_product_id,
                printify_product_url,
                base_cost_cents,
                design_id,
                product_key,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Save the mug setup before creating the draft")
        conn.execute(
            """
            UPDATE standalone_designs
            SET status = CASE WHEN ? = 'created' THEN 'on_printify' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (state, design_id),
        )
        conn.commit()


def get_mug_collection(code):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM mug_collections WHERE UPPER(code) = UPPER(?)",
            ((code or "").strip(),),
        ).fetchone()


def list_mug_text_ideas(collection_code=None, include_deleted=False):
    with get_connection() as conn:
        clauses = []
        params = []
        if collection_code:
            clauses.append("UPPER(c.code) = UPPER(?)")
            params.append((collection_code or "").strip())
        if not include_deleted:
            clauses.append("i.deleted_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return conn.execute(
            f"""
            SELECT i.id, i.category, i.text, i.rating, i.display_order,
                   c.code AS mug_collection_code,
                   c.name AS mug_collection_name
            FROM mug_text_ideas i
            LEFT JOIN mug_collections c ON c.id = i.mug_collection_id
            {where}
            ORDER BY i.display_order, i.id
            """,
            tuple(params),
        ).fetchall()


def get_standalone_product_placement_default(product_key):
    with get_connection() as conn:
        try:
            return conn.execute(
                """
                SELECT product_key, placement_x, placement_y, placement_scale,
                       placement_mode, source_printify_product_id, updated_at
                FROM standalone_product_placement_defaults
                WHERE product_key = ?
                """,
                (product_key,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None


def save_standalone_product_placement_default(
    product_key,
    *,
    placement_x,
    placement_y,
    placement_scale,
    placement_mode,
    source_printify_product_id,
):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO standalone_product_placement_defaults (
                product_key, placement_x, placement_y, placement_scale,
                placement_mode, source_printify_product_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(product_key) DO UPDATE SET
                placement_x = excluded.placement_x,
                placement_y = excluded.placement_y,
                placement_scale = excluded.placement_scale,
                placement_mode = excluded.placement_mode,
                source_printify_product_id = excluded.source_printify_product_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                product_key,
                placement_x,
                placement_y,
                placement_scale,
                placement_mode,
                source_printify_product_id,
            ),
        )
        conn.commit()


def create_mug_text_idea(category, text, collection_code="TEACHER"):
    normalized_category = " ".join((category or "").split())
    normalized_text = " ".join((text or "").split())
    if not normalized_category or not normalized_text:
        raise ValueError("Add both a category and an idea")
    with get_connection() as conn:
        collection = conn.execute(
            "SELECT id FROM mug_collections WHERE UPPER(code) = UPPER(?)",
            ((collection_code or "TEACHER").strip(),),
        ).fetchone()
        if collection is None:
            raise ValueError("Choose a valid mug collection")
        next_order = conn.execute(
            "SELECT COALESCE(MAX(display_order), 0) + 1 FROM mug_text_ideas "
            "WHERE mug_collection_id = ?",
            (collection["id"],),
        ).fetchone()[0]
        deleted_match = conn.execute(
            """
            SELECT id FROM mug_text_ideas
            WHERE text = ? COLLATE NOCASE AND mug_collection_id = ?
              AND deleted_at IS NOT NULL
            """,
            (normalized_text, collection["id"]),
        ).fetchone()
        if deleted_match is not None:
            conn.execute(
                """
                UPDATE mug_text_ideas
                SET category = ?, text = ?, display_order = ?, deleted_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    normalized_category,
                    normalized_text,
                    next_order,
                    deleted_match["id"],
                ),
            )
            conn.commit()
            return deleted_match["id"]
        try:
            cursor = conn.execute(
                """
                INSERT INTO mug_text_ideas (
                    category, text, display_order, mug_collection_id
                ) VALUES (?, ?, ?, ?)
                """,
                (normalized_category, normalized_text, next_order, collection["id"]),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("That idea is already in the list") from error
        conn.commit()
        return cursor.lastrowid


def create_mug_text_ideas_bulk(collection_code, category, texts):
    created = 0
    duplicates = 0
    for text in texts:
        if not " ".join((text or "").split()):
            continue
        try:
            create_mug_text_idea(category, text, collection_code)
            created += 1
        except ValueError as error:
            if "already" not in str(error).lower():
                raise
            duplicates += 1
    return {"created": created, "duplicates": duplicates}


def update_mug_text_idea(idea_id, category, text, collection_code):
    normalized_category = " ".join((category or "").split())
    normalized_text = " ".join((text or "").split())
    if not normalized_category or not normalized_text:
        raise ValueError("Add both a category and an idea")
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                UPDATE mug_text_ideas
                SET category = ?, text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND deleted_at IS NULL AND mug_collection_id = (
                    SELECT id FROM mug_collections WHERE UPPER(code) = UPPER(?)
                )
                """,
                (
                    normalized_category,
                    normalized_text,
                    int(idea_id),
                    (collection_code or "").strip(),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("That idea is already in the list") from error
        if cursor.rowcount == 0:
            raise ValueError("Text idea not found in this collection")
        conn.commit()


def get_or_create_mug_collection_launch(collection_code, target_count=20):
    normalized_target = int(target_count)
    if normalized_target < 1 or normalized_target > 100:
        raise ValueError("Target count must be between 1 and 100")
    with get_connection() as conn:
        collection = conn.execute(
            "SELECT * FROM mug_collections WHERE UPPER(code) = UPPER(?)",
            ((collection_code or "").strip(),),
        ).fetchone()
        if collection is None:
            raise ValueError("Mug collection not found")
        conn.execute(
            """
            INSERT INTO mug_collection_launches (mug_collection_id, target_count)
            VALUES (?, ?)
            ON CONFLICT(mug_collection_id) DO UPDATE SET
                target_count = excluded.target_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (collection["id"], normalized_target),
        )
        conn.commit()
        launch = conn.execute(
            "SELECT * FROM mug_collection_launches WHERE mug_collection_id = ?",
            (collection["id"],),
        ).fetchone()
        return collection, launch


def get_mug_collection_launch(collection_code):
    with get_connection() as conn:
        launch = conn.execute(
            """
            SELECT l.*, c.code AS collection_code, c.name AS collection_name,
                   c.profession, c.default_product_key, c.default_price_cents,
                   c.placement_x, c.placement_y, c.placement_scale,
                   c.placement_mode, c.pinterest_style
            FROM mug_collection_launches l
            JOIN mug_collections c ON c.id = l.mug_collection_id
            WHERE UPPER(c.code) = UPPER(?)
            """,
            ((collection_code or "").strip(),),
        ).fetchone()
        if launch is None:
            return None, []
        items = conn.execute(
            """
            SELECT * FROM mug_collection_launch_items
            WHERE launch_id = ? ORDER BY display_order, id
            """,
            (launch["id"],),
        ).fetchall()
        return launch, items


def lock_mug_collection_launch_ideas(collection_code, idea_ids, target_count=20):
    normalized_ids = list(dict.fromkeys(int(idea_id) for idea_id in idea_ids))
    normalized_target = int(target_count)
    if len(normalized_ids) != normalized_target:
        raise ValueError(f"Select exactly {normalized_target} ideas")
    collection, launch = get_or_create_mug_collection_launch(
        collection_code, normalized_target
    )
    with get_connection() as conn:
        placeholders = ",".join("?" for _ in normalized_ids)
        ideas = conn.execute(
            f"""
            SELECT i.id, i.text FROM mug_text_ideas i
            WHERE i.mug_collection_id = ? AND i.deleted_at IS NULL
              AND i.id IN ({placeholders})
            """,
            (collection["id"], *normalized_ids),
        ).fetchall()
        ideas_by_id = {row["id"]: row for row in ideas}
        if len(ideas_by_id) != len(normalized_ids):
            raise ValueError("One or more ideas do not belong to this collection")
        conn.execute(
            "DELETE FROM mug_collection_launch_items WHERE launch_id = ?",
            (launch["id"],),
        )
        conn.executemany(
            """
            INSERT INTO mug_collection_launch_items (
                launch_id, text_idea_id, message, display_order
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (launch["id"], idea_id, ideas_by_id[idea_id]["text"], order)
                for order, idea_id in enumerate(normalized_ids, start=1)
            ],
        )
        conn.execute(
            """
            UPDATE mug_collection_launches
            SET status = 'draft', current_step = 'artwork',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (launch["id"],),
        )
        conn.commit()
    return launch["id"]


def set_mug_collection_launch_artwork_mode(collection_code, item_id, artwork_mode):
    normalized_mode = (artwork_mode or "").strip().lower()
    if normalized_mode not in {"text_only", "text_graphics", "graphic_only"}:
        raise ValueError(
            "Choose Text Only, Text + Accent Graphics, or Graphic Only"
        )
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET artwork_mode = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            )
            """,
            (normalized_mode, int(item_id), (collection_code or "").strip()),
        )
        if cursor.rowcount == 0:
            raise ValueError("Launch artwork item not found")
        conn.commit()


def set_mug_collection_launch_artwork_message(
    collection_code, item_id, artwork_message
):
    normalized_lines = [
        " ".join(line.split())
        for line in str(artwork_message or "").splitlines()
        if line.strip()
    ]
    formatted_message = "\n".join(normalized_lines)
    if not formatted_message:
        raise ValueError("Enter the wording for the mug artwork")
    if len(formatted_message) > 180:
        raise ValueError("Keep the mug artwork wording under 180 characters")
    with get_connection() as conn:
        item = conn.execute(
            """
            SELECT i.message FROM mug_collection_launch_items i
            JOIN mug_collection_launches l ON l.id = i.launch_id
            JOIN mug_collections c ON c.id = l.mug_collection_id
            WHERE i.id = ? AND i.artwork_state != 'approved'
              AND UPPER(c.code) = UPPER(?)
            """,
            (int(item_id), (collection_code or "").strip()),
        ).fetchone()
        if item is None:
            raise ValueError("Launch artwork item not found or already approved")
        conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET message = ?, artwork_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (" ".join(formatted_message.split()), formatted_message, int(item_id)),
        )
        conn.commit()


def approve_mug_collection_launch_artwork(
    collection_code, item_id, style_variant, artwork_filename, design_id
):
    normalized_variant = int(style_variant)
    if normalized_variant < 0 or normalized_variant > 5:
        raise ValueError("Choose one of the six artwork options")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET artwork_state = 'approved', artwork_style_variant = ?,
                artwork_filename = ?, standalone_design_id = ?,
                artwork_approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND artwork_state != 'approved' AND launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            )
            """,
            (
                normalized_variant,
                artwork_filename,
                int(design_id),
                int(item_id),
                (collection_code or "").strip(),
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Launch artwork item is missing or already approved")
        remaining = conn.execute(
            """
            SELECT COUNT(*) FROM mug_collection_launch_items
            WHERE launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            ) AND artwork_state != 'approved'
            """,
            ((collection_code or "").strip(),),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute(
                """
                UPDATE mug_collection_launches
                SET current_step = 'printify', updated_at = CURRENT_TIMESTAMP
                WHERE mug_collection_id = (
                    SELECT id FROM mug_collections WHERE UPPER(code) = UPPER(?)
                )
                """,
                ((collection_code or "").strip(),),
            )
        conn.commit()


def reopen_mug_collection_launch_artwork(collection_code, item_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET artwork_state = 'waiting', artwork_style_variant = NULL,
                artwork_approved_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND artwork_state = 'approved'
              AND printify_state = 'waiting' AND launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            )
            """,
            (int(item_id), (collection_code or "").strip()),
        )
        if cursor.rowcount == 0:
            raise ValueError(
                "Artwork can only be reopened before its Printify draft begins"
            )
        conn.execute(
            """
            UPDATE mug_collection_launches
            SET current_step = 'artwork', updated_at = CURRENT_TIMESTAMP
            WHERE mug_collection_id = (
                SELECT id FROM mug_collections WHERE UPPER(code) = UPPER(?)
            )
            """,
            ((collection_code or "").strip(),),
        )
        conn.commit()


def set_mug_collection_launch_printify_state(
    collection_code, item_id, printify_state, error_message=None
):
    allowed = {
        "waiting", "draft_created", "placement_reviewed", "failed",
        "outcome_unknown",
    }
    normalized_state = (printify_state or "").strip().lower()
    if normalized_state not in allowed:
        raise ValueError("Choose a valid Printify launch state")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET printify_state = ?,
                placement_state = CASE
                    WHEN ? = 'draft_created' THEN 'needs_review'
                    ELSE placement_state
                END,
                error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND artwork_state = 'approved' AND launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            )
            """,
            (
                normalized_state,
                normalized_state,
                (error_message or "").strip() or None,
                int(item_id),
                (collection_code or "").strip(),
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Approved launch artwork not found")
        conn.commit()


def set_mug_collection_launch_mockup_state(
    collection_code, item_id, *, placement_state=None, mockup_state=None,
    error_message=None
):
    allowed_placement = {"needs_review", "reviewed"}
    allowed_mockup = {"waiting", "needs_review", "approved"}
    if placement_state not in allowed_placement:
        raise ValueError("Choose a valid placement state")
    if mockup_state not in allowed_mockup:
        raise ValueError("Choose a valid mockup state")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET placement_state = ?, mockup_state = ?, error_message = ?,
                printify_state = CASE
                    WHEN ? = 'approved' THEN 'placement_reviewed'
                    ELSE printify_state
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND printify_state = 'draft_created' AND launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            )
            """,
            (
                placement_state, mockup_state,
                (error_message or "").strip() or None,
                mockup_state, int(item_id), (collection_code or "").strip(),
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("The active Printify draft was not found")
        if mockup_state == "approved":
            remaining = conn.execute(
                """
                SELECT COUNT(*) FROM mug_collection_launch_items
                WHERE launch_id = (
                    SELECT l.id FROM mug_collection_launches l
                    JOIN mug_collections c ON c.id = l.mug_collection_id
                    WHERE UPPER(c.code) = UPPER(?)
                ) AND mockup_state != 'approved'
                """,
                ((collection_code or "").strip(),),
            ).fetchone()[0]
            if remaining == 0:
                conn.execute(
                    """
                    UPDATE mug_collection_launches
                    SET current_step = 'listings', updated_at = CURRENT_TIMESTAMP
                    WHERE mug_collection_id = (
                        SELECT id FROM mug_collections
                        WHERE UPPER(code) = UPPER(?)
                    )
                    """,
                    ((collection_code or "").strip(),),
                )
        conn.commit()


def approve_mug_collection_launch_listing(
    collection_code, item_id, *, title, description, tags, price_cents
):
    normalized_title = (title or "").strip()
    normalized_description = (description or "").strip()
    normalized_tags = (tags or "").strip()
    normalized_price = int(price_cents)
    if not normalized_title:
        raise ValueError("Enter the Etsy title")
    if not normalized_description:
        raise ValueError("Enter the Etsy description")
    if normalized_price < 100:
        raise ValueError("Enter a valid mug price")
    with get_connection() as conn:
        item = conn.execute(
            """
            SELECT i.standalone_design_id
            FROM mug_collection_launch_items i
            JOIN mug_collection_launches l ON l.id = i.launch_id
            JOIN mug_collections c ON c.id = l.mug_collection_id
            WHERE i.id = ? AND UPPER(c.code) = UPPER(?)
              AND i.mockup_state = 'approved'
            """,
            (int(item_id), (collection_code or "").strip()),
        ).fetchone()
        if item is None or not item["standalone_design_id"]:
            raise ValueError("Approve the Printify mug image first")
        design_id = int(item["standalone_design_id"])
        conn.execute(
            """
            UPDATE standalone_design_products
            SET title = ?, description = ?, price_cents = ?,
                external_state = CASE
                    WHEN printify_product_id IS NOT NULL THEN 'needs_update'
                    ELSE external_state
                END,
                external_message = CASE
                    WHEN printify_product_id IS NOT NULL
                    THEN 'Approved listing copy is ready to update in Printify.'
                    ELSE external_message
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE design_id = ? AND product_type = 'mug_11oz_black_accent'
            """,
            (
                normalized_title, normalized_description, normalized_price,
                design_id,
            ),
        )
        conn.execute(
            """
            UPDATE standalone_designs
            SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (normalized_tags, design_id),
        )
        conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET listing_state = 'approved', error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(item_id),),
        )
        remaining = conn.execute(
            """
            SELECT COUNT(*) FROM mug_collection_launch_items
            WHERE launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            ) AND listing_state != 'approved'
            """,
            ((collection_code or "").strip(),),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute(
                """
                UPDATE mug_collection_launches
                SET current_step = 'publish', updated_at = CURRENT_TIMESTAMP
                WHERE mug_collection_id = (
                    SELECT id FROM mug_collections WHERE UPPER(code) = UPPER(?)
                )
                """,
                ((collection_code or "").strip(),),
            )
        else:
            conn.execute(
                """
                UPDATE mug_collection_launches
                SET current_step = 'listings', updated_at = CURRENT_TIMESTAMP
                WHERE mug_collection_id = (
                    SELECT id FROM mug_collections WHERE UPPER(code) = UPPER(?)
                )
                """,
                ((collection_code or "").strip(),),
            )
        conn.commit()


def set_mug_collection_launch_publish_state(
    collection_code, item_id, publish_state, error_message=None
):
    allowed = {
        "waiting", "publish_requested", "waiting_for_etsy", "verified",
        "failed", "outcome_unknown",
    }
    normalized_state = (publish_state or "").strip().lower()
    if normalized_state not in allowed:
        raise ValueError("Choose a valid publication state")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mug_collection_launch_items
            SET publish_state = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND listing_state = 'approved' AND launch_id = (
                SELECT l.id FROM mug_collection_launches l
                JOIN mug_collections c ON c.id = l.mug_collection_id
                WHERE UPPER(c.code) = UPPER(?)
            )
            """,
            (
                normalized_state, (error_message or "").strip() or None,
                int(item_id), (collection_code or "").strip(),
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Approved launch listing not found")
        if normalized_state == "verified":
            remaining = conn.execute(
                """
                SELECT COUNT(*) FROM mug_collection_launch_items
                WHERE launch_id = (
                    SELECT l.id FROM mug_collection_launches l
                    JOIN mug_collections c ON c.id = l.mug_collection_id
                    WHERE UPPER(c.code) = UPPER(?)
                ) AND publish_state != 'verified'
                """,
                ((collection_code or "").strip(),),
            ).fetchone()[0]
            if remaining == 0:
                conn.execute(
                    """
                    UPDATE mug_collection_launches
                    SET status = 'published', current_step = 'complete',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE mug_collection_id = (
                        SELECT id FROM mug_collections
                        WHERE UPPER(code) = UPPER(?)
                    )
                    """,
                    ((collection_code or "").strip(),),
                )
        conn.commit()


def delete_mug_text_idea(idea_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE mug_text_ideas SET deleted_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (idea_id,),
        )
        conn.commit()


def rate_mug_text_idea(idea_id, rating):
    normalized_rating = int(rating)
    if normalized_rating < 0 or normalized_rating > 5:
        raise ValueError("Rating must be between zero and five stars")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE mug_text_ideas
            SET rating = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND deleted_at IS NULL
            """,
            (normalized_rating, idea_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Text idea not found")
        conn.commit()


def reorder_mug_text_ideas(idea_ids, collection_code=None):
    normalized_ids = [int(idea_id) for idea_id in idea_ids]
    with get_connection() as conn:
        if collection_code:
            existing_ids = {
                row[0] for row in conn.execute(
                    """
                    SELECT i.id FROM mug_text_ideas i
                    JOIN mug_collections c ON c.id = i.mug_collection_id
                    WHERE UPPER(c.code) = UPPER(?) AND i.deleted_at IS NULL
                    """,
                    ((collection_code or "").strip(),),
                )
            }
        else:
            existing_ids = {
                row[0] for row in conn.execute(
                    "SELECT id FROM mug_text_ideas WHERE deleted_at IS NULL"
                )
            }
        if len(normalized_ids) != len(existing_ids) or set(normalized_ids) != existing_ids:
            raise ValueError("The text idea list changed. Reload and try again")
        conn.executemany(
            """
            UPDATE mug_text_ideas
            SET display_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [(order, idea_id) for order, idea_id in enumerate(normalized_ids, start=1)],
        )
        conn.commit()
