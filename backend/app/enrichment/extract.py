"""Separate, source-qualified page fields in the capture shape the AI detector reads."""

import trafilatura
from bs4 import BeautifulSoup

MAX_HEADINGS = 20
MAIN_TEXT_CHARS = 6000
_METADATA_KEYS = ("description", "og:description", "og:title")


def extract_page(raw_html: bytes, url: str) -> dict:
    soup = BeautifulSoup(raw_html, "html.parser")
    metadata = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").lower()
        content = (tag.get("content") or "").strip()
        if key in _METADATA_KEYS and content:
            metadata[key] = content
    main_text = trafilatura.extract(str(soup), url=url, include_comments=False) or ""
    return {
        "title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "metadata": metadata,
        "headings": tuple(
            h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])
        )[:MAX_HEADINGS],
        "main_text": main_text[:MAIN_TEXT_CHARS],
    }
