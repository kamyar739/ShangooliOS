import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app import database
from web import db
from web.app import app
from web.collection_replacement import (
    restart_collection_with_replacement_sources,
)


class CollectionReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.root / "test.db"
        connection = sqlite3.connect(db.DATABASE_PATH)
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO brands (code, name) VALUES ('SHG', 'ShangooliShop')"
        )
        brand_id = connection.execute(
            "SELECT id FROM brands WHERE code='SHG'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO collections (
                brand_id, code, name, collection_type, vertical, status
            ) VALUES (?, 'REM', 'Remembered', 'curated', 'art', 'active')
            """,
            (brand_id,),
        )
        collection_id = connection.execute(
            "SELECT id FROM collections WHERE code='REM'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO artworks (
                artwork_code, collection_id, sequence_number, public_title,
                description, prompt, status
            ) VALUES ('REM-001', ?, 1, 'Arcade', 'Kept description',
                      'Kept prompt', 'listed')
            """,
            (collection_id,),
        )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.workspace = self.root / "REM-001 Arcade"
        source_dir = self.workspace / "01 Source Artwork"
        source_dir.mkdir(parents=True)
        Image.new("RGB", (120, 180), "gold").save(source_dir / "replacement.png")
        for folder_name in ("02 Print Files", "03 Mockups"):
            folder = self.workspace / folder_name
            folder.mkdir()
            (folder / "old.png").write_bytes(b"old")
        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='REM-001'"
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO artwork_files
                    (artwork_id, role, relative_path, stored_filename, original_filename)
                VALUES (?, 'source', '01 Source Artwork/replacement.png',
                        'replacement.png', 'replacement.png')
                """,
                (artwork_id,),
            )
            for role, path in (
                ("print_master", "02 Print Files/old.png"),
                ("ratio:2:3", "02 Print Files/old.png"),
                ("mockup:hero", "03 Mockups/old.png"),
            ):
                connection.execute(
                    """
                    INSERT INTO artwork_files
                        (artwork_id, role, relative_path, stored_filename, original_filename)
                    VALUES (?, ?, ?, 'old.png', 'old.png')
                    """,
                    (artwork_id, role, path),
                )
            connection.execute(
                """
                INSERT INTO listings (
                    artwork_id, title, description, tags, price_cents, status,
                    printify_product_id, external_listing_id
                ) VALUES (?, 'Kept title', 'Kept listing description',
                          'kept, tags', 2900, 'published', 'printify-old', 'etsy-old')
                """,
                (artwork_id,),
            )
            connection.commit()

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temporary.cleanup()

    def _folder(self, _artwork):
        return self.workspace

    def test_restart_archives_external_identity_and_preserves_copy_price_files(self):
        with patch(
            "web.collection_replacement.get_artwork_folder",
            side_effect=self._folder,
        ):
            result = restart_collection_with_replacement_sources(
                "REM", sources_confirmed=True, archive_confirmed=True
            )

        listings = list(db.get_artwork_listings("REM-001"))
        current = next(row for row in listings if row["status"] != "archived")
        archived = next(row for row in listings if row["status"] == "archived")
        self.assertEqual(current["title"], "Kept title")
        self.assertEqual(current["description"], "Kept listing description")
        self.assertEqual(current["tags"], "kept, tags")
        self.assertEqual(current["price_cents"], 2900)
        self.assertIsNone(current["printify_product_id"])
        self.assertIsNone(current["external_listing_id"])
        self.assertEqual(archived["printify_product_id"], "printify-old")
        self.assertEqual(archived["external_listing_id"], "etsy-old")

        roles = {
            row["role"] for row in db.get_artwork_file_assignments("REM-001")
        }
        self.assertEqual(roles, {"source"})
        self.assertTrue(
            list((self.workspace / "99 Archive").rglob("02 Print Files/old.png"))
        )
        self.assertTrue(
            list((self.workspace / "99 Archive").rglob("03 Mockups/old.png"))
        )
        self.assertTrue((self.workspace / "01 Source Artwork/replacement.png").is_file())
        self.assertTrue((self.workspace / "02 Print Files").is_dir())
        self.assertTrue((self.workspace / "03 Mockups").is_dir())
        self.assertEqual(len(result["items"]), 1)

    def test_confirmation_is_required_and_changes_nothing(self):
        before = [dict(row) for row in db.get_artwork_listings("REM-001")]
        with self.assertRaisesRegex(ValueError, "Confirm"):
            restart_collection_with_replacement_sources(
                "REM", sources_confirmed=False, archive_confirmed=True
            )
        self.assertEqual(
            before, [dict(row) for row in db.get_artwork_listings("REM-001")]
        )
        self.assertTrue((self.workspace / "02 Print Files/old.png").is_file())

    def test_review_page_performs_no_mutation(self):
        client = TestClient(app)
        with patch(
            "web.collection_replacement.get_artwork_folder",
            side_effect=self._folder,
        ):
            response = client.get("/collections/REM/replacement-restart")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Restart Production", response.text)
        self.assertEqual(len(db.get_artwork_listings("REM-001")), 1)
        self.assertTrue((self.workspace / "02 Print Files/old.png").is_file())


if __name__ == "__main__":
    unittest.main()
