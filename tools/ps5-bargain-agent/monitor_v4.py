#!/usr/bin/env python3
"""Final PS5 bargain monitor, scam-aware and centred on New Malden."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import monitor as base
import monitor_v2 as v2
import monitor_v3 as v3

# Conservative marketplace exclusions. A false negative is preferable to an
# alert that encourages an unsafe payment or misstates a console-only price.
v2.EXTRA_REJECT = tuple(dict.fromkeys((*v2.EXTRA_REJECT,
    "just console",
    "console by itself",
    "console itself only",
    "upfront",
    "advance payment",
    "payment before collection",
    "payment before postage",
    "holding deposit",
    "deposit required",
    "bank transfer before",
    "payment need to be",
)))

# Add dedicated local searches. The national search remains useful for items
# with delivery, while collection-only matches must be reasonably local.
v2.SOURCES = [
    {
        "name": "Gumtree London PS5",
        "kind": "gumtree",
        "url": "https://www.gumtree.com/for-sale/video-games-consoles/game-consoles/ps5/private/uk/london?sort=date&max_price=279",
    },
    {
        "name": "Gumtree New Malden radius",
        "kind": "gumtree",
        "url": "https://www.gumtree.com/search?search_category=ps5&search_location=new-malden&q=ps5%20console&max_price=279&distance=50",
    },
    {
        "name": "Gumtree PS5 Disc local",
        "kind": "gumtree",
        "url": "https://www.gumtree.com/search?search_category=ps5&search_location=london&q=ps5%20disc%20controller&max_price=279&distance=60",
    },
    *v2.SOURCES,
]

LOCAL_MARKERS = (
    "london",
    "surrey",
    "middlesex",
    "new malden",
    "kingston",
    "surbiton",
    "sutton",
    "croydon",
    "epsom",
    "esher",
    "richmond",
    "twickenham",
    "hounslow",
    "feltham",
    "heathrow",
    "wimbledon",
    "morden",
    "wallington",
    "carshalton",
    "leatherhead",
    "cobham",
    "weybridge",
    "walton-on-thames",
    "woking",
    "guildford",
    "dorking",
    "reigate",
    "redhill",
    "staines",
    "egham",
    "windsor",
    "slough",
    "berkshire",
    "buckinghamshire",
    "hertfordshire",
    "essex",
    "kent",
    "west sussex",
    "east sussex",
)

_original_location = v2.listing_location


def improved_location(product, soup: BeautifulSoup) -> str:
    candidates: list[str] = []
    original = _original_location(product, soup)
    if original and original.lower() not in {"united kingdom", "uk"}:
        candidates.append(original)

    page_title = base.clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    og_title = v2.meta(soup, "meta[property='og:title']", "meta[name='twitter:title']")
    for text in (page_title, og_title):
        match = re.search(r"\|\s*in\s+(.+?)\s*\|\s*Gumtree", text, re.I)
        if match:
            candidates.append(base.clean_text(match.group(1)))
        match = re.search(r"for Sale in\s+(.+?)\s*\|\s*Gumtree", text, re.I)
        if match:
            candidates.append(base.clean_text(match.group(1)))

    visible = base.clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"(?:^|\s)([A-Za-z][A-Za-z' -]{2,50},\s*(?:London|Surrey|Middlesex|Essex|Kent|Berkshire|Hertfordshire|Buckinghamshire|West Sussex|East Sussex))(?=\s|£)", visible)
    if match:
        candidates.append(base.clean_text(match.group(1)))

    if not candidates and original:
        candidates.append(original)
    return ", ".join(dict.fromkeys(candidates))[:180]


v2.listing_location = improved_location

_original_verify = v2.verify


def safe_local_verify(session, candidate: base.Candidate):
    okay, reason = _original_verify(session, candidate)
    if not okay:
        return okay, reason

    host = urlparse(candidate.url).netloc.lower()
    is_gumtree = "gumtree.com" in host
    collection_only = any("collection only: yes" in note.lower() for note in candidate.notes)
    location = ""
    for note in candidate.notes:
        if note.lower().startswith("location "):
            location = note[9:].strip()
            break

    if is_gumtree and collection_only:
        location_low = location.lower()
        if not location or location_low in {"united kingdom", "uk", "not extracted"}:
            return False, "collection location could not be verified"
        if not any(marker in location_low for marker in LOCAL_MARKERS):
            return False, f"collection too far from New Malden: {location}"

    return True, reason


v2.verify = safe_local_verify

if __name__ == "__main__":
    raise SystemExit(v2.main())
