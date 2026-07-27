import json
import re
from pathlib import Path

from fastapi import UploadFile

from app.database import create_artwork
from web.db import (
    create_collection,
    get_artwork,
    get_collection,
    update_artwork_details,
    update_artwork_intelligence,
    update_artwork_listing_content,
    update_collection,
    upsert_artwork_file,
)
from web.file_intake import ALLOWED_EXTENSIONS, save_uploaded_file


FAST_FLOW_IMAGE_EXTENSIONS = ALLOWED_EXTENSIONS - {".pdf"}
COLLECTION_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,9}$")


def _required_text(value, label):
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _optional_text(value):
    return str(value or "").strip()


def _comma_separated(value, label):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ", ".join(item.strip() for item in value if item.strip())
    raise ValueError(f"{label} must be text or a list of text values")


def _etsy_tags(value, label):
    tags = [tag.strip() for tag in _comma_separated(value, label).split(",") if tag.strip()]
    over_limit = [tag for tag in tags if len(tag) > 20]
    if over_limit:
        raise ValueError(
            f"{label} must use 20 characters or fewer per tag: "
            + ", ".join(over_limit)
        )
    return ", ".join(tags)


def _optional_object(value, label):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _required_metadata(value, label):
    return _required_text(value, label)


def parse_fast_flow_manifest(manifest_text, *, require_images=True):
    try:
        payload = json.loads(manifest_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Collection metadata is not valid JSON: line {error.lineno}, column {error.colno}"
        ) from error

    if not isinstance(payload, dict):
        raise ValueError("Collection metadata must be a JSON object")

    collection_payload = payload.get("collection")
    artwork_payloads = payload.get("artworks")
    if not isinstance(collection_payload, dict):
        raise ValueError("Collection metadata must include a collection object")
    if not isinstance(artwork_payloads, list) or not artwork_payloads:
        raise ValueError("Collection metadata must include at least one artwork")

    code = _required_text(collection_payload.get("code"), "Collection code").upper()
    if not COLLECTION_CODE_PATTERN.fullmatch(code):
        raise ValueError(
            "Collection code must be 1–10 letters, numbers, underscores, or hyphens"
        )
    name = _required_text(collection_payload.get("name"), "Collection name")
    description = _required_metadata(
        collection_payload.get("description"), "Collection description"
    )
    prompt = _required_metadata(
        collection_payload.get("prompt"), "Collection prompt"
    )
    status = _optional_text(collection_payload.get("status") or "active").lower()
    if status not in {"planned", "active", "complete", "paused"}:
        raise ValueError("Collection status must be planned, active, complete, or paused")

    normalized_artworks = []
    seen_images = set()
    for position, item in enumerate(artwork_payloads, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Artwork {position} must be a JSON object")
        image = Path(_optional_text(item.get("image"))).name
        if require_images:
            image = Path(
                _required_text(item.get("image"), f"Artwork {position} image")
            ).name
            if Path(image).suffix.lower() not in FAST_FLOW_IMAGE_EXTENSIONS:
                allowed = ", ".join(sorted(FAST_FLOW_IMAGE_EXTENSIONS))
                raise ValueError(
                    f"Artwork {position} image must use one of these formats: {allowed}"
                )
            image_key = image.casefold()
            if image_key in seen_images:
                raise ValueError(f"Image {image} is assigned more than once")
            seen_images.add(image_key)

        intelligence = _optional_object(
            item.get("intelligence"), f"Artwork {position} intelligence"
        )
        story_seo = _optional_object(
            item.get("story_seo"), f"Artwork {position} Story & SEO"
        )
        legacy_seo = _optional_object(
            item.get("seo"), f"Artwork {position} SEO"
        )

        normalized_artworks.append(
            {
                "image": image,
                "title": _required_text(
                    item.get("title"), f"Artwork {position} title"
                ),
                "description": _required_metadata(
                    item.get("description"), f"Artwork {position} description"
                ),
                "prompt": _required_metadata(
                    item.get("prompt"), f"Artwork {position} prompt"
                ),
                "intelligence": {
                    "theme": _required_metadata(
                        _first_present(intelligence.get("theme"), item.get("theme"))
                        , f"Artwork {position} theme"
                    ),
                    "style": _required_metadata(
                        _first_present(intelligence.get("style"), item.get("style"))
                        , f"Artwork {position} style"
                    ),
                    "mood": _required_metadata(
                        _first_present(intelligence.get("mood"), item.get("mood"))
                        , f"Artwork {position} mood"
                    ),
                    "primary_colors": _required_metadata(_comma_separated(
                        _first_present(
                            intelligence.get("primary_colors"),
                            item.get("primary_colors"),
                            item.get("colors"),
                        ),
                        f"Artwork {position} primary colors",
                    ), f"Artwork {position} primary colors"),
                    "suggested_room": _required_metadata(_comma_separated(
                        _first_present(
                            intelligence.get("suggested_rooms"),
                            intelligence.get("suggested_room"),
                            item.get("suggested_rooms"),
                            item.get("suggested_room"),
                            item.get("rooms"),
                        ),
                        f"Artwork {position} suggested rooms",
                    ), f"Artwork {position} suggested rooms"),
                    "target_customer": _required_metadata(_comma_separated(
                        _first_present(
                            intelligence.get("target_customer"),
                            item.get("target_customer"),
                            item.get("customer"),
                        ),
                        f"Artwork {position} target customer",
                    ), f"Artwork {position} target customer"),
                    "ai_model": _required_metadata(
                        _first_present(
                            intelligence.get("ai_model"), item.get("ai_model")
                        ), f"Artwork {position} AI model"
                    ),
                    "analysis_notes": _required_metadata(
                        _first_present(
                            intelligence.get("analysis_notes"),
                            item.get("analysis_notes"),
                        ), f"Artwork {position} analysis notes"
                    ),
                },
                "listing_content": {
                    "short_story": _required_metadata(
                        _first_present(
                            story_seo.get("short_story"), item.get("short_story")
                        ), f"Artwork {position} short story"
                    ),
                    "long_story": _required_metadata(
                        _first_present(
                            story_seo.get("long_story"),
                            item.get("long_story"),
                            item.get("story"),
                        ), f"Artwork {position} long story"
                    ),
                    "etsy_title": _required_metadata(
                        _first_present(
                            story_seo.get("etsy_title"),
                            item.get("etsy_title"),
                            item.get("seo_title"),
                            legacy_seo.get("title"),
                        ), f"Artwork {position} Etsy title"
                    ),
                    "etsy_description": _required_metadata(
                        _first_present(
                            story_seo.get("etsy_description"),
                            item.get("etsy_description"),
                            item.get("seo_description"),
                            legacy_seo.get("description"),
                        ), f"Artwork {position} Etsy description"
                    ),
                    "etsy_tags": _required_metadata(_etsy_tags(
                        _first_present(
                            story_seo.get("etsy_tags"),
                            item.get("etsy_tags"),
                            item.get("seo_tags"),
                            legacy_seo.get("tags"),
                        ),
                        f"Artwork {position} SEO tags",
                    ), f"Artwork {position} Etsy tags"),
                    "alt_text": _required_metadata(
                        _first_present(
                            story_seo.get("image_alt_text"),
                            story_seo.get("alt_text"),
                            item.get("image_alt_text"),
                            item.get("alt_text"),
                            legacy_seo.get("alt_text"),
                        ), f"Artwork {position} image alt text"
                    ),
                    "keywords": _required_metadata(_comma_separated(
                        _first_present(
                            story_seo.get("keywords"),
                            item.get("keywords"),
                            legacy_seo.get("keywords"),
                        ),
                        f"Artwork {position} SEO keywords",
                    ), f"Artwork {position} SEO keywords"),
                },
            }
        )

    target_count = collection_payload.get("target_artwork_count")
    if target_count is None:
        target_count = len(normalized_artworks)
    if not isinstance(target_count, int) or target_count < len(normalized_artworks):
        raise ValueError(
            "Target artwork count must be a whole number at least as large as the import"
        )

    return {
        "collection": {
            "code": code,
            "name": name,
            "description": description,
            "prompt": prompt,
            "etsy_section_name": _optional_text(
                collection_payload.get("etsy_section_name")
            ),
            "status": status,
            "target_artwork_count": target_count,
        },
        "artworks": normalized_artworks,
    }


def _uploads_by_filename(uploads):
    result = {}
    for upload in uploads:
        filename = Path(upload.filename or "").name
        if not filename:
            raise ValueError("Every uploaded image must have a filename")
        key = filename.casefold()
        if key in result:
            raise ValueError(f"Image {filename} was uploaded more than once")
        result[key] = upload
    return result


def validate_fast_flow_uploads(package, uploads):
    uploaded = _uploads_by_filename(uploads)
    expected = {item["image"].casefold() for item in package["artworks"]}
    missing = [
        item["image"]
        for item in package["artworks"]
        if item["image"].casefold() not in uploaded
    ]
    if missing:
        raise ValueError(f"Missing artwork image: {', '.join(missing)}")
    extras = [
        upload.filename
        for key, upload in uploaded.items()
        if key not in expected
    ]
    if extras:
        raise ValueError(f"Uploaded image is not in the metadata: {', '.join(extras)}")
    return uploaded


def import_fast_flow_collection(manifest_text, uploads):
    package = parse_fast_flow_manifest(manifest_text)
    uploaded = validate_fast_flow_uploads(package, uploads)
    collection = package["collection"]

    collection_code = create_collection(
        code=collection["code"],
        name=collection["name"],
        target_artwork_count=collection["target_artwork_count"],
        status=collection["status"],
        etsy_section_name=collection["etsy_section_name"] or None,
        description=collection["description"],
        prompt=collection["prompt"],
    )

    created_artworks = []
    for item in package["artworks"]:
        result = create_artwork(
            collection_code=collection_code,
            public_title=item["title"],
            theme=item["intelligence"]["theme"],
            description=item["description"],
            prompt=item["prompt"],
        )
        artwork_code = result["artwork_code"]
        artwork = get_artwork(artwork_code)
        upload = uploaded[item["image"].casefold()]
        try:
            saved = save_uploaded_file(artwork, upload, role="source")
        finally:
            upload.file.close()
        upsert_artwork_file(artwork_code=artwork_code, **saved)

        intelligence = {
            key: value
            for key, value in item["intelligence"].items()
            if value
        }
        if intelligence:
            update_artwork_intelligence(artwork_code, **intelligence)

        listing_content = {
            key: value
            for key, value in item["listing_content"].items()
            if value
        }
        if listing_content:
            update_artwork_listing_content(artwork_code, **listing_content)
        created_artworks.append(artwork_code)

    return {
        "collection_code": collection_code,
        "artwork_codes": created_artworks,
    }


def apply_fast_flow_metadata(collection_code, manifest_text):
    """Apply a complete package to an already-imported collection without touching files."""
    package = parse_fast_flow_manifest(manifest_text, require_images=False)
    collection = package["collection"]
    code = collection_code.strip().upper()
    if collection["code"] != code:
        raise ValueError("Collection package code does not match this collection")

    existing_collection, artworks, _ = get_collection(code)
    if existing_collection is None:
        raise ValueError("Collection not found")
    if len(artworks) != len(package["artworks"]):
        raise ValueError("Collection package artwork count does not match this collection")

    update_collection(
        code,
        collection["name"],
        len(artworks),
        collection["status"],
        etsy_section_name=collection["etsy_section_name"] or collection["name"],
        description=collection["description"],
        prompt=collection["prompt"],
        default_prices=tuple(
            existing_collection[f"default_price_tier_{tier}_cents"]
            for tier in range(1, 7)
        ),
    )
    for artwork, metadata in zip(artworks, package["artworks"]):
        artwork_code = artwork["artwork_code"]
        update_artwork_details(
            artwork_code,
            public_title=metadata["title"],
            description=metadata["description"],
            prompt=metadata["prompt"],
            status=artwork["status"],
        )
        update_artwork_intelligence(artwork_code, **metadata["intelligence"])
        update_artwork_listing_content(artwork_code, **metadata["listing_content"])

    return {"collection_code": code, "artwork_codes": [a["artwork_code"] for a in artworks]}
