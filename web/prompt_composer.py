def compose_artwork_prompt(collection_prompt, artwork_prompt) -> str:
    """Return the collection prompt followed by the artwork prompt."""
    parts = [
        str(value or "").strip()
        for value in (collection_prompt, artwork_prompt)
        if str(value or "").strip()
    ]
    return "\n\n".join(parts)
