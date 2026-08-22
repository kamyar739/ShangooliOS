import sqlite3
import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from app import database
from web import commerce_metrics, db


class CommerceMetricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "test.db"
        self.env_path = Path(self.directory.name) / ".env"
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path
        connection = sqlite3.connect(self.database_path)
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.close()
        self.env_patch = patch("web.commerce_metrics.LOCAL_ENV_PATH", self.env_path)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        db.DATABASE_PATH = self.original_db
        self.directory.cleanup()

    def test_pinterest_credentials_are_kept_in_local_environment(self):
        commerce_metrics.save_pinterest_ads_config("secret-token", "123456")
        self.assertEqual(commerce_metrics.pinterest_ads_config()["ad_account_id"], "123456")
        self.assertIn("PINTEREST_ADS_ACCESS_TOKEN", self.env_path.read_text())
        commerce_metrics.clear_pinterest_ads_config()
        self.assertFalse(commerce_metrics.pinterest_ads_config()["access_token"])

    def test_pinterest_oauth_authorization_uses_read_only_scopes_and_signed_state(self):
        commerce_metrics.save_pinterest_oauth_config(
            "1603143",
            "local-secret",
            "549770647450",
            commerce_metrics.PINTEREST_DEFAULT_REDIRECT_URI,
        )
        authorization_url = commerce_metrics.begin_pinterest_oauth()
        query = parse_qs(urlparse(authorization_url).query)
        self.assertEqual(query["consumer_id"], ["1603143"])
        self.assertEqual(query["scope"], ["ads:read,user_accounts:read"])
        self.assertTrue(
            commerce_metrics._verify_oauth_state(
                query["state"][0], "local-secret"
            )
        )

    def test_old_public_callback_is_migrated_to_local_server(self):
        commerce_metrics._save_env_values({
            "PINTEREST_OAUTH_REDIRECT_URI": (
                commerce_metrics.PINTEREST_LEGACY_REDIRECT_URI
            )
        })
        self.assertEqual(
            commerce_metrics.pinterest_ads_config()["redirect_uri"],
            "http://localhost:8000/pinterest-ads/oauth/callback",
        )

    def test_pinterest_oauth_callback_saves_renewable_tokens(self):
        commerce_metrics.save_pinterest_oauth_config(
            "1603143",
            "local-secret",
            "549770647450",
            commerce_metrics.PINTEREST_DEFAULT_REDIRECT_URI,
        )
        state = commerce_metrics._oauth_state("local-secret")
        with patch(
            "web.commerce_metrics._pinterest_token_request",
            return_value={
                "access_token": "pina-access",
                "refresh_token": "pinr-refresh",
                "expires_in": 2592000,
                "refresh_token_expires_in": 5184000,
            },
        ) as token_request:
            commerce_metrics.complete_pinterest_oauth("authorization-code", state)
        config = commerce_metrics.pinterest_ads_config()
        self.assertEqual(config["access_token"], "pina-access")
        self.assertEqual(config["refresh_token"], "pinr-refresh")
        self.assertEqual(
            token_request.call_args.args[0]["continuous_refresh"], "true"
        )

    def test_expiring_pinterest_access_is_refreshed_before_sync(self):
        commerce_metrics.save_pinterest_oauth_config(
            "1603143",
            "local-secret",
            "549770647450",
            commerce_metrics.PINTEREST_DEFAULT_REDIRECT_URI,
        )
        commerce_metrics._save_pinterest_tokens({
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_in": 60,
            "refresh_token_expires_in": 5184000,
        })
        with patch(
            "web.commerce_metrics._pinterest_token_request",
            return_value={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 2592000,
                "refresh_token_expires_in": 5184000,
            },
        ) as token_request, patch(
            "web.commerce_metrics._pinterest_request", return_value=[]
        ) as analytics_request:
            commerce_metrics.sync_pinterest_ads(days=1)
        self.assertEqual(
            token_request.call_args.args[0]["grant_type"], "refresh_token"
        )
        self.assertEqual(analytics_request.call_args.args[1], "new-access")

    def test_etsy_receipts_are_stored_only_as_daily_aggregates(self):
        receipt = {
            "created_timestamp": 1787184000,
            "grandtotal": {"amount": 4400, "divisor": 100},
            "transactions": [{"quantity": 2}],
            "was_canceled": False,
        }
        with patch("web.commerce_metrics._utc_today", return_value=date(2026, 8, 20)), patch(
            "web.commerce_metrics.list_etsy_shop_receipts", return_value=[receipt]
        ):
            commerce_metrics.sync_etsy_sales(days=2)
            summary = commerce_metrics.commerce_metrics_summary(days=2)
        self.assertEqual(summary["totals"]["7d"]["orders"], 1)
        self.assertEqual(summary["totals"]["7d"]["items_sold"], 2)
        self.assertEqual(summary["totals"]["7d"]["revenue_cents"], 4400)
        self.assertEqual(summary["totals"]["7d"]["estimated_profit_cents"], 473)
        self.assertEqual(summary["totals"]["7d"]["estimated_profit_per_order_cents"], 473)
        self.assertEqual(summary["profit_estimate"]["unit_cost_cents"], 1138)

    def test_pinterest_daily_spend_and_roas_are_summarized(self):
        commerce_metrics.save_pinterest_ads_config("secret-token", "123456")
        today = "2026-08-21"
        with patch("web.commerce_metrics._utc_today", return_value=date(2026, 8, 21)), patch("web.commerce_metrics._pinterest_request", return_value=[{
            "DATE": today,
            "SPEND_IN_DOLLAR": 4.25,
            "PAID_IMPRESSION": 900,
            "TOTAL_CLICKTHROUGH": 12,
        }]):
            commerce_metrics.sync_pinterest_ads(days=1)
            summary = commerce_metrics.commerce_metrics_summary(days=1)
        self.assertEqual(summary["totals"]["24h"]["ad_spend_cents"], 425)
        self.assertEqual(summary["totals"]["24h"]["paid_clicks"], 12)

    def test_pinterest_authentication_error_is_actionable(self):
        error = HTTPError(
            "https://api.pinterest.com/v5/ad_accounts/123/analytics",
            401,
            "Unauthorized",
            {},
            BytesIO(b'{"message":"Authentication failed."}'),
        )
        with patch("web.commerce_metrics.urlopen", side_effect=error):
            with self.assertRaisesRegex(
                commerce_metrics.PinterestAdsError,
                "replace the access token",
            ):
                commerce_metrics._pinterest_request("https://example.test", "expired")

    def test_pinterest_sync_uses_utc_day(self):
        commerce_metrics.save_pinterest_ads_config("secret-token", "123456")
        with patch("web.commerce_metrics._utc_today", return_value=date(2026, 8, 22)), patch(
            "web.commerce_metrics._pinterest_request", return_value=[]
        ) as request:
            commerce_metrics.sync_pinterest_ads(days=1)
        self.assertIn("start_date=2026-08-22", request.call_args.args[0])
        self.assertIn("end_date=2026-08-22", request.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
