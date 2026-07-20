import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import database
from web import db
from web.app import app


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.original_db_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO brands (code, name) VALUES ('SHG', 'ShangooliShop')")
        brand_id = connection.execute("SELECT id FROM brands WHERE code='SHG'").fetchone()["id"]
        connection.execute(
            "INSERT INTO collections (brand_id, code, name, collection_type, vertical, status) VALUES (?, 'CEL', 'Celebration', 'curated', 'home_art', 'active')",
            (brand_id,),
        )
        collection_id = connection.execute("SELECT id FROM collections WHERE code='CEL'").fetchone()["id"]
        connection.execute(
            "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) VALUES ('CEL-001', ?, 1, 'Unbound', 'approved')",
            (collection_id,),
        )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.client = TestClient(app)

    def tearDown(self):
        db.DATABASE_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _complete_artwork_files(self):
        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["id"]
            connection.executemany(
                "INSERT INTO artwork_files (artwork_id, role, relative_path, stored_filename, original_filename) VALUES (?, ?, ?, ?, ?)",
                [
                    (artwork_id, "source", "source.png", "source.png", "source.png"),
                    (artwork_id, "print_master", "master.png", "master.png", "master.png"),
                ],
            )
            connection.execute(
                "UPDATE artwork_production SET print_master_ready=1, ratio_exports_ready=1, mockups_ready=1 WHERE artwork_id=?",
                (artwork_id,),
            )
            connection.commit()

    def test_dashboard_shows_listing_work_queue(self):
        db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="", tags="",
            price_cents=0, status="draft",
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Production dashboard", response.text)
        self.assertIn("Listing work queue", response.text)
        self.assertIn("Needs attention", response.text)
        self.assertIn("Unbound Poster", response.text)
        self.assertIn("Missing: Source artwork", response.text)
        self.assertIn('aria-label="Dashboard navigation"', response.text)
        self.assertIn('href="/collections/CEL"', response.text)

    def test_dashboard_shows_ready_to_publish(self):
        self._complete_artwork_files()
        db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Complete Unbound", description="Description", tags="one, two",
            price_cents=3995, status="ready",
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ready to publish", response.text)
        self.assertIn("Complete Unbound", response.text)
        self.assertIn("Nothing needs attention", response.text)

    def test_certified_master_locks_production_orientation(self):
        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO print_master_certification (
                    artwork_id, valid, width, height, orientation,
                    master_ratio, required_ratios
                ) VALUES (?, 1, 4000, 6000, 'vertical', '2:3',
                          '2:3, 3:4, 4:5, 11:14')
                """,
                (artwork_id,),
            )
            connection.commit()

        page = self.client.get("/artworks/CEL-001")
        self.assertIn('value="vertical" readonly', page.text)
        self.assertIn("Locked by the certified print-ready file", page.text)

        response = self.client.post(
            "/artworks/CEL-001/production",
            data={"orientation": "horizontal"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("locked to vertical", response.json()["detail"])

    def test_collection_and_artwork_pages_show_guided_workflow(self):
        collection_page = self.client.get("/collections/CEL")
        self.assertEqual(collection_page.status_code, 200)
        self.assertIn('aria-label="Collection workflow"', collection_page.text)
        self.assertIn("CEL-001", collection_page.text)

        artwork_page = self.client.get("/artworks/CEL-001")
        self.assertEqual(artwork_page.status_code, 200)
        self.assertIn(
            'aria-label="Collection and artwork workflow"', artwork_page.text
        )
        labels = [
            "1. Artwork details",
            "2. Source artwork",
            "3. Print production",
            "4. Listing images",
            "5. Listing &amp; SEO",
            "6. Printify product",
            "7. Etsy publishing",
        ]
        positions = [artwork_page.text.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        for stage in ("details", "source", "print", "mockups", "listing"):
            self.assertIn(f'data-workflow-stage="{stage}"', artwork_page.text)

    def test_collection_order_is_saved_and_used_by_dashboard(self):
        with db.get_connection() as connection:
            brand_id = connection.execute(
                "SELECT id FROM brands WHERE code='SHG'"
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO collections (
                    brand_id, code, name, collection_type, vertical, status
                ) VALUES (?, 'DEN', 'Dental Collection', 'curated',
                          'home_art', 'active')
                """,
                (brand_id,),
            )
            connection.commit()

        response = self.client.post(
            "/collections/order", json={"codes": ["CEL", "DEN"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["saved"])

        page = self.client.get("/collections")
        cel_position = page.text.index('data-collection-code="CEL"')
        den_position = page.text.index('data-collection-code="DEN"')
        self.assertLess(cel_position, den_position)
        self.assertIn("Drag collections to reorder", page.text)


if __name__ == "__main__":
    unittest.main()
