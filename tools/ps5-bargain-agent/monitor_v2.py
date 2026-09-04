#!/usr/bin/env python3
"""Strict PS5 bargain monitor built on the base marketplace parsers."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

import monitor as base

MAX_TOTAL = Decimal(os.getenv("PS5_MAX_TOTAL_GBP", "280"))
ASSIGNEE = os.getenv("PS5_ASSIGNEE", "imsphmn")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")

SOURCES = [
    {
        "name": "Gumtree UK",
        "kind": "gumtree",
        "url": (
            "https://www.gumtree.com/search?search_category=ps5&search_location=uk&"
            "q=ps5%20console%20controller&max_price=279"
        ),
    },
    {
        "name": "Cash Generator",
        "kind": "generic",
        "url": "https://cashgenerator.co.uk/search?q=ps5%20console&type=product",
    },
    {
        "name": "Cash Converters",
        "kind": "generic",
        "url": "https://www.cashconverters.co.uk/search-results?query=ps5%20console",
    },
    {
        "name": "eBay UK Disc Buy It Now",
        "kind": "ebay",
        "url": (
            "https://www.ebay.co.uk/sch/i.html?"
            "_nkw=ps5+disc+console+controller&_udhi=279&LH_BIN=1&_sop=10&_ipg=120"
        ),
    },
    {
        "name": "eBay UK Original Digital Buy It Now",
        "kind": "ebay",
        "url": (
            "https://www.ebay.co.uk/sch/i.html?"
            "_nkw=ps5+825gb+digital+console+controller+-slim&_udhi=279&LH_BIN=1&_sop=10&_ipg=120"
        ),
    },
]

BING_QUERIES = [
    'site:ebay.co.uk/itm/ ("PS5" OR "PlayStation 5") (controller OR DualSense) (disc OR 825GB) -faulty -parts -"console only"',
    'site:ebay.co.uk/itm/ "PS5 Disc Edition" controller used UK £279 OR £269 OR £259 OR £249',
    'site:ebay.co.uk/itm/ "PS5 Digital Edition" controller 825GB used UK -slim £279 OR £269 OR £259 OR £249',
]

EXTRA_REJECT = (
    "controller not included",
    "does not include controller",
    "doesn't include controller",
    "controller is not included",
    "unfortunately the controller",
)

SOLD_MARKERS = (
    "this listing sold",
    "listing has ended",
    "this listing has ended",
    "out of stock",
    "sold out",
    "no longer available",
    "currently unavailable",
)


def amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace("£", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        values = base.money(str(value))
        return values[0] if values else None


def objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def types(obj: dict[str, Any]) -> set[str]:
    value = obj.get("@type")
    if isinstance(value, list):
        return {str(item).lower() for item in value}
    return {str(value).lower()}


def json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        found.extend(objects(payload))
    return found


def offer(product: dict[str, Any]) -> dict[str, Any]:
    value = product.get("offers")
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), {})
    return value if isinstance(value, dict) else {}


def canonical_product_url(product: dict[str, Any]) -> str:
    return base.canonical_url(str(product.get("url", "")))


def choose_product(soup: BeautifulSoup, candidate: base.Candidate) -> dict[str, Any] | None:
    products = [obj for obj in json_ld(soup) if "product" in types(obj)]
    if not products:
        return None

    candidate_url = base.canonical_url(candidate.url)
    candidate_words = set(re.findall(r"[a-z0-9]+", candidate.title.lower()))

    def score(product: dict[str, Any]) -> tuple[int, int]:
        product_url = canonical_product_url(product)
        title = base.clean_text(str(product.get("name", ""))).lower()
        title_words = set(re.findall(r"[a-z0-9]+", title))
        overlap = len(candidate_words & title_words)
        url_score = 1000 if product_url and product_url == candidate_url else 0
        ps5_score = 100 if ("ps5" in title or "playstation 5" in title) else 0
        description_length = len(base.clean_text(str(product.get("description", ""))))
        return url_score + ps5_score + overlap, description_length

    return max(products, key=score)


def meta(soup: BeautifulSoup, *selectors: str) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        value = node.get("content") if node.has_attr("content") else node.get_text(" ", strip=True)
        value = base.clean_text(str(value or ""))
        if value:
            return value
    return ""


def first_money(text: str, patterns: Iterable[str]) -> Decimal | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            parsed = amount(match.group(1))
            if parsed is not None:
                return parsed
    return None


def structured_shipping(current_offer: dict[str, Any]) -> Decimal | None:
    details = current_offer.get("shippingDetails")
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list):
        return None
    values: list[Decimal] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        rate = detail.get("shippingRate")
        if isinstance(rate, dict):
            parsed = amount(rate.get("value"))
            if parsed is not None:
                values.append(parsed)
    return min(values) if values else None


def search_prefilter(candidate: base.Candidate) -> tuple[bool, str]:
    text = f" {candidate.title} {candidate.raw_text} ".lower()
    if not ("ps5" in text or "playstation 5" in text):
        return False, "not PS5"
    if any(term in text for term in base.ACCESSORY_REJECT):
        return False, "accessory"
    if any(term in text for term in (*base.HARD_REJECT, *EXTRA_REJECT)):
        return False, "faulty or incomplete"
    if "slim" in text and "digital" in text:
        return False, "Slim Digital excluded"
    if not any(term in text for term in base.CONSOLE_TERMS):
        return False, "not clearly console"
    if candidate.item_price and candidate.item_price >= MAX_TOTAL:
        return False, "search price over target"
    return True, "passed"


def listing_location(product: dict[str, Any] | None, soup: BeautifulSoup) -> str:
    values: list[str] = []
    if product:
        for key in ("availableAtOrFrom", "areaServed"):
            value = product.get(key)
            if not isinstance(value, dict):
                continue
            address = value.get("address")
            if isinstance(address, dict):
                for subkey in ("addressLocality", "addressRegion", "postalCode"):
                    if address.get(subkey):
                        values.append(base.clean_text(str(address[subkey])))
            if value.get("name"):
                values.append(base.clean_text(str(value["name"])))
    extra = meta(soup, "meta[property='og:locality']", "meta[name='geo.placename']")
    if extra:
        values.append(extra)
    return ", ".join(dict.fromkeys(item for item in values if item))[:160]


def verify(session: requests.Session, candidate: base.Candidate) -> tuple[bool, str]:
    try:
        page = base.fetch(session, candidate.url)
    except Exception as exc:
        return False, f"detail fetch failed: {type(exc).__name__}: {exc}"

    soup = BeautifulSoup(page, "html.parser")
    product = choose_product(soup, candidate)
    current_offer = offer(product) if product else {}

    title = base.clean_text(str(product.get("name", ""))) if product else ""
    description = base.clean_text(str(product.get("description", ""))) if product else ""
    condition = base.clean_text(str(product.get("itemCondition", ""))) if product else ""
    availability = base.clean_text(str(current_offer.get("availability", "")))

    title = title or meta(soup, "meta[property='og:title']", "meta[name='twitter:title']")
    if not title:
        heading = soup.select_one("h1")
        title = base.clean_text(heading.get_text(" ", strip=True)) if heading else candidate.title
    description = description or meta(
        soup,
        "meta[property='og:description']",
        "meta[name='description']",
        "meta[name='twitter:description']",
    )

    main_node = soup.select_one("main") or soup.select_one("article")
    main_text = base.clean_text(main_node.get_text(" ", strip=True)) if main_node else ""
    full_text = base.clean_text(soup.get_text(" ", strip=True))
    specific = f" {title} {description} {condition} ".lower()

    if availability and any(word in availability.lower() for word in ("outofstock", "soldout", "discontinued")):
        return False, f"unavailable: {availability}"
    page_title = base.clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    status_text = f"{page_title} {meta(soup, 'meta[property=\'og:description\']')}".lower()
    if any(marker in status_text for marker in SOLD_MARKERS):
        return False, "sold or ended"

    if any(term in specific for term in base.ACCESSORY_REJECT):
        return False, "accessory"
    if any(term in specific for term in (*base.HARD_REJECT, *EXTRA_REJECT)):
        return False, "faulty, parts-only, or incomplete"
    if "slim" in specific and "digital" in specific:
        return False, "Slim Digital excluded"
    if not ("ps5" in specific or "playstation 5" in specific):
        return False, "not clearly PS5"
    if not any(term in specific for term in base.CONSOLE_TERMS):
        return False, "not clearly console"
    if not any(term in specific for term in base.CONTROLLER_TERMS):
        return False, "controller not confirmed"

    price = None
    if current_offer:
        price = amount(current_offer.get("price")) or amount(current_offer.get("lowPrice"))
    if price is None and product:
        price = amount(product.get("price"))
    if price is None:
        price = candidate.item_price
    if price is None or price <= 0:
        price = first_money(
            f"{title} {description} {main_text[:5000]}",
            (
                r"(?:price|buy now|now)\s*[:|-]?\s*£\s*(\d{1,5}(?:\.\d{1,2})?)",
                r"£\s*(\d{1,5}(?:\.\d{1,2})?)",
            ),
        )
    if price is None:
        return False, "price unknown"

    cost_text = main_text[:10000] or full_text[:10000]
    delivery = structured_shipping(current_offer)
    if delivery is None:
        delivery = first_money(
            cost_text,
            (
                r"delivery(?:\s+from|\s+costs?|\s+fee)?\s*[:|-]?\s*£\s*(\d{1,4}(?:\.\d{1,2})?)",
                r"postage(?:\s+from|\s+costs?)?\s*[:|-]?\s*£\s*(\d{1,4}(?:\.\d{1,2})?)",
                r"shipping(?:\s+from|\s+costs?)?\s*[:|-]?\s*£\s*(\d{1,4}(?:\.\d{1,2})?)",
            ),
        )
    if delivery is None and candidate.delivery_known:
        delivery = candidate.delivery

    cost_low = cost_text.lower()
    collection_only = any(
        phrase in specific or phrase in cost_low
        for phrase in ("collection only", "local collection only", "cash on collection")
    )
    if collection_only:
        delivery = Decimal("0")
    elif delivery is None and any(
        phrase in cost_low for phrase in ("free delivery", "free postage", "delivery: free", "postage: free")
    ):
        delivery = Decimal("0")
    if delivery is None:
        return False, "delivery unknown, strict total not provable"

    host = urlparse(candidate.url).netloc.lower()
    protection = Decimal("0")
    if "gumtree.com" in host and not collection_only:
        protection = first_money(
            cost_text,
            (
                r"buyer(?:'s)? protection(?:\s+fee)?\s*[:|-]?\s*£\s*(\d{1,4}(?:\.\d{1,2})?)",
                r"buyer protection(?:\s+fee)?\s*[:|-]?\s*£\s*(\d{1,4}(?:\.\d{1,2})?)",
            ),
        ) or (Decimal("0.70") + price * Decimal("0.10"))

    total = price + delivery + protection
    if total >= MAX_TOTAL:
        return False, f"total £{total:.2f} not below target"
    if price < Decimal("140"):
        return False, "implausibly low price"

    candidate.title = title
    candidate.condition = condition
    candidate.item_price = price
    candidate.delivery = delivery + protection
    candidate.delivery_known = True
    candidate.raw_text = f"{description} {candidate.raw_text}"[:5000]
    candidate.notes = [
        f"Actual delivery £{delivery:.2f}",
        f"Mandatory buyer fee £{protection:.2f}",
        f"Location {listing_location(product, soup) or 'not extracted'}",
        f"Collection only: {'yes' if collection_only else 'no'}",
    ]
    return True, "verified"


def parse_bing(page: str) -> list[base.Candidate]:
    root = ET.fromstring(page)
    found: list[base.Candidate] = []
    for item in root.findall(".//item"):
        title = base.clean_text(item.findtext("title"))
        link = base.canonical_url(base.clean_text(item.findtext("link")))
        description = base.clean_text(item.findtext("description"))
        if "ebay.co.uk/itm" not in link:
            continue
        prices = base.money(f"{title} {description}")
        found.append(
            base.Candidate(
                source="Bing discovery for eBay UK",
                title=title,
                url=link,
                item_price=prices[0] if prices else Decimal("0"),
                delivery=Decimal("0"),
                delivery_known=False,
                raw_text=description,
            )
        )
    return found


def github_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ps5-bargain-agent",
    }


def create_alert(candidate: base.Candidate) -> str:
    actual_delivery = candidate.notes[0].split("£", 1)[1] if candidate.notes else "unknown"
    protection = candidate.notes[1].split("£", 1)[1] if len(candidate.notes) > 1 else "unknown"
    location = candidate.notes[2].removeprefix("Location ") if len(candidate.notes) > 2 else "not extracted"
    detected = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"PS5 DEAL £{candidate.total:.2f}: {base.clean_text(candidate.title)[:100]}"[:240]
    body = f"""@{ASSIGNEE}

A live listing matched your strict PS5 bargain target.

- **Model:** {base.model_label(candidate)}
- **Item price:** £{candidate.item_price:.2f}
- **Delivery:** £{actual_delivery}
- **Mandatory buyer fee:** £{protection}
- **Verified total:** **£{candidate.total:.2f}**
- **Location:** {location}
- **Source:** {candidate.source}
- **Listing:** {candidate.url}
- **Detected:** {detected}

### Why it passed

- Total is strictly below £{MAX_TOTAL:.2f}.
- A PS5 console and controller are both indicated in the listing-specific text.
- PS5 Slim Digital, console-only, faulty, broken and parts listings are excluded.

### Before paying

1. Confirm the final checkout total has not changed.
2. Confirm a genuine Sony DualSense, power cable and HDMI cable are included.
3. Ask whether the console has overheated, shut down under load, been repaired or been console-banned.
4. Test HDMI, Wi-Fi, USB ports, controller drift and a 20-minute game session. Test a game disc on a Disc model.
5. Pay only through platform protection or in person after testing. Never use bank transfer for a remote private sale.

`PS5-LISTING-KEY: {candidate.key}`
"""
    response = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues",
        headers=github_headers(),
        json={"title": title, "body": body, "assignees": [ASSIGNEE]},
        timeout=base.REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("html_url", "")


def collect(session: requests.Session) -> tuple[list[base.Candidate], list[base.SourceResult]]:
    candidates: list[base.Candidate] = []
    results: list[base.SourceResult] = []
    for source in SOURCES:
        try:
            page = base.fetch(session, source["url"])
            parser = {
                "gumtree": base.parse_gumtree,
                "ebay": base.parse_ebay,
                "generic": base.parse_generic,
            }[source["kind"]]
            found = parser(source, page)
            candidates.extend(found)
            results.append(base.SourceResult(source["name"], True, len(found)))
            print(f"{source['name']}: {len(found)} candidates")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            results.append(base.SourceResult(source["name"], False, 0, error))
            print(f"{source['name']}: failed, {error}", file=sys.stderr)
        time.sleep(0.5)

    for query in BING_QUERIES:
        name = f"Bing eBay discovery: {query[:42]}"
        try:
            url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"
            page = base.fetch(session, url)
            found = parse_bing(page)
            candidates.extend(found)
            results.append(base.SourceResult(name, True, len(found)))
            print(f"{name}: {len(found)} candidates")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            results.append(base.SourceResult(name, False, 0, error))
            print(f"{name}: failed, {error}", file=sys.stderr)
        time.sleep(0.5)
    return candidates, results


def main() -> int:
    session = requests.Session()
    session.headers.update(base.HEADERS)
    candidates, results = collect(session)

    deduped: dict[str, base.Candidate] = {}
    for candidate in candidates:
        current = deduped.get(candidate.key)
        if current is None or candidate.item_price < current.item_price:
            deduped[candidate.key] = candidate

    qualified: list[base.Candidate] = []
    for candidate in sorted(deduped.values(), key=lambda item: item.item_price):
        passed, _ = search_prefilter(candidate)
        if not passed:
            continue
        okay, reason = verify(session, candidate)
        if okay:
            qualified.append(candidate)
            print(f"QUALIFIED £{candidate.total:.2f}: {candidate.title} | {candidate.url}")
        else:
            print(f"REJECTED {candidate.url}: {reason}")
        time.sleep(0.35)

    seen = base.existing_keys()
    created = 0
    for candidate in qualified:
        if candidate.key in seen:
            print(f"Already alerted: {candidate.key}")
            continue
        if GITHUB_TOKEN and GITHUB_REPOSITORY:
            print(f"Created alert: {create_alert(candidate)}")
            seen.add(candidate.key)
            created += 1

    base.write_step_summary(results, qualified, created)
    return 0 if any(result.fetched for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
