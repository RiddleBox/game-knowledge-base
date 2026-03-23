# 🎮 Game Knowledge Base

> 游戏资讯知识库 · 为 DesignAssistant 提供信息输入与沉淀

## 这是什么

一个基于 Obsidian + Git 的游戏设计知识管理系统，解决信息收集→沉淀→洞察的完整链路。

```
互联网资讯（媒体/Steam/Twitter/B站）
        ↓
  00-Inbox（速记收集）
        ↓
  分类整理（Games / Trends / Mechanics / Market）
        ↓
  05-Insights（提炼洞察）
        ↓
  06-DesignAssistant-Feed（输出给 DesignAssistant）
        ↓
  RiddleBox/DesignAssistant（机会分析 & 设计决策）
```

## 目录结构

| 目录 | 用途 |
|------|------|
| `00-Inbox/` | 速记收集，不需要整理，先扔进来 |
| `01-Games/` | 具体游戏档案（一款游戏一个文件夹） |
| `02-Trends/` | 市场趋势观察（按时间/主题） |
| `03-Mechanics/` | 游戏机制拆解与分析 |
| `04-Market/` | 市场数据、榜单、财报 |
| `05-Insights/` | 提炼后的设计洞察（最有价值） |
| `06-DesignAssistant-Feed/` | 整理好的输出，供 DesignAssistant 使用 |
| `Templates/` | Obsidian 模板文件 |

## 推荐插件

安装 Obsidian 后，前往 设置 → 第三方插件 安装：

- **Dataview** — 自动生成游戏列表、趋势汇总
- **Templater** — 快速创建标准化笔记
- **Obsidian Git** — 自动同步到 GitHub
- **QuickAdd** — 一键创建不同类型的笔记

## 与 DesignAssistant 的协作流程

1. 日常在 `00-Inbox` 速记看到的内容
2. 每周整理一次，分类到对应目录
3. 在 `05-Insights` 写提炼总结
4. 运行 `scripts/export-to-da.py` 将洞察导出为 DesignAssistant 格式
5. 在 DesignAssistant 中加载知识，进行机会分析

## 快速开始

```bash
# 克隆到本地
git clone https://github.com/RiddleBox/game-knowledge-base.git

# 用 Obsidian 打开这个文件夹
# File → Open Vault → 选择 game-knowledge-base 文件夹
```
