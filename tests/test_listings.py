import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import database
from web import db
from web.app import app


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.printify_env_patch = patch(
            "web.printify_api.LOCAL_ENV_PATH", Path(self.temp_dir.name) / ".env"
        )
        self.printify_env_patch.start()
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
        from web.printify_api import clear_printify_runtime
        clear_printify_runtime()
        self.printify_env_patch.stop()
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
        self.assertNotIn('<option value="published"', response.text)

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
        self.assertIn("listing-summary-thumb", index_response.text)
        self.assertIn("No image", index_response.text)

    def test_listings_filter_by_collection_and_sort_by_artwork_number(self):
        with db.get_connection() as connection:
            cel_id = connection.execute(
                "SELECT id FROM collections WHERE code='CEL'"
            ).fetchone()["id"]
            brand_id = connection.execute(
                "SELECT id FROM brands WHERE code='SHG'"
            ).fetchone()["id"]
            connection.execute(
                "INSERT INTO collections (brand_id, code, name, collection_type, vertical, status) "
                "VALUES (?, 'ALT', 'Alternate', 'curated', 'home_art', 'active')",
                (brand_id,),
            )
            alt_id = connection.execute(
                "SELECT id FROM collections WHERE code='ALT'"
            ).fetchone()["id"]
            connection.executemany(
                "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) "
                "VALUES (?, ?, ?, ?, 'approved')",
                [
                    ("CEL-009", cel_id, 9, "Gathering"),
                    ("CEL-002", cel_id, 2, "Interwoven"),
                    ("ALT-001", alt_id, 1, "Alternate One"),
                ],
            )
            connection.commit()
        for code, title in (
            ("CEL-009", "Gathering listing"),
            ("CEL-001", "Unbound listing"),
            ("CEL-002", "Interwoven listing"),
            ("ALT-001", "Alternate listing"),
        ):
            db.create_listing(
                code, marketplace="Etsy", product="Poster", title=title,
                description="Description", tags="one, two", price_cents=2500,
            )

        rows = db.list_listings(collection_code="CEL")
        self.assertEqual(
            [row["artwork_code"] for row in rows],
            ["CEL-001", "CEL-002", "CEL-009"],
        )
        response = self.client.get("/listings?collection=CEL")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Artwork number order", response.text)
        self.assertIn("Celebration", response.text)
        self.assertNotIn("Alternate listing", response.text)
        self.assertLess(response.text.index("Unbound listing"), response.text.index("Interwoven listing"))
        self.assertLess(response.text.index("Interwoven listing"), response.text.index("Gathering listing"))

    def test_listing_page_keeps_workflow_navigation(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="draft",
        )
        response = self.client.get(f"/listings/{listing_id}")
        self.assertEqual(response.status_code, 200)
        sidebar = response.text[:response.text.index("</aside>")]
        self.assertIn("Etsy connection", sidebar)
        self.assertNotIn('data-workflow-link=', sidebar)
        self.assertIn('id="printify"', response.text)
        self.assertIn('aria-label="Artwork workflow steps"', response.text)
        self.assertIn('data-workflow-link="listing"', response.text)
        self.assertIn('aria-current="step"', response.text)
        self.assertIn('href="/listings"', response.text)
        self.assertIn("Back to listings", response.text)
        self.assertIn('href="/artworks/CEL-001"', response.text)

    def test_listings_page_can_pause_and_reactivate_etsy_sales(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="published",
        )
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET external_listing_id='123456789', "
                "marketplace_url='https://www.etsy.com/listing/123456789/unbound' "
                "WHERE id=?",
                (listing_id,),
            )
            connection.commit()
        response = self.client.get("/listings")
        self.assertIn("Pause Etsy sales", response.text)
        self.assertNotIn("Paused on Etsy", response.text)

        response = self.client.post(
            f"/listings/{listing_id}/etsy/inventory/sold-out",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

        with patch("web.app.update_etsy_listing_state") as update:
            response = self.client.post(
                f"/listings/{listing_id}/etsy/inventory/sold-out",
                data={"confirmed": "true"}, follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        update.assert_called_once_with("123456789", "inactive")
        listing = db.get_listing(listing_id)
        self.assertIsNotNone(listing["etsy_paused_at"])
        self.assertEqual(listing["etsy_state"], "inactive")
        self.assertEqual(listing["status"], "ready")
        response = self.client.get("/listings")
        self.assertIn("Paused on Etsy ↗", response.text)
        self.assertIn("Reactivate on Etsy", response.text)
        for page in ("/?view=listings", "/collections/CEL"):
            page_response = self.client.get(page)
            self.assertEqual(page_response.status_code, 200)
            self.assertIn("Paused on Etsy", page_response.text)
        artwork_response = self.client.get("/artworks/CEL-001")
        self.assertEqual(artwork_response.status_code, 200)
        self.assertIn("Paused on Etsy ↗", artwork_response.text)
        detail_response = self.client.get(f"/listings/{listing_id}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("Paused on Etsy ↗", detail_response.text)

        with patch("web.app.update_etsy_listing_state") as reactivate:
            response = self.client.post(
                f"/listings/{listing_id}/etsy/inventory/restore",
                data={"confirmed": "true"}, follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        reactivate.assert_called_once_with("123456789", "active")
        listing = db.get_listing(listing_id)
        self.assertIsNone(listing["etsy_paused_at"])
        self.assertEqual(listing["etsy_state"], "active")
        self.assertEqual(listing["status"], "published")

    def test_etsy_pause_error_returns_to_listings_with_readable_message(self):
        from web.etsy_api import EtsyAPIError

        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="published",
        )
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET external_listing_id='123456789' WHERE id=?",
                (listing_id,),
            )
            connection.commit()
        with patch(
            "web.app.update_etsy_listing_state",
            side_effect=EtsyAPIError("Etsy is temporarily unavailable"),
        ):
            response = self.client.post(
                f"/listings/{listing_id}/etsy/inventory/sold-out",
                data={"confirmed": "true"}, follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("etsy_error=", response.headers["location"])

    def test_global_printify_connection_page_shows_status(self):
        from web.printify_api import configure_printify_runtime

        configure_printify_runtime("test-token", "24680")
        response = self.client.get("/printify/connect")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Printify connection", response.text)
        self.assertIn("24680", response.text)
        self.assertIn('href="/printify/connect" class="is-active"', response.text)

    def test_confirmed_etsy_state_controls_published_count(self):
        from web.db import record_etsy_state

        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Published on Etsy", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        record_etsy_state(listing_id, "active")
        self.assertEqual(db.get_listing(listing_id)["status"], "published")
        self.assertEqual(db.get_listing_status_counts()["published"], 1)
        self.assertEqual(db.get_artwork("CEL-001")["status"], "listed")
        with self.assertRaisesRegex(ValueError, "live on Etsy"):
            db.update_artwork_status("CEL-001", "approved")

        record_etsy_state(listing_id, "inactive")
        self.assertEqual(db.get_listing(listing_id)["status"], "ready")
        self.assertEqual(db.get_listing_status_counts()["published"], 0)

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
        self.assertIn("<strong>Live on Etsy</strong>", filtered.text)
        self.assertIn('<span class="filter-count">1</span>', filtered.text)
        self.assertIn("<strong>All</strong>", filtered.text)

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
    def _save_printify(self, listing_id):
        db.save_printify_product(
            listing_id,
            product_url="https://printify.com/app/products/example",
            product_id="printify-123",
            provider="Print Provider",
            sizes="8x10, 12x16",
            base_cost_cents=1200,
        )

    def _complete_listing_readiness(self):
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

    def test_publish_listing_records_etsy_details_and_timestamp(self):
        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        self._save_printify(listing_id)
        response = self.client.post(
            f"/listings/{listing_id}/publish",
            data={
                "marketplace_url": "https://www.etsy.com/listing/123456789/unbound",
                "external_listing_id": "123456789",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("published=1", response.headers["location"])
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["status"], "published")
        self.assertEqual(listing["external_listing_id"], "123456789")
        self.assertIsNotNone(listing["published_at"])
        self.assertEqual(db.get_artwork("CEL-001")["status"], "listed")

        page = self.client.get(f"/listings/{listing_id}")
        self.assertIn("Open Etsy listing", page.text)
        self.assertIn("https://www.etsy.com/listing/123456789/unbound", page.text)
        listing_index = self.client.get("/listings").text
        self.assertIn("Live on Etsy ↗", listing_index)
        self.assertNotIn(">Open Etsy</a>", listing_index)

    def test_marketplace_title_sync_updates_printify_etsy_and_local_listing(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster", title="Old title",
            description="Description", tags="one, two", price_cents=3995, status="published",
        )
        db.save_printify_product(
            listing_id, product_url="https://printify.com/product/abc",
            product_id="printify-123", provider="Provider", sizes="12x8", base_cost_cents=1000,
        )
        db.link_etsy_listing(listing_id, "123456789")
        api = MagicMock()
        with (
            patch("web.app.PrintifyAPI.from_env", return_value=api),
            patch("web.app.update_etsy_listing") as update_etsy,
        ):
            response = self.client.post(
                f"/listings/{listing_id}/title/sync",
                data={"title": "New marketplace title", "confirmed": "true"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(db.get_listing(listing_id)["title"], "New marketplace title")
        api.update_product.assert_called_once_with("printify-123", {"title": "New marketplace title"})
        self.assertEqual(update_etsy.call_args.kwargs["title"], "New marketplace title")

    def test_printify_product_can_be_saved_for_physical_listing(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        response = self.client.post(
            f"/listings/{listing_id}/printify",
            data={
                "product_url": "https://printify.com/app/products/example",
                "product_id": "printify-123",
                "provider": "Print Provider",
                "sizes": "8x10, 12x16",
                "base_cost": "12.00",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["printify_product_id"], "printify-123")
        self.assertEqual(listing["printify_base_cost_cents"], 1200)
        page = self.client.get(f"/listings/{listing_id}")
        self.assertIn("Open product in Printify", page.text)
        self.assertIn('target="_blank"', page.text)
        self.assertIn('rel="noopener noreferrer"', page.text)
        self.assertIn("https://printify.com/app/products/example", page.text)

    def test_listing_offers_automatic_printify_setup(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        response = self.client.get(f"/listings/{listing_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Set up with Printify API", response.text)
        self.assertIn("record an existing Printify product manually", response.text)

    @patch.dict("os.environ", {}, clear=True)
    def test_printify_setup_explains_missing_configuration(self):
        from web.printify_api import clear_printify_runtime
        clear_printify_runtime()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        response = self.client.get(f"/listings/{listing_id}/printify/create")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Printify API token", response.text)
        self.assertIn('type="password"', response.text)
        self.assertIn("Remember on this computer", response.text)
        self.assertIn("excluded from Git", response.text)

    @patch.dict("os.environ", {}, clear=True)
    def test_printify_token_then_shop_can_be_selected_in_app(self):
        from web.printify_api import clear_printify_runtime, PrintifyAPI
        clear_printify_runtime()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        response = self.client.post(
            f"/listings/{listing_id}/printify/connect-token",
            data={"api_token": "runtime-secret"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(PrintifyAPI.from_env())

        class ShopAPI:
            def list_shops(self):
                return [
                    {"id": 98765, "title": "My Etsy Shop", "sales_channel": "etsy"}
                ]

        with patch("web.app.PrintifyAPI.with_available_token", return_value=ShopAPI()):
            response = self.client.post(
                f"/listings/{listing_id}/printify/select-shop",
                data={"shop_id": "98765"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(PrintifyAPI.from_env().shop_id, "98765")
        clear_printify_runtime()

    def test_saved_printify_token_can_be_replaced_from_setup_page(self):
        from web.printify_api import PrintifyAPI, save_printify_local_config

        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        save_printify_local_config("old-secret", "98765")
        with patch("web.app.PrintifyAPI.list_blueprints", return_value=[]):
            response = self.client.get(f"/listings/{listing_id}/printify/create")
        self.assertIn("Replace API token", response.text)

        response = self.client.post(
            f"/listings/{listing_id}/printify/replace-token",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Printify API token", response.text)
        self.assertIsNone(PrintifyAPI.from_env())

    def test_api_created_printify_product_can_have_unknown_production_cost(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        db.save_printify_product(
            listing_id,
            product_url="https://printify.com/app/store/products/api-product-1",
            product_id="api-product-1",
            provider="Printify Choice",
            sizes='18\u2033 x 12\u2033 / Matte',
            base_cost_cents=None,
        )
        listing = db.get_listing(listing_id)
        self.assertIsNone(listing["printify_base_cost_cents"])

    def test_physical_listing_cannot_publish_without_printify_product(self):
        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        response = self.client.post(
            f"/listings/{listing_id}/publish",
            data={
                "marketplace_url": "https://www.etsy.com/listing/123456789/unbound",
                "external_listing_id": "123456789",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Printify product details", response.text)

    def test_printify_product_can_be_sent_to_connected_etsy_shop(self):
        class FakeAPI:
            def __init__(self):
                self.published_product_id = None

            def publish_product(self, product_id):
                self.published_product_id = product_id
                return {}

        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        self._save_printify(listing_id)
        fake_api = FakeAPI()
        with patch("web.app.PrintifyAPI.from_env", return_value=fake_api):
            response = self.client.post(
                f"/listings/{listing_id}/printify/publish",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake_api.published_product_id, "printify-123")
        self.assertIsNotNone(
            db.get_listing(listing_id)["printify_publish_requested_at"]
        )

        page = self.client.get(f"/listings/{listing_id}")
        self.assertIn("Sent to Etsy", page.text)
        self.assertIn("Finish reviewing the listing on Etsy", page.text)

    def test_recovery_waits_without_repeating_publish(self):
        class FakeAPI:
            def get_product(self, product_id):
                return {"id": product_id, "title": "Unbound Poster"}

        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        self._save_printify(listing_id)
        db.mark_printify_publish_requested(listing_id)
        with (
            patch("web.app.PrintifyAPI.from_env", return_value=FakeAPI()),
            patch("web.app.find_etsy_candidates", return_value=[]),
        ):
            response = self.client.post(
                f"/listings/{listing_id}/publishing/recover",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["publishing_recovery_stage"], "waiting_for_etsy")
        self.assertIn("has not returned", listing["publishing_recovery_message"])
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET status='published', etsy_state='active' WHERE id=?",
                (listing_id,),
            )
            connection.commit()
        page = self.client.get(f"/listings/{listing_id}?recovery_checked=1")
        self.assertIn("Check status and recover", page.text)
        self.assertIn("Wait briefly", page.text)

    def test_recovery_links_unique_etsy_match_and_synchronizes(self):
        class FakeAPI:
            def get_product(self, product_id):
                return {"id": product_id, "title": "Unbound Poster"}

        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        self._save_printify(listing_id)
        db.mark_printify_publish_requested(listing_id)
        remote = {
            "listing_id": 987654, "title": "Unbound Poster",
            "shop_id": 42, "state": "draft",
        }
        with (
            patch("web.app.PrintifyAPI.from_env", return_value=FakeAPI()),
            patch("web.app.find_etsy_candidates", return_value=[remote]),
            patch("web.app.get_etsy_listing", return_value=remote),
            patch("web.app.etsy_config", return_value={"shop_id": "42"}),
            patch("web.app.build_etsy_sync_preview", return_value={"changed_count": 1}),
            patch("web.app.sync_etsy_listing", return_value={"state": "draft"}) as sync,
        ):
            response = self.client.post(
                f"/listings/{listing_id}/publishing/recover",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["external_listing_id"], "987654")
        self.assertEqual(listing["publishing_recovery_stage"], "etsy_ready_for_review")
        sync.assert_called_once()

    def test_recovery_treats_etsy_edit_lock_as_waiting(self):
        from web.etsy_api import EtsyAPIError

        class FakeAPI:
            def get_product(self, product_id):
                return {"id": product_id, "title": "Unbound Poster"}

        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        self._save_printify(listing_id)
        db.mark_printify_publish_requested(listing_id)
        remote = {
            "listing_id": 987654, "title": "Unbound Poster",
            "shop_id": 42, "state": "draft",
        }
        lock = EtsyAPIError(
            'Etsy returned HTTP 409: {"error":"The Listing with listing_id 987654 is being edited by another process."}'
        )
        with (
            patch("web.app.PrintifyAPI.from_env", return_value=FakeAPI()),
            patch("web.app.find_etsy_candidates", return_value=[remote]),
            patch("web.app.get_etsy_listing", return_value=remote),
            patch("web.app.etsy_config", return_value={"shop_id": "42"}),
            patch("web.app.build_etsy_sync_preview", side_effect=lock),
        ):
            response = self.client.post(
                f"/listings/{listing_id}/publishing/recover",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["publishing_recovery_stage"], "waiting_for_etsy")
        self.assertIn("found and linked", listing["publishing_recovery_message"])

    def test_artwork_update_recovery_finishes_without_repeating_publish(self):
        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="published",
        )
        self._save_printify(listing_id)
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET external_listing_id='123456789', "
                "marketplace_url='https://www.etsy.com/listing/123456789/unbound' WHERE id=?",
                (listing_id,),
            )
            connection.commit()
        db.record_publishing_recovery(
            listing_id, "update_waiting_for_printify", "Printify is publishing."
        )
        api = MagicMock()
        with (
            patch("web.app.PrintifyAPI.from_env", return_value=api),
            patch("web.app.wait_for_product_unlock", return_value={"is_locked": False}) as wait,
            patch("web.app.sync_etsy_listing", return_value={"state": "active"}) as sync,
        ):
            response = self.client.post(
                f"/artworks/CEL-001/listings/{listing_id}/update-everywhere/recover",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("updated_everywhere=1", response.headers["location"])
        api.publish_product.assert_not_called()
        wait.assert_called_once_with(api, "printify-123")
        sync.assert_called_once()
        self.assertEqual(
            db.get_listing(listing_id)["publishing_recovery_stage"], "update_complete"
        )

    def test_artwork_update_recovery_publishes_saved_printify_change_once(self):
        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="published",
        )
        self._save_printify(listing_id)
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET external_listing_id='123456789' WHERE id=?",
                (listing_id,),
            )
            connection.commit()
        db.record_publishing_recovery(
            listing_id, "update_printify_ready", "The replacement is saved."
        )
        api = MagicMock()
        with (
            patch("web.app.PrintifyAPI.from_env", return_value=api),
            patch("web.app.wait_for_product_unlock", return_value={"is_locked": False}),
            patch("web.app.sync_etsy_listing", return_value={"state": "active"}),
        ):
            response = self.client.post(
                f"/artworks/CEL-001/listings/{listing_id}/update-everywhere/recover",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        api.publish_product.assert_called_once_with("printify-123")
        self.assertIsNotNone(
            db.get_listing(listing_id)["printify_publish_requested_at"]
        )
        self.assertEqual(
            db.get_listing(listing_id)["publishing_recovery_stage"], "update_complete"
        )

    def test_artwork_update_recovery_retries_only_final_etsy_sync(self):
        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="published",
        )
        self._save_printify(listing_id)
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET external_listing_id='123456789' WHERE id=?",
                (listing_id,),
            )
            connection.commit()
        db.record_publishing_recovery(
            listing_id, "update_waiting_for_etsy", "Etsy is temporarily busy."
        )
        api = MagicMock()
        with (
            patch("web.app.PrintifyAPI.from_env", return_value=api),
            patch("web.app.wait_for_product_unlock") as wait,
            patch("web.app.sync_etsy_listing", return_value={"state": "active"}) as sync,
        ):
            response = self.client.post(
                f"/artworks/CEL-001/listings/{listing_id}/update-everywhere/recover",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        api.publish_product.assert_not_called()
        wait.assert_not_called()
        sync.assert_called_once()
        self.assertEqual(
            db.get_listing(listing_id)["publishing_recovery_stage"], "update_complete"
        )

    def test_publish_listing_requires_readiness(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Incomplete", description="", tags="",
            price_cents=0, status="draft",
        )
        response = self.client.post(
            f"/listings/{listing_id}/publish",
            data={
                "marketplace_url": "https://www.etsy.com/listing/123456789/incomplete",
                "external_listing_id": "123456789",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("readiness checklist", response.text)

    def test_publish_listing_rejects_invalid_etsy_details(self):
        self._complete_listing_readiness()
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        response = self.client.post(
            f"/listings/{listing_id}/publish",
            data={
                "marketplace_url": "https://example.com/listing/abc",
                "external_listing_id": "not-a-number",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid Etsy listing URL", response.text)

    def test_standard_edit_cannot_mark_listing_published(self):
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags="one, two", price_cents=3995, status="ready",
        )
        response = self.client.post(
            f"/listings/{listing_id}",
            data={
                "marketplace": "Etsy", "product": "Poster",
                "title": "Unbound Poster", "description": "Description",
                "tags": "one, two", "price": "39.95",
                "listing_status": "published",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Etsy publishing section", response.text)
        self.assertEqual(db.get_listing(listing_id)["status"], "ready")

    def test_etsy_validation_problem_blocks_publication_and_is_explained(self):
        self._complete_listing_readiness()
        tags = ", ".join(f"tag {number}" for number in range(1, 15))
        listing_id = db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="Description",
            tags=tags, price_cents=3995, status="ready",
        )

        page = self.client.get(f"/listings/{listing_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("There are 14 tags; Etsy allows up to 13.", page.text)
        self.assertIn("Complete the readiness checklist before publishing.", page.text)

        response = self.client.post(
            f"/listings/{listing_id}/publish",
            data={
                "marketplace_url": "https://www.etsy.com/listing/123456789/unbound",
                "external_listing_id": "123456789",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("readiness checklist", response.text)

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
