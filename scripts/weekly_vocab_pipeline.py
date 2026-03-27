#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

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
from validate_weekly_vocab import validate_markdown

RUN_GROUP = "weekly-vocab"
RUN_GROUP_DIR = ensure_run_group_dir(RUN_GROUP)
TEMPLATES_DIR = ROOT / "templates" / "weekly-vocab"
FINAL_MD_DIR = ROOT / "reading-log" / "weekly-vocab"
FINAL_PDF_DIR = ROOT / "reading-log" / "pdfs"
MODULES = [
    {
        "name": "review_summary",
        "label": "回顾总结",
        "template": "review_summary.md",
        "stage": "review_summary_done",
        "required_headings": ["本周主题回顾", "高频词提醒", "易错点 / 易混点"],
    },
    {
        "name": "weekly_exam",
        "label": "周测题",
        "template": "weekly_exam.md",
        "stage": "weekly_exam_done",
        "required_headings": ["周测题", "答案解析"],
    },
    {
        "name": "study_plan",
        "label": "复习建议",
        "template": "study_plan.md",
        "stage": "study_plan_done",
        "required_headings": ["下周复习建议"],
    },
]
STAGE_ORDER = [
    "initialized",
    "skeleton_built",
    "review_summary_done",
    "weekly_exam_done",
    "study_plan_done",
    "assembled",
    "validated",
    "pdf_built",
    "delivered",
]


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
        notify_stage("weekly-vocab", manifest.get("run_id", ""), stage, status,
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
            fail("还没有 weekly vocab run。")
        return found
    fail("必须提供 --run-dir 或 --latest")


def new_manifest(target_date: str, run_dir: Path, trigger: str, requested_by: str, preferred_agent: str, delivery_target: str) -> Dict[str, Any]:
    run_id = f"weekly-vocab-{target_date}"
    prompts_dir = run_dir / "prompts"
    modules_dir = run_dir / "modules"
    artifacts_dir = run_dir / "artifacts"
    final_md = FINAL_MD_DIR / f"{target_date}-weekly-vocab.md"
    final_pdf = FINAL_PDF_DIR / f"{target_date}-weekly-vocab.pdf"
    return {
        "run_id": run_id,
        "kind": "weekly_vocab",
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
            "modules_dir": str(modules_dir),
        },
        "modules": [
            {
                **module,
                "prompt_path": str(prompts_dir / module["template"]),
                "output_path": str(modules_dir / f"{module['name']}.md"),
            }
            for module in MODULES
        ],
        "stages": {
            stage: {"status": "done" if stage == "initialized" else "pending", "updated_at": utc_now_iso()}
            for stage in STAGE_ORDER
        },
    }


def extract_headings(markdown: str) -> List[str]:
    return re.findall(r"(?m)^##\s+(.+)$", markdown)


def write_prompt_files(run_dir: Path, manifest: Dict[str, Any], skeleton_text: str) -> None:
    mapping = {
        "RUN_ID": manifest["run_id"],
        "RUN_DIR": str(run_dir),
        "DATE": manifest["date"],
        "SKELETON_PATH": manifest["paths"]["skeleton_markdown"],
        "SKELETON_TEXT": skeleton_text.strip(),
    }
    for module in manifest["modules"]:
        text = (TEMPLATES_DIR / module["template"]).read_text(encoding="utf-8")
        rendered = text
        for key, value in mapping.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        rendered = rendered.replace("{{MODULE_OUTPUT_PATH}}", module["output_path"])
        Path(module["prompt_path"]).write_text(rendered, encoding="utf-8")


def start_run(args: argparse.Namespace) -> None:
    target_date = args.date
    run_id = f"weekly-vocab-{target_date}"
    run_dir = RUN_GROUP_DIR / run_id
    if run_dir.exists() and not args.force:
        fail(f"run 已存在：{run_dir}（如需覆盖，追加 --force）")
    if run_dir.exists() and args.force:
        shutil.rmtree(run_dir)
    (run_dir / "prompts").mkdir(parents=True, exist_ok=True)
    (run_dir / "modules").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    manifest = new_manifest(
        target_date=target_date,
        run_dir=run_dir,
        trigger=args.trigger,
        requested_by=args.requested_by,
        preferred_agent=args.agent,
        delivery_target=args.delivery_target,
    )
    save_manifest(run_dir, manifest)
    record_event(run_dir, "run", "weekly run created", trigger=args.trigger, requested_by=args.requested_by)
    print(json.dumps({
        "ok": True,
        "run_id": manifest["run_id"],
        "run_dir": str(run_dir),
        "manifest": str(manifest_path(run_dir)),
    }, ensure_ascii=False, indent=2))


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
        "build-weekly",
        "--date",
        manifest["date"],
        "--out",
        str(out_md),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    generated_meta = out_md.with_suffix(".json")
    if generated_meta.exists():
        shutil.move(str(generated_meta), out_meta)
    skeleton_text = out_md.read_text(encoding="utf-8")
    write_prompt_files(run_dir, manifest, skeleton_text)
    word_entries = len(re.findall(r"(?m)^###\s+\d+\.\s+.+$", skeleton_text))
    mark_stage(manifest, "skeleton_built", "done", note=f"built via {' '.join(cmd)}", word_entries=word_entries)
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", "weekly skeleton built", stage="skeleton_built")
    print(json.dumps({
        "ok": True,
        "run_id": manifest["run_id"],
        "run_dir": str(run_dir),
        "skeleton": str(out_md),
        "meta": str(out_meta),
        "prompts": {module["name"]: module["prompt_path"] for module in manifest["modules"]},
        "word_entries": word_entries,
    }, ensure_ascii=False, indent=2))


def find_module(manifest: Dict[str, Any], module_name: str) -> Dict[str, Any]:
    module = next((item for item in manifest["modules"] if item["name"] == module_name), None)
    if not module:
        fail(f"未知模块：{module_name}")
    return module


def attach_module(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "skeleton_built")
    module = find_module(manifest, args.module)
    src = Path(args.file)
    if not src.exists():
        fail(f"模块文件不存在：{src}")
    text = src.read_text(encoding="utf-8")
    if "【待补全】" in text:
        fail("模块输出仍含 【待补全】，禁止 attach。")
    headings = extract_headings(text)
    missing = [heading for heading in module["required_headings"] if heading not in headings]
    if missing:
        fail("模块缺少标题：" + "、".join(missing))
    dst = Path(module["output_path"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    mark_stage(manifest, module["stage"], "done", note=f"copied from {src}")
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", f"module attached: {module['name']}", stage=module["stage"])
    print(f"attached -> {dst}")


def assemble(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    require_done(manifest, "skeleton_built")
    for module in manifest["modules"]:
        require_done(manifest, module["stage"])
    skeleton = Path(manifest["paths"]["skeleton_markdown"]).read_text(encoding="utf-8").strip()
    sections = [skeleton]
    for module in manifest["modules"]:
        sections.append(Path(module["output_path"]).read_text(encoding="utf-8").strip())
    final_md = "\n\n---\n\n".join(section for section in sections if section)
    out_path = Path(args.out) if args.out else Path(manifest["paths"]["assembled_markdown"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(final_md + "\n", encoding="utf-8")
    manifest["paths"]["assembled_markdown"] = str(out_path)
    mark_stage(manifest, "assembled", "done", note=f"assembled to {out_path}")
    save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", "assembled weekly markdown", stage="assembled")
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
    record_event(run_dir, "stage", "validated weekly markdown", stage="validated", ok=report["ok"])
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
    record_event(run_dir, "stage", "weekly pdf marked", stage="pdf_built")
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
    record_event(run_dir, "stage", "weekly delivered", stage="delivered")
    print("delivered marked")


def status(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir(args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 manifest：{manifest_path(run_dir)}")
    summary = build_status_summary(manifest, STAGE_ORDER)
    print(json.dumps({"summary": summary, "manifest": manifest}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Trackable weekly vocab pipeline for English workspace.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start-run", help="Create a local weekly vocab run manifest.")
    p.add_argument("--date", required=True)
    p.add_argument("--trigger", default="manual", choices=["manual", "cron"])
    p.add_argument("--requested-by", default="Combjelly")
    p.add_argument("--agent", default="claude")
    p.add_argument("--delivery-target", default="telegram:-1003726107069")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("build-skeleton", help="Run vocab_system build-weekly into the run artifacts.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")

    p = sub.add_parser("attach-module", help="Attach one Claude-written weekly module.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--module", required=True, choices=[module["name"] for module in MODULES])
    p.add_argument("--file", required=True)

    p = sub.add_parser("assemble", help="Merge skeleton with all attached weekly modules.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--out", default="")

    p = sub.add_parser("validate", help="Run weekly validator on the assembled markdown.")
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

    p = sub.add_parser("status", help="Show latest or specific weekly run status.")
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")

    args = parser.parse_args()
    if args.cmd == "start-run":
        start_run(args)
    elif args.cmd == "build-skeleton":
        build_skeleton(args)
    elif args.cmd == "attach-module":
        attach_module(args)
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
