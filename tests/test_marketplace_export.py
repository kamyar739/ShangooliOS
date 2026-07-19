import json
import sqlite3
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from web import db
from web.app import app
from web.marketplace_export import build_listing_export


class MarketplaceExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / "test.db"
        self.workspace = self.root / "CEL-001 Unbound"
        self.original_db_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO brands (code, name) VALUES ('SHG', 'ShangooliShop')")
        brand_id = connection.execute("SELECT id FROM brands").fetchone()["id"]
        connection.execute(
            """
            INSERT INTO collections (
                brand_id, code, name, collection_type, vertical, status
            ) VALUES (?, 'CEL', 'Celebration', 'curated', 'home_art', 'active')
            """,
            (brand_id,),
        )
        collection_id = connection.execute("SELECT id FROM collections").fetchone()["id"]
        connection.execute(
            "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) VALUES ('CEL-001', ?, 1, 'Unbound', 'approved')",
            (collection_id,),
        )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Wall Art", description="A joyful abstract artwork.",
            tags="abstract art, joyful art", price_cents=4200, status="ready",
        )
        self._complete_readiness()
        mockups = self.workspace / "03 Mockups"
        mockups.mkdir(parents=True)
        (mockups / "CEL-001_listing_room_style.jpg").write_bytes(b"room")
        (mockups / "CEL-001_listing_hero_style.jpg").write_bytes(b"hero")
        self.client = TestClient(app)

    def tearDown(self):
        db.DATABASE_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _complete_readiness(self):
        with db.get_connection() as connection:
            artwork_id = connection.execute("SELECT id FROM artworks").fetchone()["id"]
            connection.executemany(
                "INSERT INTO artwork_files (artwork_id, role, relative_path, stored_filename) VALUES (?, ?, ?, ?)",
                [
                    (artwork_id, "source", "source.png", "source.png"),
                    (artwork_id, "print_master", "master.png", "master.png"),
                ],
            )
            connection.execute(
                "UPDATE artwork_production SET ratio_exports_ready=1, mockups_ready=1 WHERE artwork_id=?",
                (artwork_id,),
            )
            connection.commit()

    @patch("web.marketplace_export.get_artwork_folder")
    def test_package_contains_copy_manifest_checklist_and_ordered_images(self, folder):
        folder.return_value = self.workspace
        listing = db.get_listing(self.listing_id)
        result = build_listing_export(listing, db.get_listing_readiness(self.listing_id))

        self.assertTrue(result["path"].is_file())
        with zipfile.ZipFile(result["path"]) as archive:
            names = archive.namelist()
            self.assertEqual(names[:3], ["listing.txt", "listing.json", "publish-checklist.txt"])
            self.assertIn("images/01_CEL-001_listing_hero_style.jpg", names)
            self.assertIn("images/02_CEL-001_listing_room_style.jpg", names)
            manifest = json.loads(archive.read("listing.json"))
            self.assertEqual(manifest["listing"]["price_usd"], "42.00")
            self.assertEqual(manifest["listing"]["tags"], ["abstract art", "joyful art"])

    @patch("web.marketplace_export.get_artwork_folder")
    def test_export_route_downloads_zip(self, folder):
        folder.return_value = self.workspace
        response = self.client.post(f"/listings/{self.listing_id}/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            self.assertIn("listing.txt", archive.namelist())

    @patch("web.app.inspect_listing_export")
    def test_listing_page_shows_export_action(self, inspect_export):
        inspect_export.return_value = {
            "ready": True, "blockers": [], "image_count": 2,
            "images": [], "export_folder": self.workspace / "04 Exports",
        }
        response = self.client.get(f"/listings/{self.listing_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Marketplace package", response.text)
        self.assertIn("Download export package", response.text)

    @patch("web.marketplace_export.get_artwork_folder")
    def test_export_rejects_incomplete_listing(self, folder):
        folder.return_value = self.workspace
        db.update_listing(
            self.listing_id, marketplace="Etsy", product="Poster", title="Unbound",
            description="", tags="", price_cents=0, status="draft",
        )
        response = self.client.post(f"/listings/{self.listing_id}/export")
        self.assertEqual(response.status_code, 400)
        self.assertIn("publishing checklist", response.text)


if __name__ == "__main__":
    unittest.main()
