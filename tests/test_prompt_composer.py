from web.prompt_composer import compose_artwork_prompt


def test_prompt_composer_joins_collection_and_artwork_prompts():
    assert compose_artwork_prompt(
        "Joyful figurative art in teal and gold.",
        "A gathering beneath an amber sun.",
    ) == (
        "Joyful figurative art in teal and gold.\n\n"
        "A gathering beneath an amber sun."
    )


def test_prompt_composer_ignores_an_empty_prompt():
    assert compose_artwork_prompt("  Shared direction  ", "") == "Shared direction"
    assert compose_artwork_prompt("", "  Artwork direction  ") == "Artwork direction"


def test_prompt_composer_returns_empty_string_when_both_are_empty():
    assert compose_artwork_prompt("", None) == ""
