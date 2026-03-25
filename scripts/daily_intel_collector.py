# -*- coding: utf-8 -*-
"""
daily_intel_collector.py -- Game Intel Daily Collector (System 1: Signal Collection)

Responsibilities:
  Fetch raw items from external sources, filter irrelevant content, write to Obsidian Inbox.
  Does NOT write to 2.4 knowledge base -- that is insights_to_rag.py (System 2).

Flow:
  RSS -> keyword filter -> per-item md files -> 00-Inbox/YYYY-MM-DD/

Signal types (aligned with proj_004 phase2.1):
  technical | market | team | capital

Next step (manual):
  Review 00-Inbox in Obsidian, move valuable items to 05-Insights/
  Then run insights_to_rag.py to write into 2.4 knowledge base
"""

import feedparser
import requests
import re
import time
import hashlib
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Optional

# ────────────────────────────────────────────────
# Path config
# ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # game-knowledge-base/
INBOX_DIR = BASE_DIR / "00-Inbox"
BRIEFS_DIR = BASE_DIR / "01-Briefs"
TODAY = datetime.now().strftime("%Y-%m-%d")

# ────────────────────────────────────────────────
# RSS Sources
# ────────────────────────────────────────────────
RSS_SOURCES = [
    {
        "name": "Game Developer",
        "url": "https://www.gamedeveloper.com/rss.xml",
        "lang": "en",
        "focus": ["technical", "design", "market"],
    },
    {
        "name": "IGN Game News",
        "url": "https://feeds.ign.com/ign/games-all",
        "lang": "en",
        "focus": ["market", "team"],
    },
    {
        "name": "Eurogamer",
        "url": "https://www.eurogamer.net/?format=rss",
        "lang": "en",
        "focus": ["market", "technical"],
    },
    {
        "name": "Rock Paper Shotgun",
        "url": "https://www.rockpapershotgun.com/feed",
        "lang": "en",
        "focus": ["market", "technical"],
    },
    {
        "name": "PC Gamer",
        "url": "https://www.pcgamer.com/rss/",
        "lang": "en",
        "focus": ["market", "technical"],
    },
    {
        "name": "GameSpot",
        "url": "https://www.gamespot.com/feeds/mashup/",
        "lang": "en",
        "focus": ["market", "team"],
    },
    {
        "name": "ChuApp",
        "url": "https://www.chuapp.com/feed",
        "lang": "zh",
        "focus": ["market", "team", "capital"],
    },
]

# ────────────────────────────────────────────────
# Keyword filter (aligned with phase2.1 signal_type)
# ────────────────────────────────────────────────
KEYWORD_MAP = {
    "capital": {
        "zh": ["融资", "收购", "投资", "估值", "上市", "IPO", "并购", "战略投资", "轮融资", "资本"],
        "en": ["funding", "acquisition", "invest", "valuation", "IPO", "merger", "raise", "capital",
               "series A", "series B", "series C", "acquired", "raised"],
    },
    "team": {
        "zh": ["工作室", "成立", "裁员", "招聘", "离职", "创始人", "CEO", "加入", "团队", "解散"],
        "en": ["studio", "founded", "layoff", "hire", "departure", "founder", "CEO", "joins",
               "team", "disbanded", "shut down", "closed", "new studio"],
    },
    "technical": {
        "zh": ["引擎", "Unreal", "Unity", "AI", "人工智能", "技术", "云游戏", "VR", "AR", "渲染"],
        "en": ["engine", "unreal", "unity", "AI", "artificial intelligence", "technology",
               "cloud gaming", "VR", "AR", "rendering", "algorithm", "machine learning", "neural"],
    },
    "market": {
        "zh": ["发行", "销量", "营收", "市场", "玩家", "月活", "Steam", "上线", "版号", "出海"],
        "en": ["launch", "sales", "revenue", "market", "players", "MAU", "Steam", "release",
               "global", "chart", "top grossing", "downloads"],
    },
}

STRONG_SIGNALS = {
    "capital":   ["billion", "million", "acqui", "raises", "funding", "series a", "series b",
                  "series c", "ipo", "merger", "亿", "收购", "融资"],
    "team":      ["layoff", "laid off", "job cut", "shut down", "disbanded", "closes",
                  "studio closed", "裁员", "解散", "关闭"],
    "market":    ["sales", "revenue", "top grossing", "chart", "downloads", "mau",
                  "launch", "releases", "销量", "营收", "月活", "首发"],
    "technical": ["unreal engine", "unity engine", "generative ai", "neural", "ray tracing",
                  "cloud gaming", "vr headset"],
}


# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────

def clean_html(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def detect_signal_type(title: str, summary: str, lang: str = "en") -> Optional[str]:
    title_lower = title.lower()
    summary_lower = summary.lower()
    scores = {}

    for signal_type, keywords in KEYWORD_MAP.items():
        kws = keywords.get(lang, []) + (keywords.get("en", []) if lang != "en" else [])
        score = 0
        for kw in kws:
            kw_lower = kw.lower()
            if kw_lower in title_lower:
                score += 3
            elif kw_lower in summary_lower:
                score += 1
        for strong_kw in STRONG_SIGNALS.get(signal_type, []):
            if strong_kw in title_lower:
                score += 6
            elif strong_kw in summary_lower:
                score += 2
        if score > 0:
            scores[signal_type] = score

    if not scores:
        return None
    return max(scores, key=scores.get)


def sanitize_filename(title: str, max_len: int = 60) -> str:
    name = re.sub(r'[\\/*?:"<>|]', '', title)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:max_len]


# ────────────────────────────────────────────────
# Fetch RSS
# ────────────────────────────────────────────────

def fetch_rss(source: dict, max_items: int = 15) -> list:
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (GameIntelBot/1.0)"}
        response = requests.get(source["url"], headers=headers, timeout=15)
        feed = feedparser.parse(response.content)

        for entry in feed.entries[:max_items]:
            title = getattr(entry, "title", "")
            summary = clean_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
            link = getattr(entry, "link", "")
            published = TODAY

            try:
                pub_struct = getattr(entry, "published_parsed", None)
                if pub_struct:
                    published = datetime(*pub_struct[:3]).strftime("%Y-%m-%d")
            except Exception:
                pass

            lang = source.get("lang", "en")
            signal_type = detect_signal_type(title, summary, lang)

            if signal_type is None:
                continue

            items.append({
                "title": title,
                "summary": summary[:500] if summary else "",
                "link": link,
                "published": published,
                "source_name": source["name"],
                "signal_type": signal_type,
                "lang": lang,
            })

    except Exception as e:
        print(f"  WARNING: {source['name']} fetch failed: {e}")

    return items


# ────────────────────────────────────────────────
# Output: one md file per item
# ────────────────────────────────────────────────

TYPE_EMOJI = {
    "capital":   "capital",
    "team":      "team",
    "technical": "tech",
    "market":    "market",
}

TYPE_CN = {
    "capital":   "资本信号",
    "team":      "团队信号",
    "technical": "技术信号",
    "market":    "市场信号",
}


def write_obsidian_inbox(items: list, date: str):
    """
    Write each item as a standalone md file under 00-Inbox/YYYY-MM-DD/
    Filename = signal_type prefix + title
    User can long-press in Obsidian mobile to move to 05-Insights/
    """
    day_dir = INBOX_DIR / date
    day_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for item in items:
        prefix = TYPE_EMOJI.get(item["signal_type"], "misc")
        safe_title = sanitize_filename(item["title"])
        filename = f"[{prefix}] {safe_title}.md"
        out_path = day_dir / filename

        # Skip existing (avoid overwrite on re-run)
        if out_path.exists():
            continue

        signal_cn = TYPE_CN.get(item["signal_type"], item["signal_type"])

        content = f"""---
signal_type: {item["signal_type"]}
source: {item["source_name"]}
date: {item["published"]}
status: inbox
tags:
  - inbox
  - {item["signal_type"]}
---

# {item["title"]}

**{signal_cn}** | {item["source_name"]} | {item["published"]}

[原文链接]({item["link"]})

## 摘要

{item["summary"]}

## 我的判断

> （移到 05-Insights 前在这里写下你的想法，并添加 signal_type frontmatter）

---
*auto-collected {datetime.now().strftime("%Y-%m-%d %H:%M")}*
"""
        out_path.write_text(content, encoding="utf-8")
        written += 1

    print(f"  OK  Inbox -> {day_dir}/ ({written} files)")
    return day_dir


# ────────────────────────────────────────────────
# Output: daily brief (single summary file)
# ────────────────────────────────────────────────

SIGNAL_SECTION = {
    "capital":   "💰 资本动向",
    "team":      "👥 团队动态",
    "technical": "🔧 技术趋势",
    "market":    "📊 市场信号",
}


def write_daily_brief(items: list, date: str):
    """
    Write a single daily brief to 01-Briefs/YYYY-MM-DD.md
    Groups items by signal_type, each line links to the corresponding inbox note.
    """
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    brief_path = BRIEFS_DIR / f"{date}.md"

    # Group by signal type
    grouped: dict[str, list] = {k: [] for k in SIGNAL_SECTION}
    for item in items:
        st = item["signal_type"]
        if st in grouped:
            grouped[st].append(item)

    total = len(items)
    lines = []
    lines.append(f"# 📋 每日简报 · {date}")
    lines.append(f"\n> 共 **{total}** 条情报 · 自动采集 · {datetime.now().strftime('%H:%M')}")
    lines.append(f"\n---\n")

    for signal_type, section_title in SIGNAL_SECTION.items():
        group = grouped.get(signal_type, [])
        if not group:
            continue

        lines.append(f"## {section_title}（{len(group)}条）\n")

        for item in group:
            prefix = TYPE_EMOJI.get(signal_type, "misc")
            safe_title = sanitize_filename(item["title"])
            # Obsidian internal link to the inbox note
            note_name = f"[{prefix}] {safe_title}"
            summary_short = item["summary"][:80].replace("\n", " ").strip()
            if len(item["summary"]) > 80:
                summary_short += "…"

            lines.append(f"- [[{note_name}|{item['title'][:50]}]]")
            lines.append(f"  `{item['source_name']}` · {summary_short}")
            lines.append("")

    lines.append("---")
    lines.append(f"*由 daily_intel_collector.py 自动生成 · [[{date}/|查看全部原始笔记]]*")

    brief_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  OK  Brief -> {brief_path}")
    return brief_path


# ────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────

def main():
    print(f"\n{'='*55}")
    print(f"  Game Intel Collector  {TODAY}")
    print(f"{'='*55}\n")

    all_items = []

    for source in RSS_SOURCES:
        print(f"Fetching {source['name']} ...")
        items = fetch_rss(source)
        print(f"  -> {len(items)} items after filter")
        all_items.extend(items)
        time.sleep(1)

    if not all_items:
        print("\nWARNING: No items collected. Check network or sources.")
        return

    # Dedup by title+source
    seen = set()
    unique_items = []
    for item in all_items:
        key = f"{item['source_name']}::{item['title'][:60]}"
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    print(f"\nTotal: {len(all_items)} raw -> {len(unique_items)} after dedup")
    print(f"\nWriting to Obsidian Inbox ...")
    write_obsidian_inbox(unique_items, TODAY)

    print(f"\nWriting daily brief ...")
    write_daily_brief(unique_items, TODAY)

    print(f"\nDone! {TODAY} collection complete.")
    print(f"  Inbox: {INBOX_DIR / TODAY}/")
    print(f"\n  Next: review 00-Inbox in Obsidian, move valuable items to 05-Insights/")
    print(f"        then run insights_to_rag.py to sync into 2.4 knowledge base")


if __name__ == "__main__":
    main()
