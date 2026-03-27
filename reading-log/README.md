# 阅读记忆库

每次精读结束后，将文章信息和分析摘要记录在此。

## 目录结构

```
reading-log/
├── README.md          ← 本文件（索引说明）
├── index.json         ← 结构化索引（机器可读，便于检索）
└── articles/
    └── YYYY-MM-DD-slug.md   ← 每篇文章的完整分析记录
```

## index.json 字段说明

| 字段 | 说明 |
|------|------|
| date | 阅读日期 YYYY-MM-DD |
| title | 文章标题 |
| source | 来源媒体 |
| url | 原文链接 |
| topic | 主题标签（如 science / society / tech） |
| difficulty | 难度 A2 / B1 / B2 / C1 |
| word_count | 文章字数（约） |
| file | 对应 articles/ 下的文件名 |
| summary_zh | 一句话中文概要 |

## 使用方式

- 每次精读结束后，agent 自动追加到 `index.json` 并生成对应 `.md` 文章记录
- 可用 `cat reading-log/index.json | python3 -m json.tool` 快速浏览历史
- 或直接说"帮我回顾上次读的文章"，agent 会检索记忆库
