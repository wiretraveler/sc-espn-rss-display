from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

FEED_URL = "https://wandering-cloud-adf4.northport-public-school.workers.dev"
MAX_ITEMS = 5
OUTPUT_PATH = "data/stories.json"
TIMEOUT = 30
FEED_RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def clean_text(value: Any) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", text).strip()


def fetch_homepage_html() -> str:
    last_exc: Exception | None = None

    for attempt in range(1, FEED_RETRIES + 1):
        try:
            response = requests.get(FEED_URL, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            text = response.text.strip()

            if "<html" not in text[:1000].lower():
                raise RuntimeError(f"ESPN did not return HTML: {text[:200]!r}")

            return text

        except Exception as exc:
            last_exc = exc
            print(
                f"WARNING: homepage fetch attempt {attempt}/{FEED_RETRIES} failed: {exc}",
                file=sys.stderr,
            )
            if attempt < FEED_RETRIES:
                time.sleep(2 * attempt)

    raise RuntimeError(f"Failed to fetch ESPN homepage after {FEED_RETRIES} attempts: {last_exc}")


def get_image(card: Any) -> str:
    img = card.find("img")
    if not img:
        return ""

    for attr in ["src", "data-src", "data-default-src"]:
        value = clean_text(img.get(attr))
        if value:
            return urljoin(FEED_URL, value)

    srcset = clean_text(img.get("srcset"))
    if srcset:
        first = srcset.split(",")[0].strip().split(" ")[0]
        return urljoin(FEED_URL, first)

    return ""


def get_summary(card: Any, title: str) -> str:
    for selector in [
        ".contentItem__subhead",
        ".contentItem__description",
        ".headlineStack__description",
        "p",
    ]:
        node = card.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text and text != title:
                return text
    return ""


def parse_top_stories(html_text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "lxml")
    stories: list[dict[str, Any]] = []
    seen: set[str] = set()

    cards = soup.select(".contentItem, .headlineStack, article, li")

    for card in cards:
        link_node = None

        for a in card.find_all("a", href=True):
            href = clean_text(a.get("href"))
            title = clean_text(a.get_text(" ", strip=True))

            if not href or not title:
                continue

            if "/story/" in href or "/game/" in href:
                link_node = a
                break

        if not link_node:
            continue

        title = clean_text(link_node.get_text(" ", strip=True))
        link = urljoin(FEED_URL, clean_text(link_node.get("href")))

        if not title or not link or link in seen:
            continue

        image = get_image(card)

        if not image:
            continue

        seen.add(link)

        now_iso = datetime.now(timezone.utc).isoformat()

        stories.append(
            {
                "title": title,
                "link": link,
                "pubDate": now_iso,
                "summary": get_summary(card, title),
                "source": "ESPN",
                "image": image,
                "pubDateIso": now_iso,
            }
        )

        if len(stories) >= MAX_ITEMS:
            break

    if not stories:
        raise RuntimeError("Could not find ESPN homepage story cards with images")

    return stories


def build() -> dict[str, Any]:
    html_text = fetch_homepage_html()
    stories = parse_top_stories(html_text)

    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stories": stories,
    }


def main() -> int:
    try:
        payload = build()
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        print(f"Wrote {OUTPUT_PATH}")
        return 0

    except Exception as exc:
        traceback.print_exc()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
