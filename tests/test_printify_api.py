import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from io import BytesIO

from web.printify_api import (
    PrintifyAPI,
    clear_printify_local_config,
    clear_printify_runtime,
    complete_printify_runtime,
    configure_printify_runtime,
    configure_printify_token_runtime,
    create_printify_product,
    poster_blueprints,
    printify_configuration_source,
    ratio_role_for_variant,
    save_printify_local_config,
    update_printify_product_artwork,
    variant_orientation,
    wait_for_product_unlock,
)


class FakePrintifyAPI:
    def __init__(self):
        self.uploads = []
        self.payload = None

    def upload_image(self, path):
        self.uploads.append(path)
        return {"id": f"image-{path.stem}"}

    def create_product(self, payload):
        self.payload = payload
        return {"id": "product-123", "title": payload["title"]}

    def get_product(self, product_id):
        return {"id": product_id, "variants": [
            {"id": 1, "title": "18 x 12 / Matte", "price": 2800, "is_enabled": True},
            {"id": 2, "title": "20 x 16 / Matte", "price": 3200, "is_enabled": True},
            {"id": 3, "title": "30 x 20 / Matte", "price": 4800, "is_enabled": False},
            {"id": 4, "title": "24 x 10 / Matte", "price": 5000, "is_enabled": False},
        ], "print_areas": [{
            "variant_ids": [4],
            "placeholders": [{"position": "front", "images": [{"id": "existing-panoramic"}]}],
        }]}

    def update_product(self, product_id, payload):
        self.updated_product_id = product_id
        self.payload = payload


class PrintifyAPITests(unittest.TestCase):
    def setUp(self):
        clear_printify_runtime()
        self._config_directory = tempfile.TemporaryDirectory()
        self.local_env_path = Path(self._config_directory.name) / ".env"
        self._env_path_patch = patch(
            "web.printify_api.LOCAL_ENV_PATH",
            self.local_env_path,
        )
        self._env_path_patch.start()

    def tearDown(self):
        clear_printify_runtime()
        self._env_path_patch.stop()
        self._config_directory.cleanup()

    def tearDown(self):
        clear_printify_runtime()

    def test_runtime_credentials_are_available_without_persistence(self):
        configure_printify_runtime("secret-token", "12345")
        api = PrintifyAPI.from_env()
        self.assertEqual(api.token, "secret-token")
        self.assertEqual(api.shop_id, "12345")
        self.assertEqual(printify_configuration_source(), "runtime")
        clear_printify_runtime()
        self.assertIsNone(printify_configuration_source())

    def test_token_then_shop_selection_completes_runtime_connection(self):
        configure_printify_token_runtime("secret-token", remember=False)
        self.assertIsNone(PrintifyAPI.from_env())
        self.assertIsNotNone(PrintifyAPI.with_available_token())
        complete_printify_runtime("54321")
        self.assertEqual(PrintifyAPI.from_env().shop_id, "54321")

    def test_shop_list_uses_printify_shops_endpoint(self):
        api = PrintifyAPI("secret", "")
        shops = [{"id": 1, "title": "Etsy Shop", "sales_channel": "etsy"}]
        with patch.object(api, "_request", return_value=shops) as request:
            result = api.list_shops()
        self.assertEqual(result, shops)
        request.assert_called_once_with("GET", "/shops.json")

    def test_1010_identifies_request_signature_block(self):
        api = PrintifyAPI("secret", "")
        error = HTTPError(
            "https://api.printify.com/v1/shops.json",
            403,
            "Forbidden",
            {},
            BytesIO(b'{"error":{"code":1010}}'),
        )
        with patch("web.printify_api.urlopen", side_effect=error):
            with self.assertRaisesRegex(Exception, "request signature"):
                api.list_shops()

    def test_upload_403_identifies_uploads_write_permission(self):
        api = PrintifyAPI("secret", "")
        error = HTTPError(
            "https://api.printify.com/v1/uploads/images.json",
            403,
            "Forbidden",
            {},
            BytesIO(b'{"error":"Forbidden"}'),
        )
        with patch("web.printify_api.urlopen", side_effect=error):
            with tempfile.TemporaryDirectory() as directory:
                artwork = Path(directory) / "art.png"
                artwork.write_bytes(b"art")
                with self.assertRaisesRegex(Exception, "Uploads: write"):
                    api.upload_image(artwork)

    def test_request_identifies_shangoolios_client(self):
        api = PrintifyAPI("secret", "")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"[]"
        with patch("web.printify_api.urlopen", return_value=response) as mocked_urlopen:
            api.list_shops()
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("User-agent"), "ShangooliOS/1.0 Printify-API-Client"
        )
        self.assertEqual(request.get_header("Accept"), "application/json")

    @patch.dict("os.environ", {}, clear=True)
    def test_local_env_credentials_survive_runtime_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with patch("web.printify_api.LOCAL_ENV_PATH", env_path):
                save_printify_local_config("local-secret", "24680")
                clear_printify_runtime()
                api = PrintifyAPI.from_env()
                self.assertEqual(api.token, "local-secret")
                self.assertEqual(api.shop_id, "24680")
                self.assertEqual(printify_configuration_source(), "local .env")
                self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_clear_local_config_preserves_unrelated_env_values(self):
        save_printify_local_config("local-secret", "24680")
        with self.local_env_path.open("a", encoding="utf-8") as env_file:
            env_file.write('UNRELATED_SETTING="keep-me"\n')
        clear_printify_local_config()
        content = self.local_env_path.read_text(encoding="utf-8")
        self.assertNotIn("PRINTIFY_API_TOKEN", content)
        self.assertNotIn("PRINTIFY_SHOP_ID", content)
        self.assertIn('UNRELATED_SETTING="keep-me"', content)

    def test_poster_blueprints_filters_and_sorts_catalog(self):
        result = poster_blueprints(
            [
                {"id": 2, "title": "T-Shirt"},
                {"id": 3, "title": "Vertical Poster"},
                {"id": 1, "title": "Matte Poster"},
            ]
        )
        self.assertEqual([item["id"] for item in result], [1, 3])

    def test_poster_blueprints_filter_to_artwork_orientation(self):
        result = poster_blueprints(
            [
                {"id": 1, "title": "Matte Vertical Posters"},
                {"id": 2, "title": "Matte Horizontal Posters"},
                {"id": 3, "title": "Fine Art Posters"},
            ],
            "horizontal",
        )
        self.assertEqual([item["id"] for item in result], [2])

    def test_variant_orientation_uses_print_dimensions(self):
        self.assertEqual(variant_orientation('18\u2033 x 12\u2033 / Matte'), "horizontal")
        self.assertEqual(variant_orientation('12\u2033 x 18\u2033 / Matte'), "vertical")
        self.assertEqual(variant_orientation('12\u2033 x 12\u2033 / Matte'), "square")

    def test_variant_ratio_maps_to_prepared_file_role(self):
        self.assertEqual(ratio_role_for_variant('14\u2033 x 11\u2033 / Matte'), "ratio:14:11")
        self.assertEqual(ratio_role_for_variant('18\u2033 x 12\u2033 / Matte'), "ratio:3:2")
        self.assertEqual(ratio_role_for_variant('20\u2033 x 16\u2033 / Matte'), "ratio:5:4")
        self.assertEqual(ratio_role_for_variant('24\u2033 x 18\u2033 / Matte'), "ratio:4:3")

    def test_product_creation_uploads_files_and_builds_print_areas(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            four_five = folder / "ratio_4x5.png"
            two_three = folder / "ratio_2x3.png"
            four_five.write_bytes(b"four-five")
            two_three.write_bytes(b"two-three")
            api = FakePrintifyAPI()
            result = create_printify_product(
                api,
                listing={"title": "Revelry Poster", "description": "Description"},
                blueprint_id=100,
                provider_id=200,
                provider_name="Print Provider",
                selections=[
                    {
                        "variant_id": 1, "title": "8x10", "cost_cents": 800,
                        "price_cents": 2400, "path": four_five,
                    },
                    {
                        "variant_id": 2, "title": "16x20", "cost_cents": 1200,
                        "price_cents": 3600, "path": four_five,
                    },
                    {
                        "variant_id": 3, "title": "12x18", "cost_cents": 1000,
                        "price_cents": 3000, "path": two_three,
                    },
                ],
            )

        self.assertEqual(len(api.uploads), 2)
        self.assertEqual(api.payload["blueprint_id"], 100)
        self.assertEqual(len(api.payload["variants"]), 3)
        self.assertEqual(len(api.payload["print_areas"]), 2)
        self.assertEqual(result["product"]["id"], "product-123")
        self.assertEqual(result["sizes"], "8x10, 16x20, 12x18")
        self.assertEqual(result["base_cost_cents"], 800)

    def test_product_creation_keeps_missing_catalog_cost_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "print.jpg"
            path.write_bytes(b"art")
            listing = {"title": "Revelry", "description": "Description"}
            api = FakePrintifyAPI()
            result = create_printify_product(
                api,
                listing=listing,
                blueprint_id=284,
                provider_id=99,
                provider_name="Printify Choice",
                selections=[
                    {
                        "variant_id": 43163,
                        "title": '14\u2033 x 11\u2033 / Matte',
                        "cost_cents": None,
                        "price_cents": 2500,
                        "path": path,
                    }
                ],
            )
        self.assertIsNone(result["base_cost_cents"])

    def test_product_artwork_update_preserves_variants_and_replaces_print_areas(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            three_two, five_four = folder / "3x2.png", folder / "5x4.png"
            three_two.write_bytes(b"a")
            five_four.write_bytes(b"b")
            api = FakePrintifyAPI()
            count = update_printify_product_artwork(
                api, product_id="existing-123",
                listing={"title": "Revelry", "description": "Updated"},
                files_by_role={"ratio:3:2": three_two, "ratio:5:4": five_four},
            )
        self.assertEqual(count, 2)
        self.assertEqual(api.updated_product_id, "existing-123")
        self.assertEqual([item["price"] for item in api.payload["variants"]], [2800, 3200, 4800, 5000])
        self.assertEqual(len(api.payload["print_areas"]), 3)
        self.assertEqual(
            sorted(variant for area in api.payload["print_areas"] for variant in area["variant_ids"]),
            [1, 2, 3, 4],
        )
        panoramic = next(area for area in api.payload["print_areas"] if 4 in area["variant_ids"])
        self.assertEqual(panoramic["placeholders"][0]["images"][0]["id"], "existing-panoramic")

    def test_publish_product_uses_separate_confirmed_api_operation(self):
        api = PrintifyAPI("secret", "shop-123")
        with patch.object(api, "_request", return_value={}) as request:
            api.publish_product("product-456")
        method, path, payload = request.call_args.args
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/shops/shop-123/products/product-456/publish.json")
        self.assertTrue(payload["title"])
        self.assertTrue(payload["images"])
        self.assertTrue(payload["variants"])

    def test_publish_product_can_preserve_curated_etsy_images(self):
        api = PrintifyAPI("secret", "shop-123")
        with patch.object(api, "_request", return_value={}) as request:
            api.publish_product("product-456", include_images=False)
        payload = request.call_args.args[2]
        self.assertFalse(payload["images"])

    def test_wait_for_product_unlock_checks_until_printify_finishes(self):
        api = MagicMock()
        api.get_product.side_effect = [
            {"id": "product-456", "is_locked": True},
            {"id": "product-456", "is_locked": False},
        ]
        with patch("web.printify_api.time.sleep") as sleep:
            product = wait_for_product_unlock(
                api, "product-456", attempts=3, delay_seconds=0.01
            )
        self.assertFalse(product["is_locked"])
        self.assertEqual(api.get_product.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
