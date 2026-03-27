#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List

ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = ROOT / "reading-log" / "runs"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Corrupted JSON — try backup
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            try:
                return json.loads(backup.read_text(encoding="utf-8"))
            except Exception:
                pass
        return default


def write_json(path: Path, data: Any) -> None:
    """Atomic JSON write: temp file -> rename to avoid corruption on crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    # Write to temp file in the same directory, then atomic rename
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=path.stem)
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        closed = True
        # Keep a backup of the previous version
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            try:
                os.replace(str(path), str(backup))
            except OSError:
                pass
        os.rename(tmp, str(path))
    except Exception:
        if not closed:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def manifest_lock(run_dir: Path) -> Iterator[None]:
    """Advisory file lock on manifest to prevent concurrent writes."""
    lock_path = run_dir / ".manifest.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False) + "\n")


def ensure_run_group_dir(group: str) -> Path:
    out = RUNS_ROOT / group
    out.mkdir(parents=True, exist_ok=True)
    return out


def latest_run_dir(group: str) -> Path | None:
    group_dir = ensure_run_group_dir(group)
    candidates: List[Path] = []
    for child in group_dir.iterdir():
        if child.is_dir() and (child / "manifest.json").exists():
            candidates.append(child)
    if not candidates:
        return None
    return max(candidates, key=lambda p: ((p / "manifest.json").stat().st_mtime, p.name))


def build_status_summary(manifest: Dict[str, Any], stage_order: Iterable[str]) -> Dict[str, Any]:
    stages = manifest.get("stages", {})
    ordered = list(stage_order)
    completed: List[str] = []
    running: str | None = None
    blocked: str | None = None
    pending: List[str] = []

    for stage in ordered:
        state = stages.get(stage, {})
        status = state.get("status", "pending")
        if status == "done":
            completed.append(stage)
        elif status == "failed":
            blocked = stage
        elif status == "running":
            if running is None:
                running = stage
            pending.append(stage)
        else:
            pending.append(stage)

    overall = manifest.get("status") or ("blocked" if blocked else "running")
    if all(stages.get(stage, {}).get("status") == "done" for stage in ordered):
        overall = "done"
    elif blocked:
        overall = "blocked"

    return {
        "run_id": manifest.get("run_id"),
        "kind": manifest.get("kind"),
        "status": overall,
        "current_stage": running or blocked or next((stage for stage in ordered if stages.get(stage, {}).get("status") != "done"), ordered[-1] if ordered else None),
        "completed": completed,
        "pending": pending,
        "blocked": blocked,
    }


def record_event(run_dir: Path, kind: str, message: str, **extra: Any) -> None:
    append_jsonl(run_dir / "events.jsonl", {
        "at": utc_now_iso(),
        "kind": kind,
        "message": message,
        **extra,
    })


_NOTIFY_STATUSES = {"done", "failed", "skipped"}


def notify_stage(kind: str, run_id: str, stage: str, status: str,
                 note: str = "", total_stages: int = 0,
                 completed_stages: int = 0) -> None:
    """Best-effort Telegram notification on terminal stage transitions."""
    if status not in _NOTIFY_STATUSES:
        return
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
            "--total-stages", str(total_stages),
            "--completed-stages", str(completed_stages),
        ]
        if note:
            cmd.extend(["--note", note[:200]])
        subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
