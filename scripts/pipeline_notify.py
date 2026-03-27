#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISPATCH = ROOT / "config" / "claude_dispatch.json"


def main() -> None:
    p = argparse.ArgumentParser(description="Send pipeline progress notification via OpenClaw system event.")
    p.add_argument("--kind", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--note", default="")
    args = p.parse_args()

    target = "当前群"
    if DISPATCH.exists():
        try:
            data = json.loads(DISPATCH.read_text(encoding="utf-8"))
            target = data.get("chat_id", target)
        except Exception:
            pass

    if args.status != "done":
        return

    text = f"精读进度：{args.kind} / {args.run_id} / {args.stage} 已完成"
    if args.note:
        text += f"。{args.note}"
    text += f"。目标：{target}"

    subprocess.run([
        "openclaw", "system", "event",
        "--mode", "now",
        "--text", text,
    ], cwd=ROOT, capture_output=True, text=True, timeout=60)


if __name__ == "__main__":
    main()
