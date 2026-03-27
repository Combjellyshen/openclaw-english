#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PENDING = "【待补全】"
FIELDS = ["多义辨析", "词源演变", "单词派生"]


def fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False, indent=2), file=sys.stderr)
    raise SystemExit(1)


def build_prompt(payload: dict[str, Any]) -> str:
    lines = [
        "你现在要补全英语精读词汇卡里所有仍含【待补全】的字段。",
        "不要返回 JSON。不要解释。不要代码块。严格按我给的分隔块格式输出。",
        "",
        "每个单词输出一个块，格式必须完全如下：",
        "===WORD=== academic",
        "===多义辨析===",
        "这里写内容",
        "===词源演变===",
        "这里写内容",
        "===单词派生===",
        "这里写内容",
        "===END===",
        "",
        "要求：",
        "1. 每个字段都必须是具体内容，禁止出现【待补全】、模板句、空话。",
        "2. 多义辨析：先讲核心义/核心关系，再讲义项分化路径，再讲至少两个语境差异，再补一个近义词差别。",
        "3. 词源演变：优先保留我给你的 MW etymology；然后补一小段词根词缀解析。若 MW 缺失，可明确标注'构词推测'。",
        "4. 单词派生：写 2-4 个高迁移词族成员，并讲它们和原词的关系，不要机械堆词。",
        "5. 全部用中文，必要时保留英文词形。",
        "6. 不要漏词，不要改词名。",
        "",
        "待补全词条数据如下：",
        json.dumps(payload, ensure_ascii=False, indent=2),
    ]
    return "\n".join(lines)


def parse_blocks(text: str) -> list[dict[str, str]]:
    # Use loose pattern that doesn't require ===END=== — handles both formats
    pattern = re.compile(
        r"===WORD===\s*(.*?)\n===多义辨析===\n(.*?)\n===词源演变===\n(.*?)\n===单词派生===\n(.*?)(?=\n===WORD===|\Z)",
        re.S,
    )
    out = []
    for m in pattern.finditer(text):
        out.append({
            "word": m.group(1).strip(),
            "多义辨析": m.group(2).strip(),
            "词源演变": m.group(3).strip(),
            "单词派生": m.group(4).strip(),
        })
    return out


def merge_item(item: dict[str, Any], update: dict[str, Any]) -> None:
    for key in FIELDS:
        value = str(update.get(key, "")).strip()
        if value and PENDING not in value:
            item[key] = value
    item["has_pending_content"] = any(PENDING in str(item.get(k, "")) for k in FIELDS)
    item["needs_deep_enrichment"] = item["has_pending_content"] or bool(item.get("missing_fields"))


def render_markdown(data: dict[str, Any]) -> str:
    from build_close_reading_vocab import render_markdown as _render_markdown
    return _render_markdown(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich pending close-reading vocab fields via Claude.")
    parser.add_argument("json_file")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    path = Path(args.json_file)
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for bucket in ["focus_items", "hard_items"]:
        for item in data.get(bucket, []):
            if item.get("needs_deep_enrichment") or item.get("has_pending_content"):
                items.append({
                    "word": item.get("word"),
                    "原文例句": item.get("原文例句"),
                    "中文释义": item.get("中文释义"),
                    "常见搭配 / 固定短语 / 介词搭配": item.get("常见搭配 / 固定短语 / 介词搭配"),
                    "多义辨析": item.get("多义辨析"),
                    "词源演变": item.get("词源演变"),
                    "单词派生": item.get("单词派生"),
                })

    if not items:
        print(json.dumps({"ok": True, "updated": 0}, ensure_ascii=False, indent=2))
        return

    prompt = build_prompt({"updates_needed": items})
    out_path = path.parent / "claude_vocab_enrich.txt"
    cmd = [
        "python3", str(ROOT / "scripts" / "claude_exec.py"),
        "--prompt-text", prompt,
        "--out", str(out_path),
        "--workdir", str(ROOT),
        "--model", "sonnet",
        "--timeout", str(args.timeout),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout + 60)
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "Claude failed")
    raw = out_path.read_text(encoding="utf-8").strip()
    updates = parse_blocks(raw)
    if not updates:
        fail(f"Claude 返回内容无法按分隔块解析；raw={raw[:800]}")

    by_word = {str(u.get("word", "")).strip().lower(): u for u in updates}
    changed = 0
    for bucket in ["focus_items", "hard_items"]:
        for item in data.get(bucket, []):
            key = str(item.get("word", "")).strip().lower()
            if key in by_word:
                merge_item(item, by_word[key])
                changed += 1

    out_json = Path(args.out_json) if args.out_json else path
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    out_md = Path(args.out_md) if args.out_md else path.with_suffix(".md")
    out_md.write_text(render_markdown(data), encoding="utf-8")

    pending = []
    for bucket in [data.get("focus_items", []), data.get("hard_items", [])]:
        for item in bucket:
            if item.get("needs_deep_enrichment") or item.get("has_pending_content"):
                pending.append(item.get("word"))

    print(json.dumps({"ok": True, "updated": changed, "pending": pending}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
