#!/usr/bin/env python3
"""Geo-safe PS5 monitor for New Malden, with strict Gumtree delivery checks."""

from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

import monitor as base
import monitor_v2 as v2
import monitor_v4 as v4

_previous_verify = v2.verify


def replace_location_note(candidate: base.Candidate, location: str) -> None:
    replacement = f"Location {location or 'not extracted'}"
    for index, note in enumerate(candidate.notes):
        if note.lower().startswith("location "):
            candidate.notes[index] = replacement
            return
    candidate.notes.append(replacement)


def strict_gumtree_geography(session, candidate: base.Candidate):
    okay, reason = _previous_verify(session, candidate)
    if not okay:
        return okay, reason

    if "gumtree.com" not in urlparse(candidate.url).netloc.lower():
        return True, reason

    try:
        page = base.fetch(session, candidate.url)
    except Exception as exc:
        return False, f"could not verify Gumtree location and payment route: {type(exc).__name__}: {exc}"

    soup = BeautifulSoup(page, "html.parser")
    product = v2.choose_product(soup, candidate)
    location = v4.improved_location(product, soup)
    replace_location_note(candidate, location)

    location_low = (location or "").lower()
    if any(marker in location_low for marker in v4.LOCAL_MARKERS):
        return True, reason

    visible = base.clean_text(soup.get_text(" ", strip=True)).lower()
    explicit_protected_delivery = (
        "buyer protection" in visible
        and any(phrase in visible for phrase in ("delivery from", "postage", "buy now"))
        and candidate.delivery_known
        and candidate.delivery > 0
    )
    if explicit_protected_delivery:
        return True, "verified nationwide protected delivery below target"

    if not location or location_low in {"united kingdom", "uk", "not extracted"}:
        return False, "Gumtree collection location could not be verified"
    return False, f"Gumtree collection is not local to New Malden: {location}"


v2.verify = strict_gumtree_geography

if __name__ == "__main__":
    raise SystemExit(v2.main())
