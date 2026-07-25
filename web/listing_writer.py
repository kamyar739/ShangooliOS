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


def _row_value(row, key: str) -> str:
    keys = row.keys() if hasattr(row, "keys") else ()
    return row[key] if key in keys else ""


def _subject_from_prompt(prompt: str, theme: str) -> str:
    match = re.search(
        r"\b(?:a|an)\s+(.+?)(?:\s+centered\b|\s+in\s+(?:a|an|the)\b|"
        r"\s+with\b|,|\.)",
        prompt,
        flags=re.IGNORECASE,
    )
    subject = _clean(match.group(1) if match else theme)
    return re.sub(r"^(?:single|solitary)\s+", "", subject, flags=re.IGNORECASE)


def _article(value: str) -> str:
    return "an" if value[:1].lower() in "aeiou" else "a"


def collection_series_label(artwork) -> str:
    keys = artwork.keys() if hasattr(artwork, "keys") else ()
    sequence = artwork["sequence_number"] if "sequence_number" in keys else None
    collection = _clean(artwork["collection_name"] if "collection_name" in keys else "")
    if not sequence or not collection:
        return ""
    return f"{collection} · No. {int(sequence)}"


def customer_etsy_description(listing) -> str:
    keys = listing.keys() if hasattr(listing, "keys") else ()
    description = (listing["description"] if "description" in keys else "") or ""
    label = collection_series_label(listing)
    if not label or label.casefold() in description.casefold():
        return description
    return f"{label}\n\n{description}".strip()


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
    artwork_description = _clean(_row_value(artwork, "story"))
    artwork_prompt = _clean(_row_value(artwork, "prompt"))
    theme = _clean(intelligence["theme"] or artwork["theme"])
    style = _clean(intelligence["style"]) or (
        "figurative expressionist fine art"
        if artwork_description or artwork_prompt
        else "modern abstract figurative art"
    )
    mood = _clean(intelligence["mood"]) or (
        "dramatic, intimate, and expressive"
        if artwork_description or artwork_prompt
        else "expressive, uplifting, and contemporary"
    )
    rooms = _clean(intelligence["suggested_room"]) or "living room, dining room, entryway, or creative space"
    customer = _clean(intelligence["target_customer"]) or "art lovers and modern home decor shoppers"
    colors = _csv(intelligence["primary_colors"])
    combined_artwork_text = f"{artwork_description} {artwork_prompt}".lower()
    if not colors:
        colors = [
            color for color in (
                "crimson red", "black", "gold", "teal", "orange", "blue", "green"
            )
            if color in combined_artwork_text.replace("-", " ")
        ]
    color_phrase = ", ".join(colors[:4]) if colors else "a restrained contemporary palette"
    theme_phrase = theme or "celebration and human connection"
    series_label = collection_series_label(artwork)
    subject = _subject_from_prompt(artwork_prompt, theme)

    if artwork_description or artwork_prompt:
        short_story = artwork_description or artwork_prompt
        subject_intro = (
            f" centered on {_article(subject)} {subject.lower()}"
            if subject else ""
        )
        details = artwork_description
        if artwork_prompt and artwork_prompt.casefold() not in artwork_description.casefold():
            details = f"{details} {artwork_prompt}".strip()
        long_story = (
            f'“{title}” is an expressive figurative artwork{subject_intro}. '
            f"{details}"
        ).strip()
    else:
        short_story = (
            f'“{title}” captures {theme_phrase.lower()} through movement, color, and expressive form. '
            f"Its {mood.lower()} energy is designed to bring warmth and personality into a room."
        )
        long_story = (
            f'“{title}” is a {style.lower()} piece inspired by {theme_phrase.lower()}. '
            f"Flowing shapes and a palette of {color_phrase} create a sense of motion and shared energy. "
            f"The work feels {mood.lower()}, making it a natural focal point for a {rooms.lower()}. "
            f"It was created for {customer.lower()} who want artwork that feels distinctive and personal."
        )

    subject_label = subject.title() if subject else "Figurative"
    color_label = colors[0].title() if colors else "Contemporary"
    seo_title_parts = [
        title,
        f"{subject_label} Wall Art",
        "Figurative Art Print",
        f"Dramatic {color_label} Decor",
    ]
    seo_title = ", ".join(seo_title_parts)
    if len(seo_title) > 140:
        seo_title = seo_title[:137].rstrip(" ,-") + "..."

    description = (
        f"{series_label + chr(10) + chr(10) if series_label else ''}{long_story}\n\n"
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

    subject_tags = [
        f"{subject} wall art" if subject else "",
        subject,
        f"{colors[0]} wall art" if colors else "",
        "dancer art print" if "dancer" in subject.lower() else "",
        "vertical wall art" if "vertical" in combined_artwork_text else "",
        "dramatic wall decor", "figurative art", "expressive art",
        "fine art poster", "modern wall art", "statement wall art",
        "gift for art lover", title,
    ]
    tags = [
        item.lower() for item in _unique([_clean(value) for value in subject_tags])
        if 1 <= len(item) <= 20
    ][:13]
    if not tags:
        tags = _etsy_tags(title, theme, style, mood, colors)
    alt_text = f"{title}. {artwork_description or artwork_prompt}"[:500]
    keywords = _unique([
        title, subject, theme, style, mood, *colors, artwork_description,
        "modern wall art", "figurative art print", "statement art",
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
