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
        response = self.client.get("/?view=attention")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Production dashboard", response.text)
        self.assertIn("Listings with missing items", response.text)
        self.assertIn("Needs attention", response.text)
        self.assertIn("Unbound Poster", response.text)
        self.assertIn("Missing: Source artwork", response.text)
        self.assertIn('class="dashboard-listing-thumb"', response.text)
        self.assertIn("No image", response.text)
        self.assertIn('aria-label="Dashboard navigation"', response.text)
        self.assertIn('href="/collections"', response.text)
        self.assertNotIn("Start here", response.text)
        self.assertIn('href="/?view=attention"', response.text)
        self.assertIn('data-app-wait', response.text)
        self.assertIn('app-wait-spinner', response.text)

        dashboard_focus = self.client.get("/?view=attention")
        self.assertIn("Listings with missing items", dashboard_focus.text)
        self.assertIn("Unbound Poster", dashboard_focus.text)
        self.assertIn('href="/?view=artworks"', dashboard_focus.text)

        self._complete_artwork_files()
        listings_dashboard = self.client.get("/?view=listings")
        self.assertIn(
            'src="/artworks/CEL-001/files/view?role=source"',
            listings_dashboard.text,
        )
        self.assertIn('alt="Unbound thumbnail"', listings_dashboard.text)

        default_dashboard = self.client.get("/")
        self.assertIn("Recently updated artwork", default_dashboard.text)
        self.assertIn('dashboard-metric-link is-selected', default_dashboard.text)

        focused = self.client.get("/listings?view=attention")
        self.assertEqual(focused.status_code, 200)
        self.assertIn("Listings that need attention", focused.text)
        self.assertIn("Unbound Poster", focused.text)
        self.assertIn('href="/?view=attention"', focused.text)
        self.assertIn("Back to dashboard", focused.text)

    def test_collections_filter_keeps_collection_cards_and_updates_artwork_panel(self):
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE collections SET target_artwork_count=3 WHERE code='CEL'"
            )
            collection_id = connection.execute(
                "SELECT id FROM collections WHERE code='CEL'"
            ).fetchone()["id"]
            connection.execute(
                "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) VALUES ('CEL-099', ?, 99, 'Retired Test', 'retired')",
                (collection_id,),
            )
            connection.commit()

        default_response = self.client.get("/collections")
        self.assertIn('href="/collections?collection=CEL"', default_response.text)
        self.assertIn('aria-current="true"', default_response.text)
        self.assertIn("Celebration artwork", default_response.text)
        self.assertNotIn("Your latest active artwork across all collections", default_response.text)
        self.assertIn('data-bs-target="#new-collection-modal"', default_response.text)
        self.assertIn('id="new-collection-modal"', default_response.text)

        response = self.client.get("/collections?collection=CEL")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/collections?collection=CEL"', response.text)
        self.assertIn('aria-current="true"', response.text)
        self.assertIn("Viewing artwork below", response.text)
        self.assertIn("Celebration artwork", response.text)
        self.assertIn("Unbound", response.text)
        self.assertIn('class="collection-gallery', response.text)
        self.assertIn('data-collection-gallery', response.text)
        self.assertIn('data-gallery-next', response.text)
        self.assertIn('data-bs-target="#edit-collection-modal"', response.text)
        self.assertIn('data-bs-target="#new-artwork-modal"', response.text)
        self.assertIn('id="edit-collection-modal"', response.text)
        self.assertIn('id="new-artwork-modal"', response.text)
        self.assertNotIn("Open collection", response.text)
        self.assertEqual(response.text.count("collection-empty-artwork-card"), 2)
        self.assertIn("Empty artwork slot", response.text)
        self.assertIn("CEL-003", response.text)
        artwork_grid = response.text[response.text.index('class="row g-3 dashboard-recent-grid"'):]
        self.assertLess(artwork_grid.index("CEL-001"), artwork_grid.index("CEL-003"))
        self.assertIn('data-artwork-context-menu', response.text)
        self.assertIn("Show retired (1)", response.text)
        self.assertNotIn("Retired Test", response.text)

        with_retired = self.client.get(
            "/collections?collection=CEL&show_retired=true"
        )
        self.assertEqual(with_retired.status_code, 200)
        self.assertIn("Hide retired (1)", with_retired.text)
        self.assertIn("Retired Test", with_retired.text)
        self.assertEqual(
            with_retired.text.count("collection-empty-artwork-card"), 2
        )

        with db.get_connection() as connection:
            collection_id = connection.execute("SELECT id FROM collections WHERE code='CEL'").fetchone()["id"]
            connection.executemany(
                "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) VALUES (?, ?, ?, ?, 'approved')",
                [("CEL-010", collection_id, 2, "Ten",), ("CEL-002", collection_id, 10, "Two",)],
            )
            connection.execute(
                "INSERT INTO artwork_production (artwork_id) SELECT id FROM artworks WHERE artwork_code IN ('CEL-002', 'CEL-010')"
            )
            connection.commit()
        ordered = self.client.get("/collections?collection=CEL").text
        gallery = ordered[ordered.index('data-collection-gallery'):ordered.index('</section>', ordered.index('data-collection-gallery'))]
        self.assertLess(gallery.index("CEL-001"), gallery.index("CEL-002"))
        self.assertLess(gallery.index("CEL-002"), gallery.index("CEL-010"))

        status_change = self.client.post(
            "/artworks/CEL-001/status",
            data={"status": "paused", "return_to": "/collections?collection=CEL"},
            follow_redirects=False,
        )
        self.assertEqual(status_change.status_code, 303)
        self.assertEqual(
            status_change.headers["location"], "/collections?collection=CEL"
        )
        with db.get_connection() as connection:
            changed_status = connection.execute(
                "SELECT status FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["status"]
        self.assertEqual(changed_status, "paused")

        unsafe_return = self.client.post(
            "/artworks/CEL-001/status",
            data={"status": "approved", "return_to": "https://example.com"},
            follow_redirects=False,
        )
        self.assertEqual(unsafe_return.headers["location"], "/collections")

        missing = self.client.get("/collections?collection=MISSING")
        self.assertEqual(missing.status_code, 404)

        collection_page = self.client.get("/collections/CEL")
        self.assertIn('href="/collections?collection=CEL"', collection_page.text)
        self.assertIn("All collections", collection_page.text)

        new_collection = self.client.get("/collections/new")
        self.assertIn('href="/collections"', new_collection.text)
        self.assertIn("Back to collections", new_collection.text)

        recent = self.client.get("/recent")
        self.assertEqual(recent.status_code, 200)
        self.assertIn("Recently updated", recent.text)
        self.assertIn('href="/recent" class="is-active"', recent.text)
        self.assertIn("Unbound", recent.text)

    def test_dashboard_shows_ready_to_publish(self):
        self._complete_artwork_files()
        db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Complete Unbound", description="Description", tags="one, two",
            price_cents=3995, status="ready",
        )
        response = self.client.get("/?view=ready")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ready to publish", response.text)
        self.assertIn("Complete Unbound", response.text)
        self.assertIn('href="/?view=ready"', response.text)

        dashboard_focus = self.client.get("/?view=ready")
        self.assertIn("Completed listings awaiting publication", dashboard_focus.text)
        self.assertIn("Complete Unbound", dashboard_focus.text)

        focused = self.client.get("/listings?view=ready")
        self.assertEqual(focused.status_code, 200)
        self.assertIn("Showing complete listings", focused.text)
        self.assertIn("Complete Unbound", focused.text)
        self.assertIn('href="/?view=ready"', focused.text)

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
            "Artwork details",
            "Source artwork",
            "Print production",
            "Listing images",
            "Listing &amp; SEO",
            "Printify product",
            "Etsy publishing",
        ]
        positions = [artwork_page.text.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('aria-label="Artwork workflow steps"', artwork_page.text)
        sidebar_end = artwork_page.text.index("</aside>")
        self.assertNotIn('data-workflow-link=', artwork_page.text[:sidebar_end])
        for stage in ("details", "source", "print", "mockups", "listing"):
            self.assertIn(f'data-workflow-stage="{stage}"', artwork_page.text)
        self.assertIn('data-bs-target="#prepare-artwork-modal"', artwork_page.text)
        self.assertIn('id="prepare-artwork-modal"', artwork_page.text)
        self.assertIn("Prepare automatically", artwork_page.text)
        self.assertIn("artwork-automation-button", artwork_page.text)
        self.assertIn('data-long-operation', artwork_page.text)
        self.assertIn("Do not publish to Printify or Etsy", artwork_page.text)

        missing_source = self.client.post(
            "/artworks/CEL-001/prepare",
            data={"price": "25.00", "confirmed": "true"},
        )
        self.assertEqual(missing_source.status_code, 400)
        self.assertIn("Upload source artwork first", missing_source.json()["detail"])

        unconfirmed = self.client.post(
            "/artworks/CEL-001/prepare",
            data={"price": "25.00"},
        )
        self.assertEqual(unconfirmed.status_code, 400)
        self.assertIn("Confirm automatic preparation", unconfirmed.json()["detail"])

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
