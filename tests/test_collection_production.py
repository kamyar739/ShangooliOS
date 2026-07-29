import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app import database
from web import db
from web.app import app
from web.collection_production import run_collection_production
from web.collection_review import (
    approve_artwork_for_collection,
    approve_many,
    collection_review_overview,
    refresh_selected_collection_cards,
    regenerate_selected_ratio_sets,
    send_artwork_back,
)
from web.mockup_tasks import (
    collection_branding_is_stale,
    regenerate_collection_branding_card,
)
from web.production_tasks import ensure_source_certification, regenerate_ratio_set


class CollectionProductionTests(unittest.TestCase):
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
                brand_id, code, name, collection_type, vertical, status
            ) VALUES (?, 'DUE', 'The Duende Collection', 'curated', 'art', 'active')
            """,
            (brand_id,),
        )
        collection_id = connection.execute(
            "SELECT id FROM collections WHERE code='DUE'"
        ).fetchone()[0]
        for number, title in ((1, "Surrender"), (2, "Challenge")):
            connection.execute(
                """
                INSERT INTO artworks (
                    artwork_code, collection_id, sequence_number, public_title,
                    description, prompt, status
                ) VALUES (?, ?, ?, ?, 'Factual description', 'Artwork prompt', 'approved')
                """,
                (f"DUE-{number:03d}", collection_id, number, title),
            )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        with db.get_connection() as connection:
            for code in ("DUE-001", "DUE-002"):
                artwork_id = connection.execute(
                    "SELECT id FROM artworks WHERE artwork_code=?", (code,)
                ).fetchone()["id"]
                connection.execute(
                    """
                    INSERT INTO artwork_files (
                        artwork_id, role, relative_path, stored_filename,
                        original_filename
                    ) VALUES (?, 'source', 'source.png', 'source.png', 'source.png')
                    """,
                    (artwork_id,),
                )
                connection.execute(
                    """
                    INSERT INTO artwork_intelligence (
                        artwork_id, theme, style, mood
                    ) VALUES (?, 'Flamenco', 'Figurative', 'Dramatic')
                    """,
                    (artwork_id,),
                )
                connection.execute(
                    """
                    INSERT INTO artwork_listing_content (
                        artwork_id, short_story, long_story, etsy_title,
                        etsy_description, etsy_tags, alt_text, keywords
                    ) VALUES (?, 'Short', 'Long', ?, 'Description',
                              'flamenco, art', 'Flamenco dancer', 'flamenco')
                    """,
                    (artwork_id, f"{code} poster"),
                )
            connection.commit()
        self.client = TestClient(app)

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temporary.cleanup()

    def test_schema_safely_renames_duende_and_adds_run_tables(self):
        collection, _, _ = db.get_collection("DUE")
        self.assertEqual(collection["name"], "Duende – A Flamenco Collection")
        with db.get_connection() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("collection_production_runs", tables)
        self.assertIn("collection_production_run_items", tables)

    @patch("web.collection_production.ensure_mockups", return_value="created")
    @patch("web.collection_production.ensure_ratio_files", return_value="created")
    @patch("web.collection_production.ensure_print_master", return_value="created")
    @patch("web.collection_production.approve_certified_source")
    @patch("web.collection_production.ensure_source_certification")
    def test_runner_continues_after_source_exception_and_uses_collection_price(
        self, certify, approve, master, ratios, mockups
    ):
        def certification(artwork):
            if artwork["artwork_code"] == "DUE-001":
                raise ValueError("Source quality score 70 is below the accepted threshold")
            return (
                {"valid": 1, "score": 100, "orientation": "vertical"},
                {"original_filename": "source.png"},
                Path("source.png"),
                "ai_upscale_4x",
            )

        certify.side_effect = certification
        run_id, _ = run_collection_production(
            "DUE", source_approval_confirmed=True
        )
        rows = {
            row["artwork_code"]: row
            for row in db.get_collection_production_run_items(run_id)
        }
        self.assertEqual(rows["DUE-001"]["overall_status"], "blocked")
        self.assertEqual(rows["DUE-002"]["source_used"], "ai_upscale_4x")
        processed_artwork = next(
            call.args[0]
            for call in certify.call_args_list
            if call.args[0]["artwork_code"] == "DUE-002"
        )
        self.assertEqual(processed_artwork["collection_code"], "DUE")
        self.assertEqual(
            processed_artwork["collection_name"],
            "Duende – A Flamenco Collection",
        )
        listings = list(db.get_artwork_listings("DUE-002"))
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["price_cents"], 2900)
        self.assertEqual(listings[0]["status"], "draft")

    def test_progress_page_exposes_states_and_controls(self):
        response = self.client.get("/collections/DUE/production")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Produce Collection", response.text)
        self.assertIn("Certification", response.text)
        self.assertIn("Local listing", response.text)
        self.assertIn("Review exceptions", response.text)
        self.assertIn("DUE-001", response.text)
        self.assertIn("Recommended next action", response.text)
        self.assertIn('href="/collections/DUE/review"', response.text)
        self.assertIn('href="/collections/DUE/publish-readiness"', response.text)
        self.assertIn('href="/collections/DUE/printify"', response.text)
        self.assertIn('href="/collections/DUE/publish"', response.text)

    def test_collection_workflow_navigation_is_persistent_across_pages(self):
        for path, current_label in (
            ("/collections/DUE/production", "Produce"),
            ("/collections/DUE/review", "Review"),
            ("/collections/DUE/publish-readiness", "Ready"),
            ("/collections/DUE/printify", "Printify"),
            ("/collections/DUE/publish", "Etsy"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                'aria-label="Duende – A Flamenco Collection workflow"',
                response.text,
            )
            self.assertIn('aria-current="step"', response.text)
            self.assertIn(current_label, response.text)

    def test_new_imported_collection_without_production_run_is_visible(self):
        with db.get_connection() as connection:
            brand_id = connection.execute(
                "SELECT id FROM brands WHERE code='SHG'"
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO collections (
                    brand_id, code, name, collection_type, vertical,
                    target_artwork_count, status
                ) VALUES (?, 'NEW', 'New Imported Collection',
                          'standard', 'general', 1, 'active')
                """,
                (brand_id,),
            )
            collection_id = connection.execute(
                "SELECT id FROM collections WHERE code='NEW'"
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO artworks (
                    artwork_code, collection_id, sequence_number,
                    public_title, status
                ) VALUES ('NEW-001', ?, 1, 'First Imported Artwork', 'idea')
                """,
                (collection_id,),
            )
            connection.commit()
        self.assertIsNone(db.get_collection_production_run("NEW"))

        response = self.client.get("/collections")
        self.assertEqual(response.status_code, 200)
        self.assertIn("New Imported Collection", response.text)
        self.assertIn(
            'href="/collections?collection=NEW#collection-workflow"',
            response.text,
        )

        selected = self.client.get("/collections?collection=NEW")
        self.assertEqual(selected.status_code, 200)
        self.assertIn("First Imported Artwork", selected.text)
        self.assertIn('href="/collections/NEW/production"', selected.text)
        self.assertIn("Run safe production", selected.text)

    def _make_review_ready(self, artwork_code, *, warning=False):
        production = db.get_artwork_production(artwork_code)
        required_ratios = [
            value.strip()
            for value in production["required_ratios"].split(",")
            if value.strip()
        ]
        db.upsert_artwork_file(
            artwork_code, "print_master", "master.png", "master.png", "master.png"
        )
        for ratio in required_ratios:
            db.upsert_artwork_file(
                artwork_code, f"ratio:{ratio}", f"{ratio}.png",
                f"{ratio}.png", f"{ratio}.png",
            )
        for slot in (
            "hero", "room", "bedroom", "office", "detail", "sizes",
            "how_it_works", "collection",
        ):
            db.upsert_artwork_file(
                artwork_code, f"mockup:{slot}", f"{slot}.png",
                f"{slot}.png", f"{slot}.png",
            )
        db.upsert_artwork_certification(
            artwork_code,
            {
                "valid": True, "width": 3600, "height": 5400, "mode": "RGB",
                "format": "PNG", "orientation": "horizontal",
                "source_ratio": 1.5, "closest_ratio": "3:2",
                "master_ratio": "3:2",
                "required_ratios": ["3:2", "4:3", "5:4", "14:11"],
                "score": 92, "status": "Certified for production",
                "largest_recommended_print": "24×36",
                "print_capability": [], "warnings": ["Informational note"] if warning else [],
            },
        )
        db.set_artwork_production_flags(
            artwork_code, original_approved=True, print_master_ready=True,
            ratio_exports_ready=False, mockups_ready=False,
        )
        default_set = next(
            row for row in db.list_mockup_sets() if row["name"] == "Etsy Standard"
        )
        db.record_artwork_mockup_set_generated(artwork_code, default_set["id"])

    def test_collection_review_renders_every_artwork_and_waits_for_approval(self):
        self._make_review_ready("DUE-001")
        response = self.client.get("/collections/DUE/review")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Surrender", response.text)
        self.assertIn("Challenge", response.text)
        self.assertIn("Approve Selected", response.text)
        self.assertIn("Approve All Eligible", response.text)
        production = db.get_artwork_production("DUE-001")
        self.assertFalse(production["ratio_exports_ready"])
        self.assertFalse(production["mockups_ready"])

    def test_approval_persists_and_existing_approval_is_preserved(self):
        self._make_review_ready("DUE-001")
        first = approve_artwork_for_collection("DUE", "DUE-001")
        self.assertTrue(first["approved"])
        first_approved_at = db.get_artwork_mockup_set_state("DUE-001")["approved_at"]
        second = approve_artwork_for_collection("DUE", "DUE-001")
        self.assertTrue(second["approved"])
        self.assertEqual(
            db.get_artwork_mockup_set_state("DUE-001")["approved_at"],
            first_approved_at,
        )

    def test_approve_all_eligible_skips_blocked_and_allows_information_warning(self):
        self._make_review_ready("DUE-001", warning=True)
        result = approve_many("DUE", [])
        self.assertEqual(result["approved"], ["DUE-001"])
        self.assertIn("DUE-002", result["skipped"])
        self.assertTrue(
            db.get_artwork_production("DUE-001")["ratio_exports_ready"]
        )

    def test_send_back_persists_correction_without_deleting_files(self):
        self._make_review_ready("DUE-001")
        approve_artwork_for_collection("DUE", "DUE-001")
        roles_before = {
            row["role"] for row in db.get_artwork_file_assignments("DUE-001")
        }
        send_artwork_back("DUE-001", "Replace the bedroom crop")
        roles_after = {
            row["role"] for row in db.get_artwork_file_assignments("DUE-001")
        }
        self.assertEqual(roles_after, roles_before)
        _, items, _ = collection_review_overview("DUE")
        state = next(item for item in items if item["artwork_code"] == "DUE-001")
        self.assertEqual(state["display_state"], "needs_correction")
        self.assertEqual(state["correction_note"], "Replace the bedroom crop")

    def test_listing_uses_collection_price_and_existing_listing_is_untouched(self):
        self._make_review_ready("DUE-001")
        approve_artwork_for_collection("DUE", "DUE-001")
        created = list(db.get_artwork_listings("DUE-001"))[0]
        self.assertEqual(created["price_cents"], 2900)
        existing_id = db.create_listing(
            "DUE-002", marketplace="Etsy", product="Poster",
            title="Edited title", description="Edited description",
            tags="edited tag", price_cents=4777, status="draft",
        )
        self._make_review_ready("DUE-002")
        approve_artwork_for_collection("DUE", "DUE-002")
        existing = db.get_listing(existing_id)
        self.assertEqual(existing["title"], "Edited title")
        self.assertEqual(existing["price_cents"], 4777)

    def test_ready_for_printify_requires_every_artwork_but_one_failure_is_isolated(self):
        self._make_review_ready("DUE-001")
        result = approve_many("DUE", [])
        self.assertEqual(result["approved"], ["DUE-001"])
        _, _, ready = collection_review_overview("DUE")
        self.assertFalse(ready)
        self._make_review_ready("DUE-002")
        approve_artwork_for_collection("DUE", "DUE-002")
        _, _, ready = collection_review_overview("DUE")
        self.assertTrue(ready)

    def test_one_approval_failure_does_not_block_other_eligible_artwork(self):
        self._make_review_ready("DUE-001")
        self._make_review_ready("DUE-002")
        with patch(
            "web.collection_review.approve_artwork_mockup_set",
            side_effect=[ValueError("simulated failure"), None],
        ):
            result = approve_many("DUE", [])
        self.assertEqual(result["failed"], ["DUE-001"])
        self.assertEqual(result["approved"], ["DUE-002"])

    def _ratio_workspace(self, artwork_code):
        workspace = Path(self.temporary.name) / artwork_code
        print_folder = workspace / "02 Print Files"
        print_folder.mkdir(parents=True)
        master = print_folder / f"{artwork_code}_master.png"
        Image.new("RGB", (600, 400), "blue").save(master)
        db.upsert_artwork_file(
            artwork_code, "print_master",
            str(master.relative_to(workspace)), master.name, master.name,
        )
        old_files = {}
        production = db.get_artwork_production(artwork_code)
        for ratio in [
            value.strip() for value in production["required_ratios"].split(",")
            if value.strip()
        ]:
            slug = ratio.replace(":", "x")
            path = print_folder / f"{artwork_code}_ratio_{slug}.png"
            path.write_bytes(f"old-{ratio}".encode())
            db.upsert_artwork_file(
                artwork_code, f"ratio:{ratio}",
                str(path.relative_to(workspace)), path.name, path.name,
            )
            old_files[ratio] = path
        return workspace, old_files

    def test_regenerates_selected_ratio_set_and_preserves_other_state(self):
        workspace, old_files = self._ratio_workspace("DUE-001")
        listing_id = db.create_listing(
            "DUE-001", marketplace="Etsy", product="Poster",
            title="Existing", description="Keep", tags="keep",
            price_cents=4777, status="published",
        )
        with db.get_connection() as connection:
            connection.execute(
                """
                UPDATE listings SET external_listing_id='123',
                    marketplace_url='https://www.etsy.com/listing/123'
                WHERE id=?
                """,
                (listing_id,),
            )
            connection.commit()
        db.set_artwork_production_flags(
            "DUE-001", ratio_exports_ready=True, mockups_ready=True
        )
        with (
            patch("web.production_tasks.get_artwork_folder", return_value=workspace),
            patch("web.ratio_generator.get_artwork_folder", return_value=workspace),
        ):
            regenerated = regenerate_ratio_set(db.get_artwork("DUE-001"))
        self.assertEqual(set(regenerated), set(old_files))
        for path in old_files.values():
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
        production = db.get_artwork_production("DUE-001")
        self.assertFalse(production["ratio_exports_ready"])
        self.assertTrue(production["mockups_ready"])
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["price_cents"], 4777)
        self.assertEqual(listing["external_listing_id"], "123")

    def test_failed_ratio_set_preserves_old_files_and_approval(self):
        workspace, old_files = self._ratio_workspace("DUE-001")
        before = {ratio: path.read_bytes() for ratio, path in old_files.items()}
        db.set_artwork_production_flags(
            "DUE-001", ratio_exports_ready=True, mockups_ready=True
        )
        with (
            patch("web.production_tasks.get_artwork_folder", return_value=workspace),
            patch("web.production_tasks.generate_ratio_output") as generate,
        ):
            generate.side_effect = [
                {
                    "ratio": "3:2", "status": "created",
                    "stored_filename": "DUE-001_ratio_3x2.png",
                },
                {"ratio": "4:3", "status": "failed", "message": "simulated"},
                {"ratio": "5:4", "status": "created", "stored_filename": "unused.png"},
                {"ratio": "14:11", "status": "created", "stored_filename": "unused2.png"},
            ]
            with self.assertRaises(ValueError):
                regenerate_ratio_set(db.get_artwork("DUE-001"))
        self.assertEqual(
            {ratio: path.read_bytes() for ratio, path in old_files.items()},
            before,
        )
        self.assertTrue(
            db.get_artwork_production("DUE-001")["ratio_exports_ready"]
        )

    def test_selected_ratio_batch_continues_and_does_not_touch_unselected(self):
        db.set_artwork_production_flags(
            "DUE-001", ratio_exports_ready=True
        )
        db.set_artwork_production_flags(
            "DUE-002", ratio_exports_ready=True
        )

        def regenerate(artwork):
            if artwork["artwork_code"] == "DUE-001":
                db.set_artwork_production_flags(
                    "DUE-001", ratio_exports_ready=False
                )
                return ["3:2"]
            raise ValueError("simulated failure")

        with patch(
            "web.collection_review.regenerate_ratio_set",
            side_effect=regenerate,
        ) as operation:
            result = regenerate_selected_ratio_sets(
                "DUE", ["DUE-001", "DUE-002"]
            )
        self.assertEqual(operation.call_count, 2)
        self.assertEqual(result["successes"], ["DUE-001"])
        self.assertEqual(result["failures"][0]["artwork_code"], "DUE-002")
        self.assertFalse(
            db.get_artwork_production("DUE-001")["ratio_exports_ready"]
        )
        self.assertTrue(
            db.get_artwork_production("DUE-002")["ratio_exports_ready"]
        )

        with patch("web.collection_review.regenerate_ratio_set") as unselected:
            regenerate_selected_ratio_sets("DUE", ["DUE-001"])
        self.assertEqual(unselected.call_count, 1)
        self.assertEqual(
            unselected.call_args.args[0]["artwork_code"], "DUE-001"
        )

    def _collection_card_workspace(self, artwork_code):
        workspace = Path(self.temporary.name) / artwork_code
        source = workspace / "01 Source Artwork" / "source.png"
        source.parent.mkdir(parents=True)
        Image.new("RGB", (400, 600), "red").save(source)
        card = workspace / "03 Mockups" / "collection.jpg"
        card.parent.mkdir(parents=True)
        card.write_bytes(b"previous-card")
        db.upsert_artwork_file(
            artwork_code, "source", str(source.relative_to(workspace)),
            source.name, source.name,
        )
        db.upsert_artwork_file(
            artwork_code, "mockup:collection", str(card.relative_to(workspace)),
            card.name, card.name,
        )
        mockup_set = next(
            row for row in db.list_mockup_sets() if row["name"] == "Etsy Standard"
        )
        db.record_artwork_mockup_set_generated(artwork_code, mockup_set["id"])
        db.approve_artwork_mockup_set(artwork_code, mockup_set["id"])
        db.set_artwork_production_flags(
            artwork_code, ratio_exports_ready=True, mockups_ready=True
        )
        return workspace, card

    def test_collection_card_batch_refreshes_selected_artwork_only(self):
        with patch(
            "web.collection_review.regenerate_collection_branding_card"
        ) as refresh:
            result = refresh_selected_collection_cards("DUE", ["DUE-001"])
        self.assertEqual(result["successes"], ["DUE-001"])
        self.assertEqual(result["failures"], [])
        refresh.assert_called_once_with("DUE-001")

    def test_collection_card_refresh_preserves_external_state_and_clears_approval(self):
        workspace, old_card = self._collection_card_workspace("DUE-001")
        listing_id = db.create_listing(
            "DUE-001", marketplace="Etsy", product="Poster",
            title="Existing", description="Keep", tags="keep",
            price_cents=4777, status="published",
        )
        with db.get_connection() as connection:
            connection.execute(
                """
                UPDATE listings
                SET printify_product_id='printify-existing',
                    external_listing_id='etsy-existing',
                    etsy_state='active'
                WHERE id=?
                """,
                (listing_id,),
            )
            connection.commit()

        def generate(**kwargs):
            path = kwargs["output_folder"] / "collection.jpg"
            path.write_bytes(b"new-card")
            return {
                "path": path, "stored_filename": "collection.jpg",
                "original_filename": "collection.jpg",
            }

        with (
            patch("web.mockup_tasks.get_artwork_folder", return_value=workspace),
            patch("web.ratio_generator.get_artwork_folder", return_value=workspace),
            patch("web.mockup_tasks.generate_listing_image", side_effect=generate),
        ):
            regenerate_collection_branding_card("DUE-001")

        self.assertEqual(old_card.read_bytes(), b"new-card")
        production = db.get_artwork_production("DUE-001")
        self.assertFalse(production["mockups_ready"])
        self.assertTrue(production["ratio_exports_ready"])
        self.assertIsNone(
            db.get_artwork_mockup_set_state("DUE-001")["approved_at"]
        )
        listing = db.get_listing(listing_id)
        self.assertEqual(listing["price_cents"], 4777)
        self.assertEqual(listing["printify_product_id"], "printify-existing")
        self.assertEqual(listing["external_listing_id"], "etsy-existing")

    def test_failed_collection_card_refresh_preserves_previous_file_and_approval(self):
        workspace, old_card = self._collection_card_workspace("DUE-001")
        with (
            patch("web.mockup_tasks.get_artwork_folder", return_value=workspace),
            patch("web.ratio_generator.get_artwork_folder", return_value=workspace),
            patch(
                "web.mockup_tasks.generate_listing_image",
                side_effect=ValueError("simulated failure"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "simulated failure"):
                regenerate_collection_branding_card("DUE-001")
        self.assertEqual(old_card.read_bytes(), b"previous-card")
        self.assertTrue(db.get_artwork_production("DUE-001")["mockups_ready"])
        self.assertIsNotNone(
            db.get_artwork_mockup_set_state("DUE-001")["approved_at"]
        )

    def test_collection_card_staleness_tracks_collection_source_changes(self):
        self._collection_card_workspace("DUE-001")
        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='DUE-001'"
            ).fetchone()["id"]
            connection.execute(
                "UPDATE artwork_files SET updated_at='2026-01-01 00:00:00' "
                "WHERE artwork_id=? AND role='mockup:collection'",
                (artwork_id,),
            )
            connection.execute(
                "UPDATE artwork_files SET updated_at='2026-02-01 00:00:00' "
                "WHERE artwork_id=? AND role='source'",
                (artwork_id,),
            )
            connection.commit()
        self.assertTrue(collection_branding_is_stale("DUE", "DUE-001"))
        response = self.client.get("/collections/DUE/review")
        self.assertIn("Collection card needs refresh", response.text)
        self.assertIn("Refresh Collection Cards", response.text)


class SourcePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.png"
        Image.new("RGB", (800, 1200), "red").save(self.source)
        self.artwork = {
            "artwork_code": "DUE-001",
            "collection_code": "DUE",
        }
        self.assignment = {
            "role": "source",
            "stored_filename": "source.png",
            "original_filename": "source.png",
        }

    def tearDown(self):
        self.temporary.cleanup()

    @patch("web.production_tasks.upscale_candidate")
    @patch("web.production_tasks.upsert_artwork_certification")
    @patch("web.production_tasks.get_artwork_certification")
    @patch("web.production_tasks.resolve_assigned_file")
    @patch("web.production_tasks.assignment_map")
    @patch("web.production_tasks.certify_artwork")
    def test_passing_original_is_never_upscaled(
        self, certify, assignments, resolve, get_certification, upsert, upscale
    ):
        passing = {
            "valid": True, "score": 92, "orientation": "vertical",
            "width": 3200, "height": 4800,
        }
        certify.return_value.to_dict.return_value = passing
        assignments.return_value = {"source": self.assignment}
        resolve.return_value = self.source
        get_certification.return_value = passing
        result = ensure_source_certification(self.artwork)
        self.assertEqual(result[3], "original")
        upscale.assert_not_called()

    @patch("web.production_tasks.record_ai_enhancement")
    @patch("web.production_tasks.invalidate_artwork_after_source_change")
    @patch("web.production_tasks.upsert_artwork_file")
    @patch("web.production_tasks.upsert_artwork_certification")
    @patch("web.production_tasks.get_artwork_certification")
    @patch("web.production_tasks.resolve_assigned_file")
    @patch("web.production_tasks.get_artwork_folder")
    @patch("web.production_tasks.candidate_path")
    @patch("web.production_tasks.upscale_candidate")
    @patch("web.production_tasks.assignment_map")
    @patch("web.production_tasks.certify_artwork")
    def test_low_quality_original_uses_existing_four_x_candidate(
        self, certify, assignments, upscale, candidate_path_mock, folder,
        resolve, get_certification, upsert_cert, upsert_file, invalidate,
        record,
    ):
        candidate = self.root / "DUE-001_ai_upscaled_4x.png"
        Image.new("RGB", (3200, 4800), "red").save(candidate)
        approved = self.root / "DUE-001_ai_upscaled_approved.png"
        low = {
            "valid": True, "score": 72, "orientation": "vertical",
            "width": 800, "height": 1200,
        }
        passing = {
            "valid": True, "score": 96, "orientation": "vertical",
            "width": 3200, "height": 4800,
        }
        certify.side_effect = [
            type("Result", (), {"to_dict": lambda self: low})(),
            type("Result", (), {"to_dict": lambda self: passing})(),
        ]
        assignments.side_effect = [
            {"source": self.assignment},
            {"source": {
                **self.assignment,
                "stored_filename": approved.name,
            }},
        ]
        resolve.return_value = self.source
        get_certification.side_effect = [low, passing]
        candidate_path_mock.return_value = candidate
        folder.return_value = self.root
        result = ensure_source_certification(self.artwork)
        self.assertEqual(result[3], "ai_upscale_4x")
        self.assertTrue(approved.is_file())
        upscale.assert_not_called()
        record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
