#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

from close_reading_common import (
    REQUIRED_SECTION_TITLES,
    has_source_link_near_top,
    load_manifest,
    manifest_path,
    write_json,
)
from validate_common import (
    check_content_quality,
    check_cross_entry_repetition,
    check_fields_present,
    check_sections_present,
    extract_section_body_fuzzy,
)


def count_markdown_subheads(section_body: str) -> int:
    return len(re.findall(r"(?m)^###\s+", section_body))


def count_numbered_items(section_body: str) -> int:
    # Match both "1. text" and "**1.** text" and "**1.**text" formats
    return len(re.findall(r"(?m)^(?:\*\*)?(\d+)\.(?:\*\*)?\s+", section_body))


def validate_article(markdown: str) -> Dict[str, object]:
    errors: List[str] = []
    warnings: List[str] = []
    info: Dict[str, object] = {}

    # ── Source link ──
    if not has_source_link_near_top(markdown):
        errors.append("开头缺少原文链接（source URL）。")

    # ── Section presence (fuzzy) ──
    missing_sections, positions = check_sections_present(REQUIRED_SECTION_TITLES, markdown)
    if missing_sections:
        errors.append("缺少必需模块：" + "、".join(missing_sections))
    else:
        ordered = [positions[h] for h in REQUIRED_SECTION_TITLES if h in positions]
        if ordered != sorted(ordered):
            warnings.append("模块顺序与推荐顺序不完全一致（非致命）。")

    # ── 重点词汇 ──
    vocab_body = extract_section_body_fuzzy(markdown, "重点词汇")
    vocab_count = count_markdown_subheads(vocab_body)
    info["vocab_count"] = vocab_count
    if not 8 <= vocab_count <= 12:
        errors.append(f"重点词汇数量不合格：当前 {vocab_count}，要求 8–12。")

    vocab_critical = ["音标", "中文释义", "多义辨析", "词源演变"]
    vocab_nice = ["词库标签", "原文例句", "搭配", "单词派生"]
    vc_missing, _ = check_fields_present(vocab_critical, vocab_body)
    for f in vc_missing:
        errors.append(f"重点词汇模块缺少核心字段：{f}")
    vn_missing, _ = check_fields_present(vocab_nice, vocab_body)
    for f in vn_missing:
        warnings.append(f"重点词汇模块缺少字段：{f}")

    # 词根词缀 can be standalone or embedded in 词源演变
    if not any(kw in vocab_body for kw in ["词根词缀", "词根", "前缀", "后缀", "词缀", "构词"]):
        warnings.append("重点词汇模块未见词根词缀相关内容。")

    # ── 文章难词补充 ──
    hard_body = extract_section_body_fuzzy(markdown, "文章难词补充")
    hard_count = count_markdown_subheads(hard_body)
    info["hard_word_count"] = hard_count
    if hard_count != 10:
        if 8 <= hard_count <= 12:
            warnings.append(f"文章难词补充数量偏离标准：当前 {hard_count}，推荐 10。")
        else:
            errors.append(f"文章难词补充数量不合格：当前 {hard_count}，要求 10（容差 8-12）。")

    hard_critical = ["音标", "中文释义", "多义辨析", "词源演变"]
    hard_nice = ["来源", "原文例句", "搭配", "单词派生"]
    hc_missing, _ = check_fields_present(hard_critical, hard_body)
    for f in hc_missing:
        errors.append(f"文章难词补充缺少核心字段：{f}")
    hn_missing, _ = check_fields_present(hard_nice, hard_body)
    for f in hn_missing:
        warnings.append(f"文章难词补充缺少字段：{f}")

    if not any(kw in hard_body for kw in ["词根词缀", "词根", "前缀", "后缀", "词缀", "构词"]):
        warnings.append("文章难词补充未见词根词缀相关内容。")

    # ── Content quality (semantic pattern detection) ──
    vocab_errors, vocab_warns = check_content_quality(vocab_body, "重点词汇")
    errors.extend(vocab_errors)
    warnings.extend(vocab_warns)

    hard_errors, hard_warns = check_content_quality(hard_body, "文章难词补充")
    errors.extend(hard_errors)
    warnings.extend(hard_warns)

    # ── Repetition check across vocab entries ──
    for section_name, section_body in [("重点词汇", vocab_body), ("文章难词补充", hard_body)]:
        parsed = []
        for m in re.finditer(r"(?ms)^###\s+\d+\.\s+(\S+)\s*\n(.*?)(?=^###\s+\d+\.|\Z)", section_body):
            word = m.group(1).strip()
            body = m.group(2)
            fields = {"word": word}
            for fm in re.finditer(r"(?:^|\n)\s*[-*]\s*\*\*([^*]+?)：\*\*\s*(.+?)(?=\n\s*[-*]\s*\*\*|\Z)", body, re.DOTALL):
                fields[fm.group(1).strip()] = fm.group(2).strip().replace("\n", " ")
            parsed.append(fields)
        if len(parsed) >= 4:
            for check_field in ["多义辨析", "词源演变", "单词派生"]:
                rep_warns = check_cross_entry_repetition(parsed, check_field)
                for w in rep_warns:
                    warnings.append(f"[{section_name}] {w}")

    # ── 逐句语法 ──
    grammar_body = extract_section_body_fuzzy(markdown, "逐句语法")
    grammar_count = count_markdown_subheads(grammar_body)
    info["grammar_count"] = grammar_count
    if not 8 <= grammar_count <= 15:
        if 6 <= grammar_count <= 18:
            warnings.append(f"逐句语法数量偏离标准：当前 {grammar_count}，推荐 8–15。")
        else:
            errors.append(f"逐句语法数量不合格：当前 {grammar_count}，要求 8–15。")

    # ── 精读句子 ──
    close_reading_body = extract_section_body_fuzzy(markdown, "精读句子")
    close_reading_count = count_markdown_subheads(close_reading_body)
    info["close_reading_count"] = close_reading_count
    if close_reading_count < 2:
        errors.append(f"精读句子数量不合格：当前 {close_reading_count}，要求至少 2 句。")
    elif close_reading_count != 3:
        warnings.append(f"精读句子数量偏离标准：当前 {close_reading_count}，推荐 3 句。")

    # ── 理解 / 讨论问题 ──
    discussion_body = extract_section_body_fuzzy(markdown, "理解 / 讨论问题")
    if not discussion_body:
        discussion_body = extract_section_body_fuzzy(markdown, "讨论问题")
    discussion_count = count_numbered_items(discussion_body)
    info["discussion_count"] = discussion_count
    if not 4 <= discussion_count <= 6:
        if 3 <= discussion_count <= 8:
            warnings.append(f"讨论问题数量偏离标准：当前 {discussion_count}，推荐 4–6。")
        else:
            errors.append(f"讨论问题数量不合格：当前 {discussion_count}，要求 4–6。")

    # ── 相关巩固题 ──
    practice_body = extract_section_body_fuzzy(markdown, "相关巩固题")
    practice_count = count_numbered_items(practice_body)
    info["practice_count"] = practice_count
    if not 6 <= practice_count <= 8:
        if 4 <= practice_count <= 10:
            warnings.append(f"相关巩固题数量偏离标准：当前 {practice_count}，推荐 6–8。")
        else:
            errors.append(f"相关巩固题数量不合格：当前 {practice_count}，要求 6–8。")

    # ── 考题 ──
    exam_body = extract_section_body_fuzzy(markdown, "考题")
    exam_sub_sections = ["词汇题", "语法题", "阅读题"]
    translation_variants = ["翻译 / 写作题", "翻译/写作题", "翻译题", "写作题"]
    for sub in exam_sub_sections:
        if sub not in exam_body:
            # Fuzzy: maybe embedded in ### headings
            if not re.search(rf"(?m)^###.*{re.escape(sub)}", exam_body):
                warnings.append(f"考题模块可能缺少子块：{sub}")
    if not any(v in exam_body for v in translation_variants):
        if not re.search(r"(?m)^###.*(翻译|写作)", exam_body):
            warnings.append("考题模块可能缺少翻译/写作题。")

    # ── Original Article ──
    original_body = extract_section_body_fuzzy(markdown, "Original Article")
    if not original_body:
        original_body = extract_section_body_fuzzy(markdown, "原文")
    original_word_count = len(re.findall(r"[A-Za-z]+", original_body))
    info["original_word_count"] = original_word_count
    if original_word_count < 400:
        errors.append(f"Original Article 内容过短：当前约 {original_word_count} 词，疑似未附全文。")

    if original_word_count < 30 and ("http://" in original_body or "https://" in original_body):
        errors.append("Original Article 只放了链接，没有附全文。")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


def validate_manifest(run_dir: Path) -> Dict[str, object]:
    manifest = load_manifest(run_dir)
    errors: List[str] = []
    warnings: List[str] = []
    if not manifest:
        return {"ok": False, "errors": [f"manifest 不存在：{manifest_path(run_dir)}"], "warnings": []}

    required_done = [
        "source_attached",
        "exam_matched",
        "notebook_ingested",
        "vocab_built",
        "structure_summary_done",
        "grammar_done",
        "insights_done",
        "discussion_exam_done",
        "assembled",
    ]
    for stage in required_done:
        state = manifest.get("stages", {}).get(stage, {})
        if state.get("status") != "done":
            errors.append(f"pipeline 阶段未完成：{stage}")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "manifest": manifest.get("run_id")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a close-reading markdown file against the hard pipeline rules.")
    parser.add_argument("article_file", help="Path to the assembled markdown article.")
    parser.add_argument("--run-dir", default=None, help="Optional run directory for manifest checks.")
    parser.add_argument("--out-json", default=None, help="Optional JSON report path.")
    args = parser.parse_args()

    article_path = Path(args.article_file)
    markdown = article_path.read_text(encoding="utf-8")
    article_report = validate_article(markdown)

    manifest_report = None
    if args.run_dir:
        manifest_report = validate_manifest(Path(args.run_dir))

    ok = article_report["ok"] and (manifest_report is None or manifest_report["ok"])
    report = {
        "ok": ok,
        "article": article_report,
        "manifest": manifest_report,
    }

    if args.out_json:
        write_json(Path(args.out_json), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
