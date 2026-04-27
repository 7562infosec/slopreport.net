#!/usr/bin/env python3
"""
The Slop Report — Weekly Roundup
Aggregates the past 7 days of daily Slop Report posts into a single weekly digest.
Runs every Saturday via GitHub Actions.
Usage: python3 scripts/weekly_roundup.py
"""

import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

POSTS_DIR = Path(__file__).parent.parent / "_posts"


def parse_daily_post(path: Path) -> list[dict]:
    """Extract story dicts from a daily post markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  Warning: could not read {path.name}: {e}")
        return []

    stories = []
    # Match blocks like: ### N. [Title](url)\n*Source* · Date\n\nSummary text
    pattern = re.compile(
        r'### \d+\. \[([^\]]+)\]\(([^)]+)\)\n\*([^*\n]+)\*[^\n]*\n\n(.*?)(?=\n---\n|\Z)',
        re.DOTALL
    )
    for m in pattern.finditer(text):
        title = m.group(1).strip()
        link = m.group(2).strip()
        source = m.group(3).strip()
        summary = m.group(4).strip()
        # Remove trailing separator lines or footnotes
        summary = re.sub(r'\n\*\d+ stories.*', '', summary, flags=re.DOTALL).strip()
        stories.append({
            "title": title,
            "link": link,
            "source": source,
            "summary": summary[:400],
        })
    return stories


def get_weekly_posts() -> list[tuple[str, Path]]:
    """Return (date_str, path) pairs for daily posts from the past 7 days."""
    today = datetime.now(timezone.utc).date()
    results = []
    for i in range(1, 8):  # yesterday through 7 days ago
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        path = POSTS_DIR / f"{date_str}-slop-report.md"
        if path.exists():
            results.append((date_str, path))
    return results


def generate_weekly_post(all_stories: list[dict], today: datetime) -> str:
    date_str = today.strftime("%B %-d, %Y")
    date_iso = today.strftime("%Y-%m-%d")

    # Deduplicate by URL
    seen_links: set[str] = set()
    unique: list[dict] = []
    for s in all_stories:
        if s["link"] not in seen_links:
            seen_links.add(s["link"])
            unique.append(s)

    sources = sorted(set(s["source"] for s in unique))

    header = f"""---
layout: post
title: "Weekly Slop Roundup — {date_str}"
date: {date_iso}
categories: weekly-roundup
---

*The week's biggest stories on AI-generated content, deepfakes, synthetic media, and information quality.*

**{len(unique)} stories** from {len(sources)} sources this week.

---

"""

    blocks = []
    for idx, s in enumerate(unique, 1):
        block = f"### {idx}. [{s['title']}]({s['link']})\n"
        block += f"*{s['source']}*\n\n"
        if s["summary"]:
            block += f"{s['summary']}\n"
        blocks.append(block)

    footer = (
        "\n---\n\n"
        f"*Weekly roundup of {len(unique)} stories from "
        f"{', '.join(sources)}. "
        "The Slop Report is published daily. "
        "[Subscribe via RSS](/feed.xml).*\n"
    )

    return header + "\n---\n\n".join(blocks) + footer


def main():
    today = datetime.now(timezone.utc)
    print(f"Weekly Roundup starting — {today.strftime('%Y-%m-%d %H:%M UTC')}")

    weekly_posts = get_weekly_posts()
    if not weekly_posts:
        print("No daily posts found for the past 7 days. Nothing to aggregate.")
        sys.exit(0)

    print(f"Found {len(weekly_posts)} daily post(s) to aggregate.")

    all_stories: list[dict] = []
    for date_str, path in weekly_posts:
        stories = parse_daily_post(path)
        print(f"  {date_str}: {len(stories)} stories")
        all_stories.extend(stories)

    if not all_stories:
        print("No stories could be parsed. Exiting.")
        sys.exit(0)

    content = generate_weekly_post(all_stories, today)
    filename = today.strftime("%Y-%m-%d") + "-weekly-roundup.md"
    output_path = POSTS_DIR / filename
    POSTS_DIR.mkdir(exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    print(f"\n✓ Weekly roundup written to: {output_path}")
    print(f"  Total stories: {len(all_stories)}")


if __name__ == "__main__":
    main()
