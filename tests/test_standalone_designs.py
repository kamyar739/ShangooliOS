import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app import database
from web import db
from web.app import app
from web.standalone_designs import (
    MUG_PROFILE,
    check_design_marketplace_status,
    create_mug_draft,
    design_metadata_from_message,
    render_quick_text_design,
    save_mug_setup,
    suggested_mug_description,
    suggested_mug_title,
    update_mug_draft_copy,
    update_mug_draft_graphics,
    mug_profile,
    product_asset_path,
)
from web.product_blueprints import normalized_placement_geometry
from web.pinterest_bundle import (
    pinterest_bundle_copy,
    select_printify_context_mockup,
)
from web.portfolio_refresh import apply_portfolio_refresh
from web.mug_gallery import (
    approve_mug_gallery,
    prepare_mug_gallery,
    sync_mug_gallery_to_etsy,
    upload_mug_gallery,
)
import web.standalone_designs as standalone_designs
import web.mug_gallery as mug_gallery


class FakePrintifyAPI:
    def __init__(self, *, unknown=False):
        self.unknown = unknown
        self.uploads = []
        self.payloads = []
        self.updates = []
        self.deletes = []
        self.external = None

    def list_providers(self, blueprint_id):
        profile = next(
            item for item in (MUG_PROFILE, mug_profile("mug_11oz_black_accent"))
            if item["blueprint_id"] == blueprint_id
        )
        return [{
            "id": profile["provider_id"],
            "title": profile["provider_name"],
        }]

    def list_variants(self, blueprint_id, provider_id):
        profile = next(
            item for item in (MUG_PROFILE, mug_profile("mug_11oz_black_accent"))
            if item["blueprint_id"] == blueprint_id
        )
        return [{
            "id": profile["variant_id"],
            "title": profile["variant_title"],
            "cost": 516,
            "is_available": True,
            "placeholders": [profile["print_area"]],
        }]

    def upload_image(self, path):
        self.uploads.append(path)
        return {"id": f"uploaded-design-{len(self.uploads)}"}

    def create_product(self, payload):
        from web.printify_api import PrintifyAPIConnectionError

        if self.unknown:
            raise PrintifyAPIConnectionError("connection lost")
        self.payloads.append(payload)
        product_id = (
            "accent-product-1"
            if payload["blueprint_id"]
            == mug_profile("mug_11oz_black_accent")["blueprint_id"]
            else "mug-product-1"
        )
        return {"id": product_id}

    def get_product(self, product_id):
        product = {
            "id": product_id,
            "title": "Saved mug",
            "description": "Saved description",
            "variants": [
                {
                    "id": MUG_PROFILE["variant_id"],
                    "price": 1900,
                    "is_enabled": True,
                }
            ],
        }
        if self.external:
            product["external"] = self.external
        return product

    def update_product(self, product_id, payload):
        self.updates.append((product_id, payload))
        return {"id": product_id}

    def delete_product(self, product_id):
        self.deletes.append(product_id)
        return {}


class StandaloneDesignTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "test.db"
        self.assets_path = self.root / "designs"
        self.original_database_path = db.DATABASE_PATH
        self.original_assets_path = standalone_designs.DESIGN_ASSETS_DIR
        db.DATABASE_PATH = self.database_path
        standalone_designs.DESIGN_ASSETS_DIR = self.assets_path
        connection = sqlite3.connect(self.database_path)
        connection.executescript(
            database.SCHEMA_PATH.read_text(encoding="utf-8")
        )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.client = TestClient(app)

    def tearDown(self):
        db.DATABASE_PATH = self.original_database_path
        standalone_designs.DESIGN_ASSETS_DIR = self.original_assets_path
        self.temporary.cleanup()

    def _image_bytes(self):
        output = BytesIO()
        Image.new("RGBA", (2400, 1000), (255, 255, 255, 0)).save(
            output, "PNG"
        )
        return output.getvalue()

    def _opaque_image_bytes(self):
        output = BytesIO()
        Image.new("RGBA", (2400, 1000), (220, 220, 220, 255)).save(
            output, "PNG"
        )
        return output.getvalue()

    def _white_background_design_bytes(self):
        output = BytesIO()
        image = Image.new("RGB", (2400, 1000), "white")
        from PIL import ImageDraw

        ImageDraw.Draw(image).rectangle(
            (650, 350, 1750, 650),
            fill=(20, 45, 150),
        )
        image.save(output, "PNG")
        return output.getvalue()

    def _create_design(self):
        response = self.client.post(
            "/designs",
            data={
                "name": "Every Collection Tells a Story",
                "message": "EVERY COLLECTION TELLS A STORY.",
                "description": "A mug for storytellers.",
                "tags": "storyteller gift, creative mug",
            },
            files={"image": ("message.png", self._image_bytes(), "image/png")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return int(response.headers["location"].split("/")[2].split("?")[0])

    def _save_setup(self, design_id):
        save_mug_setup(
            design_id,
            title="Every Collection Tells a Story Mug",
            description="A mug for storytellers.",
            price_cents=1900,
            placement_scale=0.45,
        )

    def _save_accent_setup(self, design_id):
        save_mug_setup(
            design_id,
            blueprint_key="mug_11oz_black_accent",
            title="Every Collection Tells a Story Black Accent Mug",
            description="A black-accent mug for storytellers.",
            price_cents=2200,
            placement_scale=0.45,
        )

    def test_retire_everywhere_review_is_read_only(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())

        with patch("web.app.PrintifyAPI.from_env") as printify, patch(
            "web.app.update_etsy_listing_state"
        ) as etsy:
            response = self.client.get(f"/designs/{design_id}/retire")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Retire Everywhere", response.text)
        printify.assert_not_called()
        etsy.assert_not_called()

    def test_retire_everywhere_handles_both_mugs_and_preserves_ids(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        api = FakePrintifyAPI()
        create_mug_draft(design_id, confirmed=True, api=api)
        create_mug_draft(
            design_id,
            confirmed=True,
            api=api,
            blueprint_key="mug_11oz_black_accent",
        )
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="1111111",
            etsy_state="active",
            product_key="mug_11oz",
        )
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="2222222",
            etsy_state="active",
            product_key="mug_11oz_black_accent",
        )

        with patch("web.app.PrintifyAPI.from_env", return_value=api), patch(
            "web.app.update_etsy_listing_state"
        ) as etsy:
            response = self.client.post(
                f"/designs/{design_id}/retire", data={"confirmed": "true"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Retirement complete", response.text)
        self.assertEqual(etsy.call_count, 2)
        self.assertEqual(set(api.deletes), {"mug-product-1", "accent-product-1"})
        products = {
            row["product_type"]: row
            for row in db.list_standalone_design_products(design_id)
        }
        self.assertEqual(products["mug_11oz"]["external_state"], "retired")
        self.assertEqual(
            products["mug_11oz_black_accent"]["external_state"], "retired"
        )
        self.assertEqual(products["mug_11oz"]["printify_product_id"], "mug-product-1")
        self.assertEqual(products["mug_11oz"]["etsy_listing_id"], "1111111")
        self.assertEqual(db.get_standalone_design(design_id)["status"], "archived")

    def test_one_design_can_prepare_two_independent_mug_products(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)

        products = {
            row["product_type"]: row
            for row in db.list_standalone_design_products(design_id)
        }

        self.assertEqual(set(products), {"mug_11oz", "mug_11oz_black_accent"})
        self.assertEqual(products["mug_11oz"]["price_cents"], 1900)
        self.assertEqual(products["mug_11oz_black_accent"]["price_cents"], 2200)
        self.assertEqual(products["mug_11oz"]["blueprint_version"], 1)
        self.assertEqual(
            products["mug_11oz_black_accent"]["blueprint_version"], 1
        )

    def test_mug_galleries_are_prepared_and_stored_per_product(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())
        create_mug_draft(
            design_id,
            blueprint_key="mug_11oz_black_accent",
            confirmed=True,
            api=FakePrintifyAPI(),
        )

        class GalleryAPI:
            def get_product(self, product_id):
                return {"images": [{"src": f"https://images.printify.com/{product_id}.jpg"}]}

        original_root = mug_gallery.GALLERY_ROOT
        mug_gallery.GALLERY_ROOT = self.root / "galleries"
        try:
            with patch.object(
                mug_gallery,
                "_download_image",
                return_value=Image.new("RGB", (600, 600), "white"),
            ):
                prepare_mug_gallery(design_id, "mug_11oz", api=GalleryAPI())
                prepare_mug_gallery(
                    design_id, "mug_11oz_black_accent", api=GalleryAPI()
                )
            white = db.get_standalone_design(design_id, "mug_11oz")
            accent = db.get_standalone_design(design_id, "mug_11oz_black_accent")
            self.assertEqual(white["gallery_state"], "prepared")
            self.assertEqual(accent["gallery_state"], "prepared")
            self.assertEqual(len(__import__("json").loads(white["gallery_manifest"])), 4)
            accent_manifest = __import__("json").loads(accent["gallery_manifest"])
            self.assertEqual(len(accent_manifest), 4)
            self.assertTrue(
                all(item["source"] == "printify_render" for item in accent_manifest)
            )
        finally:
            mug_gallery.GALLERY_ROOT = original_root

    def test_gallery_review_page_performs_no_external_action(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())
        with patch("web.mug_gallery.PrintifyAPI.from_env") as printify, patch(
            "web.mug_gallery.upload_etsy_listing_image"
        ) as etsy_upload:
            response = self.client.get(
                f"/designs/{design_id}/products/mug_11oz/gallery"
            )
        self.assertEqual(response.status_code, 200)
        printify.assert_not_called()
        etsy_upload.assert_not_called()

    def test_uploaded_galleries_and_etsy_sync_are_isolated_per_product(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="1111111",
            etsy_state="active",
            product_key="mug_11oz",
        )
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="2222222",
            etsy_state="active",
            product_key="mug_11oz_black_accent",
        )
        uploads = [
            (self._opaque_image_bytes(), f"mockup-{position}.png")
            for position in range(1, 5)
        ]
        original_root = mug_gallery.GALLERY_ROOT
        mug_gallery.GALLERY_ROOT = self.root / "galleries"
        try:
            upload_mug_gallery(design_id, "mug_11oz_black_accent", uploads)
            approve_mug_gallery(design_id, "mug_11oz_black_accent")
            with patch(
                "web.mug_gallery.upload_etsy_listing_image",
                side_effect=[
                    {"listing_image_id": 101},
                    {"listing_image_id": 102},
                    {"listing_image_id": 103},
                    {"listing_image_id": 104},
                ],
            ) as upload, patch(
                "web.mug_gallery.get_etsy_listing_images",
                return_value=[{"listing_image_id": 101}, {"listing_image_id": 9}],
            ), patch("web.mug_gallery.delete_etsy_listing_image") as delete:
                sync_mug_gallery_to_etsy(
                    design_id, "mug_11oz_black_accent", confirmed=True
                )

            self.assertEqual({call.args[0] for call in upload.call_args_list}, {"2222222"})
            delete.assert_called_once_with("2222222", 9)
            white = db.get_standalone_design(design_id, "mug_11oz")
            accent = db.get_standalone_design(
                design_id, "mug_11oz_black_accent"
            )
            self.assertEqual(white["gallery_state"], "not_prepared")
            self.assertEqual(accent["gallery_state"], "synced")
        finally:
            mug_gallery.GALLERY_ROOT = original_root

    def test_gallery_upload_failure_does_not_delete_existing_etsy_images(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="1111111",
            etsy_state="active",
            product_key="mug_11oz",
        )
        uploads = [
            (self._opaque_image_bytes(), f"mockup-{position}.png")
            for position in range(1, 5)
        ]
        original_root = mug_gallery.GALLERY_ROOT
        mug_gallery.GALLERY_ROOT = self.root / "galleries"
        try:
            upload_mug_gallery(design_id, "mug_11oz", uploads)
            approve_mug_gallery(design_id, "mug_11oz")
            with patch(
                "web.mug_gallery.upload_etsy_listing_image",
                side_effect=[{"listing_image_id": 101}, ValueError("upload failed")],
            ), patch("web.mug_gallery.delete_etsy_listing_image") as delete:
                with self.assertRaisesRegex(ValueError, "upload failed"):
                    sync_mug_gallery_to_etsy(
                        design_id, "mug_11oz", confirmed=True
                    )
            delete.assert_not_called()
            product = db.get_standalone_design(design_id, "mug_11oz")
            self.assertEqual(product["gallery_state"], "needs_review")
        finally:
            mug_gallery.GALLERY_ROOT = original_root

    def test_connected_product_copy_can_be_corrected_without_changing_setup(self):
        design_id = self._create_design()
        db.update_standalone_design(
            design_id,
            name="I have all the best cells",
            message="I have all the best cells.",
            description="A biology teacher mug.",
            tags="biology teacher, teacher gift",
        )
        self._save_accent_setup(design_id)
        create_mug_draft(
            design_id,
            confirmed=True,
            blueprint_key="mug_11oz_black_accent",
            api=FakePrintifyAPI(),
        )
        before = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )

        edit_page = self.client.get(
            f"/designs/{design_id}/products/mug_11oz_black_accent"
            "?edit_copy=1"
        )
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(
            "Biology Teacher Black Accent Mug – I have all the best cells",
            edit_page.text,
        )
        self.assertIn(
            "The black handle and interior give this 11 oz mug a bold, premium look.",
            edit_page.text,
        )
        response = self.client.post(
            f"/designs/{design_id}/products/mug_11oz_black_accent/copy",
            data={
                "title": "Biology Teacher Mug – I Have All the Best Cells",
                "description": (
                    "A biology teacher gift. The design is printed on both "
                    "sides for clear visibility when held in either hand."
                ),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        after = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(after["external_state"], "needs_update")
        self.assertEqual(after["price_cents"], before["price_cents"])
        self.assertEqual(after["placement_x"], before["placement_x"])
        self.assertEqual(
            after["printify_product_id"], before["printify_product_id"]
        )
        self.assertEqual(
            after["production_asset_filename"],
            before["production_asset_filename"],
        )

    def test_suggested_mug_title_uses_teacher_subject_when_known(self):
        self.assertEqual(
            suggested_mug_title("I have all the best cells."),
            "Biology Teacher Mug – I have all the best cells",
        )

    def test_suggested_mug_copy_is_blueprint_aware(self):
        self.assertEqual(
            suggested_mug_title(
                "I have all the best cells.", "mug_11oz_black_accent"
            ),
            "Biology Teacher Black Accent Mug – I have all the best cells",
        )
        description = suggested_mug_description(
            "A thoughtful biology teacher gift.",
            "mug_11oz_black_accent",
            "both",
        )
        self.assertIn("black handle and interior", description)
        self.assertIn("printed on both sides", description)

    def test_white_mug_suggested_copy_remains_unchanged(self):
        self.assertEqual(
            suggested_mug_title("I have all the best cells."),
            "Biology Teacher Mug – I have all the best cells",
        )
        description = suggested_mug_description(
            "A thoughtful biology teacher gift.", "mug_11oz", "both"
        )
        self.assertNotIn("black handle", description)
        self.assertIn("printed on both sides", description)

    def test_product_assets_remain_isolated_from_latest_design_source(self):
        design_id = self._create_design()
        original = db.get_standalone_design(design_id)
        original_filename = original["source_filename"]
        self._save_setup(design_id)

        second = standalone_designs.save_design_source(
            self._opaque_image_bytes(), "accent.png"
        )
        db.replace_standalone_design_source(
            design_id,
            source_filename=second["filename"],
            source_original_filename=second["original_filename"],
            image_width=second["width"],
            image_height=second["height"],
        )
        self._save_accent_setup(design_id)

        latest = standalone_designs.save_design_source(
            self._white_background_design_bytes(), "latest.png"
        )
        db.replace_standalone_design_source(
            design_id,
            source_filename=latest["filename"],
            source_original_filename=latest["original_filename"],
            image_width=latest["width"],
            image_height=latest["height"],
        )

        white = db.get_standalone_design(design_id, "mug_11oz")
        accent = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(white["production_asset_filename"], original_filename)
        self.assertEqual(accent["production_asset_filename"], second["filename"])
        self.assertEqual(product_asset_path(white).name, original_filename)
        self.assertEqual(product_asset_path(accent).name, second["filename"])
        self.assertEqual(white["source_filename"], latest["filename"])
        self.assertEqual(accent["source_filename"], latest["filename"])

    def test_legacy_white_product_falls_back_then_persists_prepared_asset(self):
        design_id = self._create_design()
        design = db.get_standalone_design(design_id)
        db.save_standalone_design_product(
            design_id,
            title="Legacy mug",
            description="Legacy setup",
            price_cents=1900,
            blueprint_id=MUG_PROFILE["blueprint_id"],
            provider_id=MUG_PROFILE["provider_id"],
            provider_name=MUG_PROFILE["provider_name"],
            variant_id=MUG_PROFILE["variant_id"],
            variant_title=MUG_PROFILE["variant_title"],
            placement_x=0.5,
            placement_y=0.5,
            placement_scale=0.45,
        )
        legacy = db.get_standalone_design(design_id)
        self.assertIsNone(legacy["production_asset_filename"])
        self.assertEqual(product_asset_path(legacy).name, design["source_filename"])

        self._save_setup(design_id)
        prepared = db.get_standalone_design(design_id)
        self.assertEqual(
            prepared["production_asset_filename"], design["source_filename"]
        )

    def test_each_blueprint_publishes_its_own_asset_and_external_state(self):
        design_id = self._create_design()
        original = db.get_standalone_design(design_id)["source_filename"]
        self._save_setup(design_id)
        accent_asset = standalone_designs.save_design_source(
            self._opaque_image_bytes(), "accent.png"
        )
        db.replace_standalone_design_source(
            design_id,
            source_filename=accent_asset["filename"],
            source_original_filename=accent_asset["original_filename"],
            image_width=accent_asset["width"],
            image_height=accent_asset["height"],
        )
        self._save_accent_setup(design_id)
        api = FakePrintifyAPI()

        white_result = create_mug_draft(design_id, confirmed=True, api=api)
        white_only = db.get_standalone_design(design_id, "mug_11oz")
        untouched_accent = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(white_only["printify_product_id"], "mug-product-1")
        self.assertIsNone(untouched_accent["printify_product_id"])
        self.assertEqual(untouched_accent["external_state"], "not_sent")
        accent_result = create_mug_draft(
            design_id,
            confirmed=True,
            api=api,
            blueprint_key="mug_11oz_black_accent",
        )

        white = db.get_standalone_design(design_id, "mug_11oz")
        accent = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(white_result["outcome"], "created")
        self.assertEqual(accent_result["outcome"], "created")
        self.assertEqual(white["printify_product_id"], "mug-product-1")
        self.assertEqual(accent["printify_product_id"], "accent-product-1")
        self.assertEqual(api.uploads[0].name, original)
        self.assertEqual(api.uploads[1].name, accent_asset["filename"])
        duplicate = create_mug_draft(design_id, confirmed=True, api=api)
        self.assertEqual(duplicate["outcome"], "existing")
        self.assertEqual(len(api.payloads), 2)

        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="1111111",
            etsy_state="active",
            product_key="mug_11oz",
        )
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="2222222",
            etsy_state="inactive",
            product_key="mug_11oz_black_accent",
        )
        white = db.get_standalone_design(design_id, "mug_11oz")
        accent = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(white["etsy_listing_id"], "1111111")
        self.assertEqual(accent["etsy_listing_id"], "2222222")
        self.assertEqual(white["etsy_state"], "active")
        self.assertEqual(accent["etsy_state"], "inactive")

    def test_saving_one_blueprint_setup_never_overwrites_prepared_assets(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        white_before = db.get_standalone_design(
            design_id, "mug_11oz"
        )["production_asset_filename"]
        accent_before = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )["production_asset_filename"]
        replacement = standalone_designs.save_design_source(
            self._white_background_design_bytes(), "replacement.png"
        )
        db.replace_standalone_design_source(
            design_id,
            source_filename=replacement["filename"],
            source_original_filename=replacement["original_filename"],
            image_width=replacement["width"],
            image_height=replacement["height"],
        )
        self._save_setup(design_id)

        white = db.get_standalone_design(design_id, "mug_11oz")
        accent = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(white["production_asset_filename"], white_before)
        self.assertEqual(accent["production_asset_filename"], accent_before)

    def test_explicit_latest_asset_preparation_is_scoped_and_confirmed(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        white_before = db.get_standalone_design(design_id, "mug_11oz")
        accent_before = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        replacement = standalone_designs.save_design_source(
            self._white_background_design_bytes(), "replacement.png"
        )
        db.replace_standalone_design_source(
            design_id,
            source_filename=replacement["filename"],
            source_original_filename=replacement["original_filename"],
            image_width=replacement["width"],
            image_height=replacement["height"],
        )

        rejected = self.client.post(
            f"/designs/{design_id}/products/mug_11oz_black_accent/prepare-latest",
            data={},
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(
            db.get_standalone_design(
                design_id, "mug_11oz_black_accent"
            )["production_asset_filename"],
            accent_before["production_asset_filename"],
        )

        prepared = self.client.post(
            f"/designs/{design_id}/products/mug_11oz_black_accent/prepare-latest",
            data={"confirmed": "true"},
            follow_redirects=False,
        )
        self.assertEqual(prepared.status_code, 303)
        white_after = db.get_standalone_design(design_id, "mug_11oz")
        accent_after = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(
            white_after["production_asset_filename"],
            white_before["production_asset_filename"],
        )
        self.assertEqual(
            accent_after["production_asset_filename"], replacement["filename"]
        )

    def test_normalized_placement_projects_to_each_verified_print_area(self):
        white = mug_profile("mug_11oz")
        accent = mug_profile("mug_11oz_black_accent")
        white_geometry = normalized_placement_geometry(
            white, x=0.5, y=0.25, scale=0.45
        )
        accent_geometry = normalized_placement_geometry(
            accent, x=0.5, y=0.25, scale=0.45
        )
        self.assertEqual(white_geometry["print_area_width"], 2700)
        self.assertEqual(white_geometry["print_area_height"], 1120)
        self.assertEqual(accent_geometry["print_area_width"], 2550)
        self.assertEqual(accent_geometry["print_area_height"], 1155)
        self.assertEqual(white_geometry["center_x"], 1350)
        self.assertEqual(accent_geometry["center_x"], 1275)

    def test_accent_review_is_read_only_and_requires_confirmation(self):
        design_id = self._create_design()
        self._save_accent_setup(design_id)
        before = [dict(row) for row in db.list_standalone_design_products(design_id)]
        with patch("web.standalone_designs.PrintifyAPI.from_env") as api:
            response = self.client.get(
                f"/designs/{design_id}/products/mug_11oz_black_accent"
            )
        after = [dict(row) for row in db.list_standalone_design_products(design_id)]
        self.assertEqual(response.status_code, 200)
        self.assertIn("Black Accent Mug 11 oz", response.text)
        self.assertEqual(before, after)
        api.assert_not_called()

        with patch("web.standalone_designs.PrintifyAPI.from_env") as api:
            rejected = self.client.post(
                f"/designs/{design_id}/mug/create",
                data={"blueprint_key": "mug_11oz_black_accent"},
            )
        self.assertEqual(rejected.status_code, 400)
        api.assert_not_called()

    def test_uncertain_white_creation_does_not_block_accent_creation(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)

        white_result = create_mug_draft(
            design_id, confirmed=True, api=FakePrintifyAPI(unknown=True)
        )
        accent_result = create_mug_draft(
            design_id,
            confirmed=True,
            api=FakePrintifyAPI(),
            blueprint_key="mug_11oz_black_accent",
        )

        white = db.get_standalone_design(design_id, "mug_11oz")
        accent = db.get_standalone_design(
            design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(white_result["outcome"], "outcome_unknown")
        self.assertEqual(white["external_state"], "outcome_unknown")
        self.assertEqual(accent_result["outcome"], "created")
        self.assertEqual(accent["external_state"], "created")
        self.assertEqual(accent["printify_product_id"], "accent-product-1")

    def test_design_can_be_uploaded_and_opened(self):
        design_id = self._create_design()
        design = db.get_standalone_design(design_id)

        self.assertEqual(design["name"], "Every Collection Tells a Story")
        self.assertEqual(design["image_width"], 2400)
        self.assertTrue(
            (self.assets_path / design["source_filename"]).is_file()
        )
        page = self.client.get(f"/designs/{design_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Launch both mugs", page.text)
        self.assertIn("Designs", self.client.get("/designs").text)

    def test_quick_text_design_creates_transparent_normal_design(self):
        rendered = render_quick_text_design(
            "Teaching is my superpower.\nCoffee is my sidekick."
        )
        with Image.open(BytesIO(rendered)) as image:
            self.assertEqual(image.size, (2400, 2400))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)

        response = self.client.post(
            "/designs/quick-text",
            data={
                "message": (
                    "Teaching is my superpower.\nCoffee is my sidekick."
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/launch", response.headers["location"])
        design_id = int(
            response.headers["location"].split("/")[2].split("?")[0]
        )
        design = db.get_standalone_design(design_id)
        self.assertEqual(
            design["message"],
            "Teaching is my superpower. Coffee is my sidekick.",
        )
        self.assertIn("typography mug", design["tags"])
        products = db.list_standalone_design_products(design_id)
        self.assertEqual(
            {product["product_type"] for product in products},
            {"mug_11oz", "mug_11oz_black_accent"},
        )
        self.assertTrue(
            all(product["placement_mode"] == "front" for product in products)
        )
        launch = self.client.get(response.headers["location"])
        self.assertEqual(launch.status_code, 200)
        self.assertIn("Launch both mugs", launch.text)
        self.assertIn("Create Both Mug Drafts", launch.text)
        with Image.open(self.assets_path / design["source_filename"]) as image:
            self.assertEqual(image.getchannel("A").getextrema(), (0, 255))

    def test_teacher_metadata_infers_subject_tone_and_etsy_safe_tags(self):
        metadata = design_metadata_from_message(
            "Biology teachers have all the best cells."
        )
        tags = [tag.strip() for tag in metadata["tags"].split(",")]

        self.assertEqual(tags[:3], ["teacher", "biology", "humor"])
        self.assertIn("biology teacher", tags)
        self.assertIn("science teacher", tags)
        self.assertIn("teacher gift", tags)
        self.assertLessEqual(len(tags), 13)
        self.assertTrue(all(len(tag) <= 20 for tag in tags))
        self.assertIn("biology teachers", metadata["description"])

    def test_teacher_metadata_endpoint_uses_shared_generator(self):
        response = self.client.post(
            "/designs/message-metadata",
            data={"message": "I'm silently correcting your grammar."},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        tags = [tag.strip() for tag in payload["tags"].split(",")]
        self.assertEqual(tags[:3], ["teacher", "english", "humor"])
        self.assertIn("english teacher", tags)

    def test_general_metadata_recognizes_espresso_as_coffee(self):
        metadata = design_metadata_from_message("Espresso yourself!")
        tags = [tag.strip() for tag in metadata["tags"].split(",")]

        self.assertEqual(tags[0], "coffee mug")

    def test_teacher_metadata_recognizes_solving_problems_as_math(self):
        metadata = design_metadata_from_message(
            "I solve problems for a living."
        )
        tags = [tag.strip() for tag in metadata["tags"].split(",")]

        self.assertEqual(tags[:3], ["teacher", "math", "humor"])
        self.assertIn("math teacher", tags)

    def test_proposed_teacher_set_infers_expected_categories(self):
        examples = {
            "I make the past present.": "history",
            "Powered by curiosity and coffee.": "science",
            "Creativity is part of the curriculum.": "art",
            "Every lesson needs a little rhythm.": "music",
            "Teaching tiny humans is my superpower.": "elementary",
            "I teach. What’s your superpower?": "teacher",
        }

        for message, expected_tag in examples.items():
            with self.subTest(message=message):
                tags = [
                    tag.strip()
                    for tag in design_metadata_from_message(message)[
                        "tags"
                    ].split(",")
                ]
                self.assertEqual(tags[0], "teacher")
                self.assertIn(expected_tag, tags)
                self.assertLessEqual(len(tags), 13)
                self.assertTrue(all(len(tag) <= 20 for tag in tags))

    def test_teacher_metadata_recognizes_lesson_language(self):
        metadata = design_metadata_from_message(
            "One lesson can change everything."
        )
        tags = [tag.strip() for tag in metadata["tags"].split(",")]

        self.assertEqual(tags[0], "teacher")
        self.assertIn("teacher gift", tags)
        self.assertIn("inspiring teacher", tags)

    def test_teacher_metadata_recognizes_brilliant_minds_language(self):
        metadata = design_metadata_from_message(
            "Helping brilliant minds find their spark."
        )
        tags = [tag.strip() for tag in metadata["tags"].split(",")]

        self.assertEqual(tags[0], "teacher")
        self.assertIn("teacher gift", tags)
        self.assertIn("inspiring teacher", tags)

    def test_designs_page_offers_both_creation_paths(self):
        page = self.client.get("/designs")
        self.assertIn("Upload finished design", page.text)
        self.assertIn("Quick text design", page.text)
        self.assertIn("Text ideas", page.text)

    def test_text_idea_library_supports_rating_reorder_and_delete(self):
        page = self.client.get("/designs/text-ideas")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Future Mug Text", page.text)
        self.assertIn("I Had a Plan. Then the Bell Rang.", page.text)

        added = self.client.post(
            "/designs/text-ideas",
            data={"category": "New Category", "text": "A fresh idea."},
            follow_redirects=False,
        )
        self.assertEqual(added.status_code, 303)
        ideas = [dict(row) for row in db.list_mug_text_ideas()]
        new_idea = next(item for item in ideas if item["text"] == "A fresh idea.")

        rated = self.client.post(
            f"/designs/text-ideas/{new_idea['id']}/rating",
            data={"rating": "4"},
            follow_redirects=False,
        )
        self.assertEqual(rated.status_code, 303)
        rated_idea = next(
            dict(item) for item in db.list_mug_text_ideas()
            if item["id"] == new_idea["id"]
        )
        self.assertEqual(rated_idea["rating"], 4)
        reordered_ids = [item["id"] for item in reversed(ideas)]
        reordered = self.client.post(
            "/designs/text-ideas/reorder", json={"ids": reordered_ids}
        )
        self.assertEqual(reordered.status_code, 200)
        self.assertEqual(db.list_mug_text_ideas()[0]["id"], reordered_ids[0])

        use_page = self.client.get(
            "/designs/quick-text", params={"message": "A fresh idea."}
        )
        self.assertIn(">A fresh idea.</textarea>", use_page.text)
        deleted = self.client.post(
            f"/designs/text-ideas/{new_idea['id']}/delete",
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        self.assertFalse(
            any(row["id"] == new_idea["id"] for row in db.list_mug_text_ideas())
        )

    def test_design_catalog_search_filter_and_pagination(self):
        created_ids = []
        for index in range(26):
            created_ids.append(
                db.create_standalone_design(
                    name=f"Catalog Design {index:02d}",
                    message=f"Message {index:02d}",
                    description="Scalable catalog test",
                    tags="catalog, mug",
                    source_filename=f"design-{index:02d}.png",
                    source_original_filename=f"design-{index:02d}.png",
                    image_width=2400,
                    image_height=1000,
                )
            )
        self._save_setup(created_ids[0])
        db.set_standalone_product_state(
            created_ids[0],
            "created",
            printify_product_id="printify-design-1",
            printify_product_url="https://printify.example/product/1",
        )
        self._save_accent_setup(created_ids[1])
        db.update_standalone_design(
            created_ids[17],
            name="Catalog Design 17",
            message="Message 17",
            description="Scalable catalog test",
            tags="teacher, biology, humor, biology teacher",
        )

        first_page = self.client.get("/designs")
        self.assertEqual(first_page.status_code, 200)
        self.assertIn("26 designs", first_page.text)
        self.assertIn("Page 1 of 2", first_page.text)
        self.assertIn("Next", first_page.text)

        second_page = self.client.get("/designs?page=2")
        self.assertEqual(second_page.status_code, 200)
        self.assertIn("Page 2 of 2", second_page.text)
        self.assertIn("Previous", second_page.text)

        search = self.client.get("/designs?search=Message+17")
        self.assertEqual(search.status_code, 200)
        self.assertIn("Catalog Design 17", search.text)
        self.assertNotIn("Catalog Design 16", search.text)
        self.assertIn("biology", search.text)
        self.assertIn("+3", search.text)

        biology = self.client.get("/designs?tag=Biology")
        self.assertEqual(biology.status_code, 200)
        self.assertIn("Catalog Design 17", biology.text)
        self.assertNotIn("Catalog Design 16", biology.text)

        printify = self.client.get("/designs?status=printify")
        self.assertEqual(printify.status_code, 200)
        self.assertIn("Catalog Design 00", printify.text)
        self.assertNotIn("Catalog Design 01", printify.text)

        catalog = self.client.get("/designs")
        self.assertIn("White Ceramic Mug", catalog.text)
        self.assertIn("Black Accent Mug 11 oz", catalog.text)

        accent = self.client.get(
            "/designs?product=mug_11oz_black_accent"
        )
        self.assertIn("Catalog Design 01", accent.text)
        self.assertNotIn("Catalog Design 00", accent.text)

        white = self.client.get("/designs?product=mug_11oz")
        self.assertIn("Catalog Design 00", white.text)
        self.assertNotIn("Catalog Design 01", white.text)

        no_product = self.client.get("/designs?product=none")
        self.assertIn("Catalog Design 02", no_product.text)
        self.assertNotIn("Catalog Design 00", no_product.text)
        self.assertNotIn("Catalog Design 01", no_product.text)

    def test_design_catalog_filters_products_needing_etsy_sync(self):
        needs_sync_id = self._create_design()
        self._save_setup(needs_sync_id)
        db.record_standalone_marketplace_status(
            needs_sync_id,
            etsy_listing_id="4546000001",
            etsy_state="active",
            paused=False,
        )
        synced_id = db.create_standalone_design(
            name="Already Synced Design",
            message="Already synchronized",
            description="Catalog sync test",
            tags="teacher, mug",
            source_filename="already-synced.png",
            source_original_filename="already-synced.png",
            image_width=2400,
            image_height=1000,
        )
        self._save_setup(synced_id)
        db.record_standalone_marketplace_status(
            synced_id,
            etsy_listing_id="4546000002",
            etsy_state="active",
            paused=False,
        )
        db.mark_standalone_etsy_synced(synced_id)

        page = self.client.get("/designs?status=etsy_sync")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Every Collection Tells a Story", page.text)
        self.assertIn("Needs Etsy Sync", page.text)
        self.assertNotIn("Already Synced Design", page.text)

    def test_mug_review_performs_no_printify_operations(self):
        design_id = self._create_design()
        with patch("web.standalone_designs.PrintifyAPI.from_env") as api:
            response = self.client.get(f"/designs/{design_id}/mug")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Review 11 oz Mug", response.text)
        api.assert_not_called()

    def test_post_without_confirmation_performs_no_external_operation(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        with patch("web.standalone_designs.PrintifyAPI.from_env") as api:
            response = self.client.post(
                f"/designs/{design_id}/mug/create",
                data={},
            )
        self.assertEqual(response.status_code, 400)
        api.assert_not_called()

    def test_confirmed_creation_reuses_printify_creator_and_saves_id(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        api = FakePrintifyAPI()

        result = create_mug_draft(design_id, confirmed=True, api=api)
        design = db.get_standalone_design(design_id)

        self.assertEqual(result["outcome"], "created")
        self.assertEqual(design["printify_product_id"], "mug-product-1")
        self.assertEqual(design["external_state"], "created")
        self.assertEqual(len(api.uploads), 1)
        self.assertEqual(len(api.payloads), 1)
        payload = api.payloads[0]
        self.assertEqual(payload["blueprint_id"], MUG_PROFILE["blueprint_id"])
        self.assertEqual(
            payload["print_provider_id"], MUG_PROFILE["provider_id"]
        )
        self.assertEqual(payload["variants"][0]["price"], 1900)
        image = payload["print_areas"][0]["placeholders"][0]["images"][0]
        self.assertEqual(image["scale"], 0.45)

        second = create_mug_draft(design_id, confirmed=True, api=api)
        self.assertEqual(second["outcome"], "existing")
        self.assertEqual(len(api.payloads), 1)

    def test_unknown_creation_result_is_protected_from_retry(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        api = FakePrintifyAPI(unknown=True)

        result = create_mug_draft(design_id, confirmed=True, api=api)
        self.assertEqual(result["outcome"], "outcome_unknown")
        self.assertEqual(
            db.get_standalone_design(design_id)["external_state"],
            "outcome_unknown",
        )
        with self.assertRaisesRegex(ValueError, "previous result is uncertain"):
            create_mug_draft(design_id, confirmed=True, api=api)

    def test_both_sides_places_the_design_twice(self):
        design_id = self._create_design()
        save_mug_setup(
            design_id,
            title="Every Collection Tells a Story Mug",
            description="A mug for storytellers.",
            price_cents=1900,
            placement_scale=0.45,
            placement_x=0.5,
            placement_y=0.5,
            placement_mode="both",
        )
        api = FakePrintifyAPI()

        create_mug_draft(design_id, confirmed=True, api=api)

        images = api.payloads[0]["print_areas"][0]["placeholders"][0]["images"]
        self.assertEqual(len(images), 2)
        self.assertEqual(
            [image["x"] for image in images],
            [
                MUG_PROFILE["right_hand_x"],
                MUG_PROFILE["left_hand_x"],
            ],
        )

    def test_mug_setup_adds_accurate_placement_copy_without_duplicates(self):
        expected = {
            "front": "printed on the right-handed side",
            "reverse": "printed on the left-handed side",
            "both": "printed on both sides",
        }
        for placement_mode, phrase in expected.items():
            with self.subTest(placement_mode=placement_mode):
                design_id = self._create_design()
                save_mug_setup(
                    design_id,
                    title="Teacher Mug",
                    description="A thoughtful teacher gift.",
                    price_cents=1900,
                    placement_scale=0.45,
                    placement_mode=placement_mode,
                )
                saved = db.get_standalone_design(design_id)
                self.assertIn(phrase, saved["product_description"])

                save_mug_setup(
                    design_id,
                    title="Teacher Mug",
                    description=saved["product_description"],
                    price_cents=1900,
                    placement_scale=0.45,
                    placement_mode=placement_mode,
                )
                saved_again = db.get_standalone_design(design_id)
                self.assertEqual(
                    saved_again["product_description"].count(phrase), 1
                )

    def test_changing_mug_sides_replaces_previous_placement_copy(self):
        design_id = self._create_design()
        save_mug_setup(
            design_id,
            title="Teacher Mug",
            description="A thoughtful teacher gift.",
            price_cents=1900,
            placement_scale=0.45,
            placement_mode="both",
        )
        previous = db.get_standalone_design(design_id)["product_description"]

        save_mug_setup(
            design_id,
            title="Teacher Mug",
            description=previous,
            price_cents=1900,
            placement_scale=0.45,
            placement_mode="front",
        )

        updated = db.get_standalone_design(design_id)["product_description"]
        self.assertNotIn("printed on both sides", updated)
        self.assertIn("printed on the right-handed side", updated)

    def test_different_designs_upload_both_graphics(self):
        design_id = self._create_design()
        opposite = standalone_designs.save_design_source(
            self._image_bytes(),
            "opposite.png",
        )
        save_mug_setup(
            design_id,
            title="Coffee or Wine Mug",
            description="A two-sided message mug.",
            price_cents=1900,
            placement_scale=0.45,
            placement_x=0.5,
            placement_y=0.5,
            placement_mode="different",
            opposite_source_filename=opposite["filename"],
        )
        api = FakePrintifyAPI()

        create_mug_draft(design_id, confirmed=True, api=api)

        images = api.payloads[0]["print_areas"][0]["placeholders"][0]["images"]
        self.assertEqual(len(api.uploads), 2)
        self.assertEqual(len(images), 2)
        self.assertNotEqual(images[0]["id"], images[1]["id"])
        self.assertEqual(
            [image["x"] for image in images],
            [
                MUG_PROFILE["right_hand_x"],
                MUG_PROFILE["left_hand_x"],
            ],
        )

    def test_replacement_preserves_product_and_updates_existing_draft(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        api = FakePrintifyAPI()
        create_mug_draft(design_id, confirmed=True, api=api)
        original = db.get_standalone_design(design_id)
        original_path = self.assets_path / original["source_filename"]
        replacement = standalone_designs.save_design_source(
            self._image_bytes(),
            "corrected.png",
        )
        db.replace_standalone_design_source(
            design_id,
            source_filename=replacement["filename"],
            source_original_filename=replacement["original_filename"],
            image_width=replacement["width"],
            image_height=replacement["height"],
        )

        pending = db.get_standalone_design(design_id)
        self.assertEqual(pending["external_state"], "needs_update")
        self.assertEqual(
            pending["printify_product_id"], original["printify_product_id"]
        )
        self.assertTrue(original_path.is_file())

        result = update_mug_draft_graphics(
            design_id, confirmed=True, api=api
        )
        updated = db.get_standalone_design(design_id)
        self.assertEqual(result["outcome"], "updated")
        self.assertEqual(updated["external_state"], "created")
        self.assertEqual(len(api.updates), 1)
        self.assertEqual(api.updates[0][0], original["printify_product_id"])
        self.assertEqual(
            api.updates[0][1]["title"], pending["product_title"]
        )
        self.assertEqual(
            api.updates[0][1]["description"],
            pending["product_description"],
        )

    def test_copy_update_sends_only_title_and_description(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        api = FakePrintifyAPI()
        create_mug_draft(design_id, confirmed=True, api=api)
        before = db.get_standalone_design(design_id)
        db.update_standalone_product_copy(
            design_id,
            "mug_11oz",
            title="Teacher Mug – Updated wording",
            description="Updated description only.",
        )

        result = update_mug_draft_copy(
            design_id, confirmed=True, api=api
        )
        after = db.get_standalone_design(design_id)

        self.assertEqual(result["outcome"], "updated")
        self.assertEqual(
            api.updates[-1],
            (
                before["printify_product_id"],
                {
                    "title": "Teacher Mug – Updated wording",
                    "description": "Updated description only.",
                },
            ),
        )
        self.assertEqual(len(api.uploads), 1)
        self.assertEqual(after["external_state"], "created")
        self.assertEqual(
            after["production_asset_filename"],
            before["production_asset_filename"],
        )
        self.assertEqual(after["price_cents"], before["price_cents"])
        self.assertEqual(after["placement_x"], before["placement_x"])

    def test_copy_update_requires_confirmation_without_external_change(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        api = FakePrintifyAPI()
        create_mug_draft(design_id, confirmed=True, api=api)

        with self.assertRaisesRegex(ValueError, "Confirm the wording update"):
            update_mug_draft_copy(design_id, confirmed=False, api=api)

        self.assertEqual(api.updates, [])

    def test_opaque_replacement_is_saved_for_background_review(self):
        design_id = self._create_design()
        original = db.get_standalone_design(design_id)

        response = self.client.post(
            f"/designs/{design_id}/replace-image",
            files={
                "image": (
                    "checkerboard.png",
                    self._opaque_image_bytes(),
                    "image/png",
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("replaced=1", str(response.url))
        current = db.get_standalone_design(design_id)
        self.assertNotEqual(
            current["source_filename"], original["source_filename"]
        )
        self.assertTrue(
            (self.assets_path / original["source_filename"]).is_file()
        )

    def test_uniform_white_background_can_be_previewed_and_removed(self):
        response = self.client.post(
            "/designs",
            data={
                "name": "Everything is fine",
                "message": "Everything is fine.",
                "description": "A blue text mug.",
                "tags": "funny mug",
            },
            files={
                "image": (
                    "canva-download.png",
                    self._white_background_design_bytes(),
                    "image/png",
                )
            },
            follow_redirects=False,
        )
        design_id = int(response.headers["location"].split("/")[2].split("?")[0])
        original = db.get_standalone_design(design_id)

        page = self.client.get(f"/designs/{design_id}")
        self.assertIn("Remove the solid background?", page.text)
        preview = self.client.get(
            f"/designs/{design_id}/background-preview"
        )
        self.assertEqual(preview.status_code, 200)
        with Image.open(BytesIO(preview.content)) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertEqual(image.getpixel((1200, 500))[3], 255)

        cleaned = self.client.post(
            f"/designs/{design_id}/remove-background",
            data={"confirmed": "true"},
            follow_redirects=False,
        )
        self.assertEqual(cleaned.status_code, 303)
        current = db.get_standalone_design(design_id)
        self.assertNotEqual(current["source_filename"], original["source_filename"])
        self.assertTrue(
            (self.assets_path / original["source_filename"]).is_file()
        )
        with Image.open(self.assets_path / current["source_filename"]) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_status_check_discovers_and_records_etsy_listing(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        api = FakePrintifyAPI()
        create_mug_draft(design_id, confirmed=True, api=api)
        api.external = {
            "id": "4546385670",
            "handle": "https://www.etsy.com/listing/4546385670/example",
        }

        with patch(
            "web.standalone_designs.get_etsy_listing",
            return_value={"listing_id": 4546385670, "state": "active"},
        ):
            result = check_design_marketplace_status(
                design_id, printify_api=api
            )

        design = db.get_standalone_design(design_id)
        self.assertTrue(result["linked"])
        self.assertEqual(design["etsy_listing_id"], "4546385670")
        self.assertEqual(design["etsy_state"], "active")
        self.assertIsNone(design["etsy_paused_at"])

    def test_finish_etsy_page_is_read_only(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())

        with patch("web.app.check_design_marketplace_status") as check:
            response = self.client.get(f"/designs/{design_id}/etsy/finish")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Finish Etsy Setup", response.text)
        self.assertIn("Find Etsy Listing", response.text)
        check.assert_not_called()

    def test_finish_etsy_rechecks_once_before_waiting_without_republishing(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())

        with (
            patch(
                "web.app.check_design_marketplace_status",
                return_value={"linked": False},
            ) as check,
            patch("web.app.time.sleep") as pause,
        ):
            response = self.client.post(
                f"/designs/{design_id}/etsy/finish",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/designs/{design_id}/etsy/finish?waiting=1",
        )
        self.assertEqual(check.call_count, 2)
        check.assert_any_call(design_id)
        pause.assert_called_once_with(1)

    def test_finish_etsy_recheck_finds_new_listing_on_first_click(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())

        with (
            patch(
                "web.app.check_design_marketplace_status",
                side_effect=[{"linked": False}, {"linked": True}],
            ) as check,
            patch("web.app.time.sleep") as pause,
        ):
            response = self.client.post(
                f"/designs/{design_id}/etsy/finish",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/designs/{design_id}/etsy?linked=1",
        )
        self.assertEqual(check.call_count, 2)
        pause.assert_called_once_with(1)

    def test_finish_etsy_hands_linked_listing_to_existing_review(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())

        with patch(
            "web.app.check_design_marketplace_status",
            return_value={"linked": True},
        ):
            response = self.client.post(
                f"/designs/{design_id}/etsy/finish",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/designs/{design_id}/etsy?linked=1",
        )

    def test_manual_etsy_link_pause_reactivate_and_archive(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        api = FakePrintifyAPI()
        create_mug_draft(design_id, confirmed=True, api=api)

        with patch(
            "web.app.get_etsy_listing",
            return_value={"listing_id": 4546385670, "state": "active"},
        ):
            linked = self.client.post(
                f"/designs/{design_id}/marketplace/check",
                data={
                    "etsy_listing": (
                        "https://www.etsy.com/your/shops/me/"
                        "listing-editor/edit/4546385670#media"
                    )
                },
                follow_redirects=False,
            )
        self.assertEqual(linked.status_code, 303)
        self.assertEqual(
            db.get_standalone_design(design_id)["etsy_listing_id"],
            "4546385670",
        )

        with patch("web.app.update_etsy_listing_state") as update_state:
            paused = self.client.post(
                f"/designs/{design_id}/etsy/pause",
                data={"confirmed": "true"},
                follow_redirects=False,
            )
        self.assertEqual(paused.status_code, 303)
        update_state.assert_called_once_with("4546385670", "inactive")
        self.assertIsNotNone(
            db.get_standalone_design(design_id)["etsy_paused_at"]
        )

        with patch("web.app.update_etsy_listing_state") as update_state:
            restored = self.client.post(
                f"/designs/{design_id}/etsy/reactivate",
                data={"confirmed": "true"},
                follow_redirects=False,
            )
        self.assertEqual(restored.status_code, 303)
        update_state.assert_called_once_with("4546385670", "active")
        self.assertIsNone(
            db.get_standalone_design(design_id)["etsy_paused_at"]
        )

        archived = self.client.post(
            f"/designs/{design_id}/archive",
            data={"confirmed": "true"},
            follow_redirects=False,
        )
        self.assertEqual(archived.status_code, 303)
        self.assertEqual(
            db.get_standalone_design(design_id)["status"], "archived"
        )
        self.assertNotIn(
            "Every Collection Tells a Story",
            self.client.get("/designs").text,
        )
        self.assertIn(
            "Every Collection Tells a Story",
            self.client.get("/designs?show=archived").text,
        )

    def test_design_page_places_lifecycle_actions_on_each_product(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())
        create_mug_draft(
            design_id,
            confirmed=True,
            blueprint_key="mug_11oz_black_accent",
            api=FakePrintifyAPI(),
        )

        response = self.client.get(f"/designs/{design_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="product-mug_11oz"', response.text)
        self.assertIn(
            'id="product-mug_11oz_black_accent"', response.text
        )
        self.assertIn(
            'name="product_key" value="mug_11oz"', response.text
        )
        self.assertIn(
            'name="product_key" value="mug_11oz_black_accent"',
            response.text,
        )
        self.assertEqual(response.text.count("Check status"), 2)
        self.assertEqual(response.text.count("Archive design"), 1)

    def test_pinterest_bundle_is_product_specific_and_read_only(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            product_key="mug_11oz",
            etsy_listing_id="1111111111",
            etsy_listing_url="https://www.etsy.com/listing/1111111111",
            etsy_state="active",
            paused=False,
        )
        db.record_standalone_marketplace_status(
            design_id,
            product_key="mug_11oz_black_accent",
            etsy_listing_id="2222222222",
            etsy_listing_url="https://www.etsy.com/listing/2222222222",
            etsy_state="active",
            paused=False,
        )
        before = [dict(row) for row in db.list_standalone_design_products(design_id)]

        white = self.client.get(
            f"/designs/{design_id}/products/mug_11oz/pinterest"
        )
        accent = self.client.get(
            f"/designs/{design_id}/products/mug_11oz_black_accent/pinterest"
        )

        self.assertEqual(white.status_code, 200)
        self.assertEqual(accent.status_code, 200)
        self.assertIn("White Ceramic Mug", white.text)
        self.assertIn("Black Accent Mug 11 oz", accent.text)
        self.assertIn("https://www.etsy.com/listing/1111111111", white.text)
        self.assertIn("https://www.etsy.com/listing/2222222222", accent.text)
        self.assertIn("Publish this Pin", accent.text)
        self.assertEqual(
            before,
            [dict(row) for row in db.list_standalone_design_products(design_id)],
        )

    def test_pinterest_bundle_image_is_downloadable_1000_by_1500_png(self):
        design_id = self._create_design()
        self._save_accent_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            product_key="mug_11oz_black_accent",
            etsy_listing_id="2222222222",
            etsy_listing_url="https://www.etsy.com/listing/2222222222",
            etsy_state="active",
            paused=False,
        )

        response = self.client.get(
            f"/designs/{design_id}/products/mug_11oz_black_accent/"
            "pinterest/image?download=true"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertIn("attachment", response.headers["content-disposition"])
        with Image.open(BytesIO(response.content)) as image:
            self.assertEqual(image.size, (1000, 1500))

    def test_pinterest_bundle_prefers_exact_product_context_mockup(self):
        product = {
            "images": [
                {
                    "src": "https://images.printify.com/front.jpg?camera_label=front",
                    "is_default": True,
                },
                {
                    "src": "https://images.printify.com/context.jpg?camera_label=context",
                    "is_default": False,
                },
            ]
        }

        self.assertEqual(
            select_printify_context_mockup(product),
            "https://images.printify.com/context.jpg?camera_label=context",
        )

    def test_pinterest_bundle_requires_linked_etsy_product(self):
        design_id = self._create_design()
        self._save_setup(design_id)

        response = self.client.get(
            f"/designs/{design_id}/products/mug_11oz/pinterest"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Connect the Etsy listing", response.text)

    def test_pinterest_copy_uses_teacher_board_and_exact_product_link(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        db.update_standalone_design(
            design_id,
            name="I teach the thinkers of tomorrow",
            message="I teach the thinkers of tomorrow.",
            description="A thoughtful teacher mug.",
            tags="teacher, teacher gift, classroom, biology",
        )
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="1111111111",
            etsy_listing_url="https://www.etsy.com/listing/1111111111",
            etsy_state="active",
            paused=False,
        )

        bundle = pinterest_bundle_copy(
            db.get_standalone_design(design_id, "mug_11oz"), "mug_11oz"
        )

        self.assertEqual(bundle["board"], "Teacher Gift Ideas")
        self.assertEqual(bundle["topics"], ["Teacher gifts", "Biology", "Coffee mugs"])
        self.assertEqual(bundle["link"], "https://www.etsy.com/listing/1111111111")
        self.assertIn("white ceramic mug", bundle["alt_text"].lower())

    def test_accent_marketplace_actions_do_not_change_white_mug(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        create_mug_draft(design_id, confirmed=True, api=FakePrintifyAPI())
        create_mug_draft(
            design_id,
            confirmed=True,
            blueprint_key="mug_11oz_black_accent",
            api=FakePrintifyAPI(),
        )
        db.record_standalone_marketplace_status(
            design_id,
            product_key="mug_11oz",
            etsy_listing_id="1111111111",
            etsy_state="active",
            paused=False,
        )

        with patch(
            "web.app.get_etsy_listing",
            return_value={"listing_id": 2222222222, "state": "active"},
        ):
            linked = self.client.post(
                f"/designs/{design_id}/marketplace/check",
                data={
                    "product_key": "mug_11oz_black_accent",
                    "etsy_listing": "https://www.etsy.com/listing/2222222222",
                },
                follow_redirects=False,
            )

        self.assertEqual(linked.status_code, 303)
        self.assertIn("product_key=mug_11oz_black_accent", linked.headers["location"])
        self.assertEqual(
            db.get_standalone_design(design_id, "mug_11oz")["etsy_listing_id"],
            "1111111111",
        )
        self.assertEqual(
            db.get_standalone_design(
                design_id, "mug_11oz_black_accent"
            )["etsy_listing_id"],
            "2222222222",
        )
        review = self.client.get(
            f"/designs/{design_id}/products/mug_11oz_black_accent"
        )
        self.assertIn("Review &amp; Sync Etsy Details", review.text)
        self.assertIn(
            f'/designs/{design_id}/etsy?product_key=mug_11oz_black_accent',
            review.text,
        )

        with patch("web.app.update_etsy_listing_state") as update_state:
            paused = self.client.post(
                f"/designs/{design_id}/etsy/pause",
                data={
                    "confirmed": "true",
                    "product_key": "mug_11oz_black_accent",
                },
                follow_redirects=False,
            )
        self.assertEqual(paused.status_code, 303)
        update_state.assert_called_once_with("2222222222", "inactive")
        self.assertIsNone(
            db.get_standalone_design(design_id, "mug_11oz")["etsy_paused_at"]
        )
        self.assertIsNotNone(
            db.get_standalone_design(
                design_id, "mug_11oz_black_accent"
            )["etsy_paused_at"]
        )

    def test_etsy_details_review_is_read_only_and_shows_changes(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="4546385670",
            etsy_listing_url="https://www.etsy.com/listing/4546385670",
            etsy_state="active",
            paused=False,
        )
        with (
            patch(
                "web.app.get_etsy_listing",
                return_value={
                    "title": "Old title",
                    "description": "Old description",
                    "tags": ["old tag"],
                    "state": "active",
                },
            ),
            patch("web.app.update_etsy_listing") as update,
        ):
            response = self.client.get(f"/designs/{design_id}/etsy")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sync Etsy Details", response.text)
        self.assertIn("Old title", response.text)
        update.assert_not_called()

    def test_etsy_details_sync_requires_confirmation(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="4546385670",
            etsy_listing_url="https://www.etsy.com/listing/4546385670",
            etsy_state="active",
            paused=False,
        )
        with patch("web.app.update_etsy_listing") as update:
            response = self.client.post(
                f"/designs/{design_id}/etsy/sync", data={}
            )
        self.assertEqual(response.status_code, 400)
        update.assert_not_called()

    def test_etsy_details_sync_sends_saved_copy_and_tags(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            etsy_listing_id="4546385670",
            etsy_listing_url="https://www.etsy.com/listing/4546385670",
            etsy_state="active",
            paused=False,
        )
        design = db.get_standalone_design(design_id)
        with (
            patch(
                "web.app.get_etsy_listing",
                return_value={"listing_id": 4546385670, "state": "active"},
            ),
            patch("web.app.update_etsy_listing") as update,
        ):
            response = self.client.post(
                f"/designs/{design_id}/etsy/sync",
                data={"confirmed": "true"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIsNotNone(
            db.get_standalone_design(design_id)["etsy_last_synced_at"]
        )
        update.assert_called_once_with(
            "4546385670",
            title=design["product_title"],
            description=design["product_description"],
            tags=["storyteller gift", "creative mug"],
        )

    def _create_refreshable_portfolio_slot(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        white_api = FakePrintifyAPI()
        accent_api = FakePrintifyAPI()
        create_mug_draft(design_id, confirmed=True, api=white_api)
        create_mug_draft(
            design_id,
            confirmed=True,
            blueprint_key="mug_11oz_black_accent",
            api=accent_api,
        )
        return design_id

    def test_portfolio_refresh_review_performs_no_external_updates(self):
        design_id = self._create_refreshable_portfolio_slot()
        before = [dict(row) for row in db.list_standalone_design_products(design_id)]
        with patch("web.portfolio_refresh.update_mug_draft_graphics") as update:
            page = self.client.get(f"/designs/{design_id}/refresh")
            preview = self.client.post(
                f"/designs/{design_id}/refresh/preview",
                data={"message": "Small steps shape bright futures."},
            )
        after = [dict(row) for row in db.list_standalone_design_products(design_id)]

        self.assertEqual(page.status_code, 200)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("White Ceramic Mug", preview.text)
        self.assertIn("Black Accent Mug 11 oz", preview.text)
        self.assertEqual(before, after)
        update.assert_not_called()

    def test_portfolio_refresh_requires_explicit_confirmation(self):
        design_id = self._create_refreshable_portfolio_slot()
        with patch("web.portfolio_refresh.update_mug_draft_graphics") as update:
            response = self.client.post(
                f"/designs/{design_id}/refresh/apply",
                data={"message": "Small steps shape bright futures."},
            )
        self.assertEqual(response.status_code, 400)
        update.assert_not_called()

    def test_completed_portfolio_refresh_can_start_another_cycle(self):
        design_id = self._create_refreshable_portfolio_slot()
        db.set_standalone_design_refresh_state(
            design_id, "complete", "Previous refresh finished."
        )

        page = self.client.get(f"/designs/{design_id}/refresh")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Refresh complete", page.text)
        self.assertIn("Start another refresh", page.text)
        self.assertIn('name="message"', page.text)
        self.assertIn("Review the Etsy listings", page.text)

    def test_portfolio_refresh_updates_both_slots_without_replacing_ids_or_setup(self):
        design_id = self._create_refreshable_portfolio_slot()
        before = {
            row["product_type"]: dict(row)
            for row in db.list_standalone_design_products(design_id)
        }
        calls = []

        def update(design_id, *, confirmed, blueprint_key, source_filename):
            calls.append((design_id, confirmed, blueprint_key, source_filename))
            return {"outcome": "updated", "message": "updated"}

        results = apply_portfolio_refresh(
            design_id,
            "Small steps shape bright futures.",
            confirmed=True,
            update_printify=update,
        )
        after = {
            row["product_type"]: dict(row)
            for row in db.list_standalone_design_products(design_id)
        }

        self.assertEqual([item["outcome"] for item in results], ["updated", "updated"])
        self.assertEqual(
            {item[2] for item in calls},
            {"mug_11oz", "mug_11oz_black_accent"},
        )
        self.assertEqual(calls[0][3], calls[1][3])
        for key in before:
            self.assertEqual(
                after[key]["printify_product_id"], before[key]["printify_product_id"]
            )
            self.assertEqual(after[key]["price_cents"], before[key]["price_cents"])
            self.assertEqual(after[key]["placement_x"], before[key]["placement_x"])
            self.assertEqual(after[key]["placement_y"], before[key]["placement_y"])
            self.assertEqual(after[key]["placement_scale"], before[key]["placement_scale"])
            self.assertEqual(after[key]["production_asset_filename"], calls[0][3])
        self.assertEqual(
            db.get_standalone_design(design_id)["refresh_state"],
            "awaiting_printify",
        )

    def test_portfolio_refresh_failure_keeps_that_products_previous_asset(self):
        design_id = self._create_refreshable_portfolio_slot()
        old_assets = {
            row["product_type"]: row["production_asset_filename"]
            for row in db.list_standalone_design_products(design_id)
        }

        def update(design_id, *, confirmed, blueprint_key, source_filename):
            if blueprint_key == "mug_11oz":
                return {"outcome": "failed", "message": "Printify rejected update"}
            return {"outcome": "updated", "message": "updated"}

        results = apply_portfolio_refresh(
            design_id,
            "Small steps shape bright futures.",
            confirmed=True,
            update_printify=update,
        )
        products = {
            row["product_type"]: row
            for row in db.list_standalone_design_products(design_id)
        }

        self.assertEqual(results[0]["outcome"], "failed")
        self.assertEqual(results[1]["outcome"], "updated")
        self.assertEqual(
            products["mug_11oz"]["production_asset_filename"],
            old_assets["mug_11oz"],
        )
        self.assertNotEqual(
            products["mug_11oz_black_accent"]["production_asset_filename"],
            old_assets["mug_11oz_black_accent"],
        )
        self.assertEqual(
            db.get_standalone_design(design_id)["refresh_state"], "needs_review"
        )


if __name__ == "__main__":
    unittest.main()
