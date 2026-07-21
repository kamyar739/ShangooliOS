from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageOps

from app.database import get_artwork_folder


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / ".local-tools/realesrgan/realesrgan-ncnn-vulkan"
MODELS = ENGINE.parent / "models"


def candidate_path(artwork) -> Path:
    return get_artwork_folder(artwork) / "01 Source Artwork" / f"{artwork['artwork_code']}_ai_upscaled_4x.png"


def upscale_candidate(artwork, source: Path) -> Path:
    if not ENGINE.is_file():
        raise ValueError("The local AI upscaler is not installed")
    ENGINE.chmod(ENGINE.stat().st_mode | 0o111)
    output = candidate_path(artwork)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        normalized = Path(temporary) / "source.png"
        with Image.open(source) as opened:
            ImageOps.exif_transpose(opened).convert("RGB").save(normalized, "PNG")
        result = subprocess.run(
            [str(ENGINE), "-i", str(normalized), "-o", str(output), "-s", "4",
             "-n", "realesrgan-x4plus-anime", "-m", str(MODELS), "-f", "png"],
            capture_output=True, text=True, timeout=600,
        )
    if result.returncode or not output.is_file():
        raise ValueError(f"AI upscaling failed: {(result.stderr or result.stdout)[-300:]}")
    return output
