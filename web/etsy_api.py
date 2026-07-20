import base64
import hashlib
import json
import secrets
import time
import mimetypes
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from web.printify_api import LOCAL_ENV_PATH


ETSY_REDIRECT_URI = "http://localhost:8000/etsy/oauth/callback"
ETSY_SCOPES = ("listings_r", "listings_w", "shops_r", "shops_w")
_runtime = {
    "api_key": "", "shared_secret": "", "access_token": "",
    "refresh_token": "", "expires_at": 0, "shop_id": "", "shop_name": "",
    "state": "", "verifier": "", "remember": True, "permission_version": "",
}


class EtsyAPIError(RuntimeError):
    pass


def _env_values() -> dict[str, str]:
    if not LOCAL_ENV_PATH.is_file():
        return {}
    values = {}
    for raw_line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _save_values(values: dict[str, str]):
    existing = LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines() if LOCAL_ENV_PATH.is_file() else []
    output, seen = [], set()
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in values:
            output.append(f"{key}={json.dumps(str(values[key]))}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={json.dumps(str(value))}")
    LOCAL_ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    LOCAL_ENV_PATH.chmod(0o600)


def clear_etsy_config():
    for key in _runtime:
        _runtime[key] = True if key == "remember" else 0 if key == "expires_at" else ""
    if not LOCAL_ENV_PATH.is_file():
        return
    keys = {"ETSY_API_KEY", "ETSY_SHARED_SECRET", "ETSY_ACCESS_TOKEN", "ETSY_REFRESH_TOKEN", "ETSY_TOKEN_EXPIRES_AT", "ETSY_SHOP_ID", "ETSY_SHOP_NAME", "ETSY_PERMISSION_VERSION"}
    lines = [line for line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines() if (line.split("=", 1)[0].strip() if "=" in line else "") not in keys]
    content = "\n".join(lines).rstrip()
    LOCAL_ENV_PATH.write_text(f"{content}\n" if content else "", encoding="utf-8")
    LOCAL_ENV_PATH.chmod(0o600)


def etsy_config() -> dict:
    local = _env_values()
    return {
        "api_key": _runtime["api_key"] or local.get("ETSY_API_KEY", ""),
        "shared_secret": _runtime["shared_secret"] or local.get("ETSY_SHARED_SECRET", ""),
        "access_token": _runtime["access_token"] or local.get("ETSY_ACCESS_TOKEN", ""),
        "refresh_token": _runtime["refresh_token"] or local.get("ETSY_REFRESH_TOKEN", ""),
        "expires_at": float(_runtime["expires_at"] or local.get("ETSY_TOKEN_EXPIRES_AT", 0) or 0),
        "shop_id": _runtime["shop_id"] or local.get("ETSY_SHOP_ID", ""),
        "shop_name": _runtime["shop_name"] or local.get("ETSY_SHOP_NAME", ""),
        "permission_version": _runtime["permission_version"] or local.get("ETSY_PERMISSION_VERSION", ""),
    }


def begin_etsy_oauth(api_key: str, shared_secret: str, remember: bool = True) -> str:
    api_key, shared_secret = api_key.strip(), shared_secret.strip()
    if not api_key or not shared_secret:
        raise ValueError("Enter both the Etsy keystring and shared secret")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)
    _runtime.update(api_key=api_key, shared_secret=shared_secret, state=state, verifier=verifier, remember=remember)
    if remember:
        _save_values({"ETSY_API_KEY": api_key, "ETSY_SHARED_SECRET": shared_secret})
    return "https://www.etsy.com/oauth/connect?" + urlencode({
        "response_type": "code", "redirect_uri": ETSY_REDIRECT_URI,
        "scope": " ".join(ETSY_SCOPES), "client_id": api_key, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })


def _request(url: str, *, method="GET", headers=None, form=None, data=None, json_body=None):
    if form is not None:
        data = urlencode(form, doseq=True).encode()
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise EtsyAPIError(f"Etsy returned HTTP {error.code}: {detail[:300]}") from error
    except (URLError, TimeoutError) as error:
        raise EtsyAPIError(f"Could not reach Etsy: {error}") from error
    return json.loads(body) if body else {}


def _save_tokens(token: dict) -> dict:
    expires_at = time.time() + int(token.get("expires_in", 3600))
    values = {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token", etsy_config()["refresh_token"]),
        "expires_at": expires_at,
    }
    _runtime.update(values)
    _runtime["permission_version"] = "2"
    if _runtime["remember"] or LOCAL_ENV_PATH.is_file():
        _save_values({
            "ETSY_ACCESS_TOKEN": values["access_token"],
            "ETSY_REFRESH_TOKEN": values["refresh_token"],
            "ETSY_TOKEN_EXPIRES_AT": str(expires_at),
        })
    return values


def _authorized_config() -> dict:
    config = etsy_config()
    if not config["api_key"] or not config["shared_secret"] or not config["refresh_token"]:
        raise EtsyAPIError("Connect Etsy before syncing a listing.")
    if not config["access_token"] or config["expires_at"] <= time.time() + 60:
        token = _request(
            "https://api.etsy.com/v3/public/oauth/token",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            form={
                "grant_type": "refresh_token",
                "client_id": config["api_key"],
                "refresh_token": config["refresh_token"],
            },
        )
        _save_tokens(token)
        config = etsy_config()
    return config


def _authorized_headers(content_type: str | None = None) -> dict[str, str]:
    config = _authorized_config()
    headers = {
        "x-api-key": f"{config['api_key']}:{config['shared_secret']}",
        "Authorization": f"Bearer {config['access_token']}",
        "Accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def list_etsy_shop_listings() -> list[dict]:
    config = _authorized_config()
    results = []
    for state in ("active", "draft", "inactive"):
        response = _request(
            f"https://api.etsy.com/v3/application/shops/{config['shop_id']}/listings?"
            + urlencode({"state": state, "limit": 100, "sort_on": "updated", "sort_order": "desc", "includes": "Images"}),
            headers=_authorized_headers(),
        )
        results.extend(response.get("results", []))
    return results


def list_etsy_shop_sections() -> list[dict]:
    config = _authorized_config()
    response = _request(
        f"https://api.etsy.com/v3/application/shops/{config['shop_id']}/sections",
        headers=_authorized_headers(),
    )
    return response.get("results", [])


def create_etsy_shop_section(title: str) -> dict:
    config = _authorized_config()
    return _request(
        f"https://api.etsy.com/v3/application/shops/{config['shop_id']}/sections",
        method="POST",
        headers=_authorized_headers("application/x-www-form-urlencoded"),
        form={"title": title},
    )


def update_etsy_listing_section(listing_id: str, section_id: int) -> dict:
    config = _authorized_config()
    return _request(
        f"https://api.etsy.com/v3/application/shops/{config['shop_id']}/listings/{listing_id}",
        method="PATCH",
        headers=_authorized_headers("application/x-www-form-urlencoded"),
        form={"shop_section_id": section_id},
    )


def get_etsy_listing(listing_id: str) -> dict:
    return _request(
        f"https://api.etsy.com/v3/application/listings/{listing_id}",
        headers=_authorized_headers(),
    )


def get_etsy_listing_images(listing_id: str) -> list[dict]:
    response = _request(
        f"https://api.etsy.com/v3/application/listings/{listing_id}/images",
        headers=_authorized_headers(),
    )
    return response.get("results", [])


def get_etsy_listing_inventory(listing_id: str) -> dict:
    return _request(
        f"https://api.etsy.com/v3/application/listings/{listing_id}/inventory",
        headers=_authorized_headers(),
    )


def update_etsy_listing_inventory(listing_id: str, inventory: dict) -> dict:
    return _request(
        f"https://api.etsy.com/v3/application/listings/{listing_id}/inventory",
        method="PUT",
        headers=_authorized_headers("application/json"),
        json_body=inventory,
    )


def update_etsy_listing(listing_id: str, *, title: str, description: str, tags: list[str]):
    config = _authorized_config()
    return _request(
        f"https://api.etsy.com/v3/application/shops/{config['shop_id']}/listings/{listing_id}",
        method="PATCH",
        headers=_authorized_headers("application/x-www-form-urlencoded"),
        form={"title": title, "description": description, "tags": ",".join(tags)},
    )


def _multipart_image(path: Path, rank: int, alt_text: str) -> tuple[bytes, str]:
    boundary = f"----ShangooliOS{secrets.token_hex(16)}"
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = []
    for name, value in (("rank", str(rank)), ("overwrite", "true"), ("alt_text", alt_text[:250])):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode()
        + path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload_etsy_listing_image(listing_id: str, path: Path, rank: int, alt_text: str):
    config = _authorized_config()
    data, content_type = _multipart_image(path, rank, alt_text)
    return _request(
        f"https://api.etsy.com/v3/application/shops/{config['shop_id']}/listings/{listing_id}/images",
        method="POST",
        headers=_authorized_headers(content_type),
        data=data,
    )


def delete_etsy_listing_image(listing_id: str, image_id: int):
    config = _authorized_config()
    return _request(
        f"https://api.etsy.com/v3/application/shops/{config['shop_id']}/listings/{listing_id}/images/{image_id}",
        method="DELETE",
        headers=_authorized_headers(),
    )


def complete_etsy_oauth(code: str, state: str) -> dict:
    if not state or not secrets.compare_digest(state, _runtime["state"]):
        raise EtsyAPIError("Etsy authorization state did not match. Start the connection again.")
    token = _request("https://api.etsy.com/v3/public/oauth/token", method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}, form={
        "grant_type": "authorization_code", "client_id": _runtime["api_key"],
        "redirect_uri": ETSY_REDIRECT_URI, "code": code, "code_verifier": _runtime["verifier"],
    })
    access_token = token["access_token"]
    user_id = access_token.split(".", 1)[0]
    headers = {"x-api-key": f"{_runtime['api_key']}:{_runtime['shared_secret']}", "Authorization": f"Bearer {access_token}"}
    shop = _request(f"https://api.etsy.com/v3/application/users/{user_id}/shops", headers=headers)
    expires_at = time.time() + int(token.get("expires_in", 3600))
    values = {
        "access_token": access_token, "refresh_token": token["refresh_token"],
        "expires_at": expires_at, "shop_id": str(shop["shop_id"]),
        "shop_name": shop.get("shop_name", ""),
    }
    _runtime.update(values)
    _runtime["state"] = _runtime["verifier"] = ""
    if _runtime["remember"]:
        _save_values({
            "ETSY_API_KEY": _runtime["api_key"], "ETSY_SHARED_SECRET": _runtime["shared_secret"],
            "ETSY_ACCESS_TOKEN": access_token, "ETSY_REFRESH_TOKEN": token["refresh_token"],
            "ETSY_TOKEN_EXPIRES_AT": str(expires_at), "ETSY_SHOP_ID": values["shop_id"],
            "ETSY_SHOP_NAME": values["shop_name"],
            "ETSY_PERMISSION_VERSION": "2",
        })
    return values
