from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


COLOR_NAMES = {
    "red": (196, 67, 62), "orange": (224, 125, 52), "gold": (190, 153, 59),
    "yellow": (225, 205, 74), "green": (75, 135, 87), "teal": (47, 126, 128),
    "blue": (66, 104, 164), "purple": (122, 83, 151), "pink": (205, 119, 151),
    "brown": (125, 88, 60), "beige": (211, 196, 166), "ivory": (235, 229, 207),
    "gray": (135, 135, 135), "charcoal": (55, 58, 61), "black": (25, 25, 25),
    "white": (240, 240, 240),
}


def _nearest_name(rgb: tuple[int, int, int]) -> str:
    return min(COLOR_NAMES, key=lambda name: sum((a-b) ** 2 for a, b in zip(rgb, COLOR_NAMES[name])))


def _dominant_colors(path: Path, count: int = 5) -> list[str]:
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((220, 220))
        quantized = image.quantize(colors=10, method=Image.Quantize.MEDIANCUT).convert("RGB")
        colors = quantized.getcolors(maxcolors=100000) or []
    names = []
    for _, rgb in sorted(colors, reverse=True):
        name = _nearest_name(rgb)
        if name not in names:
            names.append(name)
        if len(names) >= count:
            break
    return names


def analyze_artwork(artwork, source_path: Path | None) -> dict:
    title = artwork["public_title"] or artwork["working_title"] or artwork["artwork_code"]
    description = (artwork["description"] or "").strip()
    prompt = (artwork["prompt"] or "").strip()
    existing_theme = (artwork["theme"] or "").strip()
    colors = _dominant_colors(source_path) if source_path and source_path.exists() else []
    orientation = "unknown"
    dimensions = ""
    if source_path and source_path.exists():
        with Image.open(source_path) as image:
            width, height = image.size
        orientation = "horizontal" if width > height else "vertical" if height > width else "square"
        dimensions = f"{width} × {height}px"

    combined = f"{title} {existing_theme} {description} {prompt}".lower()
    if existing_theme:
        theme = existing_theme
    elif "flamenco" in combined or "dancer" in combined:
        theme = "Flamenco, movement, and emotional expression"
    elif any(word in combined for word in ("celebr", "joy", "gather")):
        theme = "Collective joy, movement, and celebration"
    else:
        theme = f"{title}: movement, emotion, and visual storytelling"

    if "minimal" in combined:
        style = "Minimalist"
    elif "impression" in combined:
        style = "Impressionist"
    elif any(word in combined for word in ("expression", "oil paint", "painterly", "flamenco")):
        style = "Contemporary expressionist figurative oil painting"
    else:
        style = "Modern abstract figurative"

    mood_rules = (
        ("Passionate", ("passion", "flamenco", "rapture", "fire")),
        ("Joyful", ("joy", "celebr", "festival", "gather")),
        ("Serene", ("serene", "calm", "quiet", "peace")),
        ("Dramatic", ("dramatic", "intense", "shadow", "storm")),
        ("Reflective", ("reflect", "solitary", "contempl", "surrender")),
        ("Empowering", ("power", "strength", "freedom", "triumph")),
    )
    mood = next(
        (label for label, words in mood_rules if any(word in combined for word in words)),
        "Reflective",
    )
    suggested_room = "Living room, Entryway, Creative space"
    target_customer = (
        "Flamenco enthusiasts, Dance lovers, Contemporary decor shoppers"
        if "flamenco" in combined or "dancer" in combined
        else "Art collectors, Contemporary decor shoppers, Gift buyers"
    )
    subject = (
        "a flamenco dancer and its expressive movement"
        if "flamenco" in combined or "dancer" in combined
        else f"the visual subject of {title}"
    )
    notes = (
        f"Analyzed {subject}. The {orientation} source is {dimensions or 'an unknown size'}; "
        "the creative fields below use controlled values and can be refined before listing generation."
    )
    return {
        "theme": theme,
        "style": style,
        "mood": mood,
        "primary_colors": ", ".join(colors),
        "suggested_room": suggested_room,
        "target_customer": target_customer,
        "analysis_notes": notes,
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
