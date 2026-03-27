#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = ROOT / "reading-log" / "runs"


KINDS = {
    "close-reading": RUNS_ROOT,
    "daily-vocab": RUNS_ROOT / "daily-vocab",
    "weekly-vocab": RUNS_ROOT / "weekly-vocab",
}

STAGE_ORDERS: Dict[str, List[str]] = {
    "close_reading": [
        "initialized", "source_attached", "exam_matched", "notebook_ingested",
        "vocab_built", "structure_summary_done", "grammar_done", "insights_done",
        "discussion_exam_done", "assembled", "validated", "pdf_built",
        "index_updated", "delivered",
    ],
    "daily_vocab": [
        "initialized", "skeleton_built", "polysemy_done", "derivation_done",
        "examples_done", "mnemonic_done", "etymology_done", "assembled",
        "validated", "pdf_built", "delivered",
    ],
    "weekly_vocab": [
        "initialized", "skeleton_built", "review_summary_done", "weekly_exam_done",
        "study_plan_done", "assembled", "validated", "pdf_built", "delivered",
    ],
}


def latest_manifest(kind: str) -> Tuple[Path, Dict[str, Any]] | None:
    base = KINDS[kind]
    if not base.exists():
        return None
    candidates: List[Path] = []
    for child in base.iterdir():
        if child.is_dir() and (child / "manifest.json").exists():
            candidates.append(child / "manifest.json")
    if not candidates:
        return None
    path = max(candidates, key=lambda p: (p.stat().st_mtime, p.parent.name))
    return path, json.loads(path.read_text(encoding="utf-8"))


def summarize(manifest: Dict[str, Any], kind_hint: str | None = None) -> Dict[str, Any]:
    stages = manifest.get("stages", {})
    kind = manifest.get("kind") or kind_hint or ""
    stage_order = STAGE_ORDERS.get(kind, STAGE_ORDERS.get(kind.replace("-", "_"), []))
    ordered_names = stage_order if stage_order else list(stages.keys())

    done: List[str] = []
    failed: List[str] = []
    pending: List[str] = []
    current = None
    for name in ordered_names:
        state = stages.get(name, {})
        st = state.get("status", "pending")
        if st == "done":
            done.append(name)
        elif st == "failed":
            failed.append(name)
            if current is None:
                current = name
        else:
            pending.append(name)
            if current is None:
                current = name

    return {
        "run_id": manifest.get("run_id"),
        "kind": kind or kind_hint,
        "status": manifest.get("status") or ("blocked" if failed else ("done" if not pending else "running")),
        "current_stage": current,
        "done": done,
        "failed": failed,
        "pending": pending,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Show latest English pipeline status.")
    parser.add_argument("--kind", default="auto", choices=["auto", "close-reading", "daily-vocab", "weekly-vocab"])
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    kinds = ["close-reading", "daily-vocab", "weekly-vocab"] if args.kind == "auto" else [args.kind]
    out: Dict[str, Any] = {}
    for kind in kinds:
        payload = latest_manifest(kind)
        if payload is None:
            out[kind] = {"ok": False, "error": "no runs"}
            continue
        path, manifest = payload
        item = {
            "ok": True,
            "manifest": str(path),
            "summary": summarize(manifest, kind_hint=kind.replace('-', '_')),
        }
        if args.full:
            item["manifestData"] = manifest
        out[kind] = item

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
