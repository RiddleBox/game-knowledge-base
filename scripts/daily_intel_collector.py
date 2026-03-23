"""
daily_intel_collector.py — 游戏行业情报日采集器（系统1：信号采集）

职责边界：
  只负责从外部信息源抓取原始条目，过滤无关内容，写入 Obsidian Inbox。
  不直接写入 2.4 知识库——那是 insights_to_rag.py（系统2）的职责。

流程：
  RSS/网页 → 关键词过滤 → 按 signal_type 分组 → 写入 00-Inbox/YYYY-MM-DD.md

信号类型（对齐 proj_004 phase2.1 命名规范）：
  technical | market | team | capital

下一步（人工）：
  在 Obsidian 里审阅 00-Inbox，把值得沉淀的笔记移到 05-Insights/
  然后运行 insights_to_rag.py 自动写入 2.4 知识库
"""

import feedparser
import requests
import re
import os
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Optional

# ────────────────────────────────────────────────
# 路径配置
# ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # game-knowledge-base/
INBOX_DIR = BASE_DIR / "00-Inbox"
TODAY = datetime.now().strftime("%Y-%m-%d")

# ────────────────────────────────────────────────
# 信息源配置
# ────────────────────────────────────────────────
RSS_SOURCES = [
    {
        "name": "GamesIndustry.biz",
        "url": "https://www.gamesindustry.biz/rss/gamesindustry_news_feed.asp",
        "lang": "en",
        "focus": ["funding", "acquisition", "team", "market"],
    },
    {
        "name": "Game Developer (Gamasutra)",
        "url": "https://www.gamedeveloper.com/rss.xml",
        "lang": "en",
        "focus": ["technical", "design", "market"],
    },
    {
        "name": "VentureBeat Games",
        "url": "https://venturebeat.com/category/games/feed/",
        "lang": "en",
        "focus": ["funding", "technical", "market"],
    },
    {
        "name": "Pocket Gamer",
        "url": "https://www.pocketgamer.biz/feed/",
        "lang": "en",
        "focus": ["market", "mobile"],
    },
    {
        "name": "游戏葡萄",
        "url": "https://gamegrape.baijia.baidu.com/rss",
        "lang": "zh",
        "focus": ["market", "team", "funding"],
    },
]

# ────────────────────────────────────────────────
# 关键词过滤配置（对齐2.1的四类信号）
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
        "zh": ["引擎", "Unreal", "Unity", "AI", "人工智能", "技术", "云游戏", "VR", "AR", "渲染", "算法"],
        "en": ["engine", "unreal", "unity", "AI", "artificial intelligence", "technology",
               "cloud gaming", "VR", "AR", "rendering", "algorithm", "machine learning", "neural"],
    },
    "market": {
        "zh": ["发行", "销量", "营收", "市场", "玩家", "月活", "Steam", "上线", "版号", "出海", "全球化"],
        "en": ["launch", "sales", "revenue", "market", "players", "MAU", "Steam", "release",
               "global", "localization", "chart", "top grossing", "downloads"],
    },
}

# 2.4知识文档的category映射 —— 仅供 insights_to_rag.py 参考，此处注释保留作为文档
# capital / team / market → market_trend
# technical               → tech_innovation
# game_design             → 需人工提炼，不做自动采集

# ────────────────────────────────────────────────
# 辅助函数
# ────────────────────────────────────────────────

def clean_html(text: str) -> str:
    """去除HTML标签，返回纯文本"""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def detect_signal_type(title: str, summary: str, lang: str = "en") -> Optional[str]:
    """
    根据标题+摘要检测信号类型（对齐2.1的四类 signal_type）
    返回匹配优先级最高的类型，无匹配返回 None（过滤掉）

    策略：
    - 标题命中权重 x3（标题比摘要更能代表核心主题）
    - capital/team 强信号词（金额/裁员等）额外 x2 加权
    - 无命中 → None（过滤）
    """
    title_lower = title.lower()
    summary_lower = summary.lower()

    # 强信号词：出现即高度确认该类型（不依赖多词累计）
    STRONG_SIGNALS = {
        "capital": ["billion", "million", "acqui", "raises", "funding", "series a", "series b",
                    "series c", "ipo", "merger", "买", "亿", "收购", "融资"],
        "team":    ["layoff", "laid off", "job cut", "workforce reduction", "shut down",
                    "disbanded", "closes", "studio closed", "裁员", "解散", "关闭"],
        "market":  ["sales", "revenue", "top grossing", "chart", "downloads", "mau", "dau",
                    "launch", "releases", "players", "销量", "营收", "月活", "首发"],
        "technical": ["unreal engine", "unity engine", "generative ai", "neural", "ray tracing",
                      "cloud gaming", "vr headset", "ar glasses"],
    }

    scores = {}

    for signal_type, keywords in KEYWORD_MAP.items():
        kws = keywords.get(lang, []) + (keywords.get("en", []) if lang != "en" else [])
        score = 0
        for kw in kws:
            kw_lower = kw.lower()
            if kw_lower in title_lower:
                score += 3  # 标题命中 x3
            elif kw_lower in summary_lower:
                score += 1  # 摘要命中 x1
        # 强信号词额外加权
        for strong_kw in STRONG_SIGNALS.get(signal_type, []):
            if strong_kw in title_lower:
                score += 6  # 强信号标题命中 x6（几乎决定分类）
            elif strong_kw in summary_lower:
                score += 2
        if score > 0:
            scores[signal_type] = score

    if not scores:
        return None
    return max(scores, key=scores.get)


def short_id(url: str, date: str) -> str:
    """基于URL+日期生成短ID（保留，供未来去重用）"""
    h = hashlib.md5(f"{url}{date}".encode()).hexdigest()[:6]
    return h


# ────────────────────────────────────────────────
# 核心采集
# ────────────────────────────────────────────────

def fetch_rss(source: dict, max_items: int = 15) -> list[dict]:
    """采集单个RSS源，返回原始条目列表"""
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (GameIntelBot/1.0)"}
        response = requests.get(source["url"], headers=headers, timeout=15)
        feed = feedparser.parse(response.content)

        for entry in feed.entries[:max_items]:
            title = getattr(entry, "title", "")
            summary = clean_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
            link = getattr(entry, "link", "")
            published = getattr(entry, "published", TODAY)

            # 尝试标准化日期
            try:
                pub_struct = getattr(entry, "published_parsed", None)
                if pub_struct:
                    published = datetime(*pub_struct[:3]).strftime("%Y-%m-%d")
            except Exception:
                published = TODAY

            lang = source.get("lang", "en")
            signal_type = detect_signal_type(title, summary, lang)

            if signal_type is None:
                continue  # 过滤掉无关内容

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
        print(f"  ⚠️  {source['name']} 获取失败: {e}")

    return items


# ────────────────────────────────────────────────
# 输出A：Obsidian Inbox Markdown
# ────────────────────────────────────────────────

def write_obsidian_inbox(items: list[dict], date: str):
    """
    输出到 00-Inbox/YYYY-MM-DD.md
    按 signal_type 分区，每条附原始链接，方便人工快速浏览
    """
    inbox_dir = INBOX_DIR
    inbox_dir.mkdir(parents=True, exist_ok=True)
    out_path = inbox_dir / f"{date}.md"

    # 按signal_type分组
    groups = {}
    for item in items:
        st = item["signal_type"]
        groups.setdefault(st, []).append(item)

    # signal_type → 中文标签
    TYPE_LABEL = {
        "capital":   "💰 资本信号（融资/收购/投资）",
        "team":      "👥 团队信号（工作室/人事变动）",
        "technical": "⚙️ 技术信号（引擎/AI/技术创新）",
        "market":    "📈 市场信号（发行/销量/趋势）",
    }

    total = len(items)
    lines = [
        f"# 📡 游戏行业情报日报 — {date}",
        f"",
        f"> 采集时间：{datetime.now().strftime('%H:%M')} | 共 {total} 条过滤后条目",
        f"> 来源：{', '.join(set(i['source_name'] for i in items))}",
        f"> **状态**：⬜ 待审阅（划掉或移动到 05-Insights 完成后标记）",
        f"",
        f"---",
        f"",
    ]

    for signal_type in ["capital", "team", "technical", "market"]:
        group = groups.get(signal_type, [])
        if not group:
            continue
        label = TYPE_LABEL[signal_type]
        lines.append(f"## {label}")
        lines.append("")
        for item in group:
            lines.append(f"### {item['title']}")
            lines.append(f"- **来源**：{item['source_name']}　**日期**：{item['published']}")
            lines.append(f"- **链接**：[原文]({item['link']})")
            lines.append(f"- **摘要**：{item['summary']}")
            lines.append(f"- **标签**：#inbox #{signal_type} #{item['source_name'].replace(' ', '-')}")
            lines.append("")

    lines += [
        "---",
        "",
        f"*由 daily_intel_collector.py 自动生成 · {datetime.now().isoformat()}*",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✅  Obsidian Inbox → {out_path}")
    return out_path


# ────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────

def main():
    print(f"\n{'='*55}")
    print(f"  游戏行业情报日采集器  {TODAY}")
    print(f"{'='*55}\n")

    all_items = []

    for source in RSS_SOURCES:
        print(f"📡 采集 {source['name']} ...")
        items = fetch_rss(source)
        print(f"   过滤后：{len(items)} 条有效条目")
        all_items.extend(items)
        time.sleep(1)  # 礼貌性间隔，避免触发限速

    if not all_items:
        print("\n⚠️  本次未采集到任何有效条目，请检查网络或信息源")
        return

    # 去重（同标题+来源）
    seen = set()
    unique_items = []
    for item in all_items:
        key = f"{item['source_name']}::{item['title'][:60]}"
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    print(f"\n📊 汇总：{len(all_items)} 条原始 → {len(unique_items)} 条去重后")

    # 写入 Obsidian Inbox（唯一输出）
    print(f"\n📝 写入 Obsidian Inbox ...")
    write_obsidian_inbox(unique_items, TODAY)

    print(f"\n✅ 完成！{TODAY} 情报采集结束")
    print(f"   Obsidian Inbox: {INBOX_DIR / TODAY}.md")
    print(f"\n   下一步：在 Obsidian 审阅 00-Inbox，把值得沉淀的笔记移到 05-Insights/")
    print(f"           然后运行 insights_to_rag.py 写入 2.4 知识库")


if __name__ == "__main__":
    main()
