# OpenClaw English

An AI-powered English learning workspace that automates close reading, vocabulary drilling, and weekly review — built on the [OpenClaw](https://github.com/Combjellyshen) multi-agent platform.

## What It Does

Every day, this system:

1. **Picks an article** from quality sources (BBC, NPR, The Guardian, Aeon, etc.) based on a topic you choose
2. **Runs a close reading pipeline** — discourse structure, sentence-by-sentence grammar, vocabulary, cultural background, comprehension questions
3. **Generates daily vocabulary cards** — pulls words from CET6/kaoyan/SAT pools with definitions, collocations, etymology, mnemonics, polysemy analysis
4. **Produces weekly review exams** — consolidates the week's vocabulary into a comprehensive test with study plans
5. **Outputs polished PDFs** delivered via Telegram

## Architecture

```
User (Telegram)
  │
  ▼
OpenClaw Agent ("english")
  │
  ├── close_reading_pipeline.py    # Article → multi-section analysis
  ├── daily_vocab_pipeline.py      # Word pools → enriched vocab cards
  ├── weekly_vocab_pipeline.py     # Weekly consolidation → exam + study plan
  ├── claude_pipeline_runner.py    # Orchestrator: auto-retry, validation, PDF
  └── generate_pdf.py              # Markdown → styled PDF
```

### Pipeline Flow

Each pipeline follows the same pattern:

```
Template selection → Claude generation (per section) → Validation → Assembly → PDF → Delivery
```

- **Model routing** (`config/model_routing.json`): routes each task to either Opus (deep reasoning: grammar, polysemy) or Sonnet (structured tasks: definitions, examples) based on complexity
- **Merriam-Webster API**: enriches vocabulary with dictionary/learner definitions, cached locally
- **Validation scripts**: catch formatting errors, missing fields, broken references before assembly

### Key Components

| Directory | Purpose |
|-----------|---------|
| `scripts/` | All pipeline logic — Python, no external frameworks |
| `templates/` | Prompt templates for each pipeline section |
| `data/exam-vocab/` | CET6, kaoyan, SAT word pools (JSON) |
| `config/` | Model routing, learning preferences |
| `reading-log/` | Article index and output archive |

### Agent Configuration

| File | Role |
|------|------|
| `SOUL.md` | Agent persona and behavior rules |
| `IDENTITY.md` | Name, role, emoji |
| `USER.md` | Learner profile and preferences |
| `AGENTS.md` | Operating rules for all three pipelines |
| `TOOLS.md` | Environment and tool preferences |
| `HEARTBEAT.md` | Proactive update policy |
| `SKILLS.md` | List of activated skills |

## Usage

```bash
# Daily check-in
python3 scripts/english_daily.py checkin

# Plan today's reading
python3 scripts/english_daily.py plan --topic "AI and education"

# Run daily vocab pipeline (auto: generate → validate → assemble → PDF)
python3 scripts/claude_pipeline_runner.py daily-vocab --create --date 2026-03-21 --build-pdf

# Run close reading pipeline
python3 scripts/claude_pipeline_runner.py close-reading --date 2026-03-21 --build-pdf

# Check pipeline status
python3 scripts/pipeline_status.py --kind auto
```

## Tech Stack

- **Python 3.12+** — all scripts, no web framework
- **Claude API** (Opus / Sonnet) — via model routing for cost/quality balance
- **Merriam-Webster Collegiate & Learner's Dictionary API** — vocabulary enrichment
- **WeasyPrint** — PDF generation from Markdown
- **Telegram Bot API** — delivery channel

## Note

This is a live workspace extracted from a personal OpenClaw deployment. Sensitive data (API keys, personal notes, article texts, learning history) has been excluded. The smudge/clean git filter in `bin/` auto-desensitizes `USER.md` on commit.

## License

MIT
