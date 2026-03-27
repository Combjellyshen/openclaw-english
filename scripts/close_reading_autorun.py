#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = ROOT / "reading-log" / "runs"

DONE_STAGES = ["assembled", "validated", "pdf_built", "index_updated"]
BLOCKING_STAGES = [
    "exam_matched",
    "vocab_built",
    "structure_summary_done",
    "grammar_done",
    "insights_done",
    "discussion_exam_done",
    "assembled",
    "validated",
    "pdf_built",
    "index_updated",
]


def run(cmd: list[str], timeout: int = 7200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def load_manifest(run_dir: Path) -> dict:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def stage_status(manifest: dict, stage: str) -> str:
    return manifest.get("stages", {}).get(stage, {}).get("status", "pending")


def current_stage(manifest: dict) -> str:
    for stage in BLOCKING_STAGES:
        s = stage_status(manifest, stage)
        if s != "done":
            return stage
    return "index_updated"


def print_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2), flush=True)


def maybe_repair_after_validation_failure(run_dir: Path, manifest: dict, timeout: int) -> bool:
    if stage_status(manifest, "validated") != "failed":
        return False
    report_path = Path(manifest["paths"]["validation_json"])
    if not report_path.exists():
        return False
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors = report.get("article", {}).get("errors", [])
    needs_root_fix = any("词根词缀解析" in str(err) for err in errors)
    if not needs_root_fix:
        return False

    repaired_json = str(run_dir / "artifacts" / "vocab.repaired.json")
    repaired_md = str(run_dir / "artifacts" / "vocab.repaired.md")
    vocab_json = manifest["paths"]["vocab_json"]
    run([
        "python3", str(ROOT / "scripts" / "repair_close_reading_vocab.py"),
        vocab_json,
        "--out-json", repaired_json,
        "--out-md", repaired_md,
    ], timeout=timeout)
    run([
        "python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "attach-vocab",
        "--run-dir", str(run_dir),
        "--md-file", repaired_md,
        "--json-file", repaired_json,
    ], timeout=1200)
    run([
        "python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "assemble",
        "--run-dir", str(run_dir),
    ], timeout=1200)
    validate_proc = run([
        "python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "validate",
        "--run-dir", str(run_dir),
    ], timeout=1200)
    return validate_proc.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-run close reading pipeline until pdf/index are ready.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--sleep-seconds", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not (run_dir / "manifest.json").exists():
        print_json({"ok": False, "error": f"manifest not found: {run_dir / 'manifest.json'}"})
        raise SystemExit(1)

    # Pre-check: fail fast if unrecoverable prerequisites are missing
    manifest = load_manifest(run_dir)
    if stage_status(manifest, "source_attached") != "done":
        print_json({"ok": False, "error": "source_attached 未完成，需要先 attach-source"})
        raise SystemExit(1)

    attempt = 0
    last_error = ""
    prev_stage = ""
    same_stage_count = 0
    while attempt < args.max_attempts:
        attempt += 1
        manifest = load_manifest(run_dir)
        if all(stage_status(manifest, s) == "done" for s in DONE_STAGES):
            print_json({"ok": True, "attempt": attempt, "status": "ready", "current_stage": current_stage(manifest)})
            return

        proc = run([
            "python3", str(ROOT / "scripts" / "claude_pipeline_runner.py"),
            "close-reading",
            "--run-dir", str(run_dir),
            "--build-pdf",
            "--update-index",
            "--timeout", str(args.timeout),
        ], timeout=args.timeout + 600)

        manifest = load_manifest(run_dir)
        if all(stage_status(manifest, s) == "done" for s in DONE_STAGES):
            print_json({"ok": True, "attempt": attempt, "status": "ready", "current_stage": current_stage(manifest)})
            return

        if maybe_repair_after_validation_failure(run_dir, manifest, args.timeout):
            manifest = load_manifest(run_dir)
            if all(stage_status(manifest, s) == "done" for s in DONE_STAGES):
                print_json({"ok": True, "attempt": attempt, "status": "ready", "current_stage": current_stage(manifest)})
                return

        # Detect stuck-on-same-stage (no progress) — give up after 3 consecutive
        cur = current_stage(manifest)
        if cur == prev_stage:
            same_stage_count += 1
            if same_stage_count >= 3:
                last_error = (proc.stderr or proc.stdout or "").strip()
                print_json({
                    "ok": False,
                    "status": "stuck",
                    "attempts": attempt,
                    "current_stage": cur,
                    "last_error": last_error[-2000:],
                })
                raise SystemExit(1)
        else:
            same_stage_count = 0
            prev_stage = cur

        last_error = (proc.stderr or proc.stdout or "").strip()
        # Exponential backoff: 10s, 20s, 40s, ...
        sleep_time = min(args.sleep_seconds * (2 ** (attempt - 1)), 120)
        print_json({
            "ok": False,
            "attempt": attempt,
            "status": "retrying",
            "current_stage": cur,
            "next_retry_in": sleep_time,
            "last_error": last_error[-1200:],
        })
        time.sleep(sleep_time)

    manifest = load_manifest(run_dir)
    print_json({
        "ok": False,
        "status": "exhausted",
        "attempts": args.max_attempts,
        "current_stage": current_stage(manifest),
        "last_error": last_error[-2000:],
    })
    raise SystemExit(1)


if __name__ == "__main__":
    main()
