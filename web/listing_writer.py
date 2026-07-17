from __future__ import annotations

import re
from datetime import datetime, timezone


def _clean(value) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _csv(value) -> list[str]:
    return [_clean(item) for item in (value or "").split(",") if _clean(item)]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _etsy_tags(title: str, theme: str, style: str, mood: str, colors: list[str]) -> list[str]:
    candidates = [
        "modern wall art",
        "abstract wall art",
        "figurative art",
        "colorful wall art",
        "horizontal wall art",
        f"{theme} art" if theme else "joyful wall decor",
        f"{mood.split(',')[0]} art" if mood else "uplifting artwork",
        "living room art",
        "contemporary decor",
        "statement wall art",
        "art print",
        "home decor gift",
        colors[0] + " wall art" if colors else "vibrant wall art",
        style,
        title,
    ]
    tags = []
    for candidate in _unique([_clean(x).lower() for x in candidates]):
        if 1 <= len(candidate) <= 20:
            tags.append(candidate)
        if len(tags) == 13:
            break
    return tags


def generate_listing_content(artwork, intelligence) -> dict:
    title = _clean(artwork["public_title"] or artwork["working_title"] or artwork["artwork_code"])
    theme = _clean(intelligence["theme"] or artwork["theme"])
    style = _clean(intelligence["style"]) or "modern abstract figurative art"
    mood = _clean(intelligence["mood"]) or "expressive, uplifting, and contemporary"
    rooms = _clean(intelligence["suggested_room"]) or "living room, dining room, entryway, or creative space"
    customer = _clean(intelligence["target_customer"]) or "art lovers and modern home decor shoppers"
    colors = _csv(intelligence["primary_colors"])
    color_phrase = ", ".join(colors[:4]) if colors else "a vibrant contemporary palette"
    theme_phrase = theme or "celebration and human connection"

    short_story = (
        f'“{title}” captures {theme_phrase.lower()} through movement, color, and expressive form. '
        f"Its {mood.lower()} energy is designed to bring warmth and personality into a room."
    )
    long_story = (
        f'“{title}” is a {style.lower()} piece inspired by {theme_phrase.lower()}. '
        f"Flowing shapes and a palette of {color_phrase} create a sense of motion and shared energy. "
        f"The work feels {mood.lower()}, making it a natural focal point for a {rooms.lower()}. "
        f"It was created for {customer.lower()} who want artwork that feels distinctive, welcoming, and full of life."
    )

    seo_title_parts = [title, "Colorful Abstract Wall Art", "Modern Figurative Print", "Joyful Home Decor"]
    seo_title = ", ".join(seo_title_parts)
    if len(seo_title) > 140:
        seo_title = seo_title[:137].rstrip(" ,-") + "..."

    description = (
        f"{long_story}\n\n"
        "ABOUT THIS ARTWORK\n"
        f"• Title: {title}\n"
        f"• Style: {style}\n"
        f"• Mood: {mood}\n"
        f"• Colors: {color_phrase}\n"
        f"• Suggested spaces: {rooms}\n\n"
        "Printed and shipped by a professional production partner. "
        "Colors may vary slightly between screens and the finished print. "
        "Frame and decorative objects shown in mockups are not included unless the listing states otherwise."
    )

    tags = _etsy_tags(title, theme, style, mood, colors)
    alt_text = (
        f"{title}, {style.lower()} featuring {color_phrase}, with a {mood.lower()} mood, "
        f"shown as wall art for {rooms.lower()}."
    )[:500]
    keywords = _unique([
        title, theme, style, mood, *colors, "modern wall art", "abstract figurative print",
        "colorful home decor", "living room artwork", "statement art",
    ])

    return {
        "short_story": short_story,
        "long_story": long_story,
        "etsy_title": seo_title,
        "etsy_description": description,
        "etsy_tags": ", ".join(tags),
        "alt_text": alt_text,
        "keywords": ", ".join(keywords),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
