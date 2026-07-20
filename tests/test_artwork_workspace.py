from app import database


def test_workspace_survives_public_title_change(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "COLLECTIONS_DIR", tmp_path)
    collection = tmp_path / "CEL"
    original = collection / "CEL-009 Golden-Gathering"
    original.mkdir(parents=True)

    renamed_artwork = {
        "collection_code": "CEL",
        "artwork_code": "CEL-009",
        "public_title": "Gathering",
    }

    assert database.get_artwork_folder(renamed_artwork) == original


def test_new_workspace_uses_current_public_title(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "COLLECTIONS_DIR", tmp_path)
    artwork = {
        "collection_code": "CEL",
        "artwork_code": "CEL-010",
        "public_title": "Together",
    }

    assert database.get_artwork_folder(artwork) == tmp_path / "CEL" / "CEL-010 Together"
