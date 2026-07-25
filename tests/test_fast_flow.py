import json
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import database
from web import db
from web.app import app


def image_bytes(color):
    output = BytesIO()
    Image.new("RGB", (120, 180), color).save(output, "PNG")
    return output.getvalue()


class FastFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.database_path = root / "test.db"
        self.collections_dir = root / "collections"
        self.original_web_database_path = db.DATABASE_PATH
        self.original_app_database_path = database.DATABASE_PATH
        self.original_collections_dir = database.COLLECTIONS_DIR
        db.DATABASE_PATH = self.database_path
        database.DATABASE_PATH = self.database_path
        database.COLLECTIONS_DIR = self.collections_dir

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO brands (code, name) VALUES ('SHG', 'ShangooliShop')"
        )
        connection.commit()
        connection.close()
        db.ensure_production_schema()
        self.client = TestClient(app)

    def tearDown(self):
        db.DATABASE_PATH = self.original_web_database_path
        database.DATABASE_PATH = self.original_app_database_path
        database.COLLECTIONS_DIR = self.original_collections_dir
        self.temp_dir.cleanup()

    def manifest(self):
        return {
            "collection": {
                "code": "FLW",
                "name": "The Flow Collection",
                "description": "A collection prepared outside ShangooliOS.",
                "prompt": "Shared visual language.",
                "etsy_section_name": "Flow",
                "status": "active",
            },
            "artworks": [
                {
                    "image": "first.png",
                    "title": "First",
                    "description": "First artwork description.",
                    "prompt": "First artwork prompt.",
                    "story": "First long story.",
                    "seo": {
                        "title": "First expressive wall art",
                        "description": "First Etsy description.",
                        "tags": ["expressive art", "wall decor"],
                        "alt_text": "A red expressive artwork.",
                        "keywords": ["red art", "movement"],
                    },
                },
                {
                    "image": "second.png",
                    "title": "Second",
                    "description": "Second artwork description.",
                    "prompt": "Second artwork prompt.",
                    "story": "Second long story.",
                    "seo": {
                        "title": "Second expressive wall art",
                        "description": "Second Etsy description.",
                        "tags": ["figurative art", "wall print"],
                        "alt_text": "A blue expressive artwork.",
                    },
                },
            ],
        }

    def test_fast_flow_page_is_an_independent_navigation_destination(self):
        response = self.client.get("/fast-flow")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Fast Flow", response.text)
        self.assertIn('href="/fast-flow"', response.text)
        self.assertIn("internal JSON format", response.text)
        self.assertIn("Choose the approved artwork images", response.text)
        self.assertIn("Add the collection details", response.text)
        self.assertIn("Review the collection", response.text)
        self.assertIn("Create collection", response.text)
        self.assertIn("Nothing is created yet", response.text)
        self.assertIn("Select all artwork images for this collection at once", response.text)
        self.assertIn("No artwork images selected", response.text)
        self.assertIn("Start over", response.text)
        self.assertIn('name="images" type="file"', response.text)
        self.assertIn(" multiple required", response.text)
        with db.get_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM collections").fetchone()[0],
                0,
            )

        reloaded = self.client.get("/fast-flow")
        self.assertNotIn("The Flow Collection", reloaded.text)
        self.assertIn("No artwork images selected", reloaded.text)

    def test_fast_flow_import_creates_normal_collection_artworks_and_sources(self):
        response = self.client.post(
            "/fast-flow/import",
            data={"manifest": json.dumps(self.manifest())},
            files=[
                ("images", ("first.png", image_bytes("#9f2f2f"), "image/png")),
                ("images", ("second.png", image_bytes("#263f80"), "image/png")),
            ],
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/collections?collection=FLW&fast_flow_imported=2",
        )

        collection, artworks, _ = db.get_collection("FLW")
        self.assertEqual(collection["name"], "The Flow Collection")
        self.assertEqual(
            collection["description"], "A collection prepared outside ShangooliOS."
        )
        self.assertEqual(collection["prompt"], "Shared visual language.")
        self.assertEqual(collection["target_artwork_count"], 2)
        self.assertEqual(
            [(item["artwork_code"], item["public_title"]) for item in artworks],
            [("FLW-001", "First"), ("FLW-002", "Second")],
        )

        first = db.get_artwork("FLW-001")
        self.assertEqual(first["description"], "First artwork description.")
        self.assertIsNone(first["story"])
        self.assertEqual(first["prompt"], "First artwork prompt.")
        assignments = {
            item["role"]: item for item in db.get_artwork_file_assignments("FLW-001")
        }
        self.assertEqual(assignments["source"]["original_filename"], "first.png")
        source_path = (
            database.get_artwork_folder(first)
            / assignments["source"]["relative_path"]
        )
        self.assertTrue(source_path.is_file())

        listing_content = db.get_artwork_listing_content("FLW-001")
        self.assertEqual(listing_content["long_story"], "First long story.")
        self.assertEqual(
            listing_content["etsy_title"], "First expressive wall art"
        )
        self.assertEqual(
            listing_content["etsy_tags"], "expressive art, wall decor"
        )
        self.assertEqual(listing_content["keywords"], "red art, movement")

        collection_page = self.client.get(
            "/collections?collection=FLW&fast_flow_imported=2"
        )
        self.assertIn("Fast Flow import complete", collection_page.text)
        self.assertIn("First", collection_page.text)
        self.assertIn("Second", collection_page.text)

    def test_fast_flow_imports_optional_intelligence_and_story_seo(self):
        package = {
            "collection": {
                "code": "RCH",
                "name": "The Rich Collection",
            },
            "artworks": [
                {
                    "image": "rich.png",
                    "title": "Resonance",
                    "description": "A factual description of the visible artwork.",
                    "prompt": "A precise artwork generation prompt.",
                    "intelligence": {
                        "theme": "Memory and connection",
                        "style": "Modern abstract figurative",
                        "mood": "Reflective",
                        "primary_colors": ["indigo", "gold", "ivory"],
                        "suggested_rooms": ["Living room", "Bedroom"],
                        "target_customer": [
                            "Art collectors",
                            "Contemporary decor shoppers",
                        ],
                        "ai_model": "GPT Image",
                        "analysis_notes": "Prepared with the completed collection.",
                    },
                    "story_seo": {
                        "short_story": "A short emotional story.",
                        "long_story": "A separate long emotional marketing narrative.",
                        "etsy_title": "Resonance Reflective Figurative Wall Art",
                        "etsy_description": "A customer-facing Etsy description.",
                        "etsy_tags": ["reflective wall art", "figurative print"],
                        "image_alt_text": "An indigo and gold figurative composition.",
                        "keywords": ["memory", "figurative art"],
                    },
                }
            ],
        }
        response = self.client.post(
            "/fast-flow/import",
            data={"manifest": json.dumps(package)},
            files=[("images", ("rich.png", image_bytes("#332266"), "image/png"))],
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        artwork = db.get_artwork("RCH-001")
        self.assertEqual(
            artwork["description"], "A factual description of the visible artwork."
        )
        self.assertIsNone(artwork["story"])
        self.assertEqual(artwork["prompt"], "A precise artwork generation prompt.")
        intelligence = db.get_artwork_intelligence("RCH-001")
        self.assertEqual(intelligence["theme"], "Memory and connection")
        self.assertEqual(
            intelligence["primary_colors"], "indigo, gold, ivory"
        )
        self.assertEqual(
            intelligence["suggested_room"], "Living room, Bedroom"
        )
        self.assertEqual(
            intelligence["target_customer"],
            "Art collectors, Contemporary decor shoppers",
        )
        listing_content = db.get_artwork_listing_content("RCH-001")
        self.assertEqual(
            listing_content["long_story"],
            "A separate long emotional marketing narrative.",
        )
        self.assertEqual(
            listing_content["etsy_tags"],
            "reflective wall art, figurative print",
        )
        self.assertEqual(
            listing_content["alt_text"],
            "An indigo and gold figurative composition.",
        )

    def test_fast_flow_rejects_missing_image_before_creating_collection(self):
        response = self.client.post(
            "/fast-flow/import",
            data={"manifest": json.dumps(self.manifest())},
            files=[
                ("images", ("first.png", image_bytes("#9f2f2f"), "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing artwork image: second.png", response.text)
        collection, _, _ = db.get_collection("FLW")
        self.assertIsNone(collection)


if __name__ == "__main__":
    unittest.main()
