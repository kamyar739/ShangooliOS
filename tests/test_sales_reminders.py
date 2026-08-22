from datetime import date
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import database
from web import db


class SalesReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.original_db_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path
        connection = sqlite3.connect(self.database_path)
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.close()
        db.ensure_production_schema()
        with db.get_connection() as connection:
            self.event_id = connection.execute(
                "SELECT id FROM sales_events WHERE code = 'nurses-week'"
            ).fetchone()["id"]

    def tearDown(self):
        db.DATABASE_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _due_names(self, current_date):
        return {
            reminder["name"]
            for reminder in db.list_due_sales_reminders(today=current_date)
        }

    def test_reminder_appears_only_when_reminder_date_is_reached(self):
        self.assertNotIn("Nurses Week", self._due_names(date(2026, 4, 14)))
        self.assertIn("Nurses Week", self._due_names(date(2026, 4, 15)))
        self.assertIn("Nurses Week", self._due_names(date(2026, 5, 6)))
        self.assertNotIn("Nurses Week", self._due_names(date(2026, 5, 7)))

    def test_snooze_hides_reminder_for_one_day(self):
        db.snooze_sales_reminder(
            self.event_id, 2026, today=date(2026, 4, 15)
        )
        self.assertNotIn("Nurses Week", self._due_names(date(2026, 4, 15)))

    def test_reminder_returns_after_snooze(self):
        db.snooze_sales_reminder(
            self.event_id, 2026, today=date(2026, 4, 15)
        )
        self.assertIn("Nurses Week", self._due_names(date(2026, 4, 16)))

    def test_dismiss_hides_reminder_for_current_year(self):
        db.dismiss_sales_reminder(
            self.event_id, 2026, today=date(2026, 4, 15)
        )
        self.assertNotIn("Nurses Week", self._due_names(date(2026, 5, 1)))

    def test_dismissed_annual_event_is_eligible_next_year(self):
        db.dismiss_sales_reminder(
            self.event_id, 2026, today=date(2026, 4, 15)
        )
        self.assertIn("Nurses Week", self._due_names(date(2027, 4, 15)))


if __name__ == "__main__":
    unittest.main()
