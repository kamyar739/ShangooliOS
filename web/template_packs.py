"""Listing-image template pack definitions.

The first version keeps templates deterministic and local.  Each pack changes
palette, frame finish, and presentation tone without requiring external assets.
"""

from __future__ import annotations


TEMPLATE_PACKS = {
    "modern_minimal": {
        "label": "Modern Minimal",
        "description": "Bright neutral rooms, dark frames, and restrained branding.",
        "accent": "#8b6f55",
        "wall": "#ebe7df",
        "floor": "#b58d6e",
        "frame": "#2d2b29",
        "mat": "#faf8f3",
        "text": "#282522",
    },
    "warm_contemporary": {
        "label": "Warm Contemporary",
        "description": "Warmer walls, natural wood frames, and softer earth tones.",
        "accent": "#b16f52",
        "wall": "#e8d8c8",
        "floor": "#9f7255",
        "frame": "#8a6042",
        "mat": "#fff8ee",
        "text": "#342822",
    },
}

DEFAULT_TEMPLATE_PACK = "modern_minimal"


def get_template_pack(template_key: str | None) -> dict:
    """Return a validated template profile."""
    key = (template_key or DEFAULT_TEMPLATE_PACK).strip().lower()
    if key not in TEMPLATE_PACKS:
        raise ValueError(f"Unknown listing-image template pack: {template_key}")
    return {"key": key, **TEMPLATE_PACKS[key]}


def template_pack_options() -> list[dict]:
    return [{"key": key, **value} for key, value in TEMPLATE_PACKS.items()]
