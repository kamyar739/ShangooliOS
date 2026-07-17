from pathlib import Path

from PIL import Image

from web.print_master import build_print_master


def artwork(tmp_path: Path):
    return {
        "artwork_code": "CEL-999",
        "collection_code": "CEL",
        "public_title": "Test",
        "working_title": "Test",
    }


def test_build_print_master_normalizes_and_writes_manifest(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    source = tmp_path / "source.png"
    Image.new("RGBA", (1200, 800), (1, 2, 3, 128)).save(source)
    monkeypatch.setattr("web.print_master.get_artwork_folder", lambda _: workspace)

    result = build_print_master(
        artwork(tmp_path),
        source,
        max_long_edge=2400,
        max_scale=2,
    )

    assert result.resized is True
    assert (result.master_width, result.master_height) == (2400, 1600)
    assert result.scale_factor == 2
    assert (workspace / result.relative_path).is_file()
    assert (workspace / result.manifest_relative_path).is_file()
    with Image.open(workspace / result.relative_path) as master:
        assert master.mode == "RGB"
        assert master.size == (2400, 1600)


def test_build_print_master_does_not_downsize_large_source(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    source = tmp_path / "source.jpg"
    Image.new("RGB", (3000, 2000), "white").save(source)
    monkeypatch.setattr("web.print_master.get_artwork_folder", lambda _: workspace)

    result = build_print_master(
        artwork(tmp_path),
        source,
        max_long_edge=2400,
    )

    assert result.resized is False
    assert (result.master_width, result.master_height) == (3000, 2000)
    assert result.method == "Normalized without enlargement"
