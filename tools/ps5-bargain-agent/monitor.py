#!/usr/bin/env python3
"""Find UK PS5 listings below a strict all-in target and create GitHub alerts.

The monitor is deliberately conservative. It looks for a working PS5 console
with an official controller, rejects parts-only and console-only listings, and
excludes PS5 Slim Digital models.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

MAX_TOTAL = Decimal(os.getenv("PS5_MAX_TOTAL_GBP", "280"))
ASSIGNEE = os.getenv("PS5_ASSIGNEE", "imsphmn")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
REQUEST_TIMEOUT = int(os.getenv("PS5_REQUEST_TIMEOUT_SECONDS", "25"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
}

SOURCES = [
    {
        "name": "eBay UK, Disc Buy It Now",
        "kind": "ebay",
        "url": (
            "https://www.ebay.co.uk/sch/i.html?"
            "_nkw=ps5+disc+console+controller&_udhi=280&LH_BIN=1&_sop=10&_ipg=120"
        ),
    },
    {
        "name": "eBay UK, Original Digital Buy It Now",
        "kind": "ebay",
        "url": (
            "https://www.ebay.co.uk/sch/i.html?"
            "_nkw=ps5+825gb+digital+console+controller+-slim&_udhi=280&LH_BIN=1&_sop=10&_ipg=120"
        ),
    },
    {
        "name": "eBay UK, General Buy It Now",
        "kind": "ebay",
        "url": (
            "https://www.ebay.co.uk/sch/i.html?"
            "_nkw=playstation+5+console+controller&_udhi=280&LH_BIN=1&_sop=10&_ipg=120"
        ),
    },
    {
        "name": "Gumtree UK",
        "kind": "gumtree",
        "url": (
            "https://www.gumtree.com/search?search_category=ps5&search_location=uk&"
            "q=ps5%20console%20controller&max_price=280"
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
]

SOLD_MARKERS = (
    "this listing sold",
    "listing has ended",
    "this listing has ended",
    "out of stock",
    "sold out",
    "no longer available",
    "item is no longer available",
)

HARD_REJECT = (
    "console only",
    "controller only",
    "no controller",
    "without controller",
    "missing controller",
    "box only",
    "empty box",
    "spares or repair",
    "spares/repair",
    "for parts",
    "parts only",
    "not working",
    "faulty",
    "broken",
    "hdmi fault",
    "banned console",
    "console banned",
    "missing disc drive",
    "no disc drive",
    "wanted",
    "looking for",
)

ACCESSORY_REJECT = (
    "faceplate",
    "cover plate",
    "cooling fan",
    "charging station",
    "controller charger",
    "headset only",
    "disc drive only",
    "replacement drive",
    "vertical stand",
    "wall mount",
    "carry case",
    "skin wrap",
)

CONTROLLER_TERMS = ("controller", "dualsense", "dual sense", "control pad", "joypad", " pad ")
CONSOLE_TERMS = (
    "console",
    "disc edition",
    "digital edition",
    "blu-ray edition",
    "825gb",
    "1tb",
    "cfi-",
    "ps5 with",
    "playstation 5 with",
)


@dataclass
class Candidate:
    source: str
    title: str
    url: str
    item_price: Decimal
    delivery: Decimal = Decimal("0")
    delivery_known: bool = True
    condition: str = ""
    raw_text: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return self.item_price + self.delivery

    @property
    def key(self) -> str:
        ebay_match = re.search(r"/itm/(?:[^/?]+/)?(\d{9,15})", self.url)
        if ebay_match:
            return f"ebay-{ebay_match.group(1)}"
        gumtree_match = re.search(r"/(?:p/[^/]+/)?(\d{8,15})(?:[/?#]|$)", self.url)
        if "gumtree.com" in self.url and gumtree_match:
            return f"gumtree-{gumtree_match.group(1)}"
        digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:18]
        return f"url-{digest}"


@dataclass
class SourceResult:
    name: str
    fetched: bool
    candidates: int = 0
    error: str = ""


def money(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for raw in re.findall(r"(?:£|GBP\s*)(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)", text or "", re.I):
        try:
            values.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            continue
    return values


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def canonical_url(url: str, base: str = "") -> str:
    absolute = urljoin(base, url)
    parsed = urlparse(absolute)
    if "ebay." in parsed.netloc:
        match = re.search(r"/itm/(?:[^/?]+/)?(\d{9,15})", parsed.path)
        if match:
            return f"https://www.ebay.co.uk/itm/{match.group(1)}"
    return parsed._replace(query="", fragment="").geturl()


def first_text(node: Any, selectors: Iterable[str]) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            value = clean_text(found.get_text(" ", strip=True))
            if value:
                return value
    return ""


def fetch(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    text = response.text
    if len(text) < 500:
        raise RuntimeError(f"response too short: {len(text)} bytes")
    return text


def parse_ebay(source: dict[str, str], page: str) -> list[Candidate]:
    soup = BeautifulSoup(page, "html.parser")
    items: list[Candidate] = []
    cards = soup.select("li.s-item")

    for card in cards:
        title = first_text(card, (".s-item__title", "[role='heading']", "h3"))
        if not title or title.lower() in {"shop on ebay", "results matching fewer words"}:
            continue
        link_node = card.select_one("a.s-item__link[href]") or card.select_one("a[href*='/itm/']")
        price_text = first_text(card, (".s-item__price", "[class*='price']"))
        if not link_node or not price_text:
            continue
        prices = money(price_text)
        if not prices:
            continue

        delivery_text = first_text(
            card,
            (
                ".s-item__shipping",
                ".s-item__logisticsCost",
                "[class*='shipping']",
                "[class*='delivery']",
            ),
        )
        delivery_prices = money(delivery_text)
        delivery = delivery_prices[0] if delivery_prices else Decimal("0")
        delivery_known = bool(delivery_text) or "free" in clean_text(card.get_text(" ", strip=True)).lower()
        condition = first_text(card, (".SECONDARY_INFO", ".s-item__subtitle", "[class*='condition']"))
        raw = clean_text(card.get_text(" ", strip=True))[:3000]
        url = canonical_url(str(link_node.get("href", "")), source["url"])

        items.append(
            Candidate(
                source=source["name"],
                title=title.replace("New listing", "").strip(),
                url=url,
                item_price=prices[0],
                delivery=delivery,
                delivery_known=delivery_known,
                condition=condition,
                raw_text=raw,
            )
        )
    return items


def json_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_objects(child)


def parse_json_ld(source: dict[str, str], soup: BeautifulSoup) -> list[Candidate]:
    items: list[Candidate] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in json_objects(payload):
            obj_type = obj.get("@type")
            if isinstance(obj_type, list):
                obj_types = {str(x).lower() for x in obj_type}
            else:
                obj_types = {str(obj_type).lower()}
            if "product" not in obj_types:
                continue
            title = clean_text(str(obj.get("name", "")))
            url = obj.get("url", "")
            offers = obj.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if not isinstance(offers, dict):
                offers = {}
            price_raw = str(offers.get("price", obj.get("price", "")))
            price_values = money(f"£{price_raw}") if "£" not in price_raw else money(price_raw)
            if not title or not url or not price_values:
                continue
            availability = clean_text(str(offers.get("availability", "")))
            raw_text = clean_text(json.dumps(obj, ensure_ascii=False))[:3000]
            items.append(
                Candidate(
                    source=source["name"],
                    title=title,
                    url=canonical_url(str(url), source["url"]),
                    item_price=price_values[0],
                    delivery=Decimal("0"),
                    delivery_known=False,
                    condition=clean_text(str(obj.get("itemCondition", ""))),
                    raw_text=f"{availability} {raw_text}",
                )
            )
    return items


def parse_generic(source: dict[str, str], page: str) -> list[Candidate]:
    soup = BeautifulSoup(page, "html.parser")
    items = parse_json_ld(source, soup)
    seen_urls = {item.url for item in items}

    anchors = soup.select("a[href]")
    for anchor in anchors:
        href = str(anchor.get("href", ""))
        anchor_text = clean_text(anchor.get_text(" ", strip=True))
        href_lower = href.lower()
        combined = f"{anchor_text} {href_lower}".lower()
        if "ps5" not in combined and "playstation-5" not in combined and "playstation 5" not in combined:
            continue
        if not any(token in href_lower for token in ("/product", "/shop/", "/p/", "/collections/")):
            continue

        parent = anchor
        for _ in range(5):
            if not getattr(parent, "parent", None):
                break
            parent = parent.parent
            block_text = clean_text(parent.get_text(" ", strip=True))
            if money(block_text) and len(block_text) < 5000:
                break
        block_text = clean_text(parent.get_text(" ", strip=True))[:5000]
        prices = money(block_text)
        if not prices:
            continue
        title = anchor_text or first_text(parent, ("h1", "h2", "h3", "h4", "[class*='title']"))
        if not title:
            continue
        url = canonical_url(href, source["url"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(
            Candidate(
                source=source["name"],
                title=title,
                url=url,
                item_price=prices[0],
                delivery=Decimal("0"),
                delivery_known=False,
                raw_text=block_text,
            )
        )
    return items


def parse_gumtree(source: dict[str, str], page: str) -> list[Candidate]:
    soup = BeautifulSoup(page, "html.parser")
    items = parse_json_ld(source, soup)
    seen_urls = {item.url for item in items}

    for anchor in soup.select("a[href*='/p/'], a[href*='/ps5/']"):
        href = str(anchor.get("href", ""))
        url = canonical_url(href, source["url"])
        if url in seen_urls:
            continue
        parent = anchor
        for _ in range(7):
            if not getattr(parent, "parent", None):
                break
            parent = parent.parent
            text = clean_text(parent.get_text(" ", strip=True))
            if money(text) and len(text) < 6000:
                break
        text = clean_text(parent.get_text(" ", strip=True))[:6000]
        prices = money(text)
        if not prices:
            continue
        title = clean_text(anchor.get_text(" ", strip=True)) or first_text(parent, ("h2", "h3", "h4"))
        if not title:
            continue
        seen_urls.add(url)
        items.append(
            Candidate(
                source=source["name"],
                title=title,
                url=url,
                item_price=prices[0],
                delivery=Decimal("0"),
                delivery_known=False,
                raw_text=text,
            )
        )
    return items


def initial_qualify(candidate: Candidate) -> tuple[bool, str]:
    text = f" {candidate.title} {candidate.condition} {candidate.raw_text} ".lower()
    text = re.sub(r"\s+", " ", text)

    if candidate.total >= MAX_TOTAL:
        return False, f"total £{candidate.total} is not below £{MAX_TOTAL}"
    if not ("ps5" in text or "playstation 5" in text):
        return False, "not clearly a PS5"
    if any(term in text for term in HARD_REJECT):
        return False, "parts, faulty, console-only, or wanted listing"
    if any(term in text for term in ACCESSORY_REJECT):
        return False, "accessory listing"
    if "slim" in text and "digital" in text:
        return False, "PS5 Slim Digital is excluded"
    if not any(term in text for term in CONSOLE_TERMS):
        return False, "not clearly a console"
    if not any(term in text for term in CONTROLLER_TERMS):
        return False, "controller not confirmed"
    return True, "passed"


def verify_listing(session: requests.Session, candidate: Candidate) -> tuple[bool, str]:
    try:
        page = fetch(session, candidate.url)
    except Exception as exc:  # A search result can still be useful if detail fetch is blocked.
        candidate.notes.append(f"Detail-page verification unavailable: {type(exc).__name__}")
        return True, "search result passed, detail page unavailable"

    soup = BeautifulSoup(page, "html.parser")
    visible = clean_text(soup.get_text(" ", strip=True))
    low = visible.lower()
    if any(marker in low for marker in SOLD_MARKERS):
        return False, "listing is sold, ended, or out of stock"

    heading = first_text(soup, ("h1", "[role='heading']"))
    if heading and 5 < len(heading) < 240:
        candidate.title = heading
    merged = f" {candidate.title} {candidate.raw_text} {visible[:20000]} ".lower()
    if any(term in merged for term in HARD_REJECT):
        return False, "detail page says faulty, parts-only, console-only, or no controller"
    if "slim" in merged and "digital" in merged:
        return False, "detail page identifies a PS5 Slim Digital"
    if not any(term in merged for term in CONTROLLER_TERMS):
        return False, "controller not confirmed on detail page"
    candidate.raw_text = visible[:5000]
    return True, "verified live"


def model_label(candidate: Candidate) -> str:
    text = f"{candidate.title} {candidate.raw_text}".lower()
    if "slim" in text and ("disc" in text or "blu-ray" in text):
        return "PS5 Slim Disc"
    if "digital" in text:
        return "Original PS5 Digital"
    if "disc" in text or "blu-ray" in text:
        return "Original PS5 Disc"
    return "PS5, model needs confirmation"


def risk_flags(candidate: Candidate) -> list[str]:
    text = f"{candidate.title} {candidate.raw_text}".lower()
    flags: list[str] = []
    if not candidate.delivery_known:
        flags.append("Delivery cost was not reliably shown, confirm the final checkout total.")
    if candidate.item_price < Decimal("200"):
        flags.append("Price is unusually low, only pay through platform protection and test the console.")
    if "no returns" in text:
        flags.append("Seller states no returns, eBay Money Back Guarantee may still apply where eligible.")
    if "collection" in text:
        flags.append("Collection may be required, test HDMI, Wi-Fi, USB ports, controller drift and disc drive before paying.")
    if "best offer" in text or "make an offer" in text:
        flags.append("The listing accepts offers, there may be room to negotiate lower.")
    return flags


def github_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ps5-bargain-agent",
    }


def existing_keys() -> set[str]:
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        return set()
    keys: set[str] = set()
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues"
    for page_number in range(1, 4):
        response = requests.get(
            url,
            headers=github_headers(),
            params={"state": "all", "per_page": 100, "page": page_number, "sort": "created", "direction": "desc"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            break
        for issue in rows:
            body = issue.get("body") or ""
            for match in re.findall(r"PS5-LISTING-KEY:\s*([A-Za-z0-9_-]+)", body):
                keys.add(match)
    return keys


def create_alert(candidate: Candidate) -> None:
    detected = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_line = f"£{candidate.total:.2f}"
    delivery_line = f"£{candidate.delivery:.2f}" if candidate.delivery_known else "not reliably shown"
    flags = risk_flags(candidate)
    flags_text = "\n".join(f"- {flag}" for flag in flags) if flags else "- No automatic risk flag, still complete the checks below."
    safe_title = clean_text(candidate.title)[:105]
    issue_title = f"PS5 DEAL {total_line}: {safe_title}"[:240]
    body = f"""@{ASSIGNEE}

A listing matched your strict PS5 bargain target.

- **Model:** {model_label(candidate)}
- **Item price:** £{candidate.item_price:.2f}
- **Delivery parsed:** {delivery_line}
- **Parsed total:** **{total_line}**
- **Source:** {candidate.source}
- **Listing:** {candidate.url}
- **Detected:** {detected}

### Why it passed

- Price is strictly below £{MAX_TOTAL:.2f}.
- A PS5 console and controller are both indicated.
- PS5 Slim Digital, console-only, faulty, broken and parts listings are excluded.

### Risk flags

{flags_text}

### Before paying

1. Confirm the final checkout total remains below £{MAX_TOTAL:.2f}, including delivery and buyer-protection fees.
2. Confirm the genuine Sony DualSense controller, power cable and HDMI cable are included.
3. Ask whether the console has ever overheated, shut down under load, been repaired or been console-banned.
4. For a Disc model, test a game disc. For every model, test HDMI, Wi-Fi, USB, controller drift and a 20-minute game session.
5. Pay only through the platform or in person after testing. Never use bank transfer for a remote private sale.

`PS5-LISTING-KEY: {candidate.key}`
"""
    response = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues",
        headers=github_headers(),
        json={"title": issue_title, "body": body, "assignees": [ASSIGNEE]},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    issue = response.json()
    print(f"Created alert: {issue.get('html_url', issue.get('url', ''))}")


def write_step_summary(results: list[SourceResult], deals: list[Candidate], created: int) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "# PS5 bargain monitor",
        "",
        f"Target: working PS5 with controller, excluding Slim Digital, below £{MAX_TOTAL:.2f}.",
        "",
        "| Source | Fetch | Candidates | Error |",
        "|---|---:|---:|---|",
    ]
    for result in results:
        error = result.error.replace("|", "\\|")[:180]
        lines.append(f"| {result.name} | {'OK' if result.fetched else 'Failed'} | {result.candidates} | {error} |")
    lines.extend(["", f"Qualified live deals: **{len(deals)}**", f"New alerts created: **{created}**", ""])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main() -> int:
    session = requests.Session()
    session.headers.update(HEADERS)
    all_candidates: list[Candidate] = []
    source_results: list[SourceResult] = []

    for source in SOURCES:
        try:
            page = fetch(session, source["url"])
            kind = source["kind"]
            if kind == "ebay":
                candidates = parse_ebay(source, page)
            elif kind == "gumtree":
                candidates = parse_gumtree(source, page)
            else:
                candidates = parse_generic(source, page)
            all_candidates.extend(candidates)
            source_results.append(SourceResult(source["name"], True, len(candidates)))
            print(f"{source['name']}: {len(candidates)} candidates")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            source_results.append(SourceResult(source["name"], False, 0, message))
            print(f"{source['name']}: failed, {message}", file=sys.stderr)
        time.sleep(1)

    deduped: dict[str, Candidate] = {}
    for candidate in all_candidates:
        current = deduped.get(candidate.key)
        if current is None or candidate.total < current.total:
            deduped[candidate.key] = candidate

    qualified: list[Candidate] = []
    for candidate in sorted(deduped.values(), key=lambda item: item.total):
        ok, reason = initial_qualify(candidate)
        if not ok:
            continue
        verified, verify_reason = verify_listing(session, candidate)
        if verified:
            candidate.notes.append(verify_reason)
            qualified.append(candidate)
            print(f"Qualified: £{candidate.total:.2f} {candidate.title} [{candidate.url}]")
        else:
            print(f"Rejected after verification: {candidate.url}, {verify_reason}")
        time.sleep(0.5)

    seen = existing_keys()
    created = 0
    for candidate in qualified:
        if candidate.key in seen:
            print(f"Already alerted: {candidate.key}")
            continue
        if GITHUB_TOKEN and GITHUB_REPOSITORY:
            create_alert(candidate)
            seen.add(candidate.key)
            created += 1
        else:
            print(json.dumps({
                "title": candidate.title,
                "total": str(candidate.total),
                "url": candidate.url,
                "key": candidate.key,
            }, indent=2))

    write_step_summary(source_results, qualified, created)
    successful_sources = sum(1 for result in source_results if result.fetched)
    if successful_sources == 0:
        print("All sources failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
