"""
insights_to_rag.py — Insights → 2.4 RAG知识库转换器（系统2：知识沉淀）

职责边界：
  扫描 05-Insights/ 目录下的 Markdown 笔记，
  将"你审阅后认可"的内容转换为 2.4 兼容的 kb_xxx.yaml 格式，
  写入 DesignAssistant/phase2.4_implementation/rag_system/data/documents/

触发方式：人工触发（你在 Obsidian 把 Inbox 笔记移到 05-Insights/ 后运行）

分类规范（严格对齐 phase2.4 models.py）：
  category 只有三值：game_design | market_trend | tech_innovation
  signal_type 保留在 tags 字段：capital | team | market | technical

笔记格式约定（05-Insights/*.md 的 frontmatter）：
  ---
  signal_type: capital        # 必填：capital/team/market/technical
  source: "GamesIndustry"     # 必填：原始信息来源
  date: 2026-03-23            # 必填：原始发布日期
  confidence: 0.85            # 可选：0-1，默认0.80
  tags: [fusion, mobile]      # 可选：额外标签
  ---
  （正文即为 content，标题即为 title）

用法：
  python scripts/insights_to_rag.py            # 处理所有未同步的 Insights
  python scripts/insights_to_rag.py --dry-run  # 预览，不实际写入
  python scripts/insights_to_rag.py --force    # 强制重新处理已同步的文件
"""

import re
import yaml
import hashlib
import argparse
from datetime import datetime
from pathlib import Path

# ────────────────────────────────────────────────
# 路径配置
# ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # game-knowledge-base/
INSIGHTS_DIR = BASE_DIR / "05-Insights"
SYNCED_LOG = BASE_DIR / "scripts" / ".synced_insights.txt"  # 已同步文件记录

DESIGN_ASSISTANT_DIR = Path("D:/AIproject/DesignAssistant")
RAG_DOCS_DIR = (
    DESIGN_ASSISTANT_DIR
    / "data-layer/projects/proj_004/phase2.4_implementation/rag_system/data/documents"
)

TODAY = datetime.now().strftime("%Y-%m-%d")

# ────────────────────────────────────────────────
# signal_type → 2.4 category 映射
# 严格使用 models.py 三值枚举
# ────────────────────────────────────────────────
SIGNAL_TO_CATEGORY = {
    "capital":   "market_trend",
    "team":      "market_trend",
    "market":    "market_trend",
    "technical": "tech_innovation",
    "game_design": "game_design",  # 手动标注时可直接指定
}


# ────────────────────────────────────────────────
# 辅助函数
# ────────────────────────────────────────────────

def parse_frontmatter(md_path: Path) -> tuple[dict, str]:
    """
    解析 Markdown frontmatter（--- 包裹的 YAML）
    返回 (meta_dict, body_text)
    若无 frontmatter，返回 ({}, 全文)
    """
    text = md_path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
                return meta, body
            except Exception:
                pass
    return {}, text.strip()


def get_next_kb_id(docs_dir: Path) -> int:
    """获取下一个可用的 kb_xxx 编号"""
    existing = [f.stem for f in docs_dir.glob("kb_*.yaml")]
    nums = []
    for name in existing:
        m = re.match(r"kb_(\d+)", name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 41


def load_synced_log() -> set:
    """读取已同步文件名集合"""
    if not SYNCED_LOG.exists():
        return set()
    return set(SYNCED_LOG.read_text(encoding="utf-8").splitlines())


def append_synced_log(filename: str):
    """记录已同步的文件名"""
    with open(SYNCED_LOG, "a", encoding="utf-8") as f:
        f.write(filename + "\n")


def md_to_yaml_doc(md_path: Path, kb_id: str) -> dict | None:
    """
    把一个 Insight Markdown 文件转换为 2.4 兼容的文档字典
    返回 None 表示跳过（缺少必填字段）
    """
    meta, body = parse_frontmatter(md_path)

    # 标题：优先用文件名（去掉日期前缀），其次用正文第一个 # 标题
    title = md_path.stem
    # 尝试从正文提取 # 标题
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # signal_type 必填检查
    signal_type = meta.get("signal_type", "").strip().lower()
    if not signal_type:
        print(f"  ⚠️  跳过 {md_path.name}：缺少 signal_type（请在 frontmatter 中填写）")
        return None

    if signal_type not in SIGNAL_TO_CATEGORY:
        print(f"  ⚠️  跳过 {md_path.name}：未知 signal_type='{signal_type}'")
        print(f"       合法值：{list(SIGNAL_TO_CATEGORY.keys())}")
        return None

    category = SIGNAL_TO_CATEGORY[signal_type]

    # source / date
    source = meta.get("source", md_path.name)
    date = str(meta.get("date", TODAY))
    confidence = float(meta.get("confidence", 0.80))

    # tags：signal_type + 自定义 tags + 日期
    extra_tags = meta.get("tags", []) or []
    if isinstance(extra_tags, str):
        extra_tags = [extra_tags]
    tags = sorted(set([signal_type] + [str(t) for t in extra_tags] + [date, "human-curated"]))

    # content：正文（去掉第一行 # 标题，避免重复）
    content_lines = []
    skip_first_heading = False
    for line in body.splitlines():
        if not skip_first_heading and line.strip().startswith("# "):
            skip_first_heading = True
            continue
        content_lines.append(line)
    content = "\n".join(content_lines).strip()

    # content 长度限制（2.4 models.py 说明最多2000字符）
    if len(content) > 2000:
        content = content[:1980] + "\n\n[内容已截断，完整内容见原始文件]"

    return {
        "id": kb_id,
        "title": title,
        "category": category,
        "tags": tags,
        "content": content,
        "metadata": {
            "source": source,
            "confidence": confidence,
            "last_updated": date,
            "origin_file": md_path.name,
            "synced_at": TODAY,
        },
    }


# ────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Insights → 2.4 RAG知识库转换器")
    parser.add_argument("--dry-run", action="store_true", help="预览，不实际写入")
    parser.add_argument("--force", action="store_true", help="强制重新处理已同步的文件")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  Insights → RAG 同步器  {TODAY}")
    if args.dry_run:
        print(f"  [DRY RUN 模式，不写入任何文件]")
    print(f"{'='*55}\n")

    # 检查路径
    if not INSIGHTS_DIR.exists():
        print(f"❌ 05-Insights/ 目录不存在：{INSIGHTS_DIR}")
        return
    if not RAG_DOCS_DIR.exists():
        print(f"❌ RAG文档目录不存在：{RAG_DOCS_DIR}")
        print(f"   请先确认 DesignAssistant 已 clone 到 D:/AIproject/DesignAssistant")
        print(f"   并已切换到 archive-claude-and-gpt-work 分支")
        return

    # 扫描 05-Insights/
    md_files = sorted(INSIGHTS_DIR.glob("*.md"))
    if not md_files:
        print("ℹ️  05-Insights/ 目录为空，无需同步")
        print("   先在 Obsidian 把 00-Inbox 里的笔记移到 05-Insights/")
        return

    synced = load_synced_log()
    to_process = []
    for f in md_files:
        if f.name in synced and not args.force:
            print(f"  ⏭️  跳过（已同步）：{f.name}")
        else:
            to_process.append(f)

    if not to_process:
        print("\n✅ 所有 Insights 已同步，无需处理")
        print("   如需重新处理，加 --force 参数")
        return

    print(f"\n📋 待处理：{len(to_process)} 个文件\n")

    next_num = get_next_kb_id(RAG_DOCS_DIR)
    written = []
    skipped = []

    for md_path in to_process:
        kb_id = f"kb_{next_num:03d}"
        doc = md_to_yaml_doc(md_path, kb_id)

        if doc is None:
            skipped.append(md_path.name)
            continue

        out_path = RAG_DOCS_DIR / f"{kb_id}.yaml"

        if args.dry_run:
            print(f"  [DRY RUN] {md_path.name}")
            print(f"    → {kb_id}.yaml  category={doc['category']}  tags={doc['tags'][:3]}...")
            print(f"    title: {doc['title']}")
            print(f"    content 长度: {len(doc['content'])} 字符")
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                yaml.dump(doc, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            append_synced_log(md_path.name)
            print(f"  ✅  {md_path.name} → {kb_id}.yaml  (category={doc['category']})")

        written.append(kb_id)
        next_num += 1

    print(f"\n{'='*55}")
    print(f"  完成！写入 {len(written)} 条，跳过 {len(skipped)} 条")
    if skipped:
        print(f"  跳过原因：缺少 signal_type frontmatter")
        for s in skipped:
            print(f"    - {s}")
    if written and not args.dry_run:
        print(f"\n  💡 提示：知识文档已更新，如需更新 FAISS 索引请运行：")
        print(f"     cd {DESIGN_ASSISTANT_DIR}/data-layer/projects/proj_004/phase2.4_implementation/rag_system")
        print(f"     python build_index_local.py")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
