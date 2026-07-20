import base64
import json
import math
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PrintifyAPIError(RuntimeError):
    pass


_runtime_config = {"token": "", "shop_id": "", "remember": False}
LOCAL_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _local_env_values() -> dict[str, str]:
    if not LOCAL_ENV_PATH.is_file():
        return {}
    values = {}
    for raw_line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value.strip('"')
        else:
            value = value.strip("'")
        values[key.strip()] = value
    return values


def save_printify_local_config(token: str, shop_id: str):
    normalized_token = (token or "").strip()
    normalized_shop_id = (shop_id or "").strip()
    if not normalized_token or not normalized_shop_id:
        raise ValueError("Enter both the Printify API token and shop ID")

    existing = []
    if LOCAL_ENV_PATH.is_file():
        existing = LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines()
    replacements = {
        "PRINTIFY_API_TOKEN": normalized_token,
        "PRINTIFY_SHOP_ID": normalized_shop_id,
    }
    output = []
    seen = set()
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in replacements:
            output.append(f"{key}={json.dumps(replacements[key])}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in replacements.items():
        if key not in seen:
            output.append(f"{key}={json.dumps(value)}")
    LOCAL_ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    LOCAL_ENV_PATH.chmod(0o600)


def clear_printify_local_config():
    if not LOCAL_ENV_PATH.is_file():
        return
    printify_keys = {"PRINTIFY_API_TOKEN", "PRINTIFY_SHOP_ID"}
    remaining = []
    for line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key not in printify_keys:
            remaining.append(line)
    content = "\n".join(remaining).rstrip()
    LOCAL_ENV_PATH.write_text(f"{content}\n" if content else "", encoding="utf-8")
    LOCAL_ENV_PATH.chmod(0o600)


def configure_printify_runtime(token: str, shop_id: str):
    normalized_token = (token or "").strip()
    normalized_shop_id = (shop_id or "").strip()
    if not normalized_token or not normalized_shop_id:
        raise ValueError("Enter both the Printify API token and shop ID")
    _runtime_config["token"] = normalized_token
    _runtime_config["shop_id"] = normalized_shop_id


def configure_printify_token_runtime(token: str, *, remember: bool = True):
    normalized_token = (token or "").strip()
    if not normalized_token:
        raise ValueError("Enter the Printify API token")
    _runtime_config["token"] = normalized_token
    _runtime_config["shop_id"] = ""
    _runtime_config["remember"] = remember


def complete_printify_runtime(shop_id: str):
    normalized_shop_id = (shop_id or "").strip()
    if not _runtime_config["token"] or not normalized_shop_id:
        raise ValueError("Choose a Printify shop")
    _runtime_config["shop_id"] = normalized_shop_id
    if _runtime_config["remember"]:
        save_printify_local_config(_runtime_config["token"], normalized_shop_id)


def clear_printify_runtime():
    _runtime_config["token"] = ""
    _runtime_config["shop_id"] = ""
    _runtime_config["remember"] = False


def available_printify_token():
    local = _local_env_values()
    return (
        _runtime_config["token"]
        or os.environ.get("PRINTIFY_API_TOKEN", "")
        or local.get("PRINTIFY_API_TOKEN", "")
    )


def printify_configuration_source():
    if _runtime_config["token"] and _runtime_config["shop_id"]:
        return "runtime"
    if os.environ.get("PRINTIFY_API_TOKEN") and os.environ.get("PRINTIFY_SHOP_ID"):
        return "environment"
    local = _local_env_values()
    if local.get("PRINTIFY_API_TOKEN") and local.get("PRINTIFY_SHOP_ID"):
        return "local .env"
    return None


class PrintifyAPI:
    base_url = "https://api.printify.com/v1"

    def __init__(self, token: str, shop_id: str):
        self.token = token.strip()
        self.shop_id = shop_id.strip()

    @classmethod
    def from_env(cls):
        local = _local_env_values()
        token = (
            _runtime_config["token"]
            or os.environ.get("PRINTIFY_API_TOKEN", "")
            or local.get("PRINTIFY_API_TOKEN", "")
        )
        shop_id = (
            _runtime_config["shop_id"]
            or os.environ.get("PRINTIFY_SHOP_ID", "")
            or local.get("PRINTIFY_SHOP_ID", "")
        )
        return cls(token, shop_id) if token and shop_id else None

    @classmethod
    def with_available_token(cls):
        token = available_printify_token()
        return cls(token, "") if token else None

    def list_shops(self):
        data = self._request("GET", "/shops.json")
        return data if isinstance(data, list) else data.get("data", [])

    def _request(self, method: str, path: str, payload=None):
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json;charset=utf-8",
            "User-Agent": "ShangooliOS/1.0 Printify-API-Client",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code == 403:
                if "1010" in detail:
                    raise PrintifyAPIError(
                        "Printify blocked the API client's request signature (error 1010). "
                        "The token permissions are not the problem."
                    ) from error
                if path.startswith("/uploads/"):
                    raise PrintifyAPIError(
                        "Printify denied the artwork upload. Generate a new token with "
                        "Uploads: write permission."
                    ) from error
                if "/products" in path:
                    raise PrintifyAPIError(
                        "Printify denied the product operation. Generate a new token with "
                        "Products: write permission."
                    ) from error
                raise PrintifyAPIError(
                    "Printify denied access. Confirm the token includes Shops: read and "
                    "paste the complete token without spaces or quotes."
                ) from error
            if error.code == 401:
                raise PrintifyAPIError(
                    "Printify did not accept the token. Paste the complete newly generated "
                    "token without spaces or quotes."
                ) from error
            raise PrintifyAPIError(f"Printify returned HTTP {error.code}: {detail[:300]}") from error
        except (URLError, TimeoutError) as error:
            raise PrintifyAPIError(f"Could not reach Printify: {error}") from error
        return json.loads(body) if body else {}

    def list_blueprints(self):
        data = self._request("GET", "/catalog/blueprints.json")
        return data if isinstance(data, list) else data.get("data", [])

    def list_providers(self, blueprint_id: int):
        data = self._request(
            "GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json"
        )
        return data if isinstance(data, list) else data.get("data", [])

    def list_variants(self, blueprint_id: int, provider_id: int):
        data = self._request(
            "GET",
            f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json",
        )
        return data.get("variants", data if isinstance(data, list) else [])

    def upload_image(self, path: Path):
        result = self._request(
            "POST",
            "/uploads/images.json",
            {
                "file_name": path.name,
                "contents": base64.b64encode(path.read_bytes()).decode("ascii"),
            },
        )
        if not result.get("id"):
            raise PrintifyAPIError("Printify did not return an uploaded image ID")
        return result

    def create_product(self, payload: dict):
        result = self._request(
            "POST", f"/shops/{self.shop_id}/products.json", payload
        )
        if not result.get("id"):
            raise PrintifyAPIError("Printify did not return a product ID")
        return result

    def get_product(self, product_id: str):
        result = self._request(
            "GET", f"/shops/{self.shop_id}/products/{product_id}.json"
        )
        if not result.get("id"):
            raise PrintifyAPIError("Printify did not return the saved product")
        return result

    def publish_product(self, product_id: str):
        return self._request(
            "POST",
            f"/shops/{self.shop_id}/products/{product_id}/publish.json",
            {
                "title": True,
                "description": True,
                "images": True,
                "variants": True,
                "tags": True,
                "keyFeatures": True,
                "shipping_template": True,
            },
        )


def poster_blueprints(
    blueprints: list[dict], orientation: str | None = None
) -> list[dict]:
    posters = [
        item for item in blueprints if "poster" in item.get("title", "").lower()
    ]
    normalized_orientation = (orientation or "").strip().lower()
    if normalized_orientation in {"horizontal", "vertical"}:
        matching = [
            item
            for item in posters
            if normalized_orientation in item.get("title", "").lower()
        ]
        if matching:
            posters = matching
    return sorted(posters, key=lambda item: item.get("title", "").lower())


def variant_orientation(title: str) -> str | None:
    match = re.search(r"(\d+(?:\.\d+)?)\D*[x×]\D*(\d+(?:\.\d+)?)", title or "")
    if not match:
        return None
    width, height = (float(value) for value in match.groups())
    if width > height:
        return "horizontal"
    if height > width:
        return "vertical"
    return "square"


def ratio_role_for_variant(title: str) -> str | None:
    match = re.search(r"(\d+)\D*[x×]\D*(\d+)", title or "")
    if not match:
        return None
    width, height = (int(value) for value in match.groups())
    divisor = math.gcd(width, height)
    return f"ratio:{width // divisor}:{height // divisor}"


def create_printify_product(
    api: PrintifyAPI,
    *,
    listing,
    blueprint_id: int,
    provider_id: int,
    provider_name: str,
    selections: list[dict],
):
    if not selections:
        raise ValueError("Select at least one Printify variant")

    uploaded_by_path = {}
    for selection in selections:
        path = selection["path"]
        if path not in uploaded_by_path:
            uploaded_by_path[path] = api.upload_image(path)["id"]

    areas_by_image = {}
    for selection in selections:
        image_id = uploaded_by_path[selection["path"]]
        areas_by_image.setdefault(image_id, []).append(selection["variant_id"])

    payload = {
        "title": listing["title"],
        "description": listing["description"] or "",
        "blueprint_id": blueprint_id,
        "print_provider_id": provider_id,
        "variants": [
            {
                "id": selection["variant_id"],
                "price": selection["price_cents"],
                "is_enabled": True,
            }
            for selection in selections
        ],
        "print_areas": [
            {
                "variant_ids": variant_ids,
                "placeholders": [
                    {
                        "position": "front",
                        "images": [
                            {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
                        ],
                    }
                ],
            }
            for image_id, variant_ids in areas_by_image.items()
        ],
    }
    product = api.create_product(payload)
    known_costs = [
        selection["cost_cents"]
        for selection in selections
        if selection.get("cost_cents") is not None
    ]
    return {
        "product": product,
        "provider": provider_name,
        "sizes": ", ".join(selection["title"] for selection in selections),
        "base_cost_cents": min(known_costs) if known_costs else None,
        "product_url": f"https://printify.com/app/store/products/{product['id']}",
    }
