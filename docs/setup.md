# Development Environment Setup

Use `/opt/homebrew/bin/python3.13`.

Do not use `/usr/bin/python3` or `/usr/local/bin/python3.13`.

## Verify
```bash
python -c "import sys, platform; print(sys.version); print(platform.machine())"
```
Expected: Python 3.13.x and `arm64`.

## Troubleshooting
- Port in use:
```bash
kill -9 $(lsof -ti:8000)
```
- Rosetta/Pillow `_imaging` error: recreate `.venv` with `/opt/homebrew/bin/python3.13`.
