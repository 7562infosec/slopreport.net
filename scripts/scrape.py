#!/usr/bin/env python3
"""
The Slop Report — Daily RSS Scraper
Fetches AI slop news from 30+ sources, filters by keyword, and generates a Jekyll post.
Usage: python3 scripts/scrape.py
"""

import json
import os
import sys
import re
import time
import textwrap
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic
import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KEYWORDS = [
    # Core AI slop terms
    "ai slop", "ai-slop",

    # AI-generated content — broad but relevant
    "ai-generated", "ai generated",
    "generative ai",
    "synthetic content", "synthetic media", "synthetic video",
    "machine-generated content",
    "artificially generated",

    # Content quality / spam
    "content farm", "content mill", "made for advertising", "mfa site",
    "clickbait farm", "ai spam", "ai garbage", "low quality content",
    "junk content", "fake content",

    # Automated journalism
    "automated journalism", "robo-journalism",
    "ai newsroom", "ai byline", "ai publisher", "news bot", "ai reporter",
    "ai journalism", "ai-written",

    # Deepfakes and identity fraud
    "deepfake", "deep fake", "voice clone", "voice cloning",
    "synthetic identity", "face swap", "ai impersonation",
    "non-consensual deepfake", "non-consensual synthetic",
    "ai nude", "ai porn",

    # Search / SEO spam
    "seo spam", "ai seo", "search spam", "search manipulation",
    "google spam update", "helpful content update",

    # Platform responses
    "ai detection", "ai watermark", "content authenticity", "c2pa",
    "content provenance", "ai disclosure",

    # Misinformation / disinfo (standalone terms, word-boundary matched)
    "disinformation", "misinformation", "fake news",
    "information pollution", "influence operation",
    "ai misinformation", "ai disinformation", "ai propaganda",

    # Ad fraud and bot traffic
    "ad fraud", "programmatic fraud", "bot traffic", "bot account",
    "social media bot", "llm bot", "fake engagement",

    # Regulation (specific to AI misuse/safety)
    "eu ai act", "take it down act", "no fakes act",
    "ai copyright", "ai liability", "ai fraud",

    # Kids / vulnerable audiences
    "youtube kids", "children's content", "kids content",
    "made for kids", "child safety",
]

RSS_SOURCES = [
    # --- AI / Tech Beat ---
    {"name": "Wired AI",           "url": "https://www.wired.com/feed/category/artificial-intelligence/latest/rss"},
    {"name": "Ars Technica",       "url": "https://feeds.arstechnica.com/arstechnica/index"},
    {"name": "Slashdot",           "url": "https://rss.slashdot.org/Slashdot/slashdotMain"},
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
    {"name": "Axios",              "url": "https://api.axios.com/feed/"},
    # --- Policy / Research ---
    {"name": "Lawfare",            "url": "https://www.lawfaremedia.org/feed"},
    {"name": "Brookings Tech",     "url": "https://www.brookings.edu/topic/technology-innovation/feed/"},
    {"name": "EFF Deeplinks",      "url": "https://www.eff.org/rss/updates.xml"},
    {"name": "Access Now",         "url": "https://www.accessnow.org/feed/"},
    # --- SEO / Marketing Trades ---
    {"name": "Search Engine Journal","url": "https://www.searchenginejournal.com/feed/"},
    {"name": "Search Engine Land", "url": "https://searchengineland.com/feed"},
    {"name": "MarTech",            "url": "https://martech.org/feed/"},
    # --- Media / Journalism ---
    {"name": "Nieman Lab",         "url": "https://www.niemanlab.org/feed/"},
    {"name": "Columbia Journalism Review","url": "https://www.cjr.org/feed"},
    {"name": "Poynter",            "url": "https://www.poynter.org/feed/"},
    # --- Disinformation / Platform Safety ---
    {"name": "First Draft",        "url": "https://firstdraftnews.org/feed/"},
    {"name": "Bellingcat",         "url": "https://www.bellingcat.com/feed/"},
    {"name": "Stanford Internet Observatory","url": "https://cyber.fsi.stanford.edu/io/rss.xml"},
]

HACKER_NEWS_SOURCE = {
    "name": "Hacker News",
    "api_url": "https://hn.algolia.com/api/v1/search",
    "queries": [
        "ai slop", "deepfake", "synthetic content", "content farm",
        "ai generated content", "ai misinformation",
    ],
}

LOOKBACK_HOURS = 36
MAX_STORIES = 25
MIN_STORIES = 3
REQUEST_TIMEOUT = 15
FETCH_DELAY = 0.3
POSTS_DIR = Path("_posts")
SEEN_URLS_FILE = Path(__file__).parent / "seen_urls.json"
SEEN_URLS_MAX_AGE_DAYS = 30

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
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                import calendar
                ts = calendar.timegm(val)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return dateutil_parser.parse(val).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def matches_keywords(text: str) -> bool:
    lower = text.lower()
    for kw in KEYWORDS:
        # Use word-boundary match for short single-word terms to avoid substrings
        if " " in kw or "-" in kw:
            if kw in lower:
                return True
        else:
            if re.search(r'\b' + re.escape(kw) + r'\b', lower):
                return True
    return False

# ---------------------------------------------------------------------------
# Cross-day deduplication
# ---------------------------------------------------------------------------

def load_seen_urls() -> dict:
    """Load the cross-day URL cache. Returns {url: 'YYYY-MM-DD'}."""
    if SEEN_URLS_FILE.exists():
        try:
            with open(SEEN_URLS_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_seen_urls(seen: dict) -> None:
    """Save the cross-day URL cache, pruning entries older than SEEN_URLS_MAX_AGE_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_URLS_MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    pruned = {url: date for url, date in seen.items() if date >= cutoff}
    with open(SEEN_URLS_FILE, "w") as f:
        json.dump(pruned, f, indent=2, sort_keys=True)
    log.info(f"Saved cross-day URL cache: {len(pruned)} entries")


def cross_day_deduplicate(stories: list[dict], seen_urls: dict) -> list[dict]:
    """Remove stories whose URLs appeared in a previous day's report."""
    fresh = [s for s in stories if s["link"] not in seen_urls]
    removed = len(stories) - len(fresh)
    if removed:
        log.info(f"Cross-day dedup removed {removed} previously-seen stories")
    return fresh

# ---------------------------------------------------------------------------
# AI summary
# ---------------------------------------------------------------------------

def get_ai_summary(url: str, fallback: str) -> str:
    """Fetch article text and summarize with Claude Haiku. Falls back to RSS description."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback[:300] if fallback else ""

    # Try to fetch the full article text
    article_text = fallback or ""
    try:
        resp = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SlopReport/1.0)"
        })
        if resp.ok:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            article_text = soup.get_text(separator=" ", strip=True)[:4000]
    except Exception as e:
        log.debug(f"Article fetch failed for {url}: {e}")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    "In 1-2 sentences, summarize the AI content/synthetic media/deepfake angle of this article. "
                    "Be specific and factual. Do not start with 'This article'.\n\n"
                    f"{article_text}"
                )
            }]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.warning(f"Claude summary failed for {url}: {e}")
        return fallback[:300] if fallback else ""

# ---------------------------------------------------------------------------
# Feed fetching
# ---------------------------------------------------------------------------

def fetch_feed(source: dict) -> list[dict]:
    name = source["name"]
    url = source["url"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    stories = []
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "SlopReport/1.0"})
    except Exception as e:
        log.warning(f"[{name}] Feed parse error: {e}")
        return []

    for entry in feed.entries:
        title = strip_html(getattr(entry, "title", "")).strip()
        summary = strip_html(
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
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
                HACKER_NEWS_SOURCE["api_url"],
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception as e:
            log.warning(f"[HN] API error for query '{query}': {e}")
            continue

        for hit in hits:
            title = (hit.get("title") or "").strip()
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
            if not title or url in seen_links:
                continue
            searchable = f"{title} {hit.get('story_text','')}"
            if not matches_keywords(searchable):
                continue
            seen_links.add(url)
            ts = hit.get("created_at_i")
            pub_date = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
            stories.append({
                "title": title,
                "summary": (hit.get("story_text") or "")[:500],
                "link": url,
                "source": HACKER_NEWS_SOURCE["name"],
                "date": pub_date,
            })

    log.info(f"[HN] {len(stories)} matching stories")
    return stories


def deduplicate(stories: list[dict]) -> list[dict]:
    """Remove same-run duplicates by normalized title and URL."""
    seen_titles: set[str] = set()
    seen_links: set[str] = set()
    result = []
    for s in stories:
        norm_title = re.sub(r"[^a-z0-9]", "", s["title"].lower())
        if norm_title in seen_titles or s["link"] in seen_links:
            continue
        seen_titles.add(norm_title)
        seen_links.add(s["link"])
        result.append(s)
    return result

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_story(story: dict) -> float:
    score = 0.0
    title = story["title"].lower()
    desc = story["summary"].lower()

    high_value = [
        "ai slop", "ai spam", "content farm", "synthetic content",
        "ai-generated content", "deepfake", "deep fake",
        "ai misinformation", "ai disinformation", "voice clone",
        "ad fraud", "seo spam", "made for advertising",
        "content mill", "ai impersonation", "influence operation",
        "ai watermark", "c2pa", "non-consensual deepfake",
        "ai byline", "ai newsroom", "information pollution",
    ]
    # Title match is worth more than description match
    score += sum(5.0 for kw in high_value if kw in title)
    score += sum(3.0 for kw in high_value if kw in desc)

    general = [
        "content authenticity", "ai detection", "eu ai act",
        "take it down act", "no fakes act", "ai copyright",
        "bot traffic", "programmatic fraud", "ai disclosure",
        "robo-journalism", "automated journalism",
    ]
    score += sum(3.0 for kw in general if kw in title)
    score += sum(1.0 for kw in general if kw in desc)

    # Recency bonus
    if story.get("date"):
        age_hours = (datetime.now(timezone.utc) - story["date"]).total_seconds() / 3600
        score += max(0, (LOOKBACK_HOURS - age_hours) / LOOKBACK_HOURS) * 2.0
    return score

# ---------------------------------------------------------------------------
# Post generation
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    today = datetime.now(timezone.utc)
    log.info(f"Slop Report scraper starting — {today.strftime('%Y-%m-%d %H:%M UTC')}")

    # Load cross-day URL cache for deduplication
    seen_urls = load_seen_urls()
    log.info(f"Cross-day cache loaded: {len(seen_urls)} URLs from previous reports")

    all_stories: list[dict] = []

    for source in RSS_SOURCES:
        stories = fetch_feed(source)
        all_stories.extend(stories)
        time.sleep(FETCH_DELAY)

    hn_stories = fetch_hacker_news()
    all_stories.extend(hn_stories)

    log.info(f"Total raw stories before dedup: {len(all_stories)}")
    all_stories = deduplicate(all_stories)
    log.info(f"Stories after same-day dedup: {len(all_stories)}")

    all_stories = cross_day_deduplicate(all_stories, seen_urls)
    log.info(f"Stories after cross-day dedup: {len(all_stories)}")

    if len(all_stories) < MIN_STORIES:
        log.warning(
            f"Only {len(all_stories)} stories found (minimum {MIN_STORIES}). "
            "Skipping post generation."
        )
        sys.exit(1)

    all_stories.sort(key=score_story, reverse=True)
    selected = all_stories[:MAX_STORIES]

    # Generate AI summaries for selected stories
    log.info(f"Generating AI summaries for {len(selected)} stories...")
    for story in selected:
        story["summary"] = get_ai_summary(story["link"], story["summary"])
        time.sleep(0.3)  # gentle rate limiting

    post_content = generate_post(selected, today)
    post_path = write_post(post_content, today)
    log.info(f"Post written to: {post_path}")

    # Update cross-day URL cache with today's published stories
    today_str = today.strftime("%Y-%m-%d")
    for story in selected:
        seen_urls[story["link"]] = today_str
    save_seen_urls(seen_urls)

    print(f"\n✓ Generated: {post_path}")
    print(f"  Stories:  {len(selected)}")
    print(f"  Sources:  {', '.join(sorted(set(s['source'] for s in selected)))}")


if __name__ == "__main__":
    main()
