import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import database
from web import db
from web.app import app


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.original_db_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO brands (code, name) VALUES ('SHG', 'ShangooliShop')"
        )
        brand_id = connection.execute(
            "SELECT id FROM brands WHERE code='SHG'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO collections (
                brand_id, code, name, collection_type, vertical, status
            ) VALUES (?, 'CEL', 'Celebration', 'curated', 'home_art', 'active')
            """,
            (brand_id,),
        )
        collection_id = connection.execute(
            "SELECT id FROM collections WHERE code='CEL'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO artworks (
                artwork_code, collection_id, sequence_number, public_title, status
            ) VALUES ('CEL-001', ?, 1, 'Unbound', 'approved')
            """,
            (collection_id,),
        )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.client = TestClient(app)

    def tearDown(self):
        db.DATABASE_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_listing_crud(self):
        listing_id = db.create_listing(
            "CEL-001",
            marketplace="Etsy",
            product="Poster",
            title="Unbound Wall Art",
            description="A joyful abstract artwork.",
            tags="abstract art, joyful art",
            price_cents=4200,
            status="draft",
        )

        listing = db.get_listing(listing_id)
        self.assertEqual(listing["title"], "Unbound Wall Art")
        self.assertEqual(listing["price_cents"], 4200)

        db.update_listing(
            listing_id,
            marketplace="Etsy",
            product="Matte Poster",
            title="Unbound Abstract Wall Art",
            description="Updated description.",
            tags="abstract wall art",
            price_cents=4800,
            status="ready",
        )
        updated = db.get_listing(listing_id)
        self.assertEqual(updated["product"], "Matte Poster")
        self.assertEqual(updated["status"], "ready")
        self.assertEqual(updated["price_cents"], 4800)

        db.delete_listing(listing_id)
        self.assertIsNone(db.get_listing(listing_id))

    def test_listing_pages_and_form_submission(self):
        response = self.client.get("/artworks/CEL-001/listings/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Create listing", response.text)

        response = self.client.post(
            "/artworks/CEL-001/listings/new",
            data={
                "marketplace": "Etsy",
                "product": "Poster",
                "title": "Unbound Poster",
                "description": "Description",
                "tags": "one, two",
                "price": "39.95",
                "listing_status": "draft",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/listings/"))

        listings = db.list_listings()
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["price_cents"], 3995)

        index_response = self.client.get("/listings")
        self.assertEqual(index_response.status_code, 200)
        self.assertIn("Unbound Poster", index_response.text)

    def test_negative_price_is_rejected(self):
        response = self.client.post(
            "/artworks/CEL-001/listings/new",
            data={
                "marketplace": "Etsy",
                "product": "Poster",
                "title": "Bad Price",
                "price": "-1.00",
                "listing_status": "draft",
            },
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()


class ListingManagementTests(ListingTests):
    def test_status_filter_counts_and_duplicate(self):
        draft_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Draft Listing", description="Draft description",
            tags="draft", price_cents=2500, status="draft",
        )
        db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Published Listing", description="Published description",
            tags="published", price_cents=4500, status="published",
        )

        filtered = self.client.get("/listings?status=published")
        self.assertEqual(filtered.status_code, 200)
        self.assertIn("Published Listing", filtered.text)
        self.assertNotIn("Draft Listing</a>", filtered.text)
        self.assertIn("Published <span>1</span>", filtered.text)
        self.assertIn("All <span>2</span>", filtered.text)

        response = self.client.post(
            f"/listings/{draft_id}/duplicate", follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("duplicated=1", response.headers["location"])

        listings = db.list_listings("draft")
        self.assertEqual(len(listings), 2)
        copy = next(item for item in listings if item["id"] != draft_id)
        self.assertEqual(copy["title"], "Draft Listing Copy")
        self.assertEqual(copy["price_cents"], 2500)
        self.assertEqual(copy["status"], "draft")

    def test_invalid_status_filter_is_rejected(self):
        response = self.client.get("/listings?status=unknown")
        self.assertEqual(response.status_code, 400)

class ListingReadinessTests(ListingTests):
    def test_readiness_reports_missing_and_complete_items(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="draft",
        )

        readiness = db.get_listing_readiness(listing_id)
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["remaining"], 4)
        missing = {item["key"] for item in readiness["items"] if not item["passed"]}
        self.assertEqual(missing, {"source", "print_master", "ratios", "mockups"})

        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["id"]
            connection.executemany(
                """
                INSERT INTO artwork_files (
                    artwork_id, role, relative_path, stored_filename, original_filename
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (artwork_id, "source", "source.png", "source.png", "source.png"),
                    (artwork_id, "print_master", "master.png", "master.png", "master.png"),
                ],
            )
            connection.execute(
                """
                UPDATE artwork_production
                SET print_master_ready=1, ratio_exports_ready=1, mockups_ready=1
                WHERE artwork_id=?
                """,
                (artwork_id,),
            )
            connection.commit()

        readiness = db.get_listing_readiness(listing_id)
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["remaining"], 0)

    def test_listing_page_shows_readiness_checklist(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="", tags="",
            price_cents=0, status="draft",
        )
        response = self.client.get(f"/listings/{listing_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Listing readiness", response.text)
        self.assertIn("7 items remaining", response.text)
        self.assertIn("Source artwork", response.text)
        self.assertIn("Price", response.text)

class ListingVisualReadinessTests(ListingTests):
    def test_readiness_includes_percentage(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="draft",
        )
        readiness = db.get_listing_readiness(listing_id)
        self.assertEqual(readiness["completed"], 4)
        self.assertEqual(readiness["percentage"], 50)

    def test_listings_page_shows_visual_readiness(self):
        db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="draft",
        )
        response = self.client.get("/listings")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Readiness", response.text)
        self.assertIn("50%", response.text)
        self.assertIn("4/8", response.text)
        self.assertIn("listing-readiness-track", response.text)

    def test_listing_page_shows_progress_bar(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="draft",
        )
        response = self.client.get(f"/listings/{listing_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-valuenow="50"', response.text)
        self.assertIn("readiness-progress-fill", response.text)
