from web.prompt_composer import compose_artwork_prompt


def test_prompt_composer_combines_collection_and_piece_directions():
    result = compose_artwork_prompt({
        "collection_prompt_snapshot": "Joyful figurative art in teal and gold.",
        "generation_prompt": "A gathering beneath an amber sun.",
        "collection_negative_prompt_snapshot": "No text, no logos.",
        "negative_prompt": "Avoid cropped hands.",
    })
    assert result["positive"] == (
        "Joyful figurative art in teal and gold.\n\n"
        "A gathering beneath an amber sun."
    )
    assert result["negative"] == "No text, no logos., Avoid cropped hands."
    assert result["complete"] is True


def test_prompt_composer_deduplicates_matching_exclusions():
    result = compose_artwork_prompt({
        "collection_prompt_snapshot": "Collection direction",
        "generation_prompt": "Piece direction",
        "collection_negative_prompt_snapshot": "No text",
        "negative_prompt": "no text",
    })
    assert result["negative"] == "No text"
