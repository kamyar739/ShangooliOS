from pathlib import Path

from PIL import Image

from web.ratio_generator import generate_ratio_output


def artwork():
    return {
        "artwork_code": "CEL-999",
        "collection_code": "CEL",
        "public_title": "Test",
        "working_title": "Test",
    }


def test_generate_ratio_output_creates_expected_ratio(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    source = tmp_path / "master.png"
    Image.new("RGB", (1800, 1200), "white").save(source)

    monkeypatch.setattr(
        "web.ratio_generator.get_artwork_folder",
        lambda _: workspace,
    )

    result = generate_ratio_output(
        artwork(),
        source,
        ratio="4:3",
        mode="crop",
        overwrite=False,
    )

    assert result["status"] == "created"
    assert result["ratio"] == "4:3"

    output_path = workspace / result["relative_path"]
    assert output_path.is_file()

    with Image.open(output_path) as output:
        assert abs((output.width / output.height) - (4 / 3)) < 0.001

def test_generate_ratio_output_preserves_existing_file(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    source = tmp_path / "master.png"
    Image.new("RGB", (1800, 1200), "white").save(source)

    monkeypatch.setattr(
        "web.ratio_generator.get_artwork_folder",
        lambda _: workspace,
    )

    first = generate_ratio_output(
        artwork(),
        source,
        ratio="3:2",
        mode="crop",
        overwrite=False,
    )
    second = generate_ratio_output(
        artwork(),
        source,
        ratio="3:2",
        mode="crop",
        overwrite=False,
    )

    assert first["status"] == "created"
    assert second["status"] == "skipped"
    assert second["relative_path"] == first["relative_path"]
