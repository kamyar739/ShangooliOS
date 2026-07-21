from __future__ import annotations


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def compose_artwork_prompt(intelligence) -> dict:
    collection_direction = _clean(intelligence["collection_prompt_snapshot"])
    piece_direction = _clean(intelligence["generation_prompt"])
    collection_exclusions = _clean(
        intelligence["collection_negative_prompt_snapshot"]
    )
    piece_exclusions = _clean(intelligence["negative_prompt"])

    positive_parts = [part for part in (collection_direction, piece_direction) if part]
    negative_parts = []
    seen = set()
    for part in (collection_exclusions, piece_exclusions):
        key = part.casefold()
        if part and key not in seen:
            negative_parts.append(part)
            seen.add(key)

    return {
        "positive": "\n\n".join(positive_parts),
        "negative": ", ".join(negative_parts),
        "complete": bool(collection_direction and piece_direction),
    }
