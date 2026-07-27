import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import database
from web import db
from web.app import app
from web.collection_publish import publish_selected_listings


class CollectionPublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = Path(self.temporary.name) / "test.db"
        connection = sqlite3.connect(db.DATABASE_PATH)
        connection.executescript(
            database.SCHEMA_PATH.read_text(encoding="utf-8")
        )
        connection.execute(
            "INSERT INTO brands (code, name) VALUES ('SHG', 'Shop')"
        )
        brand_id = connection.execute(
            "SELECT id FROM brands WHERE code='SHG'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO collections (
                brand_id, code, name, collection_type, vertical, status
            ) VALUES (?, 'PUB', 'Publish Test', 'curated', 'art', 'active')
            """,
            (brand_id,),
        )
        collection_id = connection.execute(
            "SELECT id FROM collections WHERE code='PUB'"
        ).fetchone()[0]
        for number, status in ((1, "approved"), (2, "approved"), (3, "retired")):
            connection.execute(
                """
                INSERT INTO artworks (
                    artwork_code, collection_id, sequence_number,
                    public_title, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"PUB-{number:03d}",
                    collection_id,
                    number,
                    f"Artwork {number}",
                    status,
                ),
            )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.listing_ids = [
            db.create_listing(
                f"PUB-{number:03d}",
                marketplace="Etsy",
                product="Poster",
                title=f"Artwork {number} Poster",
                description="A complete description.",
                tags="wall art, poster",
                price_cents=2900,
                status="ready",
            )
            for number in (1, 2, 3)
        ]
        for number, listing_id in enumerate(self.listing_ids, 1):
            db.save_printify_product(
                listing_id,
                product_url=(
                    "https://printify.com/app/store/products/"
                    f"product-{number}"
                ),
                product_id=f"product-{number}",
                provider="Printify Choice",
                sizes="11 x 14",
                base_cost_cents=1000,
            )
        self.client = TestClient(app)
        self.readiness = patch(
            "web.listing_publication.get_listing_readiness",
            return_value={"ready": True},
        )
        self.readiness.start()

    def tearDown(self):
        self.readiness.stop()
        db.DATABASE_PATH = self.original_path
        self.temporary.cleanup()

    def _api(self):
        api = MagicMock()
        api.get_product.side_effect = lambda product_id: {
            "id": product_id,
            "title": "Artwork 1 Poster",
        }
        api.publish_product.return_value = {}
        return api

    def _overview(self):
        collection, _, _ = db.get_collection("PUB")
        return collection, [
            {
                "listing": db.get_listing(listing_id),
                "artwork_code": f"PUB-{index:03d}",
                "public_title": f"Artwork {index}",
                "selectable": index < 3,
            }
            for index, listing_id in enumerate(self.listing_ids, 1)
        ]

    def test_individual_and_collection_use_the_same_shared_function(self):
        import web.app as app_module
        import web.collection_publish as collection_module

        self.assertIs(
            app_module.request_listing_publication,
            collection_module.request_listing_publication,
        )
        self.assertIs(
            app_module.recover_listing_publication,
            collection_module.recover_listing_publication,
        )

    def test_review_and_invalid_posts_make_zero_external_calls(self):
        collection, items = self._overview()
        api = self._api()
        with (
            patch(
                "web.app.collection_publication_overview",
                return_value=(collection, items),
            ),
        ):
            review = self.client.get("/collections/PUB/publish")
            no_confirm = self.client.post(
                "/collections/PUB/publish",
                data={"listing_ids": str(self.listing_ids[0])},
            )
            empty = self.client.post(
                "/collections/PUB/publish", data={"confirmed": "on"}
            )
        self.assertEqual(review.status_code, 200)
        self.assertEqual(no_confirm.status_code, 400)
        self.assertEqual(empty.status_code, 400)
        api.publish_product.assert_not_called()

    def test_duplicate_selection_is_processed_once_and_failure_continues(self):
        collection, items = self._overview()
        calls = []

        def shared(listing_id, api=None):
            calls.append(listing_id)
            if listing_id == self.listing_ids[0]:
                return {
                    "listing_id": listing_id,
                    "artwork_code": "PUB-001",
                    "title": "One",
                    "outcome": "failed",
                    "label": "Failed safely",
                    "message": "Rejected",
                }
            return {
                "listing_id": listing_id,
                "artwork_code": "PUB-002",
                "title": "Two",
                "outcome": "requested",
                "label": "Publish requested",
                "message": "Accepted",
            }

        with (
            patch(
                "web.collection_publish.collection_publication_overview",
                return_value=(collection, items),
            ),
            patch(
                "web.collection_publish.request_listing_publication",
                side_effect=shared,
            ),
        ):
            _, results = publish_selected_listings(
                "PUB",
                [
                    self.listing_ids[0],
                    self.listing_ids[0],
                    self.listing_ids[1],
                ],
                confirmed=True,
                api=self._api(),
            )
        self.assertEqual(calls, self.listing_ids[:2])
        self.assertEqual([item["outcome"] for item in results], ["failed", "requested"])

    def test_review_explains_mixed_collection_eligibility(self):
        with db.get_connection() as connection:
            collection_id = connection.execute(
                "SELECT id FROM collections WHERE code='PUB'"
            ).fetchone()["id"]
            connection.execute(
                "UPDATE artworks SET status='approved' WHERE artwork_code='PUB-003'"
            )
            for number, status in (
                (4, "approved"),
                (5, "retired"),
                (6, "approved"),
            ):
                connection.execute(
                    """
                    INSERT INTO artworks (
                        artwork_code, collection_id, sequence_number,
                        public_title, status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"PUB-{number:03d}",
                        collection_id,
                        number,
                        f"Artwork {number}",
                        status,
                    ),
                )
            connection.commit()
        missing_id = db.create_listing(
            "PUB-004", marketplace="Etsy", product="Poster",
            title="Artwork 4 Poster", description="Description",
            tags="wall art", price_cents=2900, status="ready",
        )
        ready_six = db.create_listing(
            "PUB-006", marketplace="Etsy", product="Poster",
            title="Artwork 6 Poster", description="Description",
            tags="wall art", price_cents=2900, status="ready",
        )
        db.save_printify_product(
            ready_six,
            product_url="https://printify.com/app/store/products/product-6",
            product_id="product-6", provider="Printify Choice",
            sizes="11 x 14", base_cost_cents=1000,
        )
        db.mark_printify_publish_requested(self.listing_ids[1])
        with db.get_connection() as connection:
            connection.execute(
                """
                UPDATE listings SET external_listing_id='etsy-3',
                    etsy_state='active', status='published'
                WHERE id=?
                """,
                (self.listing_ids[2],),
            )
            connection.commit()
        collection, _, _ = db.get_collection("PUB")
        fabricated = []
        for number, listing_id, primary in (
            (1, self.listing_ids[0], "printify_linked"),
            (2, self.listing_ids[1], "printify_linked"),
            (3, self.listing_ids[2], "etsy_linked"),
            (4, missing_id, "ready"),
            (6, ready_six, "printify_linked"),
        ):
            fabricated.append({
                "artwork_code": f"PUB-{number:03d}",
                "public_title": f"Artwork {number}",
                "artwork_status": "approved",
                "listing_id": listing_id,
                "printify_product_id": (
                    db.get_listing(listing_id)["printify_product_id"] or ""
                ),
                "etsy_listing_id": (
                    db.get_listing(listing_id)["external_listing_id"] or ""
                ),
                "primary_status": primary,
            })
        with patch(
            "web.collection_publish.collection_publish_readiness",
            return_value=(collection, fabricated, {}, False, None),
        ):
            response = self.client.get("/collections/PUB/publish")
        self.assertEqual(response.status_code, 200)
        for label in (
            "Ready",
            "Already submitted",
            "Already published",
            "Missing Printify draft",
            "Retired",
        ):
            self.assertIn(label, response.text)
        self.assertIn(f'value="{self.listing_ids[0]}" checked', response.text)
        self.assertIn(f'value="{ready_six}" checked', response.text)
        self.assertIn(
            f'value="{self.listing_ids[1]}" disabled', response.text
        )
        self.assertIn(f'value="{missing_id}" disabled', response.text)

if __name__ == "__main__":
    unittest.main()
