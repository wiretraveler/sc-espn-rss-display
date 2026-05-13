from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# YOUR CLOUDFLARE WORKER
FEED_URL = "https://wandering-cloud-adf4.northport-public-school.workers.dev"

MAX_ITEMS = 5
OUTPUT_PATH = "data/stories.json"
TIMEOUT = 30
FEED_RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

NS = {
    "media": "http://search.yahoo.com/mrss/",
}


def clean_text(value: Any) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", text).strip()


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "lxml")
    return clean_text(soup.get_text(" ", strip=True))


def fetch_feed_xml() -> str:
    last_exc: Exception | None = None

    for attempt in range(1, FEED_RETRIES + 1):
        try:
            response = requests.get(
                FEED_URL,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            response.raise_for_status()

            text = response.text.strip()

            if not text.startswith("<?xml") and "<rss" not in text[:500].lower():
                raise RuntimeError(
                    f"Worker did not return RSS XML: {text[:300]!r}"
                )

            return text

        except Exception as exc:
            last_exc = exc

            print(
                f"WARNING: feed fetch attempt {attempt}/{FEED_RETRIES} failed: {exc}",
                file=sys.stderr,
            )

            if attempt < FEED_RETRIES:
                time.sleep(2 * attempt)

    raise RuntimeError(
        f"Failed to fetch ESPN feed after {FEED_RETRIES} attempts: {last_exc}"
    )


def get_rss_image(item: ET.Element) -> str:
    media_content = item.find("media:content", NS)

    if media_content is not None:
        url = clean_text(media_content.attrib.get("url"))

        if url:
            return url

    media_thumbnail = item.find("media:thumbnail", NS)

    if media_thumbnail is not None:
        url = clean_text(media_thumbnail.attrib.get("url"))

        if url:
            return url

    enclosure = item.find("enclosure")

    if enclosure is not None:
        url = clean_text(enclosure.attrib.get("url"))

        if url:
            return url

    return ""


def enrich_story(story: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch article page and extract og:image
    This fixes missing/wrong images.
    """

    link = story.get("link", "")

    if not link:
        return story

    try:
        article_url = (
            FEED_URL
            + "?url="
            + quote(link, safe="")
        )

        response = requests.get(
            article_url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        og_image = soup.find("meta", property="og:image")

        if og_image and og_image.get("content"):
            story["image"] = clean_text(
                og_image.get("content")
            )

    except Exception as exc:
        print(
            f"WARNING: image enrich failed for {link}: {exc}",
            file=sys.stderr,
        )

    return story


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)

    except ET.ParseError as exc:
        preview = xml_text[:300].replace("\n", " ")

        raise RuntimeError(
            f"Failed to parse feed XML: {exc}; body-start={preview!r}"
        ) from exc

    channel = root.find("channel")

    if channel is None:
        raise RuntimeError(
            "RSS feed parsed, but no <channel> element was found"
        )

    stories: list[dict[str, Any]] = []

    for item in channel.findall("item")[:MAX_ITEMS]:
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        pub_date = clean_text(item.findtext("pubDate"))

        description_html = item.findtext("description") or ""

        summary = strip_html(description_html)

        image = get_rss_image(item)

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
        raise RuntimeError(
            "RSS feed parsed, but no usable stories were found"
        )

    return stories


def to_iso(pub_date: str) -> str:
    if not pub_date:
        return ""

    try:
        return parsedate_to_datetime(pub_date).isoformat()

    except Exception:
        return pub_date


def build() -> dict[str, Any]:
    xml_text = fetch_feed_xml()

    stories = parse_feed(xml_text)

    # FIX IMAGE MISMATCHES
    stories = [enrich_story(s) for s in stories]

    return {
        "generatedAt": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        ),
        "stories": stories,
    }


def main() -> int:
    try:
        payload = build()

        os.makedirs(
            os.path.dirname(OUTPUT_PATH),
            exist_ok=True,
        )

        with open(
            OUTPUT_PATH,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                payload,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print(f"Wrote {OUTPUT_PATH}")

        return 0

    except Exception as exc:
        traceback.print_exc()

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
