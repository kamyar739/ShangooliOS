"""Small, configuration-backed product rules for supported product families."""

from pathlib import Path


PLACEMENT_PROFILES = {
    "mug_centered_two_sided": {
        "label": "Centered on both mug sides",
        "x": 0.5,
        "y": 0.23037470279880246,
        "scale": 0.45,
        "right_hand_x": 0.21782915205597092,
        "left_hand_x": 0.7752521212436492,
    },
}


ARTWORK_TREATMENTS = {
    "original": {
        "label": "Use the approved graphic",
        "description": "The approved design file is used without alteration.",
    },
    "dark_product": {
        "label": "Light artwork for a dark product",
        "description": (
            "A separately derived light version is required; the approved "
            "original remains unchanged."
        ),
    },
}


WHITE_CERAMIC_MUG_11OZ = {
    "family": "mugs",
    "version": 1,
    "label": "White Ceramic Mug",
    "product_name": "11 oz White Mug",
    "blueprint_id": 68,
    "provider_id": 1,
    "provider_name": "SPOKE Custom Products",
    "variant_id": 33719,
    "variant_title": "11oz",
    "default_price_cents": 1900,
    "placement_profile": "mug_centered_two_sided",
    "artwork_treatment": "original",
    "marketplace_title_product": "Mug",
    "marketplace_description_detail": "",
    "print_area": {"position": "front", "width": 2700, "height": 1120},
    "required_for_readiness": ("source", "setup"),
}


BLACK_ACCENT_MUG_11OZ = {
    "family": "mugs",
    "version": 1,
    "label": "Black Accent Mug 11 oz",
    "product_name": "Black Accent Mug 11 oz",
    "blueprint_id": 595,
    "provider_id": 70,
    "provider_name": "Printed Mint",
    "variant_id": 71538,
    "variant_title": "11oz / Black",
    "default_price_cents": 2200,
    "placement_profile": "mug_centered_two_sided",
    "artwork_treatment": "original",
    "marketplace_title_product": "Black Accent Mug",
    "marketplace_description_detail": (
        "The black handle and interior give this 11 oz mug a bold, premium look."
    ),
    "print_area": {"position": "front", "width": 2550, "height": 1155},
    "required_for_readiness": ("source", "setup"),
}


PRODUCT_BLUEPRINTS = {
    # Keep the historic key so every existing product row remains valid.
    "mug_11oz": WHITE_CERAMIC_MUG_11OZ,
    "mug_11oz_black_accent": BLACK_ACCENT_MUG_11OZ,
}


# White mugs remain supported for historical records, but are retired from all
# new catalog work. Collections inherit this active default unless explicitly
# given a different product profile later.
ACTIVE_MUG_BLUEPRINT_KEYS = ("mug_11oz_black_accent",)
DEFAULT_MUG_BLUEPRINT_KEY = "mug_11oz"


def get_product_blueprint(product_key: str | None):
    key = (product_key or DEFAULT_MUG_BLUEPRINT_KEY).strip()
    try:
        return key, PRODUCT_BLUEPRINTS[key]
    except KeyError as error:
        raise ValueError("Choose a supported product") from error


def mug_blueprints(*, include_retired=True):
    return [
        {"key": key, **profile}
        for key, profile in PRODUCT_BLUEPRINTS.items()
        if profile["family"] == "mugs"
        and (include_retired or key in ACTIVE_MUG_BLUEPRINT_KEYS)
    ]


def placement_profile(profile_key: str):
    try:
        return PLACEMENT_PROFILES[profile_key]
    except KeyError as error:
        raise ValueError("The product placement profile is not configured") from error


def resolve_artwork_treatment(source: Path, treatment_key: str) -> Path:
    """Resolve a production asset without ever modifying the creative source."""
    if treatment_key == "original":
        return source
    if treatment_key == "dark_product":
        raise ValueError(
            "This dark product needs a reviewed light-artwork production asset"
        )
    raise ValueError("The product artwork treatment is not configured")


def normalized_placement_geometry(blueprint: dict, *, x: float, y: float, scale: float):
    """Project normalized placement onto a blueprint's verified print area."""
    area = blueprint["print_area"]
    return {
        "center_x": round(area["width"] * x),
        "center_y": round(area["height"] * y),
        "artwork_width": round(area["width"] * scale),
        "print_area_width": area["width"],
        "print_area_height": area["height"],
    }


def product_readiness(*, product, source_exists: bool, blueprint: dict):
    """Return product-specific readiness without borrowing another family’s rules."""
    blockers = []
    if "source" in blueprint["required_for_readiness"] and not source_exists:
        blockers.append("Approved graphic is missing")
    if "setup" in blueprint["required_for_readiness"]:
        if product is None:
            blockers.append("Product setup has not been saved")
        elif "product_title" in product.keys():
            if not str(product["product_title"] or "").strip():
                blockers.append("Product title is missing")
        elif not str(product["title"] or "").strip():
            blockers.append("Product title is missing")
    if product is not None and product["external_state"] in {
        "creating",
        "outcome_unknown",
        "update_outcome_unknown",
    }:
        blockers.append("Previous external result requires verification")
    return {"ready": not blockers, "blockers": blockers}
