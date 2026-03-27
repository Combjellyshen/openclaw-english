# TOOLS.md

## 词典工具链

### Merriam-Webster API（已配置）
- 脚本：`python3 scripts/mw_lookup.py <word>` → Collegiate 版（词源 + 释义）
- 脚本：`python3 scripts/mw_lookup.py <word> --learner` → Learner's 版（学习者例句）
- 批量：`python3 scripts/mw_lookup.py batch '["word1","word2"]'`
- 缓存：`data/mw-cache/`，查过的词不重复请求
- 限额：每天 1000 次（足够用）

### Skills
- `ljg-explain-words`：深度拆解单词（原始画面 + 核心意象 + 一语道破），只对重点词用
- `english-learner`：本地生词库 CRUD + 掌握度跟踪，脚本在 `~/.openclaw/skill-library/english-learner/scripts/`

### 联网搜索
- `web_search` → 查 Etymonline（词源）、Cambridge / Oxford（用法）
- `web_fetch` → 抓全文、抓词典页面

### 调用顺序
1. 本地词库（零成本）
2. MW API（低成本，有缓存）
3. 联网搜索（中成本，按需）
4. 深度推理 / ljg-explain-words（高成本，关键词才用）

## 本地脚本
- `scripts/english_daily.py` — 精读流程骨架
- `scripts/exam_vocab_match.py` — 文章词库命中
- `scripts/vocab_system.py` — 生词本 + 词卡生成
- `scripts/generate_pdf.py` — Markdown → PDF
- `scripts/mw_lookup.py` — MW API 查词

