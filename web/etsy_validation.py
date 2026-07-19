ETSY_TITLE_MAX_LENGTH = 140
ETSY_TAG_MAX_COUNT = 13
ETSY_TAG_MAX_LENGTH = 20


def parse_tags(value: str | None) -> list[str]:
    return [tag.strip() for tag in (value or "").split(",") if tag.strip()]


def validate_etsy_listing(listing) -> list[dict]:
    title = (listing["title"] or "").strip()
    description = (listing["description"] or "").strip()
    tags = parse_tags(listing["tags"])
    price_cents = listing["price_cents"]

    if not title:
        title_detail = "Add a title."
    elif len(title) > ETSY_TITLE_MAX_LENGTH:
        title_detail = (
            f"Title is {len(title)} characters; Etsy allows up to "
            f"{ETSY_TITLE_MAX_LENGTH}."
        )
    else:
        title_detail = None

    tag_problems = []
    if not tags:
        tag_problems.append("Add at least one tag.")
    if len(tags) > ETSY_TAG_MAX_COUNT:
        tag_problems.append(
            f"There are {len(tags)} tags; Etsy allows up to {ETSY_TAG_MAX_COUNT}."
        )
    long_tags = [tag for tag in tags if len(tag) > ETSY_TAG_MAX_LENGTH]
    if long_tags:
        tag_problems.append(
            "Shorten tags over 20 characters: " + ", ".join(long_tags) + "."
        )

    return [
        {
            "key": "title",
            "label": "Title",
            "passed": title_detail is None,
            "detail": title_detail,
        },
        {
            "key": "description",
            "label": "Description",
            "passed": bool(description),
            "detail": None if description else "Add a description.",
        },
        {
            "key": "tags",
            "label": "Tags",
            "passed": not tag_problems,
            "detail": " ".join(tag_problems) or None,
        },
        {
            "key": "price",
            "label": "Price",
            "passed": price_cents > 0,
            "detail": None if price_cents > 0 else "Set a price greater than $0.00.",
        },
    ]
