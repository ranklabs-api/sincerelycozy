#!/usr/bin/env python3
"""Refresh Sincerely Cozy product Offer JSON-LD from live Amazon Buy Box prices.

Read-only Selling Partner API (getItemOffers) for the six swaddle ASINs.
Writes data/amazon-prices.json and patches swaddles/{slug}.html.

Credentials are read at runtime, never logged or written to the repo:

  AMAZON_SPAPI_CLIENT_SECRET     required, from the environment
  AMAZON_SPAPI_REFRESH_TOKEN     required, from the environment
  AMAZON_SPAPI_CLIENT_ID         from the environment, unless a file is set
  AMAZON_SPAPI_CLIENT_ID_FILE    optional path; a one-line id or
  AMAZON_SPAPI_ENV_FILE          KEY=value file. The file overrides the
                                 env client id (the env value may be a
                                 pasted text block).

Does not load ~/.hermes/workspace/amazon/.env or AMAZON_LWA_* names.
Does not call any listing-write, feed, or catalog-write API.

Failure mode: if a refresh cannot produce a fresh Buy Box price, the
Offer and the visible price are removed for that product. A stale price
is never kept. No review or aggregateRating markup is added.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MARKETPLACE = "ATVPDKIKX0DER"
LWA_URL = "https://api.amazon.com/auth/o2/token"
SP_API_BASE = "https://sellingpartnerapi-na.amazon.com"
PRICE_VALID_HOURS = 48
UA = "SincerelyCozyPriceRefresh/1.0 (+https://sincerelycozy.com/)"

# ASINs are the ones on the live /swaddles/{slug} Amazon buttons.
PRODUCTS = (
    {"slug": "rose-petal", "asin": "B08N2T6RCQ"},
    {"slug": "baby-blue", "asin": "B08N1L9C2B"},
    {"slug": "cozy-teddy-bear", "asin": "B08N2P5KR8"},
    {"slug": "dreamy-clouds", "asin": "B08N2HPPVY"},
    {"slug": "little-butterfly", "asin": "B08PQ72WFD"},
    {"slug": "pickaboo-bear", "asin": "B08N1LWVYJ"},
)

PRICE_START = "<!-- amazon-price:start -->"
PRICE_END = "<!-- amazon-price:end -->"
ALLOWED_COMMIT_PATHS = frozenset(
    ["data/amazon-prices.json"]
    + [f"swaddles/{meta['slug']}.html" for meta in PRODUCTS]
)
ALERT_EXIT_2 = "ALERT:SHEIK:price-refresh:exit=2 fetch failed; existing prices still within priceValidUntil; no commit"
ALERT_PUSH_FAILED = "ALERT:SHEIK:price-refresh:push-failed"
PRICE_JSON = "data/amazon-prices.json"
# Porcelain "XY": only an unstaged modification (" M") is acceptable on allowlisted paths.
ALLOWED_PORCELAIN = " M"
# Transport failures that must enter the keep/strip path, not an uncaught exit 1.
# HTTPError is a URLError subclass; callers must handle HTTPError first.
# HTTPException covers IncompleteRead and BadStatusLine and is not a parent of
# urllib.error.HTTPError.
TRANSPORT_EXCEPTIONS = (
    urllib.error.URLError,
    OSError,
    ssl.SSLError,
    socket.timeout,
    http.client.HTTPException,
)
# Truncated or non-JSON LWA/SP-API bodies. Caught only around body parse, not
# as a blanket in main(), so an unrelated ValueError is not treated as keep/strip.
JSON_BODY_EXCEPTIONS = (json.JSONDecodeError, ValueError)
SCRIPT_RE = re.compile(
    r'(<script type="application/ld\+json">\s*)(\{.*?\})(\s*</script>)',
    re.S,
)
FORBIDDEN_SCHEMA_KEYS = ("review", "aggregateRating")


def log(msg: str) -> None:
    sys.stderr.write(msg.rstrip() + "\n")


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _first_setting_line(raw: str) -> str | None:
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    return None


def load_client_id() -> str:
    path = os.environ.get("AMAZON_SPAPI_CLIENT_ID_FILE") or os.environ.get(
        "AMAZON_SPAPI_ENV_FILE"
    )
    file_val = None
    if path:
        raw = Path(path).read_text()
        line = _first_setting_line(raw)
        if not line:
            raise SystemExit(f"ERROR: {path} has no client id line")
        if line.startswith("AMAZON_SPAPI_CLIENT_ID="):
            file_val = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif "=" in line and line.split("=", 1)[0].endswith("CLIENT_ID"):
            file_val = line.split("=", 1)[1].strip().strip('"').strip("'")
        else:
            file_val = line
        if not file_val:
            raise SystemExit(f"ERROR: {path} client id is empty")
        log(
            f"client_id source=file sha256_8={fingerprint(file_val)} chars={len(file_val)}"
        )
        return file_val
    env_val = (os.environ.get("AMAZON_SPAPI_CLIENT_ID") or "").strip()
    if not env_val:
        raise SystemExit(
            "ERROR: AMAZON_SPAPI_CLIENT_ID is not set (set the env var or AMAZON_SPAPI_CLIENT_ID_FILE)"
        )
    log(f"client_id source=env sha256_8={fingerprint(env_val)} chars={len(env_val)}")
    return env_val


def load_secret(name: str) -> str:
    val = os.environ.get(name) or ""
    if not val:
        raise SystemExit(f"ERROR: {name} is not set")
    log(f"{name} source=env sha256_8={fingerprint(val)} chars={len(val)}")
    return val


def lwa_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode()
    req = urllib.request.Request(
        LWA_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
            http = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        err = None
        try:
            err = json.loads(body).get("error")
        except Exception:
            err = None
        log(f"LWA HTTP {e.code} error={err or 'unknown'}")
        raise SystemExit(f"ERROR: LWA token exchange failed HTTP {e.code}")
    except TRANSPORT_EXCEPTIONS as e:
        log(f"LWA transport error type={type(e).__name__}")
        raise SystemExit(f"ERROR: LWA token exchange failed: {type(e).__name__}")
    except JSON_BODY_EXCEPTIONS as e:
        log(f"LWA response JSON error type={type(e).__name__}")
        raise SystemExit(f"ERROR: LWA token exchange failed: {type(e).__name__}")
    if "error" in payload:
        log(f"LWA HTTP {http} error={payload.get('error')}")
        raise SystemExit(f"ERROR: LWA token exchange failed: {payload.get('error')}")
    token = payload.get("access_token")
    if not token:
        raise SystemExit("ERROR: LWA response had no access_token")
    log(f"LWA HTTP {http} access_token_chars={len(token)}")
    return token


def _get_item_offers_once(access_token: str, asin: str) -> tuple[int, dict | None, str | None]:
    qs = urllib.parse.urlencode(
        {"MarketplaceId": MARKETPLACE, "ItemCondition": "New"}
    )
    url = f"{SP_API_BASE}/products/pricing/v0/items/{urllib.parse.quote(asin)}/offers?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "x-amz-access-token": access_token,
            "Accept": "application/json",
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        err = None
        retry_after = e.headers.get("Retry-After") if e.headers else None
        try:
            parsed = json.loads(body)
            errors = parsed.get("errors") or []
            if errors:
                err = errors[0].get("code") or errors[0].get("message")
        except Exception:
            err = None
        return e.code, {"_retry_after": retry_after}, err or f"HTTP {e.code}"
    except TRANSPORT_EXCEPTIONS as e:
        return 0, None, type(e).__name__
    except JSON_BODY_EXCEPTIONS as e:
        return 0, None, type(e).__name__
    except Exception as e:
        return 0, None, type(e).__name__


def get_item_offers(access_token: str, asin: str) -> tuple[int, dict | None, str | None]:
    # Product Pricing burst/rate limits are tight; back off on 429 instead of
    # treating QuotaExceeded as a missing Buy Box.
    delay = 10
    last_http, last_body, last_err = 0, None, None
    for attempt in range(1, 6):
        http, body, err = _get_item_offers_once(access_token, asin)
        last_http, last_body, last_err = http, body, err
        if http != 429:
            if isinstance(body, dict):
                body.pop("_retry_after", None)
            return http, body, err
        retry_after = None
        if isinstance(body, dict):
            retry_after = body.get("_retry_after")
        try:
            wait = max(delay, int(retry_after)) if retry_after else delay
        except (TypeError, ValueError):
            wait = delay
        log(f"getItemOffers ASIN={asin} HTTP 429 QuotaExceeded attempt {attempt}/5; sleeping {wait}s")
        time.sleep(wait)
        delay = min(delay * 2, 60)
    if isinstance(last_body, dict):
        last_body.pop("_retry_after", None)
        if last_body == {}:
            last_body = None
    return last_http, last_body if last_http == 200 else None, last_err


def _money(block: dict | None, key: str) -> tuple[str, str] | None:
    if not block or key not in block:
        return None
    node = block[key] or {}
    amount = node.get("Amount")
    currency = node.get("CurrencyCode")
    if amount is None or not currency:
        return None
    try:
        price = f"{float(amount):.2f}"
    except (TypeError, ValueError):
        return None
    return price, str(currency)


def _offer_subcondition(offer: dict) -> str:
    return str(offer.get("SubCondition") or offer.get("subCondition") or "").lower()


def _offer_availability_type(offer: dict) -> str:
    shipping = offer.get("ShippingTime") or offer.get("shippingTime") or {}
    raw = shipping.get("availabilityType") or shipping.get("AvailabilityType") or ""
    return str(raw).upper().replace("-", "_")


def _offer_is_backorder(offer: dict) -> bool:
    blob = json.dumps(offer).lower()
    return "backorder" in blob or "back-order" in blob or "back_order" in blob


def _availability(payload: dict) -> str:
    """Map getItemOffers offer rows to schema.org availability.

    InStock: a New-condition offer that is actually in stock. Signals:
      ShippingTime.availabilityType == NOW, or a Buy Box winner / FBA offer
      with no future/backorder shipping type.
    PreOrder: New-condition offer with availabilityType FUTURE_WITH_DATE,
      or an explicit backorder.
    OutOfStock: everything else, including TotalOfferCount>0 or
      SubCondition==New by themselves, FUTURE_WITHOUT_DATE, or no Offers list.
    """
    offers = payload.get("Offers") or payload.get("offers") or []
    if not isinstance(offers, list):
        offers = []
    winners = [o for o in offers if isinstance(o, dict) and o.get("IsBuyBoxWinner") is True]
    pool = winners or [o for o in offers if isinstance(o, dict)]

    def is_new(offer: dict) -> bool:
        return _offer_subcondition(offer) == "new"

    for offer in pool:
        if not is_new(offer):
            continue
        atype = _offer_availability_type(offer)
        if atype == "FUTURE_WITH_DATE" or _offer_is_backorder(offer):
            return "https://schema.org/PreOrder"

    for offer in pool:
        if not is_new(offer):
            continue
        atype = _offer_availability_type(offer)
        if atype == "NOW":
            return "https://schema.org/InStock"
        if atype in ("", "NOW") and (
            offer.get("IsBuyBoxWinner") is True or offer.get("IsFulfilledByAmazon") is True
        ):
            return "https://schema.org/InStock"

    return "https://schema.org/OutOfStock"


def parse_buy_box(body: dict) -> dict:
    """Return a product result dict. status is ok | no_buy_box | error."""
    payload = body.get("payload") or body
    if body.get("errors"):
        code = (body["errors"][0] or {}).get("code") or "error"
        return {"status": "error", "reason": str(code)}
    summary = payload.get("Summary") or {}
    buy_boxes = summary.get("BuyBoxPrices") or []
    chosen = None
    for row in buy_boxes:
        if str(row.get("condition") or "").lower() == "new":
            chosen = row
            break
    if chosen is None and buy_boxes:
        chosen = buy_boxes[0]
    if not chosen:
        return {"status": "no_buy_box", "reason": "no BuyBoxPrices"}
    money = _money(chosen, "LandedPrice") or _money(chosen, "ListingPrice")
    if not money:
        return {"status": "no_buy_box", "reason": "Buy Box missing amount"}
    price, currency = money
    if currency != "USD":
        return {"status": "no_buy_box", "reason": f"non-USD currency {currency}"}
    return {
        "status": "ok",
        "price": price,
        "priceCurrency": "USD",
        "availability": _availability(payload),
        "price_source": "LandedPrice" if _money(chosen, "LandedPrice") else "ListingPrice",
    }


def load_price_file(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def parse_valid_until(raw) -> dt.datetime | None:
    if not raw:
        return None
    try:
        until = dt.datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=ET)
    return until


def still_valid(data: dict | None, now: dt.datetime) -> bool:
    if not data:
        return False
    until = parse_valid_until(data.get("priceValidUntil"))
    return bool(until and now < until)


def item_still_valid(item: dict | None, catalog: dict | None, now: dt.datetime) -> bool:
    """True when this ASIN has a stored ok price and now is before its window."""
    if not item or item.get("status") != "ok" or not item.get("price"):
        return False
    until = parse_valid_until(item.get("priceValidUntil"))
    if until is None and catalog is not None:
        until = parse_valid_until(catalog.get("priceValidUntil"))
    return bool(until and now < until)


def amazon_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}"


def visible_price_html(price: str) -> str:
    return (
        f"{PRICE_START}\n"
        f'        <p class="product-price">${price} <span>on Amazon</span></p>\n'
        f"        {PRICE_END}"
    )


def strip_visible_price(html: str) -> str:
    pattern = re.compile(
        rf"\s*{re.escape(PRICE_START)}.*?{re.escape(PRICE_END)}",
        re.S,
    )
    html = pattern.sub("", html)
    # Also drop a leftover unmarked price node if a prior edit added one.
    html = re.sub(
        r'\s*<p class="product-price">.*?</p>',
        "",
        html,
    )
    return html


def upsert_visible_price(html: str, price: str) -> str:
    html = strip_visible_price(html)
    block = visible_price_html(price)
    marker = '        <div class="hero-actions">'
    if marker not in html:
        raise ValueError("hero-actions block not found")
    return html.replace(marker, block + "\n" + marker, 1)


def patch_product_json_ld(html: str, offer: dict | None) -> str:
    found = False

    def repl(match: re.Match) -> str:
        nonlocal found
        prefix, raw, suffix = match.group(1), match.group(2), match.group(3)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return match.group(0)
        if data.get("@type") != "Product":
            return match.group(0)
        found = True
        for key in FORBIDDEN_SCHEMA_KEYS:
            data.pop(key, None)
        if offer:
            # Match the pre-#15 shape, plus priceValidUntil, placed before url.
            data.pop("offers", None)
            ordered = {}
            inserted = False
            for key, val in data.items():
                if key == "url" and not inserted:
                    ordered["offers"] = offer
                    inserted = True
                ordered[key] = val
            if not inserted:
                ordered["offers"] = offer
            data = ordered
        else:
            data.pop("offers", None)
        dumped = json.dumps(data, indent=2, ensure_ascii=False)
        return prefix + dumped + suffix

    updated = SCRIPT_RE.sub(repl, html, count=0)
    if not found:
        raise ValueError("Product JSON-LD script not found")
    return updated


def price_valid_until_date(price_valid_until: str) -> str:
    """schema.org Date: the last full calendar date in ET before the expiry instant.

    An expiry of 2026-11-12 7:07 PM ET therefore becomes 2026-11-11, so the
    page never claims validity past the 48h window.
    """
    until_dt = dt.datetime.fromisoformat(price_valid_until)
    if until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=ET)
    else:
        until_dt = until_dt.astimezone(ET)
    return (until_dt.date() - dt.timedelta(days=1)).isoformat()


def offer_block(item: dict, price_valid_until: str) -> dict:
    # JSON-LD date is schema.org Date (date-only), floored to the last full
    # ET calendar date before the real expiry timestamp.
    return {
        "@type": "Offer",
        "url": item["url"],
        "priceCurrency": "USD",
        "price": item["price"],
        "availability": item["availability"],
        "priceValidUntil": price_valid_until_date(price_valid_until),
        "itemCondition": "https://schema.org/NewCondition",
    }


def patch_page(path: Path, item: dict | None, price_valid_until: str) -> bool:
    original = path.read_text()
    html = original
    if item and item.get("status") == "ok":
        html = patch_product_json_ld(html, offer_block(item, price_valid_until))
        html = upsert_visible_price(html, item["price"])
    else:
        html = patch_product_json_ld(html, None)
        html = strip_visible_price(html)
    if html == original:
        return False
    path.write_text(html)
    return True


def extract_product_ld(html: str) -> dict | None:
    for match in SCRIPT_RE.finditer(html):
        try:
            data = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "Product":
            return data
    return None


def validate_page(path: Path, item: dict | None, price_valid_until: str) -> list[str]:
    errors = []
    html = path.read_text()
    data = extract_product_ld(html)
    if data is None:
        return ["no Product JSON-LD"]
    for key in FORBIDDEN_SCHEMA_KEYS:
        if key in data:
            errors.append(f"forbidden key {key}")
    visible = re.search(
        r'<p class="product-price">\$([0-9]+\.[0-9]{2}) <span>on Amazon</span></p>',
        html,
    )
    if item and item.get("status") == "ok":
        offers = data.get("offers")
        if not isinstance(offers, dict):
            errors.append("missing offers object")
            return errors
        expected = offer_block(item, item.get("priceValidUntil") or price_valid_until)
        for key in ("@type", "url", "priceCurrency", "price", "availability", "priceValidUntil", "itemCondition"):
            if offers.get(key) != expected[key]:
                errors.append(f"offers.{key}={offers.get(key)!r} expected {expected[key]!r}")
        if offers.get("priceCurrency") != "USD":
            errors.append("priceCurrency is not USD")
        if not visible:
            errors.append("visible price missing or malformed")
        elif visible.group(1) != item["price"]:
            errors.append(
                f"visible price {visible.group(1)} != json-ld/file price {item['price']}"
            )
    else:
        if "offers" in data:
            errors.append("offers present but this product has no fresh price")
        if visible or PRICE_START in html or 'class="product-price"' in html:
            errors.append("visible price present but this product has no fresh price")
    return errors


def validate_all(root: Path, catalog: dict) -> int:
    until = catalog.get("priceValidUntil") or ""
    failed = 0
    products = catalog.get("products") or {}
    for meta in PRODUCTS:
        slug = meta["slug"]
        path = root / "swaddles" / f"{slug}.html"
        item = products.get(slug)
        errs = validate_page(path, item, (item or {}).get("priceValidUntil") or until)
        if errs:
            failed += 1
            log(f"VALIDATE FAIL {slug}: " + "; ".join(errs))
        else:
            status = (item or {}).get("status") or "absent"
            price = (item or {}).get("price") or "-"
            log(f"VALIDATE OK {slug} status={status} price={price}")
    return failed


def keep_existing_item(existing_catalog: dict | None, slug: str, meta: dict, now: dt.datetime) -> dict:
    """On a per-ASIN transport/API error, keep a still-valid stored Offer."""
    previous = ((existing_catalog or {}).get("products") or {}).get(slug) or {}
    base = {"asin": meta["asin"], "url": amazon_url(meta["asin"])}
    if item_still_valid(previous, existing_catalog, now):
        kept = {**base, **{k: previous[k] for k in previous}}
        kept["status"] = "ok"
        kept["asin"] = meta["asin"]
        kept["url"] = previous.get("url") or base["url"]
        if not kept.get("priceValidUntil") and existing_catalog:
            kept["priceValidUntil"] = existing_catalog.get("priceValidUntil")
        return kept
    return {
        **base,
        "status": "error",
        "price": None,
        "availability": None,
        "reason": "refresh failed",
    }


def merge_fetch_results(
    existing_catalog: dict | None,
    results: dict[str, dict],
    now: dt.datetime,
) -> dict[str, dict]:
    """Keep still-valid prices on per-ASIN transport/API errors; drop expired ones.

    A successful no_buy_box response is not an error: that ASIN is dropped.
    """
    merged = {}
    for meta in PRODUCTS:
        slug = meta["slug"]
        fresh = results[slug]
        if fresh.get("status") == "error":
            kept = keep_existing_item(existing_catalog, slug, meta, now)
            if kept.get("status") == "ok":
                log(
                    f"ASIN={meta['asin']} slug={slug} fetch error "
                    f"({fresh.get('reason')}); keeping stored Offer until {kept.get('priceValidUntil')}"
                )
            else:
                log(
                    f"ASIN={meta['asin']} slug={slug} fetch error "
                    f"({fresh.get('reason')}); stored Offer missing or expired; dropping"
                )
            merged[slug] = kept
            continue
        if fresh.get("status") == "ok" and not fresh.get("priceValidUntil"):
            # filled later by write_catalog from the batch until
            pass
        merged[slug] = fresh
    return merged


def neutralize_html(html: str) -> str:
    """Strip Offer JSON-LD and amazon-price marker blocks for confined-diff checks."""
    html = strip_visible_price(html)

    def repl(match: re.Match) -> str:
        prefix, raw, suffix = match.group(1), match.group(2), match.group(3)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return match.group(0)
        if data.get("@type") != "Product":
            return match.group(0)
        data.pop("offers", None)
        return prefix + json.dumps(data, indent=2, ensure_ascii=False) + suffix

    return SCRIPT_RE.sub(repl, html)


def html_changes_are_confined(old: str, new: str) -> bool:
    """True when the only HTML differences are Offer JSON-LD and price markers."""
    return neutralize_html(old) == neutralize_html(new)


def git_porcelain(root: Path) -> list[tuple[str, str]]:
    """Return (status, path) from git status --porcelain. Paths are relative to root."""
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "-uall"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append((status, path))
    return rows


def git_show(root: Path, rev_path: str) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(root), "show", rev_path],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _porcelain_problem(status: str, path: str) -> str | None:
    """Return a problem string if this porcelain entry is not an unstaged M on an allowlisted path."""
    if path not in ALLOWED_COMMIT_PATHS:
        return f"dirty path not allowed: {path}"
    if status != ALLOWED_PORCELAIN:
        kind = status.strip()
        if status == "??":
            return f"untracked path not allowed: {path}"
        if "D" in status:
            return f"deletion not allowed: {path} (status {status!r})"
        if "R" in status:
            return f"rename not allowed: {path} (status {status!r})"
        if "A" in status:
            return f"addition not allowed: {path} (status {status!r})"
        if status[0] != " ":
            return f"staged entry not allowed: {path} (status {status!r})"
        return f"porcelain status {status!r} not allowed on {path} (only unstaged M is accepted)"
    return None


def check_commit_diff(root: Path) -> list[str]:
    """Problems that should block a prices commit (pre-staging). Empty means the tree is committable."""
    problems = []
    json_path = root / PRICE_JSON
    if not json_path.is_file():
        problems.append(f"required file is missing: {PRICE_JSON}")
    dirty = git_porcelain(root)
    if not dirty:
        return problems
    for status, path in dirty:
        problem = _porcelain_problem(status, path)
        if problem:
            problems.append(problem)
    for status, path in dirty:
        if status != ALLOWED_PORCELAIN:
            continue
        if not path.startswith("swaddles/") or not path.endswith(".html"):
            continue
        if path not in ALLOWED_COMMIT_PATHS:
            continue
        old = git_show(root, f"HEAD:{path}")
        new = (root / path).read_text() if (root / path).is_file() else ""
        if not html_changes_are_confined(old, new):
            problems.append(
                f"html diff outside Offer JSON-LD / amazon-price markers: {path}"
            )
    return problems


def git_cached_name_status(root: Path) -> list[tuple[str, str]]:
    """Return (status, path) from git diff --cached --name-status."""
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-status"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        parts = line.split("	")
        status, path = parts[0], parts[-1]
        rows.append((status, path))
    return rows


def check_cached_index(root: Path) -> list[str]:
    """Post-git-add check: the index must be M-only on allowlisted paths."""
    problems = []
    json_path = root / PRICE_JSON
    if not json_path.is_file():
        problems.append(f"required file is missing: {PRICE_JSON}")
    for status, path in git_cached_name_status(root):
        code = status[0] if status else ""
        if path not in ALLOWED_COMMIT_PATHS:
            problems.append(f"cached path not allowed: {path} (status {status})")
            continue
        if code != "M":
            problems.append(f"cached status {status} not allowed: {path} (only M is accepted)")
    return problems


def fetch_all(access_token: str) -> tuple[dict[str, dict], int]:
    """Returns {slug: result} and the count of transport/API errors."""
    results = {}
    transport_errors = 0
    for i, meta in enumerate(PRODUCTS):
        if i:
            time.sleep(2.5)
        slug, asin = meta["slug"], meta["asin"]
        http, body, err = get_item_offers(access_token, asin)
        base = {"asin": asin, "url": amazon_url(asin)}
        if body is None:
            transport_errors += 1
            results[slug] = {**base, "status": "error", "reason": err or f"HTTP {http}"}
            log(f"getItemOffers ASIN={asin} slug={slug} HTTP {http} error={err}")
            continue
        parsed = parse_buy_box(body)
        results[slug] = {**base, **parsed}
        if parsed["status"] == "ok":
            log(
                f"getItemOffers ASIN={asin} slug={slug} HTTP {http} "
                f"status=ok price={parsed['price']} USD "
                f"source={parsed['price_source']} availability={parsed['availability']}"
            )
        else:
            log(
                f"getItemOffers ASIN={asin} slug={slug} HTTP {http} "
                f"status={parsed['status']} reason={parsed.get('reason')}"
            )
    return results, transport_errors


def write_catalog(path: Path, results: dict[str, dict], fetched_at: dt.datetime, until: dt.datetime) -> dict:
    products = {}
    for meta in PRODUCTS:
        slug = meta["slug"]
        item = results[slug]
        entry = {
            "asin": item["asin"],
            "url": item["url"],
            "status": item["status"],
        }
        if item["status"] == "ok":
            entry["price"] = item["price"]
            entry["priceCurrency"] = "USD"
            entry["availability"] = item["availability"]
            entry["priceValidUntil"] = item.get("priceValidUntil") or until.isoformat()
        else:
            entry["price"] = None
            entry["availability"] = None
            if item.get("reason"):
                entry["reason"] = item["reason"]
        products[slug] = entry
    catalog = {
        "marketplace": MARKETPLACE,
        "currency": "USD",
        "source": "getItemOffers",
        "fetched_at": fetched_at.isoformat(),
        "priceValidUntil": until.isoformat(),
        "products": products,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2) + "\n")
    return catalog


def apply_catalog(root: Path, catalog: dict) -> list[str]:
    # styles.css is maintained in the implementation PR only. Daily refreshes
    # must not touch it.
    changed = []
    fallback_until = catalog.get("priceValidUntil") or ""
    for meta in PRODUCTS:
        slug = meta["slug"]
        item = catalog["products"][slug]
        path = root / "swaddles" / f"{slug}.html"
        until = item.get("priceValidUntil") or fallback_until
        if patch_page(path, item, until):
            changed.append(str(path.relative_to(root)))
    return changed


def keep_or_strip_after_fetch_failure(
    root: Path, price_path: Path, existing: dict | None, now: dt.datetime
) -> int:
    """Catalog-level keep/strip when LWA or the fetch path fails before a usable result."""
    if still_valid(existing, now):
        log("FETCH FAILED; existing prices still within priceValidUntil; leaving site files unchanged")
        log(ALERT_EXIT_2)
        return 2
    if existing:
        log("FETCH FAILED; priceValidUntil has passed or is missing; stripping Offers and visible prices")
        empty = {
            slug: {
                "asin": meta["asin"],
                "url": amazon_url(meta["asin"]),
                "status": "error",
                "price": None,
                "availability": None,
                "reason": "refresh failed",
            }
            for slug, meta in ((m["slug"], m) for m in PRODUCTS)
        }
        catalog = write_catalog(price_path, empty, now, now)
        changed = apply_catalog(root, catalog)
        log("stripped files: " + (", ".join(changed) if changed else "(none)"))
        return 3
    log("FETCH FAILED; no existing price file; leaving pages without Offers")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="sincerelycozy repo root")
    ap.add_argument(
        "--validate-only",
        action="store_true",
        help="validate existing patched pages against data/amazon-prices.json",
    )
    ap.add_argument(
        "--check-commit-diff",
        action="store_true",
        help="exit 1 if the worktree has disallowed porcelain status, a missing price JSON, or HTML hunks outside Offer/price markers",
    )
    ap.add_argument(
        "--check-cached-index",
        action="store_true",
        help="exit 1 if git diff --cached --name-status is not M-only on allowlisted paths",
    )
    args = ap.parse_args()
    root = Path(args.root).resolve()
    price_path = root / "data" / "amazon-prices.json"

    if args.check_commit_diff:
        problems = check_commit_diff(root)
        for problem in problems:
            log(problem)
        if problems:
            log("COMMIT BLOCKED")
            return 1
        log("COMMIT DIFF OK")
        return 0

    if args.check_cached_index:
        problems = check_cached_index(root)
        for problem in problems:
            log(problem)
        if problems:
            log("CACHED INDEX BLOCKED")
            return 1
        log("CACHED INDEX OK")
        return 0

    if args.validate_only:
        catalog = load_price_file(price_path)
        if not catalog:
            log("ERROR: data/amazon-prices.json missing or invalid")
            return 1
        failed = validate_all(root, catalog)
        return 1 if failed else 0

    existing = load_price_file(price_path)
    now = dt.datetime.now(tz=ET)

    try:
        client_id = load_client_id()
        client_secret = load_secret("AMAZON_SPAPI_CLIENT_SECRET")
        refresh_token = load_secret("AMAZON_SPAPI_REFRESH_TOKEN")
        token = lwa_access_token(client_id, client_secret, refresh_token)
        results, transport_errors = fetch_all(token)
    except SystemExit:
        return keep_or_strip_after_fetch_failure(root, price_path, existing, now)
    except TRANSPORT_EXCEPTIONS as e:
        log(f"FETCH transport error type={type(e).__name__}")
        return keep_or_strip_after_fetch_failure(root, price_path, existing, now)

    live_ok = sum(1 for item in results.values() if item["status"] == "ok")
    if live_ok == 0 and transport_errors == len(PRODUCTS):
        if still_valid(existing, now):
            log("ALL getItemOffers calls failed; existing prices still valid; leaving site files unchanged")
            log(ALERT_EXIT_2)
            return 2
        log("ALL getItemOffers calls failed; stripping Offers rather than keeping stale prices")
        catalog = write_catalog(price_path, results, now, now)
        changed = apply_catalog(root, catalog)
        log("stripped files: " + (", ".join(changed) if changed else "(none)"))
        failed = validate_all(root, catalog)
        return 3 if not failed else 1

    results = merge_fetch_results(existing, results, now)
    until = now + dt.timedelta(hours=PRICE_VALID_HOURS)
    catalog = write_catalog(price_path, results, now, until)
    changed = apply_catalog(root, catalog)
    log("wrote data/amazon-prices.json")
    log("changed: " + (", ".join(changed) if changed else "(none, already current)"))
    failed = validate_all(root, catalog)
    if failed:
        log(f"ERROR: {failed} page(s) failed JSON-LD/visible-price validation")
        return 1
    ok_count = sum(1 for item in catalog["products"].values() if item.get("status") == "ok")
    log(f"OK: {ok_count} of {len(PRODUCTS)} products have a Buy Box Offer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
