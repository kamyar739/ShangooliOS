import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_etsy_receipts_are_stored_only_as_daily_aggregates(self):
        receipt = {
            "created_timestamp": 1787184000,
            "grandtotal": {"amount": 4400, "divisor": 100},
            "transactions": [{"quantity": 2}],
            "was_canceled": False,
        }
        with patch("web.commerce_metrics.list_etsy_shop_receipts", return_value=[receipt]):
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
        today = commerce_metrics.date.today().isoformat()
        with patch("web.commerce_metrics._pinterest_request", return_value=[{
            "DATE": today,
            "SPEND_IN_DOLLAR": 4.25,
            "PAID_IMPRESSION": 900,
            "TOTAL_CLICKTHROUGH": 12,
        }]):
            commerce_metrics.sync_pinterest_ads(days=1)
        summary = commerce_metrics.commerce_metrics_summary(days=1)
        self.assertEqual(summary["totals"]["24h"]["ad_spend_cents"], 425)
        self.assertEqual(summary["totals"]["24h"]["paid_clicks"], 12)


if __name__ == "__main__":
    unittest.main()
