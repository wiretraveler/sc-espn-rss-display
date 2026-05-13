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
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

FEED_URL = "https://www.espn.com/espn/rss/news"
MAX_ITEMS = 5
OUTPUT_PATH = "data/stories.json"
TIMEOUT = 20
FEED_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    )
}

NS = {
    "media": "http://search.yahoo.com/mrss/",
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "lxml")
    text = soup.get_text(" ", strip=True)
    return clean_text(text)


def absolutize(url: str, base: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        parts = urlparse(base)
        return f"{parts.scheme}://{parts.netloc}{url}"
    return url


def fetch_feed_xml() -> str:
    last_exc: Exception | None = None

    for attempt in range(1, FEED_RETRIES + 1):
        try:
            response = requests.get(FEED_URL, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            text = response.text.strip()
            head = text[:500].lower()

            if "xml" not in content_type and not text.startswith("<?xml") and "<rss" not in head:
                raise RuntimeError(
                    "Feed did not return RSS XML. "
                    f"status={response.status_code}, "
                    f"content-type={content_type}, "
                    f"body-start={text[:200]!r}"
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

    raise RuntimeError(f"Failed to fetch ESPN feed after {FEED_RETRIES} attempts: {last_exc}")


def get_rss_image(item: ET.Element, base_link: str) -> str:
    enclosure = item.find("enclosure")
    if enclosure is not None:
        url = enclosure.attrib.get("url", "")
        if url:
            return absolutize(clean_text(url), base_link)

    media_content = item.find("media:content", NS)
    if media_content is not None:
        url = media_content.attrib.get("url", "")
        if url:
            return absolutize(clean_text(url), base_link)

    media_thumbnail = item.find("media:thumbnail", NS)
    if media_thumbnail is not None:
        url = media_thumbnail.attrib.get("url", "")
        if url:
            return absolutize(clean_text(url), base_link)

    return ""


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        preview = xml_text[:300].replace("\n", " ")
        raise RuntimeError(f"Failed to parse feed XML: {exc}; body-start={preview!r}") from exc

    channel = root.find("channel")
    if channel is None:
        raise RuntimeError("RSS feed parsed, but no <channel> element was found")

    items: list[dict[str, Any]] = []

    for item in channel.findall("item")[:MAX_ITEMS]:
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        pub_date = clean_text(item.findtext("pubDate"))
        description_html = item.findtext("description") or ""
        description_text = strip_html(description_html)
        image = get_rss_image(item, link)

        items.append(
            {
                "title": title,
                "link": link,
                "pubDate": pub_date,
                "summary": description_text,
                "source": "ESPN",
                "image": image,
            }
        )

    if not items:
        raise RuntimeError("RSS feed parsed, but no <item> stories were found")

    return items


def extract_meta(
    soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None
) -> str:
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return clean_text(tag["content"])

    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return clean_text(tag["content"])

    return ""


def enrich_story(story: dict[str, Any]) -> dict[str, Any]:
    link = story.get("link", "")

    if not link:
        return story

    try:
        response = requests.get(link, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        page_image = (
            extract_meta(soup, prop="og:image")
            or extract_meta(soup, name="twitter:image")
        )

        page_summary = (
            extract_meta(soup, prop="og:description")
            or extract_meta(soup, name="description")
        )

        # Keep the RSS image if it exists. Only use the article page image as fallback.
        if not story.get("image") and page_image:
            story["image"] = absolutize(page_image, link)

        if page_summary:
            story["summary"] = clean_text(page_summary)

    except Exception as exc:
        print(f"WARNING: enrich failed for {link}: {exc}", file=sys.stderr)

    return story


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

    enriched: list[dict[str, Any]] = []

    for story in stories:
        enriched_story = enrich_story(story)
        enriched_story["pubDateIso"] = to_iso(enriched_story.get("pubDate", ""))
        enriched.append(enriched_story)
        time.sleep(0.6)

    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stories": enriched,
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
