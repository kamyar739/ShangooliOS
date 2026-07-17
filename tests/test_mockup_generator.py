from pathlib import Path

from PIL import Image

from web.mockup_generator import (
    CANVAS_SIZE,
    GENERATED_SLOTS,
    generate_listing_image,
    generate_mockups,
)


def test_generate_mockups_creates_eight_listing_images(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 800), "#cc6633").save(source)
    output = tmp_path / "mockups"

    results = generate_mockups(
        artwork={"artwork_code": "CEL-999", "public_title": "Test Celebration"},
        source_path=source,
        output_folder=output,
    )

    assert [item["slot_key"] for item in results] == list(GENERATED_SLOTS)
    assert len(results) == 8
    for item in results:
        assert item["path"].is_file()
        with Image.open(item["path"]) as generated:
            assert generated.size == CANVAS_SIZE
            assert generated.format == "JPEG"


def test_generate_one_listing_image_only_creates_requested_slot(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (800, 1200), "#336699").save(source)
    output = tmp_path / "mockups"

    result = generate_listing_image(
        slot_key="office",
        artwork={"artwork_code": "CEL-999", "public_title": "Office Test"},
        source_path=source,
        output_folder=output,
    )

    assert result["slot_key"] == "office"
    assert result["path"].is_file()
    assert len(list(output.glob("*.jpg"))) == 1


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


def test_generate_one_rejects_unknown_slot(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (800, 600), "#ffffff").save(source)

    try:
        generate_listing_image(
            slot_key="unknown",
            artwork={"artwork_code": "CEL-999"},
            source_path=source,
            output_folder=tmp_path / "mockups",
        )
    except ValueError as error:
        assert "unknown" in str(error).lower()
    else:
        raise AssertionError("Expected unknown listing-image slot to fail")
