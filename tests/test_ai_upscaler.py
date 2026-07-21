import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from web.ai_upscaler import upscale_candidate


def test_ai_upscale_uses_local_four_x_illustration_model():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.tif"
        Image.new("RGB", (20, 10), "orange").save(source)
        artwork = {"artwork_code": "TST-001"}
        with (
            patch("web.ai_upscaler.ENGINE", root / "engine"),
            patch("web.ai_upscaler.MODELS", root / "models"),
            patch("web.ai_upscaler.candidate_path", return_value=root / "candidate.png"),
            patch("web.ai_upscaler.subprocess.run") as run,
        ):
            (root / "engine").touch()
            (root / "candidate.png").touch()
            run.return_value.returncode = 0
            result = upscale_candidate(artwork, source)
        command = run.call_args.args[0]
        assert result == root / "candidate.png"
        assert command[command.index("-s") + 1] == "4"
        assert command[command.index("-n") + 1] == "realesrgan-x4plus-anime"
