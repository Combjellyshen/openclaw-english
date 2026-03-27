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
    check_cross_entry_repetition,
    check_fields_present,
    fuzzy_heading_match,
)

REQUIRED_FIELDS = [
    "来源", "音标", "完整词义", "常见搭配 / 固定短语 / 介词搭配", "多义辨析",
    "例句", "拆词 / 构词", "词源演变", "单词派生", "助记",
]

# Fields where cross-entry repetition is a sign of lazy generation
REPETITION_CHECK_FIELDS = ["多义辨析", "词源演变", "单词派生", "助记"]

SECTION_TITLES = ["六级词", "考研词", "生词本复习"]

# Minimum content length for key fields (semantic density gate)
DENSITY_CHECKS = {
    "多义辨析": 24,
    "词源演变": 18,
    "单词派生": 16,
    "助记": 16,
}


def split_entries(markdown: str) -> List[str]:
    parts = re.split(r"(?m)^###\s+\d+\.\s+.+$", markdown)
    heads = re.findall(r"(?m)^###\s+\d+\.\s+.+$", markdown)
    entries: List[str] = []
    for i, head in enumerate(heads):
        body = parts[i + 1] if i + 1 < len(parts) else ""
        entries.append(head + "\n" + body)
    return entries


def title_of(entry: str) -> str:
    m = re.search(r"(?m)^###\s+(\d+\.\s+.+)$", entry)
    return m.group(1).strip() if m else "(unknown)"


def extract_field_content(entry: str, field_label: str) -> str | None:
    """Extract the value of a **label：** field from a markdown entry.
    Uses fuzzy matching on the label.
    """
    for m in re.finditer(r"-\s+\*\*([^*]+?)：\*\*\s*(.+?)(?=\n\s*-\s+\*\*|\Z)", entry, re.DOTALL):
        found_label = m.group(1).strip()
        if fuzzy_heading_match(field_label, found_label, threshold=0.72):
            return m.group(2).strip().replace("\n", " ").strip()
    return None


def validate_entry(entry: str) -> Dict[str, object]:
    errors: List[str] = []
    warnings: List[str] = []
    title = title_of(entry)

    # ── Field presence (semantic group matching) ──
    # Only truly critical fields are errors; others are warnings
    critical_fields = ["音标", "完整词义", "多义辨析", "词源演变"]
    nice_to_have = [f for f in REQUIRED_FIELDS if f not in critical_fields]

    missing_critical, _ = check_fields_present(critical_fields, entry)
    for f in missing_critical:
        errors.append(f"{title} 缺少核心字段：{f}")

    missing_nice, _ = check_fields_present(nice_to_have, entry)
    for f in missing_nice:
        warnings.append(f"{title} 缺少字段：{f}")

    # ── Content quality (pattern-family detection) ──
    hard_errors, soft_warns = check_content_quality(entry, title)
    errors.extend(hard_errors)
    warnings.extend(soft_warns)

    # ── Density checks: key fields must have real content ──
    for field_label, min_len in DENSITY_CHECKS.items():
        content = extract_field_content(entry, field_label)
        if content is not None and len(content) < min_len:
            warnings.append(f"{title} 的 {field_label} 内容过短（{len(content)}字），疑似空泛")

    # ── Structural pollution check: no embedded markdown headings inside field values ──
    for field_label in ["完整词义", "常见搭配 / 固定短语 / 介词搭配", "多义辨析", "例句", "词源演变", "单词派生", "助记"]:
        content = extract_field_content(entry, field_label)
        if content and re.search(r"(^|\s)#{2,4}\s+", content):
            errors.append(f"{title} 的 {field_label} 混入了 markdown 标题污染")

    collocation = extract_field_content(entry, "常见搭配 / 固定短语 / 介词搭配")
    if collocation:
        approx_items = [x for x in re.split(r"；|;", collocation) if x.strip()]
        if len(approx_items) < 2:
            warnings.append(f"{title} 的搭配明显偏少")
        if "（" not in collocation and "(" not in collocation:
            errors.append(f"{title} 的搭配缺少中文义")

    definition = extract_field_content(entry, "完整词义")
    if definition:
        if re.search(r"####|###|##", definition):
            errors.append(f"{title} 的完整词义混入了标题污染")
        items = [x.strip() for x in re.split(r"；|;", definition) if x.strip()]
        if len(items) >= 2 and len(set(items)) < len(items):
            errors.append(f"{title} 的完整词义存在重复义项")

    return {"title": title, "ok": not errors, "errors": errors, "warnings": warnings}


def validate_markdown(markdown: str) -> Dict[str, object]:
    errors: List[str] = []
    warnings: List[str] = []
    info: Dict[str, object] = {}

    if not markdown.lstrip().startswith("# 每日词卡包"):
        warnings.append('文档标题不是 "# 每日词卡包（YYYY-MM-DD）" 格式（非致命）。')

    present_sections = [title for title in SECTION_TITLES if f"## {title}" in markdown]
    if not present_sections:
        errors.append("缺少词卡分组标题（六级词 / 考研词 / 生词本复习）。")
    info["sections"] = present_sections

    entries = split_entries(markdown)
    info["entry_count"] = len(entries)
    if not entries:
        errors.append("没有检测到任何词条（### N. word）。")

    entry_reports = [validate_entry(entry) for entry in entries]
    for report in entry_reports:
        errors.extend(report["errors"])
        warnings.extend(report.get("warnings", []))

    # ── Cross-entry repetition check ──
    if entries:
        parsed_entries = []
        for entry in entries:
            word = title_of(entry).split(".", 1)[-1].strip() if "." in title_of(entry) else title_of(entry)
            fields: Dict[str, str] = {"word": word}
            for field_label in REPETITION_CHECK_FIELDS:
                content = extract_field_content(entry, field_label)
                if content:
                    fields[field_label] = content
            parsed_entries.append(fields)

        for field_label in REPETITION_CHECK_FIELDS:
            rep_warnings = check_cross_entry_repetition(parsed_entries, field_label)
            warnings.extend(rep_warnings)

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "entries": entry_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate daily vocab markdown against hard rules.")
    parser.add_argument("md_file", help="Path to daily vocab markdown.")
    parser.add_argument("--out-json", default=None, help="Optional JSON report path.")
    args = parser.parse_args()

    md_path = Path(args.md_file)
    markdown = md_path.read_text(encoding="utf-8")
    report = validate_markdown(markdown)

    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
