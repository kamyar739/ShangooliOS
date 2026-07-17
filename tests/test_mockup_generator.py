from pathlib import Path

from PIL import Image

from web.mockup_generator import CANVAS_SIZE, generate_mockups


def test_generate_mockups_creates_three_listing_images(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 800), "#cc6633").save(source)
    output = tmp_path / "mockups"

    results = generate_mockups(
        artwork={"artwork_code": "CEL-999", "public_title": "Test Celebration"},
        source_path=source,
        output_folder=output,
    )

    assert [item["slot_key"] for item in results] == ["hero", "detail", "sizes"]
    for item in results:
        assert item["path"].is_file()
        with Image.open(item["path"]) as generated:
            assert generated.size == CANVAS_SIZE
            assert generated.format == "JPEG"


def test_generate_mockups_rejects_pdf(tmp_path: Path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"not an image")

    try:
        generate_mockups(
            artwork={"artwork_code": "CEL-999", "public_title": "Test"},
            source_path=source,
            output_folder=tmp_path / "mockups",
        )
    except ValueError as error:
        assert "require" in str(error).lower()
    else:
        raise AssertionError("Expected unsupported source file to fail")
