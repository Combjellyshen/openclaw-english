# Daily English Reading Workspace

这是 Combjelly 的每日英语精读 workspace。

> 已合并原 `workspace-englisharticle`。后续英语文章精读、单词/短语解释、句子拆解、闪卡/Anki 导出、每日词卡与每周词汇任务，统一在这个 workspace 与同一个 `english` agent 中维护。

## 目标
- 每天先确认今晚想了解的主题
- 再挑选一篇中等长度英文文章
- 围绕文章做词汇、语法、文化背景和精读讲解

## 修改保护前缀
凡是要改这个 workspace 本身（脚本、配置、规则、资料文件等），用户指令必须以前缀：

```text
配置agent
```

开头，否则不得落盘修改。

可用脚本快速判断：

```bash
python3 scripts/english_daily.py guard --message "配置agent 请修改 profile"
python3 scripts/english_daily.py guard --message "帮我修改 profile"
```

## 主要文件
- `AGENTS.md`：英语 agent 的工作规则（含精读 / 每日词卡 / 每周综合卷）
- `config/profile.json`：学习偏好
- `scripts/english_daily.py`：每日提问、课程骨架、修改保护判断
- `scripts/close_reading_pipeline.py`：精读 pipeline
- `scripts/daily_vocab_pipeline.py`：每日词卡 pipeline
- `scripts/weekly_vocab_pipeline.py`：每周综合卷 pipeline
- `scripts/pipeline_status.py`：统一进度查询
- `scripts/claude_pipeline_runner.py`：Claude 自动推进（daily / weekly / close-reading）

## 常用命令
```bash
python3 scripts/english_daily.py checkin
python3 scripts/english_daily.py plan --topic "AI and education"
python3 scripts/english_daily.py guard --message "配置agent 把默认难度改成 B2"

# 查看最新任务进度（精读 + 每日词卡 + 每周综合卷）
python3 scripts/pipeline_status.py --kind auto

# 直接跑今日词卡（Claude 自动写字段 + 回填 + 组装 + 校验 + 可选 PDF）
python3 scripts/claude_pipeline_runner.py daily-vocab --create --date 2026-03-21 --build-pdf
```
