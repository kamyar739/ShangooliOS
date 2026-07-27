import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from web import db
from web.app import app
from web.collection_printify import (
    HORIZONTAL_PRINTIFY_PROFILE,
    VERTICAL_PRINTIFY_PROFILE,
    create_selected_printify_drafts,
)
from web.local_listings import ensure_local_listing_draft
from web.printify_api import PrintifyAPIConnectionError


class FakePrintifyAPI:
    def __init__(self):
        self.catalog_calls = 0
        self.uploads = []
        self.payloads = []
        self.publish_calls = 0
        self.fail_provider_call = None
        self.unknown_create = False

    def list_providers(self, blueprint_id):
        self.catalog_calls += 1
        if self.fail_provider_call == self.catalog_calls:
            return []
        profile = (
            HORIZONTAL_PRINTIFY_PROFILE
            if blueprint_id == HORIZONTAL_PRINTIFY_PROFILE["blueprint_id"]
            else VERTICAL_PRINTIFY_PROFILE
        )
        return [{
            "id": profile["provider_id"],
            "title": profile["provider_name"],
        }]

    def list_variants(self, blueprint_id, provider_id):
        profile = (
            HORIZONTAL_PRINTIFY_PROFILE
            if blueprint_id == HORIZONTAL_PRINTIFY_PROFILE["blueprint_id"]
            else VERTICAL_PRINTIFY_PROFILE
        )
        return [
            {
                "id": variant_id,
                "title": title,
                "cost": 1000 + index,
                "is_available": True,
            }
            for index, (variant_id, title, _) in enumerate(profile["variants"])
        ]

    def upload_image(self, path):
        self.uploads.append(path)
        return {"id": f"upload-{len(self.uploads)}"}

    def create_product(self, payload):
        if self.unknown_create:
            raise PrintifyAPIConnectionError("connection lost")
        self.payloads.append(payload)
        return {"id": f"product-{len(self.payloads)}"}

    def publish_product(self, product_id):
        self.publish_calls += 1
        raise AssertionError("Collection draft creation must not publish")


class CollectionPrintifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "test.db"
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path
        connection = sqlite3.connect(self.database_path)
        connection.executescript(
            database.SCHEMA_PATH.read_text(encoding="utf-8")
        )
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
                default_price_tier_1_cents, default_price_tier_2_cents,
                default_price_tier_3_cents, default_price_tier_4_cents,
                default_price_tier_5_cents, default_price_tier_6_cents
            ) VALUES (?, 'CPF', 'Printify Test', 'curated', 'art', 'active',
                      2900, 3400, 3900, 4600, 5800, 7200)
            """,
            (brand_id,),
        )
        collection_id = connection.execute(
            "SELECT id FROM collections WHERE code='CPF'"
        ).fetchone()[0]
        for number, title, status in (
            (1, "Horizontal", "approved"),
            (2, "Vertical", "approved"),
            (3, "Retired", "retired"),
        ):
            connection.execute(
                """
                INSERT INTO artworks (
                    artwork_code, collection_id, sequence_number, public_title,
                    description, prompt, status
                ) VALUES (?, ?, ?, ?, 'Description', 'Prompt', ?)
                """,
                (f"CPF-{number:03d}", collection_id, number, title, status),
            )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        with db.get_connection() as connection:
            for number in range(1, 4):
                code = f"CPF-{number:03d}"
                artwork_id = connection.execute(
                    "SELECT id FROM artworks WHERE artwork_code=?", (code,)
                ).fetchone()["id"]
                connection.execute(
                    """
                    INSERT INTO artwork_listing_content (
                        artwork_id, short_story, long_story, etsy_title,
                        etsy_description, etsy_tags, alt_text, keywords
                    ) VALUES (?, 'Short', 'Long', ?, 'Description',
                              'wall art, poster', 'Alt text', 'art')
                    """,
                    (artwork_id, f"{code} Poster"),
                )
            connection.commit()
        self.client = TestClient(app)
        self.exists_patch = patch(
            "web.publish_readiness.assigned_file_exists", return_value=True
        )
        self.exists_patch.start()
        self.folder_patch = patch(
            "web.collection_printify.get_artwork_folder",
            side_effect=lambda row: self.root / row["artwork_code"],
        )
        self.folder_patch.start()
        self._make_ready("CPF-001", "horizontal")
        self._make_ready("CPF-002", "vertical")
        self._make_ready("CPF-003", "horizontal")

    def tearDown(self):
        self.folder_patch.stop()
        self.exists_patch.stop()
        db.DATABASE_PATH = self.original_path
        self.temporary.cleanup()

    def _add_file(self, code, role):
        relative = f"{role.replace(':', '-')}.png"
        folder = self.root / code
        folder.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_bytes(b"image")
        db.upsert_artwork_file(code, role, relative, relative, relative)

    def _make_ready(self, code, orientation):
        ratios = (
            ("3:2", "4:3", "5:4", "14:11")
            if orientation == "horizontal"
            else ("2:3", "3:4", "4:5", "11:14")
        )
        db.update_artwork_production(
            code,
            orientation=orientation,
            master_ratio=ratios[0],
            required_ratios=", ".join(ratios),
            notes="",
            original_approved=True,
            print_master_ready=True,
            ratio_exports_ready=True,
            mockups_ready=True,
            listing_content_ready=True,
        )
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
            code,
            original_approved=True,
            print_master_ready=True,
            ratio_exports_ready=True,
            mockups_ready=True,
            listing_content_ready=True,
        )
        default_set = next(
            row for row in db.list_mockup_sets()
            if row["name"] == "Etsy Standard"
        )
        db.record_artwork_mockup_set_generated(code, default_set["id"])
        db.approve_artwork_mockup_set(code, default_set["id"])
        collection, _, _ = db.get_collection("CPF")
        return ensure_local_listing_draft(collection, code)["listing_id"]

    def test_review_page_is_local_and_shows_only_eligible_plus_protected(self):
        api = FakePrintifyAPI()
        with patch(
            "web.collection_printify.PrintifyAPI.from_env", return_value=api
        ):
            response = self.client.get("/collections/CPF/printify")
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="CPF-001"', response.text)
        self.assertIn('value="CPF-002"', response.text)
        self.assertNotIn("CPF-003", response.text)
        self.assertEqual(api.catalog_calls, 0)
        self.assertFalse(api.uploads)

    def test_existing_printify_product_is_visible_but_not_selectable(self):
        listing_id = list(db.get_artwork_listings("CPF-001"))[0]["id"]
        db.save_printify_product(
            listing_id,
            product_url="https://printify.com/app/store/products/existing",
            product_id="existing",
            provider="Printify Choice",
            sizes="14 x 11",
            base_cost_cents=1000,
        )
        response = self.client.get("/collections/CPF/printify")
        self.assertIn("PROTECTED PRODUCTS", response.text)
        self.assertIn("CPF-001", response.text)
        self.assertNotIn('value="CPF-001"', response.text)

    def test_confirmation_and_selection_are_required_before_external_calls(self):
        api = FakePrintifyAPI()
        with patch(
            "web.collection_printify.PrintifyAPI.from_env", return_value=api
        ):
            no_confirm = self.client.post(
                "/collections/CPF/printify",
                data={"artwork_codes": "CPF-001"},
            )
            empty = self.client.post(
                "/collections/CPF/printify",
                data={"confirmed": "true"},
            )
        self.assertEqual(no_confirm.status_code, 400)
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(api.catalog_calls, 0)

    def test_horizontal_and_vertical_mapping_uses_collection_prices(self):
        api = FakePrintifyAPI()
        _, results = create_selected_printify_drafts(
            "CPF", ["CPF-001", "CPF-002"], confirmed=True, api=api
        )
        self.assertEqual([item["outcome"] for item in results], [
            "created", "created",
        ])
        self.assertEqual(
            [payload["blueprint_id"] for payload in api.payloads], [284, 282]
        )
        for payload in api.payloads:
            self.assertEqual(
                [variant["price"] for variant in payload["variants"]],
                [2900, 3400, 3900, 4600, 5800, 7200],
            )
            self.assertEqual(len(payload["variants"]), 6)
            self.assertEqual(payload["description"], "Description")
        self.assertEqual(api.payloads[0]["title"], "CPF-001 Poster")
        self.assertEqual(api.payloads[1]["title"], "CPF-002 Poster")
        self.assertEqual(api.publish_calls, 0)

    def test_existing_id_and_duplicate_selection_make_no_duplicate(self):
        listing_id = list(db.get_artwork_listings("CPF-001"))[0]["id"]
        db.save_printify_product(
            listing_id,
            product_url="https://printify.com/app/store/products/existing",
            product_id="existing",
            provider="Printify Choice",
            sizes="14 x 11",
            base_cost_cents=1000,
        )
        api = FakePrintifyAPI()
        _, results = create_selected_printify_drafts(
            "CPF", ["CPF-001", "CPF-001"], confirmed=True, api=api
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["outcome"], "existing")
        self.assertEqual(api.catalog_calls, 0)

    def test_repeated_submission_skips_successful_product(self):
        api = FakePrintifyAPI()
        create_selected_printify_drafts(
            "CPF", ["CPF-001"], confirmed=True, api=api
        )
        _, second = create_selected_printify_drafts(
            "CPF", ["CPF-001"], confirmed=True, api=api
        )
        self.assertEqual(second[0]["outcome"], "existing")
        self.assertEqual(len(api.payloads), 1)

    def test_definite_failure_does_not_stop_later_artwork(self):
        api = FakePrintifyAPI()
        api.fail_provider_call = 1
        _, results = create_selected_printify_drafts(
            "CPF", ["CPF-001", "CPF-002"], confirmed=True, api=api
        )
        self.assertEqual(results[0]["outcome"], "failed")
        self.assertEqual(results[1]["outcome"], "created")
        self.assertFalse(
            db.get_listing(
                list(db.get_artwork_listings("CPF-001"))[0]["id"]
            )["printify_product_id"]
        )
        self.assertTrue(
            db.get_listing(
                list(db.get_artwork_listings("CPF-002"))[0]["id"]
            )["printify_product_id"]
        )

    def test_ambiguous_product_creation_requires_manual_reconciliation(self):
        api = FakePrintifyAPI()
        api.unknown_create = True
        _, results = create_selected_printify_drafts(
            "CPF", ["CPF-001"], confirmed=True, api=api
        )
        self.assertEqual(results[0]["outcome"], "unknown")
        listing = list(db.get_artwork_listings("CPF-001"))[0]
        self.assertFalse(listing["printify_product_id"])

    def test_artwork_that_becomes_not_ready_is_skipped(self):
        db.set_artwork_production_flags("CPF-001", ratio_exports_ready=False)
        api = FakePrintifyAPI()
        _, results = create_selected_printify_drafts(
            "CPF", ["CPF-001"], confirmed=True, api=api
        )
        self.assertEqual(results[0]["outcome"], "skipped")
        self.assertEqual(api.catalog_calls, 0)

    def test_route_never_calls_publish_or_etsy(self):
        api = FakePrintifyAPI()
        with (
            patch(
                "web.collection_printify.PrintifyAPI.from_env",
                return_value=api,
            ),
            patch("web.app.sync_etsy_listing") as etsy,
        ):
            response = self.client.post(
                "/collections/CPF/printify",
                data={
                    "artwork_codes": "CPF-001",
                    "confirmed": "true",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Created", response.text)
        self.assertEqual(api.publish_calls, 0)
        etsy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
