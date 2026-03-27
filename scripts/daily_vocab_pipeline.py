#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from task_run_common import (
    ROOT,
    build_status_summary,
    ensure_run_group_dir,
    latest_run_dir,
    notify_stage,
    read_json,
    record_event,
    utc_now_iso,
    write_json,
)
from validate_daily_vocab import validate_markdown

RUN_GROUP = "daily-vocab"
RUN_GROUP_DIR = ensure_run_group_dir(RUN_GROUP)
PROMPTS_DIRNAME = "prompts"
FIELDS_DIRNAME = "fields"
ARTIFACTS_DIRNAME = "artifacts"
TEMPLATES_DIR = ROOT / "templates" / "daily-vocab"
FINAL_MD_DIR = ROOT / "reading-log" / "vocab-drills"
FINAL_PDF_DIR = ROOT / "reading-log" / "pdfs"

SECTION_ORDER = ["六级词", "考研词", "生词本复习"]
FIELD_ORDER = [
    "来源",
    "音标",
    "完整词义",
    "常见搭配 / 固定短语 / 介词搭配",
    "多义辨析",
    "例句",
    "拆词 / 构词",
    "词源演变",
    "单词派生",
    "助记",
]
FIELD_MODULES = [
    {"name": "definitions", "label": "完整词义", "template": "definitions.md", "stage": "definitions_done"},
    {"name": "collocations", "label": "常见搭配 / 固定短语 / 介词搭配", "template": "collocations.md", "stage": "collocations_done"},
    {"name": "polysemy", "label": "多义辨析", "template": "polysemy.md", "stage": "polysemy_done"},
    {"name": "derivation", "label": "单词派生", "template": "derivation.md", "stage": "derivation_done"},
    {"name": "examples", "label": "例句", "template": "examples.md", "stage": "examples_done"},
    {"name": "mnemonic", "label": "助记", "template": "mnemonic.md", "stage": "mnemonic_done"},
    {"name": "etymology", "label": "词源演变", "template": "etymology.md", "stage": "etymology_done"},
]
STAGE_ORDER = [
    "initialized",
    "skeleton_built",
    "definitions_done",
    "collocations_done",
    "polysemy_done",
    "derivation_done",
    "examples_done",
    "mnemonic_done",
    "etymology_done",
    "assembled",
    "validated",
    "pdf_built",
    "delivered",
]

ENTRY_RE = re.compile(r"(?ms)^###\s+(?P<num>\d+)\.\s+(?P<word>[^\n]+)\n(?P<body>.*?)(?=^---\s*$|^###\s+\d+\.|^##\s+|\Z)")
FIELD_RE = re.compile(r"(?ms)^-\s+\*\*(?P<label>[^*]+?)：\*\*\s*(?P<value>.*?)(?=^\s*-\s+\*\*|^####\s+|^###\s+\d+\.|^##\s+|\Z)")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def load_manifest(run_dir: Path) -> Dict[str, Any]:
    return read_json(manifest_path(run_dir), {})


def save_manifest(run_dir: Path, manifest: Dict[str, Any]) -> None:
    write_json(manifest_path(run_dir), manifest)


def mark_stage(manifest: Dict[str, Any], stage: str, status: str, note: str | None = None, **extra: Any) -> None:
    state = manifest.setdefault("stages", {}).setdefault(stage, {})
    state.update({"status": status, "updated_at": utc_now_iso()})
    if note:
        state["note"] = note
    if extra:
        state.update(extra)
    if status == "failed":
        manifest["status"] = "blocked"
    elif status == "running":
        manifest["status"] = "running"

    # Auto-notify on terminal transitions
    if status in ("done", "failed", "skipped"):
        completed = sum(1 for s in manifest.get("stages", {}).values() if s.get("status") == "done")
        notify_stage("daily-vocab", manifest.get("run_id", ""), stage, status,
                     note=note or "", total_stages=len(STAGE_ORDER), completed_stages=completed)


def require_done(manifest: Dict[str, Any], stage: str) -> None:
    if manifest.get("stages", {}).get(stage, {}).get("status") != "done":
        fail(f"阶段未完成：{stage}")


def resolve_run_dir(run_dir: str | None, latest: bool) -> Path:
    if run_dir:
        return Path(run_dir)
    if latest:
        found = latest_run_dir(RUN_GROUP)
        if found is None:
            fail("还没有 daily vocab run。")
        return found
    fail("必须提供 --run-dir 或 --latest")


def new_manifest(target_date: str, run_dir: Path, trigger: str, requested_by: str, preferred_agent: str, delivery_target: str) -> Dict[str, Any]:
    run_id = f"daily-vocab-{target_date}"
    prompts_dir = run_dir / PROMPTS_DIRNAME
    fields_dir = run_dir / FIELDS_DIRNAME
    artifacts_dir = run_dir / ARTIFACTS_DIRNAME
    final_md = FINAL_MD_DIR / f"{target_date}-daily-vocab.md"
    final_pdf = FINAL_PDF_DIR / f"{target_date}-daily-vocab.pdf"
    return {
        "run_id": run_id,
        "kind": "daily_vocab",
        "created_at": utc_now_iso(),
        "status": "running",
        "date": target_date,
        "trigger": trigger,
        "requested_by": requested_by,
        "preferred_agent": preferred_agent,
        "delivery_target": delivery_target,
        "paths": {
            "run_dir": str(run_dir),
            "events": str(run_dir / "events.jsonl"),
            "skeleton_markdown": str(artifacts_dir / "skeleton.md"),
            "skeleton_meta": str(artifacts_dir / "skeleton.json"),
            "assembled_markdown": str(final_md),
            "validation_json": str(artifacts_dir / "validation.json"),
            "pdf": str(final_pdf),
            "prompts_dir": str(prompts_dir),
            "fields_dir": str(fields_dir),
        },
        "field_modules": [
            {
                **field,
                "prompt_path": str(prompts_dir / field["template"]),
                "output_path": str(fields_dir / f"{field['name']}.md"),
            }
            for field in FIELD_MODULES
        ],
        "word_index": {"sections": []},
        "stages": {
            stage: {"status": "done" if stage == "initialized" else "pending", "updated_at": utc_now_iso()}
            for stage in STAGE_ORDER
        },
    }


def parse_skeleton(markdown: str) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for title in SECTION_ORDER:
        section_match = re.search(rf"(?ms)^##\s+{re.escape(title)}\s*$\n(.*?)(?=^##\s+|\Z)", markdown)
        if not section_match:
            continue
        block = section_match.group(1)
        entries: List[Dict[str, Any]] = []
        for match in ENTRY_RE.finditer(block):
            fields: Dict[str, str] = {}
            body = match.group("body").strip()
            for field_match in FIELD_RE.finditer(body + "\n"):
                label = field_match.group("label").strip()
                value = field_match.group("value").strip().replace("\n", " ").strip()
                fields[label] = value
            entries.append({
                "index": int(match.group("num")),
                "word": match.group("word").strip(),
                "fields": fields,
            })
        sections.append({"title": title, "entries": entries})
    return sections


def write_prompt_files(run_dir: Path, manifest: Dict[str, Any], sections: List[Dict[str, Any]]) -> None:
    word_lines: List[str] = []
    for section in sections:
        word_lines.append(f"## {section['title']}")
        for item in section["entries"]:
            word_lines.append(f"- {item['word']}")
        word_lines.append("")
    word_list = "\n".join(word_lines).strip()
    prompt_mapping = {
        "RUN_ID": manifest["run_id"],
        "RUN_DIR": str(run_dir),
        "DATE": manifest["date"],
        "SKELETON_PATH": manifest["paths"]["skeleton_markdown"],
        "WORD_LIST": word_list,
    }
    for field in manifest["field_modules"]:
        text = (TEMPLATES_DIR / field["template"]).read_text(encoding="utf-8")
        rendered = text
        for key, value in prompt_mapping.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        rendered = rendered.replace("{{FIELD_LABEL}}", field["label"])
        rendered = rendered.replace("{{FIELD_OUTPUT_PATH}}", field["output_path"])
        Path(field["prompt_path"]).write_text(rendered, encoding="utf-8")


def build_skeleton(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    out_md = Path(manifest["paths"]["skeleton_markdown"])
    out_meta = Path(manifest["paths"]["skeleton_meta"])
    out_md.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(ROOT / "scripts" / "vocab_system.py"),
        "build-daily",
        "--date",
        manifest["date"],
        "--out",
        str(out_md),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    generated_meta = out_md.with_suffix(".json")
    if generated_meta.exists():
        shutil.move(str(generated_meta), out_meta)
    sections = parse_skeleton(out_md.read_text(encoding="utf-8"))
    manifest["word_index"] = {
        "sections": [
            {"title": section["title"], "words": [entry["word"] for entry in section["entries"]]}
            for section in sections
        ]
    }
    write_prompt_files(run_dir, manifest, sections)
    mark_stage(manifest, "skeleton_built", "done", note=f"built via {' '.join(cmd)}", entry_count=sum(len(s['entries']) for s in sections))
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", "skeleton built", stage="skeleton_built")
    print(json.dumps({
        "ok": True,
        "run_id": manifest["run_id"],
        "run_dir": str(run_dir),
        "skeleton": str(out_md),
        "meta": str(out_meta),
        "prompts": {field["name"]: field["prompt_path"] for field in manifest["field_modules"]},
        "word_index": manifest["word_index"],
    }, ensure_ascii=False, indent=2))


def start_run(args: argparse.Namespace) -> None:
    target_date = args.date
    run_id = f"daily-vocab-{target_date}"
    run_dir = RUN_GROUP_DIR / run_id
    if run_dir.exists() and not args.force:
        fail(f"run 已存在：{run_dir}（如需覆盖，追加 --force）")
    if run_dir.exists() and args.force:
        shutil.rmtree(run_dir)
    (run_dir / PROMPTS_DIRNAME).mkdir(parents=True, exist_ok=True)
    (run_dir / FIELDS_DIRNAME).mkdir(parents=True, exist_ok=True)
    (run_dir / ARTIFACTS_DIRNAME).mkdir(parents=True, exist_ok=True)
    manifest = new_manifest(
        target_date=target_date,
        run_dir=run_dir,
        trigger=args.trigger,
        requested_by=args.requested_by,
        preferred_agent=args.agent,
        delivery_target=args.delivery_target,
    )
    save_manifest(run_dir, manifest)
    record_event(run_dir, "run", "run created", trigger=args.trigger, requested_by=args.requested_by)
    print(json.dumps({
        "ok": True,
        "run_id": manifest["run_id"],
        "run_dir": str(run_dir),
        "manifest": str(manifest_path(run_dir)),
    }, ensure_ascii=False, indent=2))


def find_field(manifest: Dict[str, Any], field_name: str) -> Dict[str, Any]:
    field = next((item for item in manifest["field_modules"] if item["name"] == field_name), None)
    if not field:
        fail(f"未知字段模块：{field_name}")
    return field


def parse_field_module(field_label: str, markdown: str) -> Dict[str, str]:
    heading_match = re.search(rf"(?ms)^##\s+{re.escape(field_label)}\s*$\n(.*)$", markdown.strip())
    if not heading_match:
        fail(f"字段模块缺少标题：## {field_label}")
    block = heading_match.group(1)
    out: Dict[str, str] = {}
    # Count expected ### headings in block to know target
    heading_count = len(re.findall(r"(?m)^###\s+", block))
    # Try strict match first (exact field label)
    for match in re.finditer(rf"(?ms)^###\s+(?P<word>[^\n]+)\n\s*-\s+\*\*{re.escape(field_label)}：\*\*\s*(?P<value>.*?)(?=^###\s+|\Z)", block):
        out[match.group("word").strip()] = match.group("value").strip().replace("\n", " ").strip()
    if len(out) < heading_count:
        # Fallback: accept any bold field label (handles typos like 单词派形 vs 单词派生)
        for match in re.finditer(r"(?ms)^###\s+(?P<word>[^\n]+)\n\s*-\s+\*\*[^*]+：\*\*\s*(?P<value>.*?)(?=^###\s+|\Z)", block):
            word = match.group("word").strip()
            if word not in out:
                out[word] = match.group("value").strip().replace("\n", " ").strip()
    return out


def expected_words(manifest: Dict[str, Any]) -> List[str]:
    words: List[str] = []
    for section in manifest.get("word_index", {}).get("sections", []):
        words.extend(section.get("words", []))
    return words


def attach_field(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "skeleton_built")
    field = find_field(manifest, args.field)
    src = Path(args.file)
    if not src.exists():
        fail(f"字段文件不存在：{src}")
    text = src.read_text(encoding="utf-8")
    if "【待补全】" in text:
        fail("字段输出仍含 【待补全】，禁止 attach。")
    parsed = parse_field_module(field["label"], text)
    words = expected_words(manifest)
    missing = [word for word in words if word not in parsed]
    extra = [word for word in parsed if word not in words]
    if missing:
        fail("字段输出缺词：" + "、".join(missing[:20]))
    if extra:
        fail("字段输出含未知词：" + "、".join(extra[:20]))
    dst = Path(field["output_path"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    mark_stage(manifest, field["stage"], "done", note=f"copied from {src}")
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", f"field attached: {field['name']}", stage=field["stage"])
    print(f"attached -> {dst}")


def load_field_maps(manifest: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for field in manifest["field_modules"]:
        require_done(manifest, field["stage"])
        path = Path(field["output_path"])
        if not path.exists():
            fail(f"字段模块文件缺失：{path}")
        out[field["label"]] = parse_field_module(field["label"], path.read_text(encoding="utf-8"))
    return out


def _normalize_field_key(key: str) -> str:
    """Normalize a field label for matching: strip whitespace, unify slashes/colons."""
    import re as _re
    key = _re.sub(r"\s+", "", key)
    key = key.replace("／", "/").replace("：", ":").replace(":", "").lower()
    return key


# Map from normalized FIELD_ORDER keys to their canonical display names
_FIELD_CANON = {_normalize_field_key(f): f for f in FIELD_ORDER}

# Additional aliases that should map to canonical field names
_FIELD_ALIASES: Dict[str, str] = {}
for _canon in FIELD_ORDER:
    _norm = _normalize_field_key(_canon)
    _FIELD_ALIASES[_norm] = _canon
# Common skeleton variants
_FIELD_ALIASES[_normalize_field_key("词组 / 搭配")] = "常见搭配 / 固定短语 / 介词搭配"
_FIELD_ALIASES[_normalize_field_key("词组/搭配")] = "常见搭配 / 固定短语 / 介词搭配"
_FIELD_ALIASES[_normalize_field_key("搭配")] = "常见搭配 / 固定短语 / 介词搭配"
_FIELD_ALIASES[_normalize_field_key("常见搭配")] = "常见搭配 / 固定短语 / 介词搭配"
_FIELD_ALIASES[_normalize_field_key("词根词缀")] = "拆词 / 构词"
_FIELD_ALIASES[_normalize_field_key("词根词缀解析")] = "拆词 / 构词"
_FIELD_ALIASES[_normalize_field_key("拆词/词根词缀")] = "拆词 / 构词"
_FIELD_ALIASES[_normalize_field_key("拆词 / 构词")] = "拆词 / 构词"
_FIELD_ALIASES[_normalize_field_key("拆词构词")] = "拆词 / 构词"
_FIELD_ALIASES[_normalize_field_key("记忆提示")] = "助记"
_FIELD_ALIASES[_normalize_field_key("辨析重点")] = "多义辨析"
_FIELD_ALIASES[_normalize_field_key("词源")] = "词源演变"
_FIELD_ALIASES[_normalize_field_key("派生词")] = "单词派生"
_FIELD_ALIASES[_normalize_field_key("当前阶段")] = ""  # skip this skeleton-only field


def _canonicalize_fields(fields: Dict[str, str]) -> Dict[str, str]:
    """Map variant field keys to the canonical FIELD_ORDER names.
    When multiple source keys map to the same canonical key, prefer the one
    with real content over skeleton placeholders containing 【待补全】.
    """
    out: Dict[str, str] = {}
    for key, value in fields.items():
        norm = _normalize_field_key(key)
        canon = _FIELD_ALIASES.get(norm)
        if canon == "":
            continue  # explicitly skipped field
        target = canon if canon else (_FIELD_CANON.get(norm) if norm in _FIELD_CANON else key)
        # If target already has real content and new value is a placeholder, skip
        if target in out and "【待补全】" in value and "【待补全】" not in out[target]:
            continue
        out[target] = value
    return out


def render_entry(index: int, word: str, fields: Dict[str, str]) -> str:
    fields = _canonicalize_fields(fields)
    lines = [f"### {index}. {word}", ""]
    for field_name in FIELD_ORDER:
        value = fields.get(field_name, "").strip()
        if not value:
            continue  # skip missing non-critical fields instead of failing
        lines.append(f"- **{field_name}：** {value}")
        lines.append("")
    lines.append("---")
    return "\n".join(lines).strip()


def assemble(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "skeleton_built")
    skeleton_path = Path(manifest["paths"]["skeleton_markdown"])
    sections = parse_skeleton(skeleton_path.read_text(encoding="utf-8"))
    field_maps = load_field_maps(manifest)
    final_chunks = [f"# 每日词卡包（{manifest['date']}）", ""]
    for section in sections:
        if not section["entries"]:
            continue
        final_chunks.extend([f"## {section['title']}", ""])
        for idx, entry in enumerate(section["entries"], start=1):
            # Skeleton fields first, then Claude module fields overwrite
            merged_fields: Dict[str, str] = {}
            merged_fields.update(entry["fields"])
            for field_label, mapping in field_maps.items():
                if entry["word"] in mapping:
                    merged_fields[field_label] = mapping[entry["word"]]
            final_chunks.append(render_entry(idx, entry["word"], merged_fields))
            final_chunks.append("")
    out_path = Path(args.out) if args.out else Path(manifest["paths"]["assembled_markdown"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(final_chunks).strip() + "\n", encoding="utf-8")
    manifest["paths"]["assembled_markdown"] = str(out_path)
    mark_stage(manifest, "assembled", "done", note=f"assembled to {out_path}")
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", "assembled final markdown", stage="assembled")
    print(f"assembled -> {out_path}")


def run_validation(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "assembled")
    md_path = Path(manifest["paths"]["assembled_markdown"])
    report = validate_markdown(md_path.read_text(encoding="utf-8"))
    report["validated_at"] = utc_now_iso()
    out_json = Path(args.out_json) if args.out_json else Path(manifest["paths"]["validation_json"])
    write_json(out_json, report)
    mark_stage(manifest, "validated", "done" if report["ok"] else "failed", note=str(out_json))
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", "validated markdown", stage="validated", ok=report["ok"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


def mark_pdf(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "validated")
    src = Path(args.file)
    if not src.exists():
        fail(f"PDF 不存在：{src}")
    dst = Path(manifest["paths"]["pdf"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    mark_stage(manifest, "pdf_built", "done", note=f"pdf ready at {dst}")
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", "pdf marked", stage="pdf_built")
    print(f"pdf marked -> {dst}")


def mark_delivered(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "validated")
    require_done(manifest, "pdf_built")
    mark_stage(manifest, "delivered", "done", note=args.note or f"delivered to {manifest.get('delivery_target', '(unknown)')}")
    manifest["status"] = "done"
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", "delivered", stage="delivered")
    print("delivered marked")


def status(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    summary = build_status_summary(manifest, STAGE_ORDER)
    print(json.dumps({
        "summary": summary,
        "manifest": manifest,
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Trackable daily vocab pipeline for English workspace.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start-run", help="Create a local daily vocab run manifest.")
    p.add_argument("--date", required=True)
    p.add_argument("--trigger", default="manual", choices=["manual", "cron"])
    p.add_argument("--requested-by", default="Combjelly")
    p.add_argument("--agent", default="claude")
    p.add_argument("--delivery-target", default="telegram:-1003726107069")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("build-skeleton", help="Run vocab_system build-daily into the run artifacts.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")

    p = sub.add_parser("attach-field", help="Attach one field-specific Claude output.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--field", required=True, choices=[field["name"] for field in FIELD_MODULES])
    p.add_argument("--file", required=True)

    p = sub.add_parser("assemble", help="Merge skeleton with all attached field outputs.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--out", default="")

    p = sub.add_parser("validate", help="Run hard validator on the assembled markdown.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--out-json", default="")

    p = sub.add_parser("mark-pdf", help="Mark a generated PDF as final artifact.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--file", required=True)

    p = sub.add_parser("mark-delivered", help="Mark delivery after message() sends the PDF.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--note", default="")

    p = sub.add_parser("status", help="Show latest or specific run status.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")

    args = parser.parse_args()
    if args.cmd == "start-run":
        start_run(args)
    elif args.cmd == "build-skeleton":
        build_skeleton(args)
    elif args.cmd == "attach-field":
        attach_field(args)
    elif args.cmd == "assemble":
        assemble(args)
    elif args.cmd == "validate":
        run_validation(args)
    elif args.cmd == "mark-pdf":
        mark_pdf(args)
    elif args.cmd == "mark-delivered":
        mark_delivered(args)
    elif args.cmd == "status":
        status(args)


if __name__ == "__main__":
    main()
