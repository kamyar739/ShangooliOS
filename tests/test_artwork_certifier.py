from pathlib import Path

from PIL import Image

from web.artwork_certifier import certify_artwork, detect_orientation


def test_detect_orientation():
    assert detect_orientation(6000, 4000) == "horizontal"
    assert detect_orientation(4000, 6000) == "vertical"
    assert detect_orientation(4000, 3999) == "square"


def test_horizontal_certification_uses_horizontal_ratios(tmp_path: Path):
    path = tmp_path / "horizontal.png"
    Image.new("RGB", (7200, 4800), "white").save(path)
    result = certify_artwork(path)
    assert result.orientation == "horizontal"
    assert result.required_ratios == ("3:2", "4:3", "5:4", "14:11")
    assert result.largest_recommended_print == "48×32"


def test_vertical_certification_reverses_ratios_and_sizes(tmp_path: Path):
    path = tmp_path / "vertical.png"
    Image.new("RGB", (4800, 7200), "white").save(path)
    result = certify_artwork(path)
    assert result.orientation == "vertical"
    assert result.required_ratios == ("2:3", "3:4", "4:5", "11:14")
    assert result.print_capability[0]["size"] == "8×12"
