from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import traceback
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

RSS_URL = "https://www.espn.com/"
FEED_URL = "https://api.rss2json.com/v1/api.json?rss_url=" + quote(RSS_URL, safe="")
MAX_ITEMS = 5
OUTPUT_PATH = "data/stories.json"
TIMEOUT = 30
FEED_RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,*/*",
}


def clean_text(value: Any) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_html(value: Any) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(str(value), "lxml")
    return clean_text(soup.get_text(" ", strip=True))


def fetch_feed_json() -> dict[str, Any]:
    last_exc: Exception | None = None

    for attempt in range(1, FEED_RETRIES + 1):
        try:
            response = requests.get(FEED_URL, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "ok":
                raise RuntimeError(f"rss2json returned non-ok response: {data}")

            if not data.get("items"):
                raise RuntimeError(f"rss2json returned no items: {data}")

            return data

        except Exception as exc:
            last_exc = exc
            print(
                f"WARNING: feed fetch attempt {attempt}/{FEED_RETRIES} failed: {exc}",
                file=sys.stderr,
            )
            if attempt < FEED_RETRIES:
                time.sleep(2 * attempt)

    raise RuntimeError(f"Failed to fetch feed after {FEED_RETRIES} attempts: {last_exc}")


def extract_image(item: dict[str, Any]) -> str:
    enclosure = item.get("enclosure") or {}
    if isinstance(enclosure, dict):
        url = clean_text(enclosure.get("link") or enclosure.get("url"))
        if url:
            return url

    thumbnail = clean_text(item.get("thumbnail"))
    if thumbnail:
        return thumbnail

    content = item.get("content") or item.get("description") or ""
    soup = BeautifulSoup(str(content), "lxml")
    img = soup.find("img")
    if img:
        return clean_text(img.get("src") or img.get("data-src"))

    return ""


def to_iso(pub_date: str) -> str:
    if not pub_date:
        return ""
    try:
        return parsedate_to_datetime(pub_date).isoformat()
    except Exception:
        return pub_date


def build() -> dict[str, Any]:
    data = fetch_feed_json()

    stories: list[dict[str, Any]] = []

    for item in data.get("items", [])[:MAX_ITEMS]:
        title = clean_text(item.get("title"))
        link = clean_text(item.get("link"))
        pub_date = clean_text(item.get("pubDate"))
        summary = strip_html(item.get("description") or item.get("content") or "")
        image = extract_image(item)

        if not title or not link:
            continue

        stories.append(
            {
                "title": title,
                "link": link,
                "pubDate": pub_date,
                "summary": summary,
                "source": "ESPN",
                "image": image,
                "pubDateIso": to_iso(pub_date),
            }
        )

    if not stories:
        raise RuntimeError("No usable stories found")

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
