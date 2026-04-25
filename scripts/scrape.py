#!/usr/bin/env python3
"""
The Slop Report — Daily RSS Scraper
Fetches AI slop news from 30+ sources, filters by keyword, and generates a Jekyll post.
Usage: python3 scripts/scrape.py
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
    # Core AI slop terms
    "ai slop", "ai-slop", "slop",

    # AI-generated content quality issues
    "content farm", "content mill", "made for advertising", "mfa site",
    "clickbait farm", "ai spam", "ai garbage", "low quality content",
    "junk content", "fake content",

    # Automated / synthetic content
    "automated journalism", "robo-journalism",
    "machine-generated content", "synthetic content", "synthetic media",
    "ai-generated content", "artificially generated",

    # Deepfakes and identity fraud
    "deepfake", "deep fake", "voice clone", "voice cloning",
    "synthetic identity", "face swap", "ai impersonation",
    "non-consensual deepfake", "non-consensual synthetic",
    "ai nude", "ai porn",

    # Search / SEO spam
    "seo spam", "ai seo", "search spam", "search manipulation",
    "google spam update", "helpful content update",

    # Platform responses to AI content
    "ai detection", "ai watermark", "content authenticity", "c2pa",
    "content provenance", "ai-generated label", "ai disclosure",

    # Specific AI misuse legislation
    "eu ai act", "take it down act", "no fakes act", "ai copyright",
    "ai liability", "ai fraud",

    # Journalism quality (AI replacing reporters badly)
    "ai newsroom", "ai byline", "ai publisher", "news bot", "ai reporter",
    "ai journalism", "ai-written",

    # Ad fraud and bot traffic
    "ad fraud", "programmatic fraud", "bot traffic", "bot account",
    "social media bot", "llm bot", "fake engagement",

    # Misinformation — compound terms only (not standalone)
    "information pollution", "disinformation campaign",
    "misinformation campaign", "ai misinformation", "ai disinformation",
    "ai propaganda", "influence operation",

    # Kids / vulnerable audiences
    "youtube kids", "children's content", "kids content",
    "made for kids", "child safety",
]

RSS_SOURCES = [
    # --- Core AI / Tech News ---
    {"name": "The Verge AI",       "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"name": "The Verge Tech",     "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "Ars Technica",       "url": "https://feeds.arstechnica.com/arstechnica/technology-lab"},
    {"name": "Wired AI",           "url": "https://www.wired.com/feed/tag/ai/latest/rss"},
    {"name": "Wired",              "url": "https://www.wired.com/feed/rss"},
    {"name": "MIT Technology Review","url": "https://www.technologyreview.com/feed/"},
    {"name": "VentureBeat AI",     "url": "https://venturebeat.com/category/ai/feed/"},
    {"name": "TechCrunch AI",      "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "TechCrunch",         "url": "https://techcrunch.com/feed/"},
    {"name": "404 Media",          "url": "https://www.404media.co/rss/"},
    {"name": "Futurism",           "url": "https://futurism.com/feed"},
    {"name": "The Register",       "url": "https://www.theregister.com/headlines.atom"},
    {"name": "Engadget",           "url": "https://www.engadget.com/rss.xml"},
    {"name": "Gizmodo",            "url": "https://gizmodo.com/rss"},
    {"name": "The Next Web",       "url": "https://thenextweb.com/feed/"},
    {"name": "Digital Trends",     "url": "https://www.digitaltrends.com/feed/"},
    # --- Mainstream Tech Coverage ---
    {"name": "The Guardian Tech",  "url": "https://www.theguardian.com/technology/rss"},
    {"name": "NY Times Tech",      "url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"},
    {"name": "Reuters Tech",       "url": "https://feeds.reuters.com/reuters/technologyNews"},
    {"name": "BBC Technology",     "url": "https://feeds.bbci.co.uk/news/technology/rss.xml"},
    {"name": "NPR Technology",     "url": "https://feeds.npr.org/1019/rss.xml"},
    {"name": "Fast Company Tech",  "url": "https://www.fastcompany.com/technology/rss"},
    {"name": "Forbes AI",          "url": "https://www.forbes.com/innovation/ai/feed2/"},
    {"name": "Axios",              "url": "https://api.axios.com/feed/top"},
    # --- Media / Journalism ---
    {"name": "Nieman Lab",         "url": "https://www.niemanlab.org/feed/"},
    {"name": "Poynter",            "url": "https://www.poynter.org/feed/"},
    {"name": "Columbia Journalism Review", "url": "https://www.cjr.org/feed/"},
    {"name": "Reuters Institute",  "url": "https://reutersinstitute.politics.ox.ac.uk/rss.xml"},
    # --- Advertising / Marketing ---
    {"name": "Adweek",             "url": "https://www.adweek.com/feed/"},
    {"name": "Digiday",            "url": "https://digiday.com/feed/"},
    {"name": "Search Engine Land", "url": "https://searchengineland.com/feed"},
    {"name": "Search Engine Journal","url": "https://www.searchenginejournal.com/feed/"},
    # --- Security (for deepfake / fraud / misuse angle) ---
    {"name": "Krebs on Security",  "url": "https://krebsonsecurity.com/feed/"},
    {"name": "Dark Reading",       "url": "https://www.darkreading.com/rss.xml"},
    # --- Science / Research ---
    {"name": "IEEE Spectrum",      "url": "https://spectrum.ieee.org/feeds/feed.rss"},
    {"name": "Science Daily AI",   "url": "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml"},
    # --- Slashdot (broad tech community) ---
    {"name": "Slashdot",           "url": "http://rss.slashdot.org/Slashdot/slashdotMain"},
]

HACKER_NEWS_SOURCE = {
    "name": "Hacker News",
    "api_url": "https://hn.algolia.com/api/v1/search_by_date",
    "queries": [
        "AI slop", "generative AI content", "LLM content farm",
        "AI spam", "deepfake", "AI moderation", "AI copyright",
        "synthetic content", "AI regulation",
    ],
}

# How many hours back to look for stories
LOOKBACK_HOURS = 36
# Target number of stories for the post
MAX_STORIES = 25
MIN_STORIES = 3
# Request timeout in seconds
REQUEST_TIMEOUT = 15
# Delay between feed fetches (be polite)
FETCH_DELAY = 0.3
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
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def matches_keywords(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in KEYWORDS)


def parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated", "created"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return dateutil_parser.parse(val).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def fetch_feed(source: dict) -> list[dict]:
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
        summary = strip_html(
            getattr(entry, "summary", "") or getattr(entry, "description", "")
        )
        link = getattr(entry, "link", "")
        if not title or not link:
            continue
        pub_date = parse_date(entry)
        if pub_date and pub_date < cutoff:
            continue
        searchable = f"{title} {summary}"
        if not matches_keywords(searchable):
            continue
        stories.append({
            "title": title,
            "summary": summary[:500] if summary else "",
            "link": link,
            "source": name,
            "date": pub_date,
        })

    log.info(f"[{name}] {len(stories)} matching stories from {len(feed.entries)} entries")
    return stories


def fetch_hacker_news() -> list[dict]:
    stories = []
    cutoff_ts = int(
        (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp()
    )
    seen_links = set()
    for query in HACKER_NEWS_SOURCE["queries"]:
        params = {
            "tags": "story",
            "query": query,
            "numericFilters": f"created_at_i>{cutoff_ts}",
            "hitsPerPage": 20,
        }
        try:
            resp = requests.get(
                HACKER_NEWS_SOURCE["api_url"], params=params, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning(f"[Hacker News] API error for query '{query}': {exc}")
            continue

        for hit in data.get("hits", []):
            title = hit.get("title", "")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
            if url in seen_links:
                continue
            seen_links.add(url)
            created_ts = hit.get("created_at_i")
            pub_date = (
                datetime.fromtimestamp(created_ts, tz=timezone.utc) if created_ts else None
            )
            points = hit.get("points", 0) or 0
            if points < 10:
                continue
            if not title or not matches_keywords(title):
                continue
            stories.append({
                "title": title,
                "summary": f"{points} points on Hacker News",
                "link": url,
                "source": "Hacker News",
                "date": pub_date,
            })

    log.info(f"[Hacker News] {len(stories)} matching stories")
    return stories


def deduplicate(stories: list[dict]) -> list[dict]:
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
    score = 0.0
    text = f"{story['title']} {story['summary']}".lower()
    high_value = [
        "ai slop", "ai spam", "content farm", "synthetic content",
        "ai-generated content", "deepfake", "deep fake",
        "ai misinformation", "ai disinformation", "voice clone",
        "ad fraud", "seo spam", "made for advertising",
        "content mill", "ai impersonation", "influence operation",
        "ai watermark", "c2pa", "non-consensual deepfake",
        "ai byline", "ai newsroom", "information pollution",
    ]
    score += sum(3.0 for kw in high_value if kw in text)
    general = [
        "content authenticity", "ai detection", "eu ai act",
        "take it down act", "no fakes act", "ai copyright",
        "bot traffic", "programmatic fraud", "ai disclosure",
        "robo-journalism", "automated journalism",
    ]
    score += sum(1.0 for kw in general if kw in text)
    if story["summary"]:
        score += 1.0
    if story["date"]:
        age_hours = (datetime.now(timezone.utc) - story["date"]).total_seconds() / 3600
        score += max(0, (LOOKBACK_HOURS - age_hours) / LOOKBACK_HOURS) * 2.0
    return score


def format_story_block(idx: int, story: dict) -> str:
    title = story["title"]
    source = story["source"]
    link = story["link"]
    summary = story["summary"]
    date_str = story["date"].strftime("%b %-d") if story["date"] else ""
    block = f"### {idx}. [{title}]({link})\n"
    block += f"*{source}*"
    if date_str:
        block += f" · {date_str}"
    block += "\n\n"
    if summary:
        wrapped = textwrap.fill(summary, width=100)
        block += f"{wrapped}\n"
    return block


def generate_post(stories: list[dict], today: datetime) -> str:
    date_str = today.strftime("%B %-d, %Y")
    date_iso = today.strftime("%Y-%m-%d")
    sources_list = sorted(set(s["source"] for s in stories))
    header = f"""---
layout: post
title: "The Slop Report — {date_str}"
date: {date_iso}
categories: daily-roundup
---

*Your daily digest of AI-generated content news from around the web. All signal, no slop.*

---

"""
    story_blocks = []
    for i, story in enumerate(stories, start=1):
        story_blocks.append(format_story_block(i, story))

    footer = (
        "\n---\n\n"
        f"*{len(stories)} stories sourced from "
        f"{', '.join(sources_list)}. "
        "The Slop Report is published daily. "
        "[Subscribe via RSS](/feed.xml).*\n"
    )
    return header + "\n---\n\n".join(story_blocks) + footer


def write_post(content: str, today: datetime) -> Path:
    POSTS_DIR.mkdir(exist_ok=True)
    filename = today.strftime("%Y-%m-%d") + "-slop-report.md"
    post_path = POSTS_DIR / filename
    with open(post_path, "w", encoding="utf-8") as f:
        f.write(content)
    return post_path


def main():
    today = datetime.now(timezone.utc)
    log.info(f"Slop Report scraper starting — {today.strftime('%Y-%m-%d %H:%M UTC')}")

    all_stories: list[dict] = []

    for source in RSS_SOURCES:
        stories = fetch_feed(source)
        all_stories.extend(stories)
        time.sleep(FETCH_DELAY)

    hn_stories = fetch_hacker_news()
    all_stories.extend(hn_stories)

    log.info(f"Total raw stories before dedup: {len(all_stories)}")
    all_stories = deduplicate(all_stories)
    log.info(f"Stories after deduplication: {len(all_stories)}")

    if len(all_stories) < MIN_STORIES:
        log.warning(
            f"Only {len(all_stories)} stories found (minimum {MIN_STORIES}). "
            "Post will still be written but may be sparse."
        )

    all_stories.sort(key=score_story, reverse=True)
    selected = all_stories[:MAX_STORIES]
    log.info(f"Selected {len(selected)} stories for today's post")

    if not selected:
        log.error("No stories found — skipping post generation.")
        sys.exit(1)

    post_content = generate_post(selected, today)
    post_path = write_post(post_content, today)
    log.info(f"Post written to: {post_path}")

    print(f"\n✓ Generated: {post_path}")
    print(f"  Stories:  {len(selected)}")
    print(f"  Sources:  {', '.join(sorted(set(s['source'] for s in selected)))}")


if __name__ == "__main__":
    main()
