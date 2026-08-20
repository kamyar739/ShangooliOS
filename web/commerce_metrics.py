from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from web.db import get_connection
from web.etsy_api import list_etsy_shop_receipts
from web.printify_api import LOCAL_ENV_PATH


class PinterestAdsError(RuntimeError):
    pass


# Conservative fallback for the active Printed Mint 11 oz Black Accent mug.
# Saved Printify product costs take precedence as soon as they are available.
FALLBACK_MUG_COST_CENTS = 1138
PRINTIFY_FIRST_ITEM_SHIPPING_CENTS = 879
PRINTIFY_ADDITIONAL_ITEM_SHIPPING_CENTS = 309
ETSY_PERCENT_FEE = 0.095
ETSY_FIXED_FEE_PER_ORDER_CENTS = 45


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


def _save_env_values(values: dict[str, str]):
    lines = LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines() if LOCAL_ENV_PATH.is_file() else []
    output, seen = [], set()
    for line in lines:
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


def pinterest_ads_config() -> dict[str, str]:
    values = _env_values()
    return {
        "access_token": values.get("PINTEREST_ADS_ACCESS_TOKEN", ""),
        "ad_account_id": values.get("PINTEREST_AD_ACCOUNT_ID", ""),
    }


def save_pinterest_ads_config(access_token: str, ad_account_id: str):
    access_token = (access_token or "").strip()
    ad_account_id = (ad_account_id or "").strip()
    if not access_token or not ad_account_id:
        raise ValueError("Enter both the Pinterest access token and ad account ID")
    if not ad_account_id.isdigit():
        raise ValueError("Pinterest ad account ID must contain digits only")
    _save_env_values({
        "PINTEREST_ADS_ACCESS_TOKEN": access_token,
        "PINTEREST_AD_ACCOUNT_ID": ad_account_id,
    })


def clear_pinterest_ads_config():
    if not LOCAL_ENV_PATH.is_file():
        return
    keys = {"PINTEREST_ADS_ACCESS_TOKEN", "PINTEREST_AD_ACCOUNT_ID"}
    lines = [
        line for line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines()
        if (line.split("=", 1)[0].strip() if "=" in line else "") not in keys
    ]
    content = "\n".join(lines).rstrip()
    LOCAL_ENV_PATH.write_text(f"{content}\n" if content else "", encoding="utf-8")
    LOCAL_ENV_PATH.chmod(0o600)


def _money_cents(value) -> int:
    if not value:
        return 0
    if isinstance(value, dict):
        if value.get("amount") is not None:
            divisor = int(value.get("divisor") or 100)
            return round(int(value["amount"]) * 100 / divisor)
        if value.get("value") is not None:
            return round(float(value["value"]) * 100)
    return round(float(value) * 100)


def _receipt_date(receipt: dict) -> str:
    timestamp = receipt.get("created_timestamp") or receipt.get("create_timestamp") or receipt.get("paid_timestamp")
    return datetime.fromtimestamp(int(timestamp), timezone.utc).date().isoformat()


def _upsert_daily(source: str, rows: dict[str, dict]):
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO commerce_metrics_daily (
                metric_date, source, orders, items_sold, revenue_cents,
                ad_spend_cents, impressions, paid_clicks, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(metric_date, source) DO UPDATE SET
                orders = excluded.orders,
                items_sold = excluded.items_sold,
                revenue_cents = excluded.revenue_cents,
                ad_spend_cents = excluded.ad_spend_cents,
                impressions = excluded.impressions,
                paid_clicks = excluded.paid_clicks,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    day, source, row.get("orders", 0), row.get("items_sold", 0),
                    row.get("revenue_cents", 0), row.get("ad_spend_cents", 0),
                    row.get("impressions", 0), row.get("paid_clicks", 0),
                )
                for day, row in rows.items()
            ],
        )
        conn.commit()


def sync_etsy_sales(days: int = 30) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(1, days) - 1)
    receipts = list_etsy_shop_receipts(
        min_created=int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp()),
        max_created=int((datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc)).timestamp()),
    )
    rows = { (start + timedelta(days=i)).isoformat(): {} for i in range((today - start).days + 1) }
    for receipt in receipts:
        if receipt.get("was_canceled") or receipt.get("is_canceled"):
            continue
        day = _receipt_date(receipt)
        if day not in rows:
            continue
        row = rows[day]
        row["orders"] = row.get("orders", 0) + 1
        transactions = receipt.get("transactions") or []
        row["items_sold"] = row.get("items_sold", 0) + sum(int(item.get("quantity") or 0) for item in transactions)
        row["revenue_cents"] = row.get("revenue_cents", 0) + _money_cents(
            receipt.get("grandtotal") or receipt.get("total_price") or receipt.get("subtotal")
        )
    _upsert_daily("etsy", rows)
    return {"days": len(rows), "orders": sum(row.get("orders", 0) for row in rows.values())}


def _pinterest_request(url: str, token: str):
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"{}")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise PinterestAdsError(f"Pinterest returned HTTP {error.code}: {detail[:240]}") from error
    except (URLError, TimeoutError) as error:
        raise PinterestAdsError(f"Could not reach Pinterest: {error}") from error


def sync_pinterest_ads(days: int = 30) -> dict:
    config = pinterest_ads_config()
    if not config["access_token"] or not config["ad_account_id"]:
        raise PinterestAdsError("Connect Pinterest Ads before synchronizing spend")
    today = date.today()
    start = today - timedelta(days=max(1, days) - 1)
    query = urlencode({
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "granularity": "DAY",
        "columns": "SPEND_IN_DOLLAR,PAID_IMPRESSION,TOTAL_CLICKTHROUGH",
    })
    payload = _pinterest_request(
        f"https://api.pinterest.com/v5/ad_accounts/{config['ad_account_id']}/analytics?{query}",
        config["access_token"],
    )
    results = payload if isinstance(payload, list) else payload.get("items") or payload.get("results") or []
    rows = { (start + timedelta(days=i)).isoformat(): {} for i in range((today - start).days + 1) }
    for item in results:
        day = str(item.get("DATE") or item.get("date") or item.get("start_date") or "")[:10]
        if day not in rows:
            continue
        rows[day] = {
            "ad_spend_cents": round(float(item.get("SPEND_IN_DOLLAR") or 0) * 100),
            "impressions": int(float(item.get("PAID_IMPRESSION") or 0)),
            "paid_clicks": int(float(item.get("TOTAL_CLICKTHROUGH") or 0)),
        }
    _upsert_daily("pinterest", rows)
    return {"days": len(rows), "spend_cents": sum(row.get("ad_spend_cents", 0) for row in rows.values())}


def commerce_metrics_summary(days: int = 30) -> dict:
    today = date.today()
    start = today - timedelta(days=max(1, days) - 1)
    with get_connection() as conn:
        cost_row = conn.execute(
            """
            SELECT ROUND(AVG(printify_base_cost_cents)) AS average_cost_cents
            FROM standalone_design_products
            WHERE product_type = 'mug_11oz_black_accent'
              AND printify_base_cost_cents IS NOT NULL
              AND printify_base_cost_cents > 0
            """
        ).fetchone()
        records = conn.execute(
            """
            SELECT metric_date,
                   SUM(orders) AS orders,
                   SUM(items_sold) AS items_sold,
                   SUM(revenue_cents) AS revenue_cents,
                   SUM(ad_spend_cents) AS ad_spend_cents,
                   SUM(impressions) AS impressions,
                   SUM(paid_clicks) AS paid_clicks,
                   MAX(updated_at) AS updated_at
            FROM commerce_metrics_daily
            WHERE metric_date >= ?
            GROUP BY metric_date
            ORDER BY metric_date
            """,
            (start.isoformat(),),
        ).fetchall()
    estimated_unit_cost_cents = int(
        (cost_row["average_cost_cents"] if cost_row else 0)
        or FALLBACK_MUG_COST_CENTS
    )
    by_date = {row["metric_date"]: dict(row) for row in records}
    daily = []
    for offset in range((today - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        row = {"metric_date": day, "orders": 0, "items_sold": 0, "revenue_cents": 0, "ad_spend_cents": 0, "impressions": 0, "paid_clicks": 0}
        row.update(by_date.get(day, {}))
        items_sold = int(row.get("items_sold") or 0)
        orders = int(row.get("orders") or 0)
        revenue_cents = int(row.get("revenue_cents") or 0)
        production_cents = items_sold * estimated_unit_cost_cents
        shipping_cents = (
            orders * PRINTIFY_FIRST_ITEM_SHIPPING_CENTS
            + max(0, items_sold - orders) * PRINTIFY_ADDITIONAL_ITEM_SHIPPING_CENTS
        )
        etsy_fee_cents = round(revenue_cents * ETSY_PERCENT_FEE) + (
            orders * ETSY_FIXED_FEE_PER_ORDER_CENTS
        )
        row["estimated_profit_cents"] = (
            revenue_cents
            - production_cents
            - shipping_cents
            - etsy_fee_cents
            - int(row.get("ad_spend_cents") or 0)
        )
        daily.append(row)

    def totals_for(period: int):
        rows = daily[-period:]
        totals = {key: sum(int(row.get(key) or 0) for row in rows) for key in ("orders", "items_sold", "revenue_cents", "estimated_profit_cents", "ad_spend_cents", "impressions", "paid_clicks")}
        totals["roas"] = round(totals["revenue_cents"] / totals["ad_spend_cents"], 2) if totals["ad_spend_cents"] else 0
        totals["cost_per_order_cents"] = round(totals["ad_spend_cents"] / totals["orders"]) if totals["orders"] else 0
        totals["estimated_profit_per_order_cents"] = round(
            totals["estimated_profit_cents"] / totals["orders"]
        ) if totals["orders"] else 0
        return totals

    return {
        "totals": {"24h": totals_for(1), "7d": totals_for(7), "30d": totals_for(30)},
        "daily": daily,
        "connections": {
            "etsy_sales": bool(_env_values().get("ETSY_REFRESH_TOKEN")),
            "pinterest_ads": bool(pinterest_ads_config()["access_token"] and pinterest_ads_config()["ad_account_id"]),
        },
        "profit_estimate": {
            "unit_cost_cents": estimated_unit_cost_cents,
            "first_item_shipping_cents": PRINTIFY_FIRST_ITEM_SHIPPING_CENTS,
            "additional_item_shipping_cents": PRINTIFY_ADDITIONAL_ITEM_SHIPPING_CENTS,
            "etsy_percent_fee": ETSY_PERCENT_FEE,
            "etsy_fixed_fee_per_order_cents": ETSY_FIXED_FEE_PER_ORDER_CENTS,
        },
        "updated_at": max((row.get("updated_at") or "" for row in daily), default=""),
    }
