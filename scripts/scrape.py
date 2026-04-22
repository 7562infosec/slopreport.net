#!/usr/bin/env python3
"""
The Slop Report — Daily RSS Scraper
Fetches AI slop news from 12 sources, filters by keyword,
and generates a Jekyll post in _posts/.

Usage:
    python3 scripts/scrape.py

The script assumes it is run from the repository root.
"""

import os
import sys
import re
import time
import textwrap
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests
from dateutil import parser as dateutil_parser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KEYWORDS = [
    "ai slop",
    "ai-generated",
    "ai generated",
    "artificial intelligence content",
    "llm",
    "generative ai",
    "synthetic content",
    "ai spam",
    "ai content farm",
    "content farm",
    "machine-generated",
    "chatgpt",
    "gpt-4",
    "claude",
    "gemini",
    "deepfake",
    "synthetic media",
    "automated content",
    "ai writing",
    "ai text",
    "large language model",
    "foundation model",
]

RSS_SOURCES = [
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    },
    {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
    },
    {
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
    },
    {
        "name": "404 Media",
        "url": "https://www.404media.co/rss/",
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "name": "Futurism",
        "url": "https://futurism.com/feed",
    },
    {
        "name": "The Guardian Tech",
        "url": "https://www.theguardian.com/technology/rss",
    },
    {
        "name": "NY Times Tech",
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    },
    {
        "name": "Reuters Tech",
        "url": "https://feeds.reuters.com/reuters/technologyNews",
    },
]

HACKER_NEWS_SOURCE = {
    "name": "Hacker News",
    "api_url": "https://hn.algolia.com/api/v1/search_by_date",
    "queries": ["AI slop", "generative AI", "LLM content"],
}

# How many hours back to look for stories
LOOKBACK_HOURS = 36

# Target number of stories for the post (will use up to this many)
MAX_STORIES = 12
MIN_STORIES = 3

# Request timeout in seconds
REQUEST_TIMEOUT = 15

# Delay between feed fetches (be polite)
FETCH_DELAY = 0.5

# Output directory (relative to repo root)
POSTS_DIR = Path("_posts")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("slop-report")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def matches_keywords(text: str) -> bool:
    """Return True if any keyword appears in text (case-insensitive)."""
    lower = text.lower()
    return any(kw in lower for kw in KEYWORDS)


def parse_date(entry) -> datetime | None:
    """Extract a timezone-aware datetime from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    # Fallback: try string fields
    for attr in ("published", "updated", "created"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return dateutil_parser.parse(val).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def fetch_feed(source: dict) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of story dicts."""
    url = source["url"]
    name = source["name"]
    stories = []

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; SlopReport/1.0; +https://slopreport.net)"
        }
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        log.warning(f"[{name}] Failed to fetch feed: {exc}")
        return stories

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    for entry in feed.entries:
        title = strip_html(getattr(entry, "title", ""))
        summary = strip_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        link = getattr(entry, "link", "")

        if not title or not link:
            continue

        # Date filter
        pub_date = parse_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        # Keyword filter
        searchable = f"{title} {summary}"
        if not matches_keywords(searchable):
            continue

        stories.append(
            {
                "title": title,
                "summary": summary[:400] if summary else "",
                "link": link,
                "source": name,
                "date": pub_date,
            }
        )

    log.info(f"[{name}] {len(stories)} matching stories from {len(feed.entries)} entries")
    return stories


def fetch_hacker_news() -> list[dict]:
    """Fetch relevant Hacker News stories via Algolia API."""
    stories = []
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp())

    for query in HACKER_NEWS_SOURCE["queries"]:
        params = {
            "tags": "story",
            "query": query,
            "numericFilters": f"created_at_i>{cutoff_ts}",
            "hitsPerPage": 20,
        }
        try:
            resp = requests.get(
                HACKER_NEWS_SOURCE["api_url"],
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning(f"[Hacker News] API error for query '{query}': {exc}")
            continue

        for hit in data.get("hits", []):
            title = hit.get("title", "")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            created_ts = hit.get("created_at_i")
            pub_date = (
                datetime.fromtimestamp(created_ts, tz=timezone.utc) if created_ts else None
            )
            points = hit.get("points", 0) or 0

            # Require at least 10 points to reduce noise
            if points < 10:
                continue

            if not title or not matches_keywords(title):
                continue

            stories.append(
                {
                    "title": title,
                    "summary": f"{points} points on Hacker News",
                    "link": url,
                    "source": "Hacker News",
                    "date": pub_date,
                }
            )

    # Deduplicate by link
    seen = set()
    unique = []
    for s in stories:
        if s["link"] not in seen:
            seen.add(s["link"])
            unique.append(s)

    log.info(f"[Hacker News] {len(unique)} matching stories")
    return unique


def deduplicate(stories: list[dict]) -> list[dict]:
    """Remove near-duplicate stories by normalizing titles."""
    seen_titles = set()
    seen_links = set()
    result = []

    for s in stories:
        norm_title = re.sub(r"\W+", " ", s["title"].lower()).strip()
        if norm_title in seen_titles or s["link"] in seen_links:
            continue
        seen_titles.add(norm_title)
        seen_links.add(s["link"])
        result.append(s)

    return result


def score_story(story: dict) -> float:
    """Score a story for ranking — higher = more relevant."""
    score = 0.0
    text = f"{story['title']} {story['summary']}".lower()

    # Direct slop keywords score higher
    high_value = ["ai slop", "ai spam", "content farm", "synthetic content", "ai-generated"]
    score += sum(3.0 for kw in high_value if kw in text)

    # General AI keywords
    general = ["llm", "generative ai", "chatgpt", "deepfake", "automated content"]
    score += sum(1.0 for kw in general if kw in text)

    # Prefer stories with a summary
    if story["summary"]:
        score += 1.0

    # Prefer recent stories
    if story["date"]:
        age_hours = (datetime.now(timezone.utc) - story["date"]).total_seconds() / 3600
        score += max(0, (LOOKBACK_HOURS - age_hours) / LOOKBACK_HOURS) * 2.0

    return score


def format_story_block(idx: int, story: dict) -> str:
    """Format a single story as a Markdown block."""
    title = story["title"]
    source = story["source"]
    link = story["link"]
    summary = story["summary"]

    block = f"### {idx}. [{title}]({link})\n"
    block += f"*{source}*\n\n"

    if summary:
        # Wrap summary for readability
        wrapped = textwrap.fill(summary, width=100)
        block += f"{wrapped}\n"

    return block


def generate_post(stories: list[dict], today: datetime) -> str:
    """Generate a complete Jekyll post as a string."""
    date_str = today.strftime("%B %-d, %Y")
    date_iso = today.strftime("%Y-%m-%d")

    header = f"""---
layout: post
title: "The Slop Report — {date_str}"
date: {date_iso}
categories: daily-roundup
---

Good morning. Here's today's digest of AI-generated content news from around the web.

---

"""

    story_blocks = []
    for i, story in enumerate(stories, start=1):
        story_blocks.append(format_story_block(i, story))

    footer = (
        "\n---\n\n"
        f"*{len(stories)} stories sourced from "
        f"{', '.join(sorted(set(s['source'] for s in stories)))}. "
        "The Slop Report is published daily. "
        "[Subscribe via RSS](/feed.xml).*\n"
    )

    return header + "\n---\n\n".join(story_blocks) + footer


def write_post(content: str, today: datetime) -> Path:
    """Write the Jekyll post file and return its path."""
    POSTS_DIR.mkdir(exist_ok=True)
    filename = today.strftime("%Y-%m-%d") + "-slop-report.md"
    post_path = POSTS_DIR / filename

    with open(post_path, "w", encoding="utf-8") as f:
        f.write(content)

    return post_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    today = datetime.now(timezone.utc)
    log.info(f"Slop Report scraper starting — {today.strftime('%Y-%m-%d %H:%M UTC')}")

    all_stories: list[dict] = []

    # Fetch RSS feeds
    for source in RSS_SOURCES:
        stories = fetch_feed(source)
        all_stories.extend(stories)
        time.sleep(FETCH_DELAY)

    # Fetch Hacker News
    hn_stories = fetch_hacker_news()
    all_stories.extend(hn_stories)

    log.info(f"Total raw stories before dedup: {len(all_stories)}")

    # Deduplicate
    all_stories = deduplicate(all_stories)
    log.info(f"Stories after deduplication: {len(all_stories)}")

    if len(all_stories) < MIN_STORIES:
        log.warning(
            f"Only {len(all_stories)} stories found (minimum {MIN_STORIES}). "
            "The post will still be written but may be sparse."
        )

    # Score and sort
    all_stories.sort(key=score_story, reverse=True)

    # Take top N
    selected = all_stories[:MAX_STORIES]
    log.info(f"Selected {len(selected)} stories for today's post")

    if not selected:
        log.error("No stories found — skipping post generation.")
        sys.exit(1)

    # Generate post
    post_content = generate_post(selected, today)

    # Write post
    post_path = write_post(post_content, today)
    log.info(f"Post written to: {post_path}")

    # Print summary
    print(f"\n✓ Generated: {post_path}")
    print(f"  Stories: {len(selected)}")
    print(f"  Sources: {', '.join(sorted(set(s['source'] for s in selected)))}")


if __name__ == "__main__":
    main()
