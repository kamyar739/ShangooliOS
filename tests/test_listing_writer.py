from web.listing_writer import (
    collection_series_label,
    customer_etsy_description,
    generate_listing_content,
)


def test_collection_series_label_uses_stable_artwork_number_without_total():
    artwork = {
        "sequence_number": 3,
        "collection_name": "The Celebration Collection",
    }
    assert collection_series_label(artwork) == (
        "The Celebration Collection · No. 3"
    )


def test_customer_description_adds_series_label_once_and_preserves_copy():
    listing = {
        "sequence_number": 3,
        "collection_name": "The Celebration Collection",
        "description": "Original edited description.",
    }
    description = customer_etsy_description(listing)
    assert description == (
        "The Celebration Collection · No. 3\n\n"
        "Original edited description."
    )
    assert customer_etsy_description({**listing, "description": description}) == description


def test_generated_listing_keeps_seo_title_and_adds_collection_identity():
    artwork = {
        "artwork_code": "CEL-003",
        "sequence_number": 3,
        "public_title": "Gathering",
        "working_title": "",
        "theme": "Celebration",
        "collection_name": "The Celebration Collection",
    }
    intelligence = {
        "theme": "Celebration",
        "style": "Modern abstract figurative art",
        "mood": "Joyful",
        "suggested_room": "Living room",
        "target_customer": "Art lovers",
        "primary_colors": "gold, teal",
    }
    content = generate_listing_content(artwork, intelligence)
    assert content["etsy_title"].startswith("Gathering,")
    assert "The Celebration Collection · No. 3" not in content["etsy_title"]
    assert content["etsy_description"].startswith(
        "The Celebration Collection · No. 3\n\n"
    )
