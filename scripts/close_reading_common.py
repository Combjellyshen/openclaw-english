#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "reading-log" / "runs"
ARTICLES_DIR = ROOT / "reading-log" / "articles"
PDFS_DIR = ROOT / "reading-log" / "pdfs"
INDEX_PATH = ROOT / "reading-log" / "index.json"
TEMPLATES_DIR = ROOT / "templates" / "close-reading"

REQUIRED_SECTION_TITLES = [
    "行文结构",
    "中文概要",
    "考试词库命中概览",
    "重点词汇",
    "文章难词补充",
    "逐句语法",
    "语言学重点 & 中英对比",
    "文化 / 背景知识",
    "精读句子 3 句",
    "理解 / 讨论问题",
    "相关巩固题",
    "考题",
    "Follow-up 三选一",
    "Original Article",
]

VOCAB_REQUIRED_FIELDS = [
    "词库标签",
    "音标",
    "中文释义",
    "原文例句",
    "常见搭配 / 固定短语 / 介词搭配",
    "多义辨析",
    "词源演变",
    "单词派生",
]

PIPELINE_STAGE_ORDER = [
    "initialized",
    "source_attached",
    "exam_matched",
    "notebook_ingested",
    "vocab_built",
    "structure_summary_done",
    "grammar_done",
    "insights_done",
    "discussion_exam_done",
    "assembled",
    "validated",
    "pdf_built",
    "index_updated",
    "delivered",
]

SUBAGENT_TASKS = [
    {
        "name": "structure_summary",
        "label": "结构+概要",
        "template": "structure_summary.md",
        "output": "module_structure_summary.md",
        "required_headings": ["行文结构", "中文概要"],
    },
    {
        "name": "grammar",
        "label": "逐句语法",
        "template": "grammar.md",
        "output": "module_grammar.md",
        "required_headings": ["逐句语法"],
    },
    {
        "name": "insights",
        "label": "语言学+背景+精读句",
        "template": "insights.md",
        "output": "module_insights.md",
        "required_headings": ["语言学重点 & 中英对比", "文化 / 背景知识", "精读句子 3 句"],
    },
    {
        "name": "discussion_exam",
        "label": "讨论+题目+follow-up",
        "template": "discussion_exam.md",
        "output": "module_discussion_exam.md",
        "required_headings": ["理解 / 讨论问题", "相关巩固题", "考题", "Follow-up 三选一"],
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "article"


def ensure_run_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)


def latest_run_dir() -> Path | None:
    ensure_run_dirs()
    candidates = [child for child in RUNS_DIR.iterdir() if child.is_dir() and (child / "manifest.json").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: ((p / "manifest.json").stat().st_mtime, p.name))


def new_manifest(article: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    article_slug = article["slug"]
    article_date = article["date"]
    article_md = ARTICLES_DIR / f"{article_date}-{article_slug}.md"
    pdf_path = PDFS_DIR / f"{article_date}-{article_slug}.pdf"
    prompts_dir = run_dir / "prompts"
    modules_dir = run_dir / "modules"
    artifacts_dir = run_dir / "artifacts"
    manifest = {
        "run_id": f"{article_date}-{article_slug}",
        "kind": "close_reading",
        "created_at": utc_now_iso(),
        "article": article,
        "paths": {
            "run_dir": str(run_dir),
            "article_markdown": str(article_md),
            "pdf": str(pdf_path),
            "original_article": str(artifacts_dir / "original_article.md"),
            "vocab_markdown": str(artifacts_dir / "vocab.md"),
            "vocab_json": str(artifacts_dir / "vocab.json"),
            "exam_json": str(artifacts_dir / "exam_match.json"),
            "validation_json": str(artifacts_dir / "validation.json"),
            "index": str(INDEX_PATH),
            "prompts_dir": str(prompts_dir),
            "modules_dir": str(modules_dir),
        },
        "subagent_tasks": [
            {
                **task,
                "prompt_path": str(prompts_dir / task["template"]),
                "output_path": str(modules_dir / task["output"]),
            }
            for task in SUBAGENT_TASKS
        ],
        "stages": {
            stage: {"status": "done" if stage == "initialized" else "pending", "updated_at": utc_now_iso()}
            for stage in PIPELINE_STAGE_ORDER
        },
        "notes": [],
    }
    return manifest


def manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def load_manifest(run_dir: Path) -> Dict[str, Any]:
    return read_json(manifest_path(run_dir), {})


def save_manifest(run_dir: Path, manifest: Dict[str, Any]) -> None:
    write_json(manifest_path(run_dir), manifest)


def mark_stage(manifest: Dict[str, Any], stage: str, status: str, note: str | None = None, **extra: Any) -> Dict[str, Any]:
    if "stages" not in manifest:
        manifest["stages"] = {}
    current = manifest["stages"].setdefault(stage, {})
    current.update({"status": status, "updated_at": utc_now_iso()})
    if note:
        current["note"] = note
    if extra:
        current.update(extra)
    if status == "failed":
        manifest["status"] = "blocked"
    elif status == "running":
        manifest["status"] = "running"

    # Auto-notify on terminal transitions
    if status in ("done", "failed", "skipped"):
        completed = sum(1 for s in manifest.get("stages", {}).values() if s.get("status") == "done")
        _auto_notify("close-reading", manifest.get("run_id", ""), stage, status,
                     note=note or "", total=len(PIPELINE_STAGE_ORDER), completed=completed)

    return manifest


def _auto_notify(kind: str, run_id: str, stage: str, status: str,
                 note: str = "", total: int = 0, completed: int = 0) -> None:
    """Best-effort Telegram notification — never blocks the pipeline."""
    tg_notify = Path(__file__).resolve().parent / "tg_notify.py"
    if not tg_notify.exists():
        return
    try:
        cmd = [
            sys.executable, str(tg_notify),
            "--kind", kind,
            "--run-id", run_id,
            "--stage", stage,
            "--status", status,
            "--total-stages", str(total),
            "--completed-stages", str(completed),
        ]
        if note:
            cmd.extend(["--note", note[:200]])
        subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def render_template(text: str, mapping: Dict[str, str]) -> str:
    rendered = text
    for key, value in mapping.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    remaining = re.findall(r"\{\{[A-Z_]+\}\}", rendered)
    if remaining:
        raise ValueError(f"模板中有未替换的变量：{remaining}")
    return rendered


def load_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    return path.read_text(encoding="utf-8")


def extract_section_body(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)")
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def count_numbered_subsections(section_body: str) -> int:
    return len(re.findall(r"(?m)^###\s+\d+\b", section_body))


def heading_positions(markdown: str, headings: List[str]) -> Dict[str, int]:
    positions: Dict[str, int] = {}
    for heading in headings:
        token = f"## {heading}"
        positions[heading] = markdown.find(token)
    return positions


def has_source_link_near_top(markdown: str) -> bool:
    top = "\n".join(markdown.splitlines()[:30])
    return bool(re.search(r"https?://", top)) and ("原文链接" in top or "链接" in top or "URL" in top)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
