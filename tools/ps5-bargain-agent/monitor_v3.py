#!/usr/bin/env python3
"""Add safe Gumtree collection-price handling to the strict PS5 monitor."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import monitor as base
import monitor_v2 as v2

ORIGINAL_VERIFY = v2.verify


def verify_gumtree_collection(session, candidate: base.Candidate):
    okay, reason = ORIGINAL_VERIFY(session, candidate)
    if okay:
        return okay, reason
    if "gumtree.com" not in urlparse(candidate.url).netloc.lower():
        return okay, reason
    if reason != "delivery unknown, strict total not provable":
        return okay, reason

    try:
        page = base.fetch(session, candidate.url)
    except Exception as exc:
        return False, f"collection verification fetch failed: {type(exc).__name__}: {exc}"

    soup = BeautifulSoup(page, "html.parser")
    product = v2.choose_product(soup, candidate)
    current_offer = v2.offer(product) if product else {}

    title = base.clean_text(str(product.get("name", ""))) if product else ""
    description = base.clean_text(str(product.get("description", ""))) if product else ""
    condition = base.clean_text(str(product.get("itemCondition", ""))) if product else ""
    availability = base.clean_text(str(current_offer.get("availability", "")))

    title = title or v2.meta(soup, "meta[property='og:title']", "meta[name='twitter:title']")
    if not title:
        heading = soup.select_one("h1")
        title = base.clean_text(heading.get_text(" ", strip=True)) if heading else candidate.title
    description = description or v2.meta(
        soup,
        "meta[property='og:description']",
        "meta[name='description']",
        "meta[name='twitter:description']",
    )

    specific = f" {title} {description} {condition} ".lower()
    if availability and any(word in availability.lower() for word in ("outofstock", "soldout", "discontinued")):
        return False, f"unavailable: {availability}"
    page_title = base.clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    status_text = f"{page_title} {v2.meta(soup, 'meta[property=\'og:description\']')}".lower()
    if any(marker in status_text for marker in v2.SOLD_MARKERS):
        return False, "sold or ended"
    if any(term in specific for term in base.ACCESSORY_REJECT):
        return False, "accessory"
    if any(term in specific for term in (*base.HARD_REJECT, *v2.EXTRA_REJECT)):
        return False, "faulty, parts-only, or incomplete"
    if "slim" in specific and "digital" in specific:
        return False, "Slim Digital excluded"
    if not ("ps5" in specific or "playstation 5" in specific):
        return False, "not clearly PS5"
    if not any(term in specific for term in base.CONSOLE_TERMS):
        return False, "not clearly console"
    if not any(term in specific for term in base.CONTROLLER_TERMS):
        return False, "controller not confirmed"

    price = v2.amount(current_offer.get("price")) or v2.amount(current_offer.get("lowPrice"))
    if price is None and product:
        price = v2.amount(product.get("price"))
    if price is None:
        price = candidate.item_price
    if price is None or price <= 0:
        return False, "collection price unknown"
    if price >= v2.MAX_TOTAL:
        return False, f"collection price £{price:.2f} not below target"
    if price < Decimal("140"):
        return False, "implausibly low price"

    location = v2.listing_location(product, soup) or "not extracted"
    candidate.title = title
    candidate.condition = condition
    candidate.item_price = price
    candidate.delivery = Decimal("0")
    candidate.delivery_known = True
    candidate.raw_text = f"{description} {candidate.raw_text}"[:5000]
    candidate.notes = [
        "Actual delivery £0.00",
        "Mandatory buyer fee £0.00",
        f"Location {location}",
        "Collection only: yes",
    ]
    return True, "verified Gumtree collection bargain"


v2.verify = verify_gumtree_collection

if __name__ == "__main__":
    raise SystemExit(v2.main())
