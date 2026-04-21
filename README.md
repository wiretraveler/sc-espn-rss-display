# ESPN RSS Display

Simple static display for ESPN headlines with article images.

## Overview

* Pulls headlines from ESPN RSS
* Enriches each item by extracting metadata from the article page (`og:image`, summary)
* Outputs structured data to `data/stories.json`
* Frontend rotates through stories on a fixed interval

---

## Structure

```
.
├── index.html
├── data/stories.json
├── scripts/build_feed.py
└── .github/workflows/refresh-espn.yml
```

---

## How it works

* **GitHub Action** runs every 15 minutes
* Fetches RSS → scrapes article pages → writes JSON
* `index.html` loads that JSON and displays stories

---

## Config

```python
# scripts/build_feed.py
MAX_ITEMS = 5
```

```js
// index.html
const ROTATE_MS = 18000;
```

---

## Run manually

Actions → **Refresh ESPN feed** → Run workflow

---

## Notes

* Images come from article metadata (`og:image`), not RSS
* No fallback images used
* Fully static at runtime (GitHub Pages)
