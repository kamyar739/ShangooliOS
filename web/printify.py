from urllib.parse import urlparse


def is_physical_product(product: str | None) -> bool:
    normalized = (product or "").strip().lower()
    return not any(word in normalized for word in ("digital", "download", "printable"))


def validate_printify_product(listing) -> dict:
    if not is_physical_product(listing["product"]):
        return {"required": False, "ready": True, "blockers": []}

    blockers = []
    url = (listing["printify_product_url"] or "").strip()
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (
        hostname == "printify.com" or hostname.endswith(".printify.com")
    ):
        blockers.append("Printify product URL")
    if not (listing["printify_product_id"] or "").strip():
        blockers.append("Printify product ID")
    if not (listing["printify_provider"] or "").strip():
        blockers.append("Print provider")
    if not (listing["printify_sizes"] or "").strip():
        blockers.append("Available sizes")
    if not listing["printify_base_cost_cents"] or listing["printify_base_cost_cents"] <= 0:
        blockers.append("Base production cost")
    return {"required": True, "ready": not blockers, "blockers": blockers}
