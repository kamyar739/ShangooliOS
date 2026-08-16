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
    normalize_pinterest_style,
    pinterest_bundle_copy,
    pinterest_style_options,
    select_printify_context_mockup,
)
from web.portfolio_refresh import apply_portfolio_refresh, apply_uploaded_portfolio_refresh
from web.mug_gallery import (
    approve_mug_gallery,
    prepare_mug_gallery,
    sync_mug_gallery_to_etsy,
    upload_mug_gallery,
    save_product_thumbnail,
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

    def test_product_thumbnail_is_saved_locally_for_catalog_reuse(self):
        design_id = self._create_refreshable_portfolio_slot()
        image = Image.new("RGB", (900, 1200), "white")
        buffer = BytesIO()
        image.save(buffer, "JPEG")
        original_root = mug_gallery.GALLERY_ROOT
        mug_gallery.GALLERY_ROOT = self.root / "galleries"
        try:
            filename = save_product_thumbnail(
                design_id,
                "mug_11oz_black_accent",
                buffer.getvalue(),
                "right-side.jpg",
            )
            product = db.get_standalone_design(
                design_id, "mug_11oz_black_accent"
            )
            self.assertEqual(product["product_thumbnail_filename"], filename)
            self.assertTrue((mug_gallery.GALLERY_ROOT / filename).is_file())
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
        self.assertIn("Launch Black Accent mug", page.text)
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
            {"mug_11oz_black_accent"},
        )
        self.assertTrue(
            all(product["placement_mode"] == "front" for product in products)
        )
        launch = self.client.get(response.headers["location"])
        self.assertEqual(launch.status_code, 200)
        self.assertIn("Launch Black Accent mug", launch.text)
        self.assertIn("Create Mug Draft", launch.text)
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
        self.assertNotIn("Upload finished design", page.text)
        self.assertNotIn("Quick text design", page.text)
        self.assertIn("Update Shangooli.com", page.text)
        collection_page = self.client.get("/designs?collection=teacher")
        self.assertIn("Upload finished design", collection_page.text)
        self.assertIn("Quick text design", collection_page.text)
        self.assertIn("Pinterest launch", collection_page.text)
        self.assertNotIn(">Text Ideas</a>", page.text)

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
        self.assertTrue(
            any(
                row["id"] == new_idea["id"]
                for row in db.list_mug_text_ideas(include_deleted=True)
            )
        )
        restored = self.client.post(
            "/designs/text-ideas",
            data={"category": "Restored Category", "text": "A fresh idea."},
            follow_redirects=False,
        )
        self.assertEqual(restored.status_code, 303)
        restored_idea = next(
            row for row in db.list_mug_text_ideas() if row["text"] == "A fresh idea."
        )
        self.assertEqual(restored_idea["id"], new_idea["id"])
        self.assertEqual(restored_idea["category"], "Restored Category")

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
        self._save_accent_setup(created_ids[0])
        db.set_standalone_product_state(
            created_ids[0],
            "created",
            printify_product_id="printify-design-1",
            printify_product_url="https://printify.example/product/1",
            product_key="mug_11oz_black_accent",
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
        self.assertNotIn(">Tags<", search.text)

        biology = self.client.get("/designs?tag=Biology")
        self.assertEqual(biology.status_code, 200)
        self.assertIn("Catalog Design 17", biology.text)
        self.assertNotIn("Catalog Design 16", biology.text)

        printify = self.client.get("/designs?status=printify")
        self.assertEqual(printify.status_code, 200)
        self.assertIn("Catalog Design 00", printify.text)
        self.assertNotIn("Catalog Design 01", printify.text)

        catalog = self.client.get("/designs")
        self.assertIn("Black Accent Mug 11 oz", catalog.text)
        self.assertNotIn("White Ceramic Mug", catalog.text)

        accent = self.client.get(
            "/designs?product=mug_11oz_black_accent"
        )
        self.assertIn("Catalog Design 01", accent.text)
        self.assertIn("Catalog Design 00", accent.text)

        no_product = self.client.get("/designs?product=none")
        self.assertIn("Catalog Design 25", no_product.text)
        self.assertNotIn("Catalog Design 00", no_product.text)
        self.assertNotIn("Catalog Design 01", no_product.text)

    def test_mug_collection_foundation_assigns_teacher_and_filters_catalog(self):
        teacher_id = self._create_design()
        teacher = db.get_standalone_design(teacher_id)
        collections = [dict(row) for row in db.list_mug_collections()]

        self.assertEqual(collections[0]["code"], "TEACHER")
        self.assertEqual(collections[0]["default_product_key"], "mug_11oz_black_accent")
        self.assertEqual(teacher["mug_collection_id"], collections[0]["id"])

        page = self.client.get("/designs?collection=teacher")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Every Collection Tells a Story", page.text)
        self.assertIn("Teacher", page.text)

        collections_page = self.client.get("/designs/collections")
        self.assertEqual(collections_page.status_code, 200)
        self.assertIn("Teacher Mugs", collections_page.text)
        self.assertIn("Everyday Mugs", collections_page.text)
        self.assertNotIn("Design Library", collections_page.text)
        self.assertIn("Paused white mugs preserved", collections_page.text)

    def test_creating_future_collection_does_not_publish_or_move_designs(self):
        design_id = self._create_design()
        response = self.client.post(
            "/designs/collections",
            data={
                "code": "DOCTOR",
                "name": "Doctor Mugs",
                "profession": "Doctor",
                "description": "Mugs for medical professionals.",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        collections = {row["code"]: row for row in db.list_mug_collections()}
        self.assertIn("DOCTOR", collections)
        self.assertEqual(collections["DOCTOR"]["active_design_count"], 0)
        self.assertEqual(
            db.get_standalone_design(design_id)["mug_collection_id"],
            collections["TEACHER"]["id"],
        )

    def test_doctor_ideas_are_separate_and_launch_is_resumable(self):
        doctor_page = self.client.get("/designs/text-ideas?collection=DOCTOR")
        self.assertEqual(doctor_page.status_code, 200)
        self.assertIn("Doctor Mugs", doctor_page.text)
        self.assertNotIn("I Had a Plan. Then the Bell Rang.", doctor_page.text)

        first = db.create_mug_text_idea(
            "Doctor Humor", "Trust Me, I Read the Chart.", "DOCTOR"
        )
        second = db.create_mug_text_idea(
            "Doctor Humor", "Powered by Rounds and Coffee.", "DOCTOR"
        )
        response = self.client.post(
            "/designs/text-ideas/launch",
            data={
                "collection": "DOCTOR",
                "target_count": "2",
                "idea_ids": [str(first), str(second)],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/designs/collections/DOCTOR/launch")

        launch_page = self.client.get(response.headers["location"])
        self.assertEqual(launch_page.status_code, 200)
        self.assertIn("Launch Doctor Mugs", launch_page.text)
        self.assertIn("Trust Me, I Read the Chart.", launch_page.text)
        self.assertIn("Nothing external has been created", launch_page.text)

        launch, items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(launch["current_step"], "artwork")
        self.assertEqual(len(items), 2)

    def test_collection_launch_artwork_format_is_saved_per_mug(self):
        idea_id = db.create_mug_text_idea(
            "Doctor Humor", "Powered by Rounds and Coffee.", "DOCTOR"
        )
        db.lock_mug_collection_launch_ideas("DOCTOR", [idea_id], 1)
        _, items = db.get_mug_collection_launch("DOCTOR")
        item_id = items[0]["id"]
        self.assertEqual(items[0]["artwork_mode"], "text_only")

        for artwork_mode, label in (
            ("text_graphics", "Text + Accent Graphics"),
            ("graphic_only", "Graphic Only"),
            ("text_only", "Text Only"),
        ):
            response = self.client.post(
                "/designs/collections/DOCTOR/launch/artwork-mode",
                data={"item_id": str(item_id), "artwork_mode": artwork_mode},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(
                response.headers["location"],
                f"/designs/collections/DOCTOR/launch#artwork-{item_id}",
            )
            _, refreshed_items = db.get_mug_collection_launch("DOCTOR")
            self.assertEqual(refreshed_items[0]["artwork_mode"], artwork_mode)
            page = self.client.get("/designs/collections/DOCTOR/launch")
            self.assertIn(label, page.text)

        invalid = self.client.post(
            "/designs/collections/DOCTOR/launch/artwork-mode",
            data={"item_id": str(item_id), "artwork_mode": "anything"},
            follow_redirects=False,
        )
        self.assertEqual(invalid.status_code, 400)
        _, unchanged_items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(unchanged_items[0]["artwork_mode"], "text_only")

        approval_page = self.client.get("/designs/collections/DOCTOR/launch")
        self.assertIn("Approve choice and continue", approval_page.text)
        self.assertEqual(approval_page.text.count("Artwork option "), 6)
        line_breaks = self.client.post(
            "/designs/collections/DOCTOR/launch/artwork-message",
            data={
                "item_id": str(item_id),
                "artwork_message": "Powered by\nRounds and\nCoffee.",
            },
            follow_redirects=False,
        )
        self.assertEqual(line_breaks.status_code, 303)
        _, relaid_items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(
            relaid_items[0]["artwork_message"],
            "Powered by\nRounds and\nCoffee.",
        )
        refreshed_choices = self.client.get("/designs/collections/DOCTOR/launch")
        self.assertIn("Powered by\nRounds and\nCoffee.", refreshed_choices.text)
        revised_phrase = self.client.post(
            "/designs/collections/DOCTOR/launch/artwork-message",
            data={
                "item_id": str(item_id),
                "artwork_message": "Rounds first.\nCoffee immediately after.",
            },
            follow_redirects=False,
        )
        self.assertEqual(revised_phrase.status_code, 303)
        _, revised_items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(
            revised_items[0]["message"],
            "Rounds first. Coffee immediately after.",
        )
        self.assertEqual(
            revised_items[0]["artwork_message"],
            "Rounds first.\nCoffee immediately after.",
        )
        original_idea = next(
            row for row in db.list_mug_text_ideas("DOCTOR") if row["id"] == idea_id
        )
        self.assertEqual(original_idea["text"], "Powered by Rounds and Coffee.")
        approved = self.client.post(
            "/designs/collections/DOCTOR/launch/artwork-approve",
            data={"item_id": str(item_id), "style_variant": "2"},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303)
        launch, approved_items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(launch["current_step"], "printify")
        self.assertEqual(approved_items[0]["artwork_state"], "approved")
        self.assertEqual(approved_items[0]["artwork_style_variant"], 2)
        self.assertTrue(approved_items[0]["artwork_filename"])
        design = db.get_standalone_design(
            approved_items[0]["standalone_design_id"],
            "mug_11oz_black_accent",
        )
        self.assertEqual(
            db.get_mug_collection_profile_for_design(design["id"])["code"],
            "DOCTOR",
        )
        self.assertIsNotNone(design["product_id"])
        completed_page = self.client.get("/designs/collections/DOCTOR/launch")
        self.assertIn("All 1 artworks are approved.", completed_page.text)
        self.assertIn("Printify drafts and placement", completed_page.text)
        self.assertIn("Ready", completed_page.text)
        self.assertIn("Reopen artwork", completed_page.text)

        original_design_id = approved_items[0]["standalone_design_id"]
        original_filename = approved_items[0]["artwork_filename"]
        reopened = self.client.post(
            "/designs/collections/DOCTOR/launch/artwork-reopen",
            data={"item_id": str(item_id)},
            follow_redirects=False,
        )
        self.assertEqual(reopened.status_code, 303)
        launch, reopened_items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(launch["current_step"], "artwork")
        self.assertEqual(reopened_items[0]["artwork_state"], "waiting")
        self.client.post(
            "/designs/collections/DOCTOR/launch/artwork-message",
            data={
                "item_id": str(item_id),
                "artwork_message": "Revised before\nPrintify begins.",
            },
            follow_redirects=False,
        )
        reapproved = self.client.post(
            "/designs/collections/DOCTOR/launch/artwork-approve",
            data={"item_id": str(item_id), "style_variant": "4"},
            follow_redirects=False,
        )
        self.assertEqual(reapproved.status_code, 303)
        launch, reapproved_items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(launch["current_step"], "printify")
        self.assertEqual(
            reapproved_items[0]["standalone_design_id"], original_design_id
        )
        self.assertNotEqual(
            reapproved_items[0]["artwork_filename"], original_filename
        )
        revised_design = db.get_standalone_design(
            original_design_id, "mug_11oz_black_accent"
        )
        self.assertEqual(revised_design["message"], "Revised before Printify begins.")
        self.assertEqual(
            revised_design["production_asset_filename"],
            reapproved_items[0]["artwork_filename"],
        )

        def create_fake_launch_draft(design_id, **kwargs):
            db.set_standalone_product_state(
                design_id,
                "created",
                "Unpublished mug draft created in Printify.",
                product_key="mug_11oz_black_accent",
                printify_product_id="doctor-draft-1",
                printify_product_url="https://printify.example/doctor-draft-1",
            )
            return {
                "outcome": "created",
                "message": "Unpublished mug draft created in Printify.",
                "product_url": "https://printify.example/doctor-draft-1",
            }

        with patch(
            "web.app.create_mug_draft", side_effect=create_fake_launch_draft
        ) as create_draft:
            draft = self.client.post(
                "/designs/collections/DOCTOR/launch/printify-draft",
                data={"item_id": str(item_id), "confirmed": "true"},
                follow_redirects=False,
            )
        self.assertEqual(draft.status_code, 303)
        create_draft.assert_called_once()
        _, draft_items = db.get_mug_collection_launch("DOCTOR")
        self.assertEqual(draft_items[0]["printify_state"], "draft_created")
        self.assertEqual(draft_items[0]["placement_state"], "needs_review")
        printify_page = self.client.get("/designs/collections/DOCTOR/launch")
        self.assertIn("Open draft in Printify", printify_page.text)
        self.assertIn("https://printify.example/doctor-draft-1", printify_page.text)

    def test_doctor_candidate_generator_creates_fifty_reviewable_ideas(self):
        response = self.client.post(
            "/designs/text-ideas/generate",
            data={"collection": "DOCTOR", "count": "50"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("generated=50", response.headers["location"])
        doctor_ideas = db.list_mug_text_ideas("DOCTOR")
        self.assertEqual(len(doctor_ideas), 50)
        self.assertTrue(all(row["mug_collection_code"] == "DOCTOR" for row in doctor_ideas))
        normalized_texts = {" ".join(row["text"].lower().split()) for row in doctor_ideas}
        self.assertEqual(len(normalized_texts), 50)
        self.assertNotIn("Doctor Appreciation", {row["category"] for row in doctor_ideas})
        self.assertNotIn("Medical Team", {row["category"] for row in doctor_ideas})

        repeated = self.client.post(
            "/designs/text-ideas/generate",
            data={"collection": "DOCTOR", "count": "50"},
            follow_redirects=False,
        )
        self.assertIn("generated=50", repeated.headers["location"])
        doctor_ideas = db.list_mug_text_ideas("DOCTOR")
        self.assertEqual(len(doctor_ideas), 100)
        self.assertEqual(
            len({" ".join(row["text"].lower().split()) for row in doctor_ideas}),
            100,
        )
        self.assertTrue(
            all(row["category"] == "Double-Take Wit" for row in doctor_ideas[50:])
        )
        deleted_text = doctor_ideas[0]["text"]
        db.delete_mug_text_idea(doctor_ideas[0]["id"])
        third_batch = self.client.post(
            "/designs/text-ideas/generate",
            data={"collection": "DOCTOR", "count": "50"},
            follow_redirects=False,
        )
        self.assertIn("generated=50", third_batch.headers["location"])
        visible_texts = {row["text"] for row in db.list_mug_text_ideas("DOCTOR")}
        self.assertEqual(len(visible_texts), 149)
        self.assertNotIn(deleted_text, visible_texts)

        collection_home = self.client.get(
            "/designs/collections/DOCTOR", follow_redirects=False
        )
        self.assertEqual(collection_home.status_code, 303)
        self.assertEqual(
            collection_home.headers["location"],
            "/designs?collection=doctor",
        )
        returned_page = self.client.get(collection_home.headers["location"])
        self.assertIn("Powered by Rounds and Coffee.", returned_page.text)
        self.assertIn("Future potentials", returned_page.text)
        self.assertIn("Doctor Mugs", returned_page.text)

        ideas_page = self.client.get("/designs/text-ideas?collection=DOCTOR")
        self.assertIn('id="idea-total-count">149 ideas', ideas_page.text)

    def test_doctor_candidate_can_be_edited_without_moving_or_resetting_it(self):
        idea_id = db.create_mug_text_idea(
            "Doctor Reality", "Powered by Rounds and Coffee.", "DOCTOR"
        )
        db.rate_mug_text_idea(idea_id, 4)

        response = self.client.post(
            f"/designs/text-ideas/{idea_id}/edit",
            data={
                "collection": "DOCTOR",
                "category": "  Doctor Humor  ",
                "text": "  Powered by Rounds, Coffee, and Good Notes.  ",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/designs/text-ideas?collection=DOCTOR&updated=1",
        )
        edited = [row for row in db.list_mug_text_ideas("DOCTOR") if row["id"] == idea_id][0]
        self.assertEqual(edited["category"], "Doctor Humor")
        self.assertEqual(edited["text"], "Powered by Rounds, Coffee, and Good Notes.")
        self.assertEqual(edited["rating"], 4)
        self.assertFalse(any(row["id"] == idea_id for row in db.list_mug_text_ideas("TEACHER")))

        page = self.client.get(response.headers["location"])
        self.assertIn("Text idea updated.", page.text)
        self.assertIn("Save changes", page.text)

    def test_design_catalog_pinterest_rating_and_manual_order(self):
        first_id = self._create_design()
        self._save_accent_setup(first_id)
        second_id = db.create_standalone_design(
            name="Second Rated Design",
            message="Second",
            description="Pinterest rating test",
            tags="teacher",
            source_filename="second.png",
            source_original_filename="second.png",
            image_width=2400,
            image_height=1000,
        )
        self._save_accent_setup(second_id)

        rated = self.client.post(
            f"/designs/{first_id}/products/mug_11oz_black_accent/pinterest-rating",
            data={"rating": "3"},
            follow_redirects=False,
        )
        self.assertEqual(rated.status_code, 303)
        products = {
            row["design_id"]: row for row in db.list_standalone_product_summaries()
        }
        self.assertEqual(products[first_id]["pinterest_ad_rating"], 3)

        reordered = self.client.post(
            "/designs/reorder", json={"ids": [second_id, first_id]}
        )
        self.assertEqual(reordered.status_code, 200)
        ordered_ids = [row["id"] for row in db.list_standalone_designs()]
        self.assertEqual(ordered_ids[:2], [second_id, first_id])

        sorted_page = self.client.get("/designs?sort=pinterest_desc")
        self.assertLess(
            sorted_page.text.index("Every Collection Tells a Story"),
            sorted_page.text.index("Second Rated Design"),
        )

    def test_design_catalog_filters_products_needing_etsy_sync(self):
        needs_sync_id = self._create_design()
        self._save_accent_setup(needs_sync_id)
        db.record_standalone_marketplace_status(
            needs_sync_id,
            product_key="mug_11oz_black_accent",
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
        self._save_accent_setup(synced_id)
        db.record_standalone_marketplace_status(
            synced_id,
            product_key="mug_11oz_black_accent",
            etsy_listing_id="4546000002",
            etsy_state="active",
            paused=False,
        )
        db.mark_standalone_etsy_synced(
            synced_id, product_key="mug_11oz_black_accent"
        )

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
        self.assertNotIn('id="product-mug_11oz"', response.text)
        self.assertIn(
            'id="product-mug_11oz_black_accent"', response.text
        )
        self.assertNotIn('name="product_key" value="mug_11oz"', response.text)
        self.assertIn(
            'name="product_key" value="mug_11oz_black_accent"',
            response.text,
        )
        self.assertEqual(response.text.count("Check status"), 1)
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
        self.assertIn(
            "https://shangooli.com/mugs/every-collection-tells-a-story",
            white.text,
        )
        self.assertIn(
            "https://shangooli.com/mugs/every-collection-tells-a-story",
            accent.text,
        )
        self.assertIn("Publish this Pin", accent.text)
        self.assertIn("Six ready-to-use classroom scenes", accent.text)
        self.assertIn("High-school classroom", accent.text)
        self.assertIn("Kindergarten art", accent.text)
        self.assertIn("Kindergarten reading", accent.text)
        self.assertIn("Kindergarten learning", accent.text)
        self.assertEqual(
            before,
            [dict(row) for row in db.list_standalone_design_products(design_id)],
        )

    def test_pinterest_full_launch_reviews_only_live_unpaused_products(self):
        design_id = self._create_design()
        self._save_setup(design_id)
        self._save_accent_setup(design_id)
        db.record_standalone_marketplace_status(
            design_id,
            product_key="mug_11oz",
            etsy_listing_id="1111111111",
            etsy_listing_url="https://www.etsy.com/listing/1111111111",
            etsy_state="inactive",
            paused=True,
        )
        db.record_standalone_marketplace_status(
            design_id,
            product_key="mug_11oz_black_accent",
            etsy_listing_id="2222222222",
            etsy_listing_url="https://www.etsy.com/listing/2222222222",
            etsy_state="active",
            paused=False,
        )

        page = self.client.get("/designs/pinterest-launch?collection=TEACHER")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Pinterest Launch", page.text)
        self.assertIn("1 active Etsy mugs", page.text)
        self.assertIn("Black Accent Mug 11 oz", page.text)
        self.assertNotIn("White Ceramic Mug", page.text)

    def test_doctor_pinterest_launch_uses_only_medical_office_scenes(self):
        options = pinterest_style_options("DOCTOR")

        self.assertEqual(len(options), 6)
        self.assertTrue(all(item["key"].startswith("doctor_") for item in options))
        self.assertEqual(
            normalize_pinterest_style("doctor_exam_room", "DOCTOR"),
            "doctor_exam_room",
        )
        with self.assertRaises(ValueError):
            normalize_pinterest_style("classroom_story", "DOCTOR")

    def test_pinterest_full_launch_saves_review_and_exports_official_columns(self):
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
        saved = self.client.post(
            f"/designs/pinterest-launch/item/{design_id}/mug_11oz_black_accent",
            data={"style": "kindergarten_art", "approved": "1", "collection": "TEACHER"},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303)
        state = db.list_pinterest_launch_states()[0]
        self.assertEqual(state["selected_style"], "kindergarten_art")
        self.assertEqual(state["approved"], 1)

        export = self.client.get(
            "/designs/pinterest-launch/export.csv?collection=TEACHER&start_date=2026-08-20&pins_per_day=2"
        )
        text = export.content.decode("utf-8-sig")
        self.assertEqual(export.status_code, 200)
        self.assertIn(
            "Title,Media URL,Pinterest board,Thumbnail,Description,Link,Publish date,Keywords",
            text,
        )
        self.assertIn("https://shangooli.com/images/pinterest-launch/", text)
        self.assertIn("https://shangooli.com/mugs/every-collection-tells-a-story", text)
        self.assertIn("2026-08-20", text)

    def test_pinterest_full_launch_can_schedule_every_pin_at_once(self):
        items = [
            {
                "approved": True,
                "filename": f"pin-{number}.png",
                "bundle": {
                    "title": f"Pin {number}",
                    "board": "Teacher Gift Ideas",
                    "description": "Teacher mug",
                    "link": f"https://shangooli.com/mugs/pin-{number}",
                    "topics": ["Teacher gifts", "Coffee mugs"],
                },
            }
            for number in range(3)
        ]
        from web.pinterest_launch import launch_csv

        content = launch_csv(
            items, start_date="2026-08-20", pins_per_day=0
        ).decode("utf-8-sig")

        self.assertEqual(content.count("2026-08-20"), 3)
        self.assertNotIn("2026-08-21", content)

    def test_pinterest_launch_verifies_public_images_before_download(self):
        with patch(
            "web.app.verify_public_pin_urls",
            return_value={
                "checked_count": 20,
                "verified_count": 20,
                "failed_urls": [],
            },
        ):
            response = self.client.post(
                "/designs/pinterest-launch/verify-public",
                data={
                    "collection": "DOCTOR",
                    "start_date": "2026-08-20",
                    "pins_per_day": "0",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("public_verified=1", response.headers["location"])
        self.assertIn("verified_count=20", response.headers["location"])

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

        for style in (
            "classroom_story",
            "elementary_classroom",
            "middle_school_science",
            "kindergarten_art",
            "kindergarten_reading",
            "kindergarten_learning",
        ):
            styled = self.client.get(
                f"/designs/{design_id}/products/mug_11oz_black_accent/"
                f"pinterest/image?style={style}"
            )
            self.assertEqual(styled.status_code, 200)
            with Image.open(BytesIO(styled.content)) as image:
                self.assertEqual(image.size, (1000, 1500))

        invalid = self.client.get(
            f"/designs/{design_id}/products/mug_11oz_black_accent/"
            "pinterest/image?style=unsupported"
        )
        self.assertEqual(invalid.status_code, 400)

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

        from web.pinterest_bundle import select_printify_camera_mockup

        self.assertEqual(
            select_printify_camera_mockup(product, "front"),
            "https://images.printify.com/front.jpg?camera_label=front",
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
        self.assertEqual(
            bundle["link"],
            "https://shangooli.com/mugs/i-teach-the-thinkers-of-tomorrow",
        )
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
        self.assertNotIn("White Ceramic Mug", preview.text)
        self.assertIn("Black Accent Mug 11 oz", preview.text)
        self.assertIn("Choose your favorite design", preview.text)
        self.assertEqual(preview.text.count('name="style_variant"'), 6)
        self.assertEqual(before, after)
        update.assert_not_called()

    def test_quick_text_style_variants_are_distinct(self):
        variants = {
            render_quick_text_design("Small steps shape bright futures.", style_variant=index)
            for index in range(6)
        }
        self.assertEqual(len(variants), 6)

    def test_three_line_quick_text_variants_render_with_room_between_lines(self):
        rendered = render_quick_text_design(
            "Please save your\nbest excuse\nfor Friday", style_variant=0
        )
        with Image.open(BytesIO(rendered)) as image:
            self.assertEqual(image.size, (2400, 2400))
            self.assertEqual(image.mode, "RGBA")

    def test_two_line_quick_text_variants_render_with_room_between_lines(self):
        rendered = render_quick_text_design(
            "Variables\nBuild Character", style_variant=0
        )
        with Image.open(BytesIO(rendered)) as image:
            self.assertEqual(image.size, (2400, 2400))
            self.assertEqual(image.mode, "RGBA")

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
        self.assertIn("Review the Etsy listing", page.text)

    def test_portfolio_refresh_updates_only_active_slot_without_replacing_history(self):
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

        self.assertEqual([item["outcome"] for item in results], ["updated"])
        self.assertEqual({item[2] for item in calls}, {"mug_11oz_black_accent"})
        for key in before:
            self.assertEqual(
                after[key]["printify_product_id"], before[key]["printify_product_id"]
            )
            self.assertEqual(after[key]["price_cents"], before[key]["price_cents"])
            self.assertEqual(after[key]["placement_x"], before[key]["placement_x"])
            self.assertEqual(after[key]["placement_y"], before[key]["placement_y"])
            self.assertEqual(after[key]["placement_scale"], before[key]["placement_scale"])
        self.assertEqual(
            after["mug_11oz"]["production_asset_filename"],
            before["mug_11oz"]["production_asset_filename"],
        )
        self.assertEqual(
            after["mug_11oz_black_accent"]["production_asset_filename"],
            calls[0][3],
        )
        self.assertEqual(
            db.get_standalone_design(design_id)["refresh_state"],
            "awaiting_printify",
        )

    def test_uploaded_portfolio_refresh_updates_only_active_product_slot(self):
        design_id = self._create_refreshable_portfolio_slot()
        before = {
            row["product_type"]: dict(row)
            for row in db.list_standalone_design_products(design_id)
        }
        image = Image.new("RGBA", (1200, 1200), (255, 255, 255, 0))
        buffer = BytesIO()
        image.save(buffer, "PNG")
        calls = []

        def update(design_id, *, confirmed, blueprint_key, source_filename):
            calls.append((blueprint_key, source_filename))
            return {"outcome": "updated", "message": "updated"}

        results = apply_uploaded_portfolio_refresh(
            design_id,
            "My uploaded message",
            buffer.getvalue(),
            "finished-graphic.png",
            confirmed=True,
            update_printify=update,
        )
        after = {
            row["product_type"]: dict(row)
            for row in db.list_standalone_design_products(design_id)
        }

        self.assertEqual([item["outcome"] for item in results], ["updated"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "mug_11oz_black_accent")
        for key in before:
            self.assertEqual(after[key]["printify_product_id"], before[key]["printify_product_id"])
            self.assertEqual(after[key]["price_cents"], before[key]["price_cents"])
            self.assertEqual(after[key]["placement_x"], before[key]["placement_x"])
            self.assertEqual(after[key]["placement_y"], before[key]["placement_y"])
            self.assertEqual(after[key]["placement_scale"], before[key]["placement_scale"])

    def test_portfolio_refresh_failure_keeps_that_products_previous_asset(self):
        design_id = self._create_refreshable_portfolio_slot()
        old_assets = {
            row["product_type"]: row["production_asset_filename"]
            for row in db.list_standalone_design_products(design_id)
        }

        def update(design_id, *, confirmed, blueprint_key, source_filename):
            return {"outcome": "failed", "message": "Printify rejected update"}

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
        self.assertEqual(
            products["mug_11oz"]["production_asset_filename"],
            old_assets["mug_11oz"],
        )
        self.assertEqual(
            products["mug_11oz_black_accent"]["production_asset_filename"],
            old_assets["mug_11oz_black_accent"],
        )
        self.assertEqual(
            db.get_standalone_design(design_id)["refresh_state"], "needs_review"
        )


if __name__ == "__main__":
    unittest.main()
