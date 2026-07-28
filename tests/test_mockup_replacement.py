import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import app


class MockupReplacementTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.overview = {
            "mockup_replacement": {
                "complete": True,
                "approved": True,
                "listing": {"id": 42},
            },
            "mockup_set_state": {"set_id": 7},
        }

    def test_sync_requires_explicit_confirmation_and_performs_no_external_call(self):
        with patch(
            "web.app._mockup_replacement_overview",
            return_value=self.overview,
        ), patch("web.app.sync_etsy_listing_images") as sync:
            response = self.client.post("/artworks/CEL-001/replace-mockup/sync")

        self.assertEqual(response.status_code, 400)
        sync.assert_not_called()

    def test_sync_reuses_etsy_image_sync_without_contacting_printify(self):
        listing = {"id": 42, "artwork_code": "CEL-001"}
        with patch(
            "web.app._mockup_replacement_overview",
            return_value=self.overview,
        ), patch("web.app.get_listing", return_value=listing), patch(
            "web.app.sync_etsy_listing_images",
            return_value={"state": "inactive", "image_count": 8},
        ) as sync, patch("web.app.mark_etsy_synced") as mark, patch(
            "web.app.PrintifyAPI.from_env"
        ) as printify:
            response = self.client.post(
                "/artworks/CEL-001/replace-mockup/sync",
                data={"confirmed": "true"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        sync.assert_called_once_with(listing)
        mark.assert_called_once_with(42, "inactive")
        printify.assert_not_called()

    def test_approval_reuses_existing_mockup_set_approval(self):
        unapproved = {
            **self.overview,
            "mockup_replacement": {
                **self.overview["mockup_replacement"],
                "approved": False,
            },
        }
        with patch(
            "web.app._mockup_replacement_overview",
            return_value=unapproved,
        ), patch("web.app.approve_artwork_mockup_set") as approve, patch(
            "web.app.set_artwork_production_flags"
        ) as flags:
            response = self.client.post(
                "/artworks/CEL-001/replace-mockup/approve",
                data={"confirmed": "true"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        approve.assert_called_once_with("CEL-001", 7)
        flags.assert_called_once_with("CEL-001", mockups_ready=True)


if __name__ == "__main__":
    unittest.main()
