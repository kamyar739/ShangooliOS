import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from web.app import app
from web.etsy_api import (
    EtsyAPIError,
    begin_etsy_oauth,
    clear_etsy_config,
    complete_etsy_oauth,
    etsy_config,
    get_etsy_listing,
    update_etsy_listing,
    update_etsy_listing_state,
    update_etsy_listing_section,
)
from web.etsy_sync import set_etsy_inventory_quantity, sync_etsy_listing


class EtsyAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env_path = Path(self.directory.name) / ".env"
        self.env_patch = patch("web.etsy_api.LOCAL_ENV_PATH", self.env_path)
        self.env_patch.start()
        clear_etsy_config()

    def tearDown(self):
        clear_etsy_config()
        self.env_patch.stop()
        self.directory.cleanup()

    def test_authorization_uses_exact_callback_scopes_and_pkce(self):
        url = begin_etsy_oauth("keystring", "secret", remember=True)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["redirect_uri"], ["http://localhost:8000/etsy/oauth/callback"])
        self.assertEqual(query["scope"], ["listings_r listings_w shops_r shops_w"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(query["code_challenge"][0])
        contents = self.env_path.read_text(encoding="utf-8")
        self.assertIn("ETSY_API_KEY", contents)
        self.assertIn("ETSY_SHARED_SECRET", contents)
        self.assertNotIn("ETSY_ACCESS_TOKEN", contents)

    def test_callback_rejects_wrong_state_before_network_call(self):
        begin_etsy_oauth("keystring", "secret", remember=False)
        with patch("web.etsy_api._request") as request:
            with self.assertRaisesRegex(EtsyAPIError, "state did not match"):
                complete_etsy_oauth("code", "wrong-state")
        request.assert_not_called()

    def test_callback_saves_tokens_and_shop_without_overwriting_other_settings(self):
        self.env_path.write_text('PRINTIFY_SHOP_ID="123"\n', encoding="utf-8")
        url = begin_etsy_oauth("keystring", "secret", remember=True)
        state = parse_qs(urlparse(url).query)["state"][0]
        responses = [
            {"access_token": "27841912.token", "refresh_token": "refresh", "expires_in": 3600},
            {"shop_id": 987, "shop_name": "ShangooliShop"},
        ]
        with patch("web.etsy_api._request", side_effect=responses):
            result = complete_etsy_oauth("authorization-code", state)
        self.assertEqual(result["shop_id"], "987")
        self.assertEqual(etsy_config()["shop_name"], "ShangooliShop")
        contents = self.env_path.read_text(encoding="utf-8")
        self.assertIn("PRINTIFY_SHOP_ID", contents)
        self.assertIn("ETSY_REFRESH_TOKEN", contents)

    def test_disconnect_removes_only_etsy_settings(self):
        self.env_path.write_text(
            'PRINTIFY_SHOP_ID="123"\nETSY_API_KEY="key"\nETSY_SHARED_SECRET="secret"\n',
            encoding="utf-8",
        )
        clear_etsy_config()
        contents = self.env_path.read_text(encoding="utf-8")
        self.assertIn("PRINTIFY_SHOP_ID", contents)
        self.assertNotIn("ETSY_API_KEY", contents)

    def test_expired_access_token_refreshes_before_listing_request(self):
        self.env_path.write_text(
            '\n'.join((
                'ETSY_API_KEY="key"', 'ETSY_SHARED_SECRET="secret"',
                'ETSY_ACCESS_TOKEN="expired"', 'ETSY_REFRESH_TOKEN="refresh"',
                'ETSY_TOKEN_EXPIRES_AT="1"', 'ETSY_SHOP_ID="987"',
            )) + '\n',
            encoding="utf-8",
        )
        responses = [
            {"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 3600},
            {"listing_id": 123, "title": "Revelry"},
        ]
        with patch("web.etsy_api._request", side_effect=responses) as request:
            result = get_etsy_listing("123")
        self.assertEqual(result["listing_id"], 123)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].kwargs["form"]["grant_type"], "refresh_token")

    def test_update_listing_sends_copy_but_not_printify_inventory(self):
        self.env_path.write_text(
            '\n'.join((
                'ETSY_API_KEY="key"', 'ETSY_SHARED_SECRET="secret"',
                'ETSY_ACCESS_TOKEN="token"', 'ETSY_REFRESH_TOKEN="refresh"',
                'ETSY_TOKEN_EXPIRES_AT="9999999999"', 'ETSY_SHOP_ID="987"',
            )) + '\n',
            encoding="utf-8",
        )
        with patch("web.etsy_api._request", return_value={}) as request:
            update_etsy_listing("123", title="Revelry", description="Story", tags=["wall art", "abstract art"])
        form = request.call_args.kwargs["form"]
        self.assertEqual(form["title"], "Revelry")
        self.assertEqual(form["tags"], "wall art,abstract art")
        self.assertNotIn("inventory", form)
        self.assertNotIn("price", form)

    def test_reactivate_listing_sends_only_active_state(self):
        self.env_path.write_text(
            '\n'.join((
                'ETSY_API_KEY="key"', 'ETSY_SHARED_SECRET="secret"',
                'ETSY_ACCESS_TOKEN="token"', 'ETSY_REFRESH_TOKEN="refresh"',
                'ETSY_TOKEN_EXPIRES_AT="9999999999"', 'ETSY_SHOP_ID="987"',
            )) + '\n', encoding="utf-8",
        )
        with patch("web.etsy_api._request", return_value={}) as request:
            update_etsy_listing_state("123", "active")
        self.assertEqual(request.call_args.kwargs["form"], {"state": "active"})

    def test_section_assignment_uses_current_etsy_field_name(self):
        self.env_path.write_text(
            '\n'.join((
                'ETSY_API_KEY="key"', 'ETSY_SHARED_SECRET="secret"',
                'ETSY_ACCESS_TOKEN="token"', 'ETSY_REFRESH_TOKEN="refresh"',
                'ETSY_TOKEN_EXPIRES_AT="9999999999"', 'ETSY_SHOP_ID="987"',
            )) + '\n', encoding="utf-8",
        )
        with patch("web.etsy_api._request", return_value={}) as request:
            update_etsy_listing_section("123", 77)
        self.assertEqual(request.call_args.kwargs["form"], {"shop_section_id": 77})

    def test_sync_uploads_curated_images_before_removing_remaining_old_images(self):
        listing = {
            "external_listing_id": "123", "title": "Revelry",
            "description": "Story", "tags": "wall art", "artwork_code": "CEL-005",
        }
        preview = {
            "linked": True,
            "images": [Path("one.jpg"), Path("two.jpg")],
            "images_changed": True,
        }
        events = []
        with patch("web.etsy_sync.build_etsy_sync_preview", return_value=preview), \
             patch("web.etsy_sync.update_etsy_listing", side_effect=lambda *a, **k: events.append("copy")), \
             patch("web.etsy_sync.upload_etsy_listing_image", side_effect=[{"listing_image_id": 10}, {"listing_image_id": 11}]), \
             patch("web.etsy_sync.get_etsy_listing_images", return_value=[{"listing_image_id": 10}, {"listing_image_id": 11}, {"listing_image_id": 9}]), \
             patch("web.etsy_sync.delete_etsy_listing_image", side_effect=lambda *a: events.append("delete")) as delete:
            result = sync_etsy_listing(listing)
        self.assertEqual(result["image_count"], 2)
        delete.assert_called_once_with("123", 9)
        self.assertEqual(events, ["copy", "delete"])

    def test_repeat_sync_skips_unchanged_images(self):
        listing = {
            "external_listing_id": "123", "title": "Revelry",
            "description": "Story", "tags": "wall art", "artwork_code": "CEL-005",
        }
        preview = {
            "linked": True,
            "images": [Path("one.jpg")],
            "images_changed": False,
        }
        with patch("web.etsy_sync.build_etsy_sync_preview", return_value=preview), \
             patch("web.etsy_sync.update_etsy_listing"), \
             patch("web.etsy_sync.upload_etsy_listing_image") as upload, \
             patch("web.etsy_sync.delete_etsy_listing_image") as delete:
            result = sync_etsy_listing(listing)
        self.assertEqual(result["image_count"], 0)
        upload.assert_not_called()
        delete.assert_not_called()

    def test_sync_reuses_existing_collection_section(self):
        listing = {
            "external_listing_id": "123", "title": "Revelry",
            "description": "Story", "tags": "wall art", "artwork_code": "CEL-005",
        }
        preview = {
            "linked": True,
            "remote": {"shop_section_id": None},
            "images": [Path("one.jpg")],
            "images_changed": False,
            "desired_section": "Celebration Collection",
            "sections": [{"shop_section_id": 77, "title": "Celebration Collection"}],
        }
        with patch("web.etsy_sync.build_etsy_sync_preview", return_value=preview), \
             patch("web.etsy_sync.create_etsy_shop_section") as create, \
             patch("web.etsy_sync.update_etsy_listing_section") as assign, \
             patch("web.etsy_sync.get_etsy_listing", return_value={"shop_section_id": 77}), \
             patch("web.etsy_sync.update_etsy_listing"):
            sync_etsy_listing(listing)
        create.assert_not_called()
        assign.assert_called_once_with("123", 77)

    def test_inventory_cap_preserves_skus_prices_and_variant_properties(self):
        listing = {"external_listing_id": "123"}
        current = {
            "products": [{
                "product_id": 44,
                "sku": "PRINTIFY-11X14",
                "property_values": [{
                    "property_id": 100, "property_name": "Size",
                    "scale_id": 1, "value_ids": [10], "values": ["11 x 14"],
                }],
                "offerings": [{
                    "offering_id": 55, "quantity": 999, "is_enabled": True,
                    "price": {"amount": 2500, "divisor": 100, "currency_code": "USD"},
                    "readiness_state_id": 1,
                }],
            }],
            "price_on_property": [100],
            "quantity_on_property": [],
            "sku_on_property": [100],
        }
        verified = {
            **current,
            "products": [{
                **current["products"][0],
                "offerings": [{**current["products"][0]["offerings"][0], "quantity": 2}],
            }],
        }
        with patch("web.etsy_sync.get_etsy_listing_inventory", side_effect=[current, verified]), \
             patch("web.etsy_sync.update_etsy_listing_inventory") as update:
            rows = set_etsy_inventory_quantity(listing, 2)
        payload = update.call_args.args[1]
        product = payload["products"][0]
        self.assertEqual(product["sku"], "PRINTIFY-11X14")
        self.assertEqual(product["offerings"][0]["price"], 25.0)
        self.assertEqual(product["offerings"][0]["quantity"], 2)
        self.assertEqual(product["property_values"][0]["values"], ["11 x 14"])
        self.assertEqual(payload["price_on_property"], [100])
        self.assertEqual(rows[0]["quantity"], 2)

    def test_inventory_rejects_zero_before_calling_etsy(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 999"):
            set_etsy_inventory_quantity({"external_listing_id": "123"}, 0)


class EtsyConnectionPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_connect_page_keeps_credentials_private(self):
        with patch("web.app.etsy_config", return_value={"access_token": "", "shop_id": "", "shop_name": ""}):
            response = self.client.get("/etsy/connect")
        self.assertEqual(response.status_code, 200)
        self.assertIn('type="password" name="api_key"', response.text)
        self.assertIn('type="password" name="shared_secret"', response.text)

    def test_connect_form_redirects_to_etsy(self):
        with patch("web.app.begin_etsy_oauth", return_value="https://www.etsy.com/oauth/connect?state=test"):
            response = self.client.post(
                "/etsy/connect",
                data={"api_key": "key", "shared_secret": "secret", "remember": "true"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("https://www.etsy.com/oauth/connect"))

    def test_callback_redirects_after_success(self):
        with patch("web.app.complete_etsy_oauth") as complete:
            response = self.client.get(
                "/etsy/oauth/callback?code=code&state=state", follow_redirects=False
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/etsy/connect?connected=1")
        complete.assert_called_once_with("code", "state")


if __name__ == "__main__":
    unittest.main()
