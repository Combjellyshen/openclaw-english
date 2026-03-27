#!/usr/bin/env python3
"""Send a stage-completion notification to Telegram for English learning tasks.

Usage:
  python3 scripts/tg_notify.py --kind close-reading --run-id 2026-03-24-psychology \
      --stage grammar_done --status done --note "15 sentences parsed"
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

OPENCLAW_CONFIG = Path(__file__).resolve().parents[2] / "openclaw.json"
CHAT_ID = "-1003726107069"

KIND_LABELS = {
    "close-reading": "\u7cbe\u8bfb",
    "close_reading": "\u7cbe\u8bfb",
    "daily-vocab": "\u6bcf\u65e5\u8bcd\u5361",
    "daily_vocab": "\u6bcf\u65e5\u8bcd\u5361",
    "weekly-vocab": "\u5468\u6d4b",
    "weekly_vocab": "\u5468\u6d4b",
}

STAGE_LABELS = {
    # Close reading stages
    "initialized": "\u521d\u59cb\u5316",
    "source_attached": "\u6587\u7ae0\u5bfc\u5165",
    "exam_matched": "\u8003\u8bd5\u8bcd\u5e93\u5339\u914d",
    "notebook_ingested": "\u751f\u8bcd\u672c\u5bfc\u5165",
    "vocab_built": "\u8bcd\u6c47\u69cb\u5efa",
    "structure_summary_done": "\u884c\u6587\u7ed3\u6784+\u6982\u8981",
    "grammar_done": "\u8bed\u6cd5\u89e3\u6790",
    "insights_done": "\u8bed\u8a00\u6d1e\u5bdf",
    "discussion_exam_done": "\u8ba8\u8bba+\u8003\u9898",
    "assembled": "\u7ec4\u88c5\u5b8c\u6210",
    "validated": "\u8d28\u91cf\u6821\u9a8c",
    "pdf_built": "PDF \u751f\u6210",
    "index_updated": "\u7d22\u5f15\u66f4\u65b0",
    "delivered": "\u4ea4\u4ed8\u5b8c\u6210",
    # Daily vocab stages
    "skeleton_built": "\u9aa8\u67b6\u751f\u6210",
    "polysemy_done": "\u591a\u4e49\u8fa8\u6790",
    "derivation_done": "\u8bcd\u6839\u6d3e\u751f",
    "examples_done": "\u4f8b\u53e5\u751f\u6210",
    "mnemonic_done": "\u8bb0\u5fc6\u6cd5",
    "etymology_done": "\u8bcd\u6e90\u6f14\u53d8",
    # Weekly vocab stages
    "review_summary_done": "\u590d\u4e60\u6982\u8981",
    "weekly_exam_done": "\u5468\u6d4b\u51fa\u9898",
    "study_plan_done": "\u5b66\u4e60\u8ba1\u5212",
}

STATUS_EMOJI = {
    "done": "\u2705",
    "skipped": "\u23ed\ufe0f",
    "failed": "\u274c",
    "running": "\U0001f504",
}


def _get_bot_token() -> str:
    try:
        cfg = json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
        return cfg.get("channels", {}).get("telegram", {}).get("botToken", "")
    except Exception:
        return ""


def send_telegram(text: str) -> bool:
    bot_token = _get_bot_token()
    if not bot_token:
        print(json.dumps({"notification": True, "chat_id": CHAT_ID, "message": text},
              ensure_ascii=False, indent=2))
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(url, data, timeout=10)
        return True
    except Exception:
        print(json.dumps({"notification": True, "chat_id": CHAT_ID, "message": text},
              ensure_ascii=False, indent=2))
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Send English pipeline stage notification to Telegram")
    parser.add_argument("--kind", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--status", default="done", choices=["done", "skipped", "failed", "running"])
    parser.add_argument("--note", default="")
    parser.add_argument("--total-stages", type=int, default=0)
    parser.add_argument("--completed-stages", type=int, default=0)
    args = parser.parse_args()

    emoji = STATUS_EMOJI.get(args.status, "\u2139\ufe0f")
    kind_label = KIND_LABELS.get(args.kind, args.kind)
    stage_label = STAGE_LABELS.get(args.stage, args.stage)
    note_line = f"\n\u5907\u6ce8\uff1a{args.note}" if args.note else ""

    progress = ""
    if args.total_stages > 0 and args.completed_stages > 0:
        progress = f" ({args.completed_stages}/{args.total_stages})"

    text = (
        f"{emoji} <b>{kind_label}</b> \u00b7 {stage_label} {args.status}{progress}\n"
        f"\U0001f4d6 {args.run_id}"
        f"{note_line}"
    )

    send_telegram(text)


if __name__ == "__main__":
    main()
