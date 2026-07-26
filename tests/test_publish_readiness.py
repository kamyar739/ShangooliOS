import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from web import db
from web.app import app
from web.local_listings import ensure_local_listing_draft
from web.publish_readiness import (
    collection_publish_readiness,
    prepare_missing_collection_drafts,
)


class PublishReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "test.db"
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path
        connection = sqlite3.connect(self.database_path)
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
                brand_id, code, name, collection_type, vertical, status,
                default_price_tier_1_cents
            ) VALUES (?, 'PUB', 'Publish Test', 'curated', 'art', 'active', 2900)
            """,
            (brand_id,),
        )
        collection_id = connection.execute(
            "SELECT id FROM collections WHERE code='PUB'"
        ).fetchone()[0]
        for number, title in ((1, "First"), (2, "Second")):
            connection.execute(
                """
                INSERT INTO artworks (
                    artwork_code, collection_id, sequence_number, public_title,
                    description, prompt, status
                ) VALUES (?, ?, ?, ?, 'Factual description', 'Prompt', 'approved')
                """,
                (f"PUB-{number:03d}", collection_id, number, title),
            )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        with db.get_connection() as connection:
            for code in ("PUB-001", "PUB-002"):
                artwork_id = connection.execute(
                    "SELECT id FROM artworks WHERE artwork_code=?", (code,)
                ).fetchone()["id"]
                connection.execute(
                    """
                    INSERT INTO artwork_listing_content (
                        artwork_id, short_story, long_story, etsy_title,
                        etsy_description, etsy_tags, alt_text, keywords
                    ) VALUES (?, 'Short', 'Long', ?, 'Description',
                              'wall art, poster', 'Artwork in a room', 'art')
                    """,
                    (artwork_id, f"{code} wall art"),
                )
            connection.commit()
        self.client = TestClient(app)
        self.files_patch = patch(
            "web.publish_readiness.assigned_file_exists", return_value=True
        )
        self.files_patch.start()

    def tearDown(self):
        self.files_patch.stop()
        db.DATABASE_PATH = self.original_path
        self.temporary.cleanup()

    def _add_file(self, code, role):
        db.upsert_artwork_file(
            code, role, f"{role.replace(':', '-')}.png",
            f"{role.replace(':', '-')}.png", f"{role.replace(':', '-')}.png",
        )

    def _make_ready(self, code, *, listing=True):
        production = db.get_artwork_production(code)
        ratios = [
            value.strip()
            for value in production["required_ratios"].split(",")
            if value.strip()
        ]
        for role in ("source", "print_master"):
            self._add_file(code, role)
        for ratio in ratios:
            self._add_file(code, f"ratio:{ratio}")
        for slot in (
            "hero", "room", "bedroom", "office", "detail", "sizes",
            "how_it_works", "collection",
        ):
            self._add_file(code, f"mockup:{slot}")
        db.set_artwork_production_flags(
            code, original_approved=True, print_master_ready=True,
            ratio_exports_ready=True, mockups_ready=True,
            listing_content_ready=True,
        )
        default_set = next(
            row for row in db.list_mockup_sets() if row["name"] == "Etsy Standard"
        )
        db.record_artwork_mockup_set_generated(code, default_set["id"])
        db.approve_artwork_mockup_set(code, default_set["id"])
        if listing:
            collection, _, _ = db.get_collection("PUB")
            return ensure_local_listing_draft(collection, code)["listing_id"]
        return None

    def _state(self, code):
        _, items, _, _, _ = collection_publish_readiness("PUB")
        return next(item for item in items if item["artwork_code"] == code)

    def test_completely_ready_artwork(self):
        self._make_ready("PUB-001")
        state = self._state("PUB-001")
        self.assertEqual(state["primary_status"], "ready")
        self.assertFalse(state["blockers"])
        self.assertFalse(state["review_items"])

    def test_missing_ratio_files_blocks(self):
        self._make_ready("PUB-001")
        with db.get_connection() as connection:
            connection.execute(
                """
                DELETE FROM artwork_files WHERE artwork_id=(
                    SELECT id FROM artworks WHERE artwork_code='PUB-001'
                ) AND role LIKE 'ratio:%'
                """
            )
            connection.commit()
        state = self._state("PUB-001")
        self.assertEqual(state["primary_status"], "blocked")
        self.assertIn("Required ratio files are missing", state["blockers"])

    def test_unapproved_ratios_need_review(self):
        self._make_ready("PUB-001")
        db.set_artwork_production_flags("PUB-001", ratio_exports_ready=False)
        state = self._state("PUB-001")
        self.assertEqual(state["primary_status"], "needs_review")
        self.assertIn("Ratio-file approval is outstanding", state["review_items"])

    def test_missing_mockups_block(self):
        self._make_ready("PUB-001")
        with db.get_connection() as connection:
            connection.execute(
                """
                DELETE FROM artwork_files WHERE artwork_id=(
                    SELECT id FROM artworks WHERE artwork_code='PUB-001'
                ) AND role LIKE 'mockup:%'
                """
            )
            connection.commit()
        state = self._state("PUB-001")
        self.assertEqual(state["primary_status"], "blocked")
        self.assertIn("Curated listing images are missing", state["blockers"])

    def test_unapproved_mockups_need_review(self):
        self._make_ready("PUB-001")
        db.set_artwork_production_flags("PUB-001", mockups_ready=False)
        state = self._state("PUB-001")
        self.assertEqual(state["primary_status"], "needs_review")
        self.assertIn("Mockup approval is outstanding", state["review_items"])

    def test_missing_listing_content_and_price_block(self):
        listing_id = self._make_ready("PUB-001")
        db.update_listing(
            listing_id, marketplace="Etsy", product="Poster",
            title="", description="", tags="", price_cents=0, status="draft",
        )
        state = self._state("PUB-001")
        self.assertEqual(state["primary_status"], "blocked")
        self.assertFalse(state["title_ready"])
        self.assertFalse(state["description_ready"])
        self.assertFalse(state["tags_ready"])
        self.assertFalse(state["price_ready"])

    def test_prepare_missing_draft_uses_collection_price(self):
        self._make_ready("PUB-001", listing=False)
        result = prepare_missing_collection_drafts("PUB")
        self.assertIn("PUB-001", result["created"])
        listing = list(db.get_artwork_listings("PUB-001"))[0]
        self.assertEqual(listing["price_cents"], 2900)

    def test_existing_listing_price_and_external_ids_are_preserved(self):
        listing_id = self._make_ready("PUB-001")
        with db.get_connection() as connection:
            connection.execute(
                """
                UPDATE listings SET price_cents=4777,
                    printify_product_id='printify-existing',
                    external_listing_id='etsy-existing',
                    marketplace_url='https://www.etsy.com/listing/etsy-existing'
                WHERE id=?
                """,
                (listing_id,),
            )
            connection.commit()
        result = prepare_missing_collection_drafts("PUB")
        self.assertIn("PUB-001", result["existing"])
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["price_cents"], 4777)
        self.assertEqual(listing["printify_product_id"], "printify-existing")
        self.assertEqual(listing["external_listing_id"], "etsy-existing")

    def test_status_precedence_etsy_then_printify_then_blocked_then_review(self):
        listing_id = self._make_ready("PUB-001")
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET printify_product_id='printify-1' WHERE id=?",
                (listing_id,),
            )
            connection.commit()
        self.assertEqual(self._state("PUB-001")["primary_status"], "printify_linked")
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE listings SET external_listing_id='etsy-1' WHERE id=?",
                (listing_id,),
            )
            connection.execute(
                """
                DELETE FROM artwork_files WHERE artwork_id=(
                    SELECT id FROM artworks WHERE artwork_code='PUB-001'
                ) AND role='print_master'
                """
            )
            connection.commit()
        state = self._state("PUB-001")
        self.assertEqual(state["primary_status"], "etsy_linked")
        self.assertTrue(state["blockers"])

    def test_collection_ready_only_when_all_active_items_are_acceptable(self):
        self._make_ready("PUB-001")
        _, _, _, ready, _ = collection_publish_readiness("PUB")
        self.assertFalse(ready)
        self._make_ready("PUB-002")
        _, _, _, ready, _ = collection_publish_readiness("PUB")
        self.assertTrue(ready)

    def test_all_externally_linked_collection_is_acceptable(self):
        for code in ("PUB-001", "PUB-002"):
            listing_id = self._make_ready(code)
            with db.get_connection() as connection:
                connection.execute(
                    "UPDATE listings SET external_listing_id=? WHERE id=?",
                    (f"etsy-{code}", listing_id),
                )
                connection.commit()
        _, _, counts, ready, _ = collection_publish_readiness("PUB")
        self.assertTrue(ready)
        self.assertEqual(counts["etsy_linked"], 2)

    def test_no_production_run_is_computed_without_fabricating_one(self):
        self._make_ready("PUB-001")
        self.assertIsNone(db.get_collection_production_run("PUB"))
        state = self._state("PUB-001")
        self.assertEqual(state["production_status"], "No production run")
        self.assertIsNone(db.get_collection_production_run("PUB"))

    def test_retired_artwork_is_excluded(self):
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE artworks SET status='retired' WHERE artwork_code='PUB-002'"
            )
            connection.commit()
        _, items, counts, _, _ = collection_publish_readiness("PUB")
        self.assertEqual([item["artwork_code"] for item in items], ["PUB-001"])
        self.assertEqual(counts["total"], 1)

    def test_get_page_is_read_only_and_calls_no_external_services(self):
        self._make_ready("PUB-001")
        with db.get_connection() as connection:
            before = {
                "content": connection.execute(
                    "SELECT COUNT(*) FROM artwork_listing_content"
                ).fetchone()[0],
                "listings": connection.execute(
                    "SELECT COUNT(*) FROM listings"
                ).fetchone()[0],
                "runs": connection.execute(
                    "SELECT COUNT(*) FROM collection_production_runs"
                ).fetchone()[0],
                "mockups": connection.execute(
                    "SELECT COUNT(*) FROM artwork_mockup_sets"
                ).fetchone()[0],
            }
        with (
            patch("web.app.PrintifyAPI.from_env") as printify,
            patch("web.etsy_api.get_etsy_listing") as etsy,
        ):
            response = self.client.get("/collections/PUB/publish-readiness")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Publish Readiness", response.text)
        printify.assert_not_called()
        etsy.assert_not_called()
        with db.get_connection() as connection:
            after = {
                "content": connection.execute(
                    "SELECT COUNT(*) FROM artwork_listing_content"
                ).fetchone()[0],
                "listings": connection.execute(
                    "SELECT COUNT(*) FROM listings"
                ).fetchone()[0],
                "runs": connection.execute(
                    "SELECT COUNT(*) FROM collection_production_runs"
                ).fetchone()[0],
                "mockups": connection.execute(
                    "SELECT COUNT(*) FROM artwork_mockup_sets"
                ).fetchone()[0],
            }
        self.assertEqual(after, before)

    def test_prepare_missing_drafts_isolates_failures(self):
        self._make_ready("PUB-001", listing=False)
        db.update_artwork_listing_content(
            "PUB-002", etsy_title="", etsy_description="", etsy_tags=""
        )
        result = prepare_missing_collection_drafts("PUB")
        self.assertEqual(result["created"], ["PUB-001"])
        self.assertEqual(result["failed"][0]["artwork_code"], "PUB-002")

    def test_collection_review_uses_visual_review_wording_and_navigation(self):
        response = self.client.get("/collections/PUB/review")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Continue to Publish Readiness", response.text)
        self.assertNotIn("Ready for Printify</span>", response.text)


if __name__ == "__main__":
    unittest.main()
