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


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.original_db_path = db.DATABASE_PATH
        db.DATABASE_PATH = self.database_path

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO brands (code, name) VALUES ('SHG', 'ShangooliShop')")
        brand_id = connection.execute("SELECT id FROM brands WHERE code='SHG'").fetchone()["id"]
        connection.execute(
            "INSERT INTO collections (brand_id, code, name, collection_type, vertical, status) VALUES (?, 'CEL', 'Celebration', 'curated', 'home_art', 'active')",
            (brand_id,),
        )
        collection_id = connection.execute("SELECT id FROM collections WHERE code='CEL'").fetchone()["id"]
        connection.execute(
            "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) VALUES ('CEL-001', ?, 1, 'Unbound', 'approved')",
            (collection_id,),
        )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.client = TestClient(app)

    def tearDown(self):
        db.DATABASE_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _complete_artwork_files(self):
        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["id"]
            connection.executemany(
                "INSERT INTO artwork_files (artwork_id, role, relative_path, stored_filename, original_filename) VALUES (?, ?, ?, ?, ?)",
                [
                    (artwork_id, "source", "source.png", "source.png", "source.png"),
                    (artwork_id, "print_master", "master.png", "master.png", "master.png"),
                ],
            )
            connection.execute(
                "UPDATE artwork_production SET print_master_ready=1, ratio_exports_ready=1, mockups_ready=1 WHERE artwork_id=?",
                (artwork_id,),
            )
            connection.commit()

    def test_dashboard_shows_listing_work_queue(self):
        db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Unbound Poster", description="", tags="",
            price_cents=0, status="draft",
        )
        response = self.client.get("/?view=attention")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Production dashboard", response.text)
        self.assertIn("Listings with missing items", response.text)
        self.assertIn("Needs attention", response.text)
        self.assertIn("Unbound Poster", response.text)
        self.assertIn("Missing: Source artwork", response.text)
        self.assertIn('class="dashboard-listing-thumb"', response.text)
        self.assertIn("No image", response.text)
        self.assertIn('aria-label="Dashboard navigation"', response.text)
        self.assertIn('href="/collections"', response.text)
        self.assertNotIn("Start here", response.text)
        self.assertIn('href="/?view=attention"', response.text)
        self.assertIn('data-app-wait', response.text)
        self.assertIn('app-wait-spinner', response.text)

        dashboard_focus = self.client.get("/?view=attention")
        self.assertIn("Listings with missing items", dashboard_focus.text)
        self.assertIn("Unbound Poster", dashboard_focus.text)
        self.assertIn('href="/?view=artworks"', dashboard_focus.text)

        self._complete_artwork_files()
        listings_dashboard = self.client.get("/?view=listings")
        self.assertIn(
            'src="/artworks/CEL-001/files/view?role=source"',
            listings_dashboard.text,
        )
        self.assertIn('alt="Unbound thumbnail"', listings_dashboard.text)

        default_dashboard = self.client.get("/")
        self.assertIn("Recently updated artwork", default_dashboard.text)
        self.assertIn('dashboard-metric-link is-selected', default_dashboard.text)

        focused = self.client.get("/listings?view=attention")
        self.assertEqual(focused.status_code, 200)
        self.assertIn("Listings that need attention", focused.text)
        self.assertIn("Unbound Poster", focused.text)
        self.assertIn('href="/?view=attention"', focused.text)
        self.assertIn("Back to dashboard", focused.text)

    def test_mockup_studio_saves_and_offers_reusable_room_scene(self):
        image_bytes = BytesIO()
        Image.new("RGB", (800, 600), "#ddd6cb").save(image_bytes, "PNG")
        scenes_folder = Path(self.temp_dir.name) / "mockup-scenes"
        with patch("web.app.MOCKUP_SCENES_DIR", scenes_folder):
            response = self.client.post(
                "/mockup-studio/scenes",
                data={
                    "name": "Bright sofa wall", "room_type": "Living room",
                    "orientation": "horizontal", "placement_x": "25",
                    "placement_y": "15", "placement_width": "50",
                    "placement_height": "45",
                    "source_url": "https://www.pexels.com/photo/example/",
                    "creator": "Example Artist", "license_name": "Pexels License",
                },
                files={"upload": ("living-room.png", image_bytes.getvalue(), "image/png")},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            scene = db.list_mockup_scenes()[0]
            self.assertEqual(scene["name"], "Bright sofa wall")
            self.assertEqual(scene["creator"], "Example Artist")
            self.assertTrue((scenes_folder / scene["image_path"]).is_file())
            image_response = self.client.get(
                f"/mockup-studio/scenes/{scene['id']}/image"
            )
            self.assertEqual(image_response.status_code, 200)

        studio = self.client.get("/mockup-studio")
        self.assertIn("Mockup Studio", studio.text)
        self.assertIn("Bright sofa wall", studio.text)
        self.assertIn("Example Artist", studio.text)
        self.assertIn("Pexels License", studio.text)
        artwork = self.client.get("/artworks/CEL-001")
        self.assertIn("Living room · Bright sofa wall", artwork.text)

        scene_id = db.list_mockup_scenes()[0]["id"]
        response = self.client.post(
            f"/mockup-studio/scenes/{scene_id}/placement",
            data={
                "placement_x": "10", "placement_y": "12",
                "placement_width": "60", "placement_height": "55",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        scene = db.get_mockup_scene(scene_id)
        self.assertEqual(scene["placement_x"], 10)
        self.assertEqual(scene["placement_width"], 60)

        response = self.client.post(
            f"/mockup-studio/scenes/{scene_id}/disable", follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertFalse(db.get_mockup_scene(scene_id)["active"])
        self.assertIn("No room scenes yet", self.client.get("/mockup-studio").text)

    def test_collections_filter_keeps_collection_cards_and_updates_artwork_panel(self):
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE collections SET target_artwork_count=3 WHERE code='CEL'"
            )
            collection_id = connection.execute(
                "SELECT id FROM collections WHERE code='CEL'"
            ).fetchone()["id"]
            connection.execute(
                "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) VALUES ('CEL-099', ?, 99, 'Retired Test', 'retired')",
                (collection_id,),
            )
            connection.commit()

        default_response = self.client.get("/collections")
        self.assertIn('href="/collections?collection=CEL"', default_response.text)
        self.assertIn('aria-current="true"', default_response.text)
        self.assertIn("Celebration artwork", default_response.text)
        self.assertNotIn("Your latest active artwork across all collections", default_response.text)
        self.assertIn('data-bs-target="#new-collection-modal"', default_response.text)
        self.assertIn('id="new-collection-modal"', default_response.text)

        response = self.client.get("/collections?collection=CEL")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/collections?collection=CEL"', response.text)
        self.assertIn('aria-current="true"', response.text)
        self.assertIn("Viewing artwork below", response.text)
        self.assertIn("Celebration artwork", response.text)
        self.assertIn(
            'class="collection-heading-link" href="/collections/CEL"',
            response.text,
        )
        self.assertIn("Unbound", response.text)
        self.assertIn('class="collection-gallery', response.text)
        self.assertIn('data-collection-gallery', response.text)
        self.assertIn('data-gallery-next', response.text)
        self.assertIn('data-bs-target="#edit-collection-modal"', response.text)
        self.assertIn('data-bs-target="#new-artwork-modal"', response.text)
        self.assertIn('id="edit-collection-modal"', response.text)
        self.assertIn('id="new-artwork-modal"', response.text)
        self.assertNotIn("Open collection", response.text)
        self.assertEqual(response.text.count("collection-empty-artwork-card"), 2)
        self.assertIn("Empty artwork slot", response.text)
        self.assertIn("CEL-003", response.text)
        artwork_grid = response.text[response.text.index('class="row g-3 dashboard-recent-grid"'):]
        self.assertLess(artwork_grid.index("CEL-001"), artwork_grid.index("CEL-003"))
        self.assertIn('data-artwork-context-menu', response.text)
        self.assertIn("Show retired (1)", response.text)
        self.assertNotIn("Retired Test", response.text)

        with_retired = self.client.get(
            "/collections?collection=CEL&show_retired=true"
        )
        self.assertEqual(with_retired.status_code, 200)
        self.assertIn("Hide retired (1)", with_retired.text)
        self.assertIn("Retired Test", with_retired.text)
        self.assertEqual(
            with_retired.text.count("collection-empty-artwork-card"), 2
        )

        with db.get_connection() as connection:
            collection_id = connection.execute("SELECT id FROM collections WHERE code='CEL'").fetchone()["id"]
            connection.executemany(
                "INSERT INTO artworks (artwork_code, collection_id, sequence_number, public_title, status) VALUES (?, ?, ?, ?, 'approved')",
                [("CEL-010", collection_id, 2, "Ten",), ("CEL-002", collection_id, 10, "Two",)],
            )
            connection.execute(
                "INSERT INTO artwork_production (artwork_id) SELECT id FROM artworks WHERE artwork_code IN ('CEL-002', 'CEL-010')"
            )
            connection.commit()
        ordered = self.client.get("/collections?collection=CEL").text
        gallery = ordered[ordered.index('data-collection-gallery'):ordered.index('</section>', ordered.index('data-collection-gallery'))]
        self.assertLess(gallery.index("CEL-001"), gallery.index("CEL-002"))
        self.assertLess(gallery.index("CEL-002"), gallery.index("CEL-010"))

        status_change = self.client.post(
            "/artworks/CEL-001/status",
            data={"status": "paused", "return_to": "/collections?collection=CEL"},
            follow_redirects=False,
        )
        self.assertEqual(status_change.status_code, 303)
        self.assertEqual(
            status_change.headers["location"], "/collections?collection=CEL"
        )
        with db.get_connection() as connection:
            changed_status = connection.execute(
                "SELECT status FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["status"]
        self.assertEqual(changed_status, "paused")

        unsafe_return = self.client.post(
            "/artworks/CEL-001/status",
            data={"status": "approved", "return_to": "https://example.com"},
            follow_redirects=False,
        )
        self.assertEqual(unsafe_return.headers["location"], "/collections")

        missing = self.client.get("/collections?collection=MISSING")
        self.assertEqual(missing.status_code, 404)

        collection_page = self.client.get("/collections/CEL")
        self.assertIn('href="/collections?collection=CEL"', collection_page.text)
        self.assertIn("All collections", collection_page.text)
        self.assertIn("Empty artwork slot", collection_page.text)
        self.assertIn("CEL-003", collection_page.text)
        detail_grid = collection_page.text[
            collection_page.text.index('class="row g-4"'):
            collection_page.text.index("Archived artwork")
            if "Archived artwork" in collection_page.text else len(collection_page.text)
        ]
        self.assertLess(detail_grid.index("CEL-001"), detail_grid.index("CEL-002"))
        self.assertLess(detail_grid.index("CEL-002"), detail_grid.index("CEL-003"))
        self.assertLess(detail_grid.index("CEL-003"), detail_grid.index("CEL-010"))

        new_collection = self.client.get("/collections/new")
        self.assertIn('href="/collections"', new_collection.text)
        self.assertIn("Back to collections", new_collection.text)

        recent = self.client.get("/recent")
        self.assertEqual(recent.status_code, 200)
        self.assertIn("Recently updated", recent.text)
        self.assertIn('href="/recent" class="is-active"', recent.text)
        self.assertIn("Unbound", recent.text)

    def test_dashboard_shows_ready_to_publish(self):
        self._complete_artwork_files()
        db.create_listing(
            "CEL-001", marketplace="Etsy", product="Poster",
            title="Complete Unbound", description="Description", tags="one, two",
            price_cents=3995, status="ready",
        )
        response = self.client.get("/?view=ready")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ready to publish", response.text)
        self.assertIn("Complete Unbound", response.text)
        self.assertIn('href="/?view=ready"', response.text)

        dashboard_focus = self.client.get("/?view=ready")
        self.assertIn("Completed listings awaiting publication", dashboard_focus.text)
        self.assertIn("Complete Unbound", dashboard_focus.text)

        focused = self.client.get("/listings?view=ready")
        self.assertEqual(focused.status_code, 200)
        self.assertIn("Showing complete listings", focused.text)
        self.assertIn("Complete Unbound", focused.text)
        self.assertIn('href="/?view=ready"', focused.text)

    def test_certified_master_locks_production_orientation(self):
        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO print_master_certification (
                    artwork_id, valid, width, height, orientation,
                    master_ratio, required_ratios
                ) VALUES (?, 1, 4000, 6000, 'vertical', '2:3',
                          '2:3, 3:4, 4:5, 11:14')
                """,
                (artwork_id,),
            )
            connection.commit()

        page = self.client.get("/artworks/CEL-001")
        self.assertIn('value="vertical" readonly', page.text)
        self.assertIn("Locked by the certified print-ready file", page.text)

        response = self.client.post(
            "/artworks/CEL-001/production",
            data={"orientation": "horizontal"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("locked to vertical", response.json()["detail"])

    def test_collection_and_artwork_pages_show_guided_workflow(self):
        collection_page = self.client.get("/collections/CEL")
        self.assertEqual(collection_page.status_code, 200)
        self.assertIn('aria-label="Collection workflow"', collection_page.text)
        self.assertIn("CEL-001", collection_page.text)

        artwork_page = self.client.get("/artworks/CEL-001")
        self.assertEqual(artwork_page.status_code, 200)
        self.assertIn(
            'aria-label="Collection and artwork workflow"', artwork_page.text
        )
        labels = [
            "Details",
            "Source",
            "Quality",
            "Print files",
            "Mockups",
            "Listing",
            "Publish",
        ]
        workflow_buttons = artwork_page.text[
            artwork_page.text.index('<nav class="workflow-step-buttons"'):
        ]
        positions = [workflow_buttons.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('aria-label="Artwork workflow steps"', artwork_page.text)
        sidebar_end = artwork_page.text.index("</aside>")
        self.assertNotIn('data-workflow-link=', artwork_page.text[:sidebar_end])
        for stage in (
            "details", "source", "certification", "print", "mockups", "listing", "publish"
        ):
            self.assertIn(f'data-workflow-stage="{stage}"', artwork_page.text)
        self.assertIn('data-bs-target="#prepare-artwork-modal"', artwork_page.text)
        self.assertIn("artwork-marketplace-status", artwork_page.text)
        self.assertIn('id="prepare-artwork-modal"', artwork_page.text)
        self.assertIn("Prepare automatically", artwork_page.text)
        self.assertIn('data-long-operation', artwork_page.text)
        self.assertIn("Do not publish to Printify or Etsy", artwork_page.text)

        missing_source = self.client.post(
            "/artworks/CEL-001/prepare",
            data={"price": "25.00", "confirmed": "true"},
        )
        self.assertEqual(missing_source.status_code, 400)
        self.assertIn("Upload source artwork first", missing_source.json()["detail"])

        unconfirmed = self.client.post(
            "/artworks/CEL-001/prepare",
            data={"price": "25.00"},
        )
        self.assertEqual(unconfirmed.status_code, 400)
        self.assertIn("Confirm automatic preparation", unconfirmed.json()["detail"])

    def test_source_change_marks_downstream_work_stale_and_resets_ai_lock(self):
        self._complete_artwork_files()
        db.set_artwork_production_flags(
            "CEL-001", original_approved=True, listing_content_ready=True,
        )
        db.record_ai_enhancement(
            "CEL-001", original_width=1000, original_height=800,
            enhanced_width=4000, enhanced_height=3200,
        )
        db.invalidate_artwork_after_source_change("CEL-001")

        production = db.get_artwork_production("CEL-001")
        self.assertFalse(production["original_approved"])
        self.assertFalse(production["print_master_ready"])
        self.assertFalse(production["ratio_exports_ready"])
        self.assertFalse(production["mockups_ready"])
        self.assertFalse(production["listing_content_ready"])
        self.assertIsNone(production["ai_enhanced_at"])
        self.assertEqual(len(db.get_artwork_file_assignments("CEL-001")), 2)

        page = self.client.get("/artworks/CEL-001?step=print")
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-workflow-state="out_of_date"', page.text)
        self.assertIn('data-workflow-stage="certification"', page.text)

    def test_ai_enhancement_is_blocked_after_approval_record(self):
        db.record_ai_enhancement(
            "CEL-001", original_width=1000, original_height=800,
            enhanced_width=4000, enhanced_height=3200,
        )
        response = self.client.post("/artworks/CEL-001/ai-upscale")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already been AI enhanced", response.json()["detail"])

    def test_existing_approved_ai_source_is_backfilled_as_enhanced(self):
        db.upsert_artwork_file(
            "CEL-001", role="source", relative_path="approved.png",
            stored_filename="CEL-001_ai_upscaled_approved.png",
            original_filename="CEL-001_ai_upscaled_approved.png",
        )
        db.ensure_production_schema()
        production = db.get_artwork_production("CEL-001")
        self.assertIsNotNone(production["ai_enhanced_at"])

    def test_existing_source_can_run_quality_check_without_rebuilding(self):
        self._complete_artwork_files()
        source_path = Path(self.temp_dir.name) / "source.png"
        Image.new("RGB", (1800, 1200), "orange").save(source_path)

        page = self.client.get("/artworks/CEL-001?step=certification")
        self.assertIn("Run quality check", page.text)
        self.assertIn("Needs review", page.text)
        with patch("web.app.resolve_assigned_file", return_value=source_path):
            response = self.client.post(
                "/artworks/CEL-001/certification/run", follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("step=certification", response.headers["location"])
        certification = db.get_artwork_certification("CEL-001")
        self.assertEqual(certification["width"], 1800)
        self.assertEqual(certification["height"], 1200)
        self.assertTrue(db.get_artwork_production("CEL-001")["print_master_ready"])

    def test_generated_print_files_awaiting_crop_approval_need_review(self):
        with db.get_connection() as connection:
            artwork_id = connection.execute(
                "SELECT id FROM artworks WHERE artwork_code='CEL-001'"
            ).fetchone()["id"]
            connection.executemany(
                "INSERT INTO artwork_files "
                "(artwork_id, role, relative_path, stored_filename, original_filename) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (artwork_id, "source", "source.png", "source.png", "source.png"),
                    (artwork_id, "print_master", "master.png", "master.png", "master.png"),
                    *[
                        (
                            artwork_id, f"ratio:{ratio}", f"{ratio}.png",
                            f"{ratio}.png", f"{ratio}.png",
                        )
                        for ratio in ("3:2", "4:3", "5:4", "14:11")
                    ],
                ],
            )
            connection.execute(
                "UPDATE artwork_production SET original_approved=1, "
                "print_master_ready=1, ratio_exports_ready=0 WHERE artwork_id=?",
                (artwork_id,),
            )
            connection.commit()

        page = self.client.get("/artworks/CEL-001?step=print")
        workflow = page.text[page.text.index('aria-label="Artwork workflow steps"'):]
        self.assertIn("Print files", workflow)
        self.assertIn("Needs review", workflow)

        with db.get_connection() as connection:
            connection.execute(
                "UPDATE artwork_production SET print_master_ready=0 WHERE artwork_id=?",
                (artwork_id,),
            )
            connection.commit()
        stale_page = self.client.get("/artworks/CEL-001?step=print")
        stale_workflow = stale_page.text[
            stale_page.text.index('aria-label="Artwork workflow steps"'):
        ]
        self.assertIn("Out of date", stale_workflow)

    def test_collection_prompt_is_versioned_and_applied_explicitly(self):
        db.update_collection(
            "CEL", "Celebration", 8, "active",
            etsy_section_name="Celebration",
            creative_direction="Shared joyful movement and warm color.",
            negative_prompt="No text or logos.",
        )
        intelligence = db.get_artwork_intelligence("CEL-001")
        saved_version = intelligence["collection_prompt_version"]
        self.assertEqual(
            intelligence["collection_prompt_snapshot"],
            "Shared joyful movement and warm color.",
        )

        db.update_collection(
            "CEL", "Celebration", 8, "active",
            etsy_section_name="Celebration",
            creative_direction="Updated collection direction.",
            negative_prompt="No text, logos, or borders.",
        )
        unchanged = db.get_artwork_intelligence("CEL-001")
        self.assertEqual(unchanged["collection_prompt_version"], saved_version)
        page = self.client.get("/artworks/CEL-001?step=details")
        self.assertIn("The collection direction has changed", page.text)

        response = self.client.post(
            "/artworks/CEL-001/intelligence/apply-collection-prompt",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        refreshed = db.get_artwork_intelligence("CEL-001")
        self.assertEqual(
            refreshed["collection_prompt_snapshot"],
            "Updated collection direction.",
        )
        self.assertGreater(refreshed["collection_prompt_version"], saved_version)

    def test_collection_order_is_saved_and_used_by_dashboard(self):
        with db.get_connection() as connection:
            brand_id = connection.execute(
                "SELECT id FROM brands WHERE code='SHG'"
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO collections (
                    brand_id, code, name, collection_type, vertical, status
                ) VALUES (?, 'DEN', 'Dental Collection', 'curated',
                          'home_art', 'active')
                """,
                (brand_id,),
            )
            connection.commit()

        response = self.client.post(
            "/collections/order", json={"codes": ["CEL", "DEN"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["saved"])

        page = self.client.get("/collections")
        cel_position = page.text.index('data-collection-code="CEL"')
        den_position = page.text.index('data-collection-code="DEN"')
        self.assertLess(cel_position, den_position)
        self.assertIn("Drag collections to reorder", page.text)


if __name__ == "__main__":
    unittest.main()
