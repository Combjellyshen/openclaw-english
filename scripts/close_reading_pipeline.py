#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

from close_reading_common import (
    INDEX_PATH,
    PIPELINE_STAGE_ORDER,
    REQUIRED_SECTION_TITLES,
    RUNS_DIR,
    SUBAGENT_TASKS,
    ARTICLES_DIR,
    PDFS_DIR,
    ensure_run_dirs,
    extract_section_body,
    load_manifest,
    load_template,
    manifest_path,
    mark_stage,
    new_manifest,
    render_template,
    save_manifest,
    slugify,
    utc_now_iso,
    write_json,
    latest_run_dir,
)
from validate_close_reading import validate_article, validate_manifest


STAGE_BY_MODULE = {
    "structure_summary": "structure_summary_done",
    "grammar": "grammar_done",
    "insights": "insights_done",
    "discussion_exam": "discussion_exam_done",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def copy_into(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def notify_progress(manifest: Dict, stage: str, status: str, note: str = "") -> None:
    # Auto-notification is now handled inside mark_stage() via tg_notify.py.
    # This function is kept for backward compatibility but is a no-op.
    pass


def start_run(args: argparse.Namespace) -> None:
    ensure_run_dirs()
    slug = args.slug or slugify(args.topic or args.title)
    run_id = f"{args.lesson_date}-{slug}"
    run_dir = RUNS_DIR / run_id
    if run_dir.exists() and not args.force:
        fail(f"run 已存在：{run_dir}（如需覆盖，追加 --force）")
    if run_dir.exists() and args.force:
        shutil.rmtree(run_dir)
    (run_dir / "prompts").mkdir(parents=True, exist_ok=True)
    (run_dir / "modules").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    article = {
        "slug": slug,
        "title": args.title,
        "source": args.source,
        "url": args.url,
        "author": args.author or "",
        "date": args.lesson_date,
        "published_date": args.published_date or "",
        "topic": args.topic,
        "difficulty": args.difficulty or "C1",
        "word_count": args.word_count or 0,
    }
    manifest = new_manifest(article, run_dir)

    mapping = {
        "RUN_DIR": str(run_dir),
        "RUN_ID": manifest["run_id"],
        "ARTICLE_TITLE": article["title"],
        "ARTICLE_SOURCE": article["source"],
        "ARTICLE_URL": article["url"],
        "ARTICLE_AUTHOR": article["author"],
        "ARTICLE_TOPIC": article["topic"],
        "ARTICLE_DIFFICULTY": article["difficulty"],
        "ORIGINAL_ARTICLE_PATH": manifest["paths"]["original_article"],
        "VOCAB_JSON_PATH": manifest["paths"]["vocab_json"],
        "VOCAB_MD_PATH": manifest["paths"]["vocab_markdown"],
    }
    for task in manifest["subagent_tasks"]:
        template_text = load_template(task["template"])
        prompt_text = render_template(template_text, mapping)
        Path(task["prompt_path"]).write_text(prompt_text, encoding="utf-8")

    save_manifest(run_dir, manifest)
    print(json.dumps({
        "ok": True,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "original_article": manifest["paths"]["original_article"],
    }, ensure_ascii=False, indent=2))


def generic_mark_stage(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    if args.stage not in PIPELINE_STAGE_ORDER:
        fail(f"未知 stage：{args.stage}")
    mark_stage(manifest, args.stage, args.status, note=args.note or None)
    save_manifest(run_dir, manifest)
    notify_progress(manifest, args.stage, args.status, args.note or "")
    print(f"updated: {args.stage} -> {args.status}")


def attach_source(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    src = Path(args.file)
    if not src.exists():
        fail(f"源文件不存在：{src}")
    dst = Path(manifest["paths"]["original_article"])
    if src.resolve() != dst.resolve():
        copy_into(src, dst)
    mark_stage(manifest, "source_attached", "done", note=f"copied from {src}")
    save_manifest(run_dir, manifest)
    notify_progress(manifest, "source_attached", "done", f"copied from {src}")
    print(f"source attached -> {dst}")


def attach_vocab(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    md_src = Path(args.md_file)
    json_src = Path(args.json_file)
    if not md_src.exists() or not json_src.exists():
        fail("词汇 markdown/json 文件不存在。")

    md_text = md_src.read_text(encoding="utf-8")
    if "【待补全】" in md_text:
        fail("词汇模块仍含 【待补全】 标记；必须先补全后才能 attach-vocab。")

    banned_needles = [
        "本文优先取",
        "另一个常见义项是",
        "阅读时先锁定本文语境",
        "这些义项最好别拆开硬背",
        "这个词不适合只背一个中文词头",
        "多义词别当成一排中文义项背",
        "构词推测：先从词形与上下文一起记",
    ]
    for needle in banned_needles:
        if needle in md_text:
            fail(f"词汇模块仍含兜底模板：{needle}；必须先补全后才能 attach-vocab。")

    data = json.loads(json_src.read_text(encoding="utf-8"))
    pending_words = []
    for bucket in [data.get("focus_items", []), data.get("hard_items", [])]:
        for item in bucket:
            if item.get("needs_deep_enrichment") or item.get("has_pending_content"):
                pending_words.append(str(item.get("word", "")))
    if pending_words:
        fail("以下词条仍未完成深度补全，禁止 attach-vocab：" + "、".join(pending_words[:20]))

    md_dst = Path(manifest["paths"]["vocab_markdown"])
    json_dst = Path(manifest["paths"]["vocab_json"])
    if md_src.resolve() != md_dst.resolve():
        copy_into(md_src, md_dst)
    if json_src.resolve() != json_dst.resolve():
        copy_into(json_src, json_dst)
    exam_dst = Path(manifest["paths"]["exam_json"])
    summary = data.get("summary", {})
    write_json(exam_dst, summary)
    mark_stage(manifest, "exam_matched", "done", note="exam counts captured via build_close_reading_vocab")
    mark_stage(manifest, "vocab_built", "done", note=f"copied from {md_src}")
    save_manifest(run_dir, manifest)
    notify_progress(manifest, "exam_matched", "done", "exam counts captured via build_close_reading_vocab")
    notify_progress(manifest, "vocab_built", "done", f"copied from {md_src}")
    print(f"vocab attached -> {md_dst}")


def attach_module(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    module_name = args.name
    task = next((task for task in manifest["subagent_tasks"] if task["name"] == module_name), None)
    if not task:
        fail(f"未知模块：{module_name}")
    src = Path(args.file)
    if not src.exists():
        fail(f"模块文件不存在：{src}")
    dst = Path(task["output_path"])
    if src.resolve() != dst.resolve():
        copy_into(src, dst)
    text = dst.read_text(encoding="utf-8")
    missing = [heading for heading in task["required_headings"] if f"## {heading}" not in text]
    if missing:
        fail(f"模块 {module_name} 缺少必需标题：{'、'.join(missing)}")
    stage = STAGE_BY_MODULE[module_name]
    mark_stage(manifest, stage, "done", note=f"copied from {src}")
    save_manifest(run_dir, manifest)
    notify_progress(manifest, stage, "done", f"copied from {src}")
    print(f"module attached -> {dst}")


def require_done(manifest: Dict, stage: str) -> None:
    status = manifest.get("stages", {}).get(stage, {}).get("status")
    if status != "done":
        fail(f"pipeline 未完成阶段：{stage}")


def front_matter(article: Dict) -> str:
    lines = [
        f"# {article['title']}",
        "",
        f"- **来源：** {article['source']}",
    ]
    if article.get("author"):
        lines.append(f"- **作者：** {article['author']}")
    if article.get("published_date"):
        lines.append(f"- **发布日期：** {article['published_date']}")
    if article.get("difficulty"):
        lines.append(f"- **难度：** {article['difficulty']}")
    if article.get("word_count"):
        lines.append(f"- **字数：** {article['word_count']}")
    lines.append(f"- **原文链接：** {article['url']}")
    lines.append("")
    return "\n".join(lines)


def assemble(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")

    for stage in [
        "source_attached",
        "exam_matched",
        "notebook_ingested",
        "vocab_built",
        "structure_summary_done",
        "grammar_done",
        "insights_done",
        "discussion_exam_done",
    ]:
        require_done(manifest, stage)

    article = manifest["article"]
    paths = manifest["paths"]
    structure_path = next(task["output_path"] for task in manifest["subagent_tasks"] if task["name"] == "structure_summary")
    grammar_path = next(task["output_path"] for task in manifest["subagent_tasks"] if task["name"] == "grammar")
    insights_path = next(task["output_path"] for task in manifest["subagent_tasks"] if task["name"] == "insights")
    discussion_path = next(task["output_path"] for task in manifest["subagent_tasks"] if task["name"] == "discussion_exam")

    sections = [
        front_matter(article).strip(),
        Path(structure_path).read_text(encoding="utf-8").strip(),
        Path(paths["vocab_markdown"]).read_text(encoding="utf-8").strip(),
        Path(grammar_path).read_text(encoding="utf-8").strip(),
        Path(insights_path).read_text(encoding="utf-8").strip(),
        Path(discussion_path).read_text(encoding="utf-8").strip(),
        "## Original Article\n\n" + re.sub(r"(?m)^##\s+", "### ", Path(paths["original_article"]).read_text(encoding="utf-8").strip()),
    ]
    final_md = "\n\n---\n\n".join(section for section in sections if section)
    out_path = Path(args.out) if args.out else Path(paths["article_markdown"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(final_md + "\n", encoding="utf-8")

    manifest["paths"]["article_markdown"] = str(out_path)
    mark_stage(manifest, "assembled", "done", note=f"assembled to {out_path}")
    save_manifest(run_dir, manifest)
    notify_progress(manifest, "assembled", "done", f"assembled to {out_path.name}")
    print(f"assembled -> {out_path}")


def run_validation(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    article_path = Path(args.article_file or manifest["paths"]["article_markdown"])
    report = {
        "ok": False,
        "article": validate_article(article_path.read_text(encoding="utf-8")),
        "manifest": validate_manifest(run_dir),
        "validated_at": utc_now_iso(),
    }
    report["ok"] = report["article"]["ok"] and report["manifest"]["ok"]
    out_path = Path(args.out_json) if args.out_json else Path(manifest["paths"]["validation_json"])
    write_json(out_path, report)
    status = "done" if report["ok"] else "failed"
    mark_stage(manifest, "validated", status, note=str(out_path))
    save_manifest(run_dir, manifest)
    notify_progress(manifest, "validated", status, str(out_path))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


def mark_pdf(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "validated")
    src = Path(args.file)
    if not src.exists():
        fail(f"PDF 不存在：{src}")
    dst = Path(manifest["paths"]["pdf"])
    if src.resolve() != dst.resolve():
        copy_into(src, dst)
    mark_stage(manifest, "pdf_built", "done", note=f"pdf ready at {dst}")
    save_manifest(run_dir, manifest)
    notify_progress(manifest, "pdf_built", "done", f"pdf ready at {dst.name}")
    print(f"pdf marked -> {dst}")


def append_index(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "validated")
    require_done(manifest, "pdf_built")

    article_md = Path(manifest["paths"]["article_markdown"])
    text = article_md.read_text(encoding="utf-8")
    summary = extract_section_body(text, "中文概要").splitlines()
    summary = [line.strip(" -") for line in summary if line.strip()]
    summary_zh = " ".join(summary[:2]).strip()

    index = []
    if INDEX_PATH.exists():
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    entry = {
        "date": manifest["article"]["date"],
        "title": manifest["article"]["title"],
        "source": manifest["article"]["source"],
        "url": manifest["article"]["url"],
        "topic": manifest["article"]["topic"],
        "difficulty": manifest["article"]["difficulty"],
        "word_count": manifest["article"]["word_count"],
        "file": article_md.name,
        "summary_zh": summary_zh,
    }
    index = [row for row in index if row.get("file") != article_md.name]
    index.append(entry)
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_stage(manifest, "index_updated", "done", note=f"updated {INDEX_PATH}")
    save_manifest(run_dir, manifest)
    notify_progress(manifest, "index_updated", "done", f"updated {INDEX_PATH.name}")
    print(f"index updated -> {INDEX_PATH}")


def mark_delivered(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "validated")
    require_done(manifest, "pdf_built")
    require_done(manifest, "index_updated")
    note = args.note or "delivered to user"
    mark_stage(manifest, "delivered", "done", note=note)
    save_manifest(run_dir, manifest)
    notify_progress(manifest, "delivered", "done", note)
    print("delivered marked")


def status(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir) if args.run_dir else latest_run_dir() if args.latest else None
    if run_dir is None:
        fail("必须提供 --run-dir 或 --latest")
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    print(json.dumps({
        "run_id": manifest.get("run_id"),
        "article": manifest.get("article"),
        "paths": manifest.get("paths"),
        "stages": manifest.get("stages"),
        "subagent_tasks": manifest.get("subagent_tasks"),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Hard-gated close-reading pipeline manager.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start-run", help="Create a run manifest + fixed subagent prompt files.")
    p.add_argument("--lesson-date", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--topic", required=True)
    p.add_argument("--author", default="")
    p.add_argument("--published-date", default="")
    p.add_argument("--difficulty", default="C1")
    p.add_argument("--word-count", type=int, default=0)
    p.add_argument("--slug", default="")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("mark-stage", help="Manually mark a pipeline stage.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--status", required=True, choices=["pending", "done", "failed", "skipped"])
    p.add_argument("--note", default="")

    p = sub.add_parser("attach-source", help="Attach the fetched original article text to the run.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--file", required=True)

    p = sub.add_parser("attach-vocab", help="Attach vocab markdown/json generated by build_close_reading_vocab.py.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--md-file", required=True)
    p.add_argument("--json-file", required=True)

    p = sub.add_parser("attach-module", help="Attach a fixed subagent module output.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--name", required=True, choices=[task["name"] for task in SUBAGENT_TASKS])
    p.add_argument("--file", required=True)

    p = sub.add_parser("assemble", help="Assemble the final article markdown in the hard-coded section order.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out", default="")

    p = sub.add_parser("validate", help="Validate the assembled markdown and manifest; fail closed on error.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--article-file", default="")
    p.add_argument("--out-json", default="")

    p = sub.add_parser("mark-pdf", help="Mark a generated PDF as the final artifact.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--file", required=True)

    p = sub.add_parser("append-index", help="Append / replace the article entry in reading-log/index.json.")
    p.add_argument("--run-dir", required=True)

    p = sub.add_parser("mark-delivered", help="Mark the validated PDF as delivered to the user.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--note", default="")

    p = sub.add_parser("status", help="Print the run manifest summary.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")

    args = parser.parse_args()

    if args.cmd == "start-run":
        start_run(args)
    elif args.cmd == "mark-stage":
        generic_mark_stage(args)
    elif args.cmd == "attach-source":
        attach_source(args)
    elif args.cmd == "attach-vocab":
        attach_vocab(args)
    elif args.cmd == "attach-module":
        attach_module(args)
    elif args.cmd == "assemble":
        assemble(args)
    elif args.cmd == "validate":
        run_validation(args)
    elif args.cmd == "mark-pdf":
        mark_pdf(args)
    elif args.cmd == "append-index":
        append_index(args)
    elif args.cmd == "mark-delivered":
        mark_delivered(args)
    elif args.cmd == "status":
        status(args)


if __name__ == "__main__":
    main()
