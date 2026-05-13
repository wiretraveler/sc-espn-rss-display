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
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

FEED_URL = "https://site.api.espn.com/apis/site/v2/sports"
MAX_ITEMS = 5
OUTPUT_PATH = "data/stories.json"
TIMEOUT = 20
FEED_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
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


def fetch_feed_json() -> dict[str, Any]:
    last_exc: Exception | None = None

    for attempt in range(1, FEED_RETRIES + 1):
        try:
            response = requests.get(FEED_URL, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            text = response.text.strip()

            if "json" not in content_type and not text.startswith("{"):
                raise RuntimeError(
                    "ESPN API did not return JSON. "
                    f"status={response.status_code}, "
                    f"content-type={content_type}, "
                    f"body-start={text[:200]!r}"
                )

            data = response.json()

            if "articles" not in data:
                raise RuntimeError(
                    "ESPN API response missing 'articles'. "
                    f"keys={list(data.keys())}"
                )

            return data

        except Exception as exc:
            last_exc = exc
            print(
                f"WARNING: API fetch attempt {attempt}/{FEED_RETRIES} failed: {exc}",
                file=sys.stderr,
            )
            if attempt < FEED_RETRIES:
                time.sleep(2 * attempt)

    raise RuntimeError(f"Failed to fetch ESPN API after {FEED_RETRIES} attempts: {last_exc}")


def get_article_link(article: dict[str, Any]) -> str:
    links = article.get("links") or {}
    web = links.get("web") or {}
    return clean_text(web.get("href") or "")


def get_article_image(article: dict[str, Any]) -> str:
    images = article.get("images") or []

    if not images:
        return ""

    # Prefer the widest image if dimensions are available.
    best = None
    best_width = -1

    for image in images:
        if not isinstance(image, dict):
            continue

        url = clean_text(image.get("url") or "")
        if not url:
            continue

        width = image.get("width") or 0
        try:
            width = int(width)
        except Exception:
            width = 0

        if width > best_width:
            best = url
            best_width = width

    return best or ""


def parse_feed(data: dict[str, Any]) -> list[dict[str, Any]]:
    articles = data.get("articles") or []

    if not articles:
        raise RuntimeError("No articles found in ESPN API response")

    stories: list[dict[str, Any]] = []

    for article in articles[:MAX_ITEMS]:
        if not isinstance(article, dict):
            continue

        title = clean_text(
            article.get("headline")
            or article.get("title")
            or article.get("shortLinkText")
            or ""
        )

        link = get_article_link(article)

        summary = clean_text(
            article.get("description")
            or article.get("summary")
            or strip_html(article.get("story") or "")
            or ""
        )

        image = get_article_image(article)

        pub_date = clean_text(
            article.get("published")
            or article.get("lastModified")
            or article.get("now")
            or ""
        )

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
            }
        )

    if not stories:
        raise RuntimeError("ESPN API returned articles, but none had title/link")

    return stories


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

        # Keep the API image if it exists. Only use article-page image as fallback.
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
        pass

    try:
        return pub_date.replace("Z", "+00:00")
    except Exception:
        return pub_date


def build() -> dict[str, Any]:
    data = fetch_feed_json()
    stories = parse_feed(data)

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
