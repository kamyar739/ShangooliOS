from pathlib import Path

from PIL import Image, ImageChops

from web.mockup_generator import generate_listing_image
from web.template_packs import get_template_pack, template_pack_options


def test_template_pack_options_include_two_distinct_packs():
    options = template_pack_options()
    assert [item["key"] for item in options] == ["modern_minimal", "warm_contemporary"]
    assert options[0]["label"] != options[1]["label"]


def test_unknown_template_pack_is_rejected():
    try:
        get_template_pack("not-a-pack")
    except ValueError as error:
        assert "unknown" in str(error).lower()
    else:
        raise AssertionError("Expected an unknown pack to fail")


def test_room_template_packs_create_visibly_different_images(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 800), "#4d78a8").save(source)
    output = tmp_path / "mockups"
    artwork = {"artwork_code": "CEL-999", "public_title": "Template Test"}

    minimal = generate_listing_image(
        slot_key="room",
        artwork=artwork,
        source_path=source,
        output_folder=output,
        template_key="modern_minimal",
    )
    warm = generate_listing_image(
        slot_key="room",
        artwork=artwork,
        source_path=source,
        output_folder=output,
        template_key="warm_contemporary",
    )

    assert minimal["path"] != warm["path"]
    with Image.open(minimal["path"]) as first, Image.open(warm["path"]) as second:
        difference = ImageChops.difference(first.convert("RGB"), second.convert("RGB"))
        assert difference.getbbox() is not None
