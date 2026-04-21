# ESPN RSS Display

A lightweight web display that renders ESPN headlines with associated article images.

## Overview

This project pulls data from the ESPN RSS feed, enriches each item by extracting metadata from the linked article (including the primary image), and renders the results in a rotating display.

It is designed to run entirely from a static host (e.g., GitHub Pages) with a scheduled GitHub Actions workflow acting as the data pipeline.

---

## Architecture

**Data pipeline (GitHub Actions):**

* Fetch ESPN RSS feed
* Parse feed items
* Request each article page
* Extract:

  * title
  * summary
  * publish time
  * `og:image`
* Output JSON to:

```text
data/stories.json
```

**Frontend (static):**

* `index.html` loads `data/stories.json`
* Displays one story at a time
* Rotates through stories on a fixed interval

---

## Project Structure

```text
.
├── index.html
├── data/
│   └── stories.json
├── scripts/
│   └── build_feed.py
└── .github/
    └── workflows/
        └── refresh-espn.yml
```

---

## Configuration

### Number of stories

```python
# scripts/build_feed.py
MAX_ITEMS = 5
```

### Rotation interval

```js
// index.html
const ROTATE_MS = 18000;
```

---

## Workflow

The GitHub Actions workflow (`Refresh ESPN feed`) runs on a schedule and can also be triggered manually.

To run manually:

1. Open the **Actions** tab
2. Select **Refresh ESPN feed**
3. Click **Run workflow**

---

## Deployment

This project is intended to be deployed via GitHub Pages.

The frontend reads from the generated `data/stories.json` file and requires no backend at runtime.

---

## Notes

* Images are extracted from article pages (`og:image`), not from the RSS feed
* Stories without valid metadata may have limited content
* The data file is regenerated periodically and committed to the repository

---

## License

No license specified.
