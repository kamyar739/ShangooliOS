import sqlite3
from pathlib import Path

import web.db as db


def _prepare_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE artworks (
                id INTEGER PRIMARY KEY,
                artwork_code TEXT NOT NULL UNIQUE,
                theme TEXT,
                status TEXT DEFAULT 'idea',
                updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO artworks (id, artwork_code, theme) VALUES (1, 'CEL-001', 'Joy')"
        )
        conn.commit()


def test_template_selection_persists_per_listing_image(tmp_path, monkeypatch):
    database_path = tmp_path / "shangooli.db"
    _prepare_database(database_path)
    monkeypatch.setattr(db, "DATABASE_PATH", database_path)
    db.ensure_production_schema()

    db.save_artwork_mockup_template("CEL-001", "living_room", "warm_contemporary")
    db.save_artwork_mockup_template("CEL-001", "office", "modern_minimal")

    selections = {
        row["slot_key"]: row["template_key"]
        for row in db.get_artwork_mockup_templates("CEL-001")
    }
    assert selections == {
        "living_room": "warm_contemporary",
        "office": "modern_minimal",
    }


def test_generate_all_style_update_overwrites_saved_selections(tmp_path, monkeypatch):
    database_path = tmp_path / "shangooli.db"
    _prepare_database(database_path)
    monkeypatch.setattr(db, "DATABASE_PATH", database_path)
    db.ensure_production_schema()

    db.save_artwork_mockup_templates(
        "CEL-001",
        {
            "hero": "warm_contemporary",
            "living_room": "warm_contemporary",
        },
    )
    db.save_artwork_mockup_templates(
        "CEL-001",
        {
            "hero": "modern_minimal",
            "living_room": "modern_minimal",
        },
    )

    selections = {
        row["slot_key"]: row["template_key"]
        for row in db.get_artwork_mockup_templates("CEL-001")
    }
    assert selections == {
        "hero": "modern_minimal",
        "living_room": "modern_minimal",
    }
