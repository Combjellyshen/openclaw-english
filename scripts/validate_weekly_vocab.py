#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

from validate_common import (
    check_content_quality,
    check_sections_present,
    extract_section_body_fuzzy,
)

REQUIRED_SECTIONS = [
    "本周词汇清单",
    "本周主题回顾",
    "高频词提醒",
    "易错点 / 易混点",
    "周测题",
    "答案解析",
    "下周复习建议",
]


def validate_markdown(markdown: str) -> Dict[str, object]:
    errors: List[str] = []
    warnings: List[str] = []

    if not markdown.lstrip().startswith("# 每周词汇综合卷"):
        warnings.append('文档标题不是 "# 每周词汇综合卷（...）" 格式（非致命）。')

    # ── Section presence (fuzzy) ──
    missing, _ = check_sections_present(REQUIRED_SECTIONS, markdown)
    for section in missing:
        errors.append(f"缺少模块：{section}")

    # ── Content quality (semantic) ──
    hard_errors, soft_warns = check_content_quality(markdown)
    errors.extend(hard_errors)
    warnings.extend(soft_warns)

    # ── Word entry count ──
    # Count both ### N. word format AND numbered bold entries (1. **word**)
    word_entries_h3 = re.findall(r"(?m)^###\s+\d+\.\s+.+$", markdown)
    word_entries_bold = re.findall(r"(?m)^\d+\.\s+\*\*\w+\*\*", markdown)
    word_entry_count = max(len(word_entries_h3), len(word_entries_bold))
    if word_entry_count < 10:
        if word_entry_count >= 5:
            warnings.append(f"本周词汇清单偏少：当前 {word_entry_count} 个，推荐至少 10 个。")
        else:
            errors.append(f"本周词汇清单过少：当前 {word_entry_count} 个，要求至少 10 个。")

    # ── Exam item count ──
    exam_body = extract_section_body_fuzzy(markdown, "周测题")
    exam_items = re.findall(r"(?m)^\d+\.\s+.+$", exam_body)
    if len(exam_items) < 6:
        if len(exam_items) >= 4:
            warnings.append(f"周测题偏少：当前 {len(exam_items)} 题，推荐至少 6 题。")
        else:
            errors.append(f"周测题过少：当前 {len(exam_items)} 题，要求至少 6 题。")

    # ── Answer count ──
    answers_body = extract_section_body_fuzzy(markdown, "答案解析")
    answer_items = re.findall(r"(?m)^\d+\.\s+.+$", answers_body)
    if len(answer_items) < 6:
        warnings.append(f"答案解析少于 6 条（当前 {len(answer_items)}），建议补齐。")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": {
            "word_entries": word_entry_count,
            "exam_items": len(exam_items),
            "answer_items": len(answer_items),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate weekly vocab markdown against hard rules.")
    parser.add_argument("md_file", help="Path to weekly vocab markdown.")
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args()

    report = validate_markdown(Path(args.md_file).read_text(encoding="utf-8"))
    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
