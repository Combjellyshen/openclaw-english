#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "config" / "profile.json"
INDEX_PATH = ROOT / "reading-log" / "index.json"
REQUIRED_PREFIX = "配置agent"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def load_read_history() -> list[dict]:
    """Load previously read articles from index.json."""
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def build_exclusion_block(history: list[dict]) -> str:
    """Build a markdown block listing already-read articles for exclusion."""
    if not history:
        return ""
    lines = ["## Already-read articles (DO NOT select these or very similar articles)"]
    # Group by topic to show coverage
    topics_seen: set[str] = set()
    for entry in history:
        title = entry.get("title", "?")
        source = entry.get("source", "?")
        url = entry.get("url", "")
        topic = entry.get("topic") or ""
        date = entry.get("date", "")
        lines.append(f"- [{date}] \"{title}\" ({source}) — topic: {topic}")
        if topic:
            for t in topic.split("/"):
                topics_seen.add(t.strip().lower())
    lines.append("")
    lines.append(f"Topics already covered: {', '.join(sorted(topics_seen))}")
    lines.append("Try to pick a topic or angle NOT heavily represented above.")
    return "\n".join(lines)


def workspace_change_allowed(user_message: str) -> bool:
    return user_message.strip().startswith(REQUIRED_PREFIX)


def build_checkin(profile: dict) -> str:
    time_text = profile.get("daily_checkin_time", "20:00")
    return dedent(
        f"""
        今晚英语精读时间到啦（{time_text}）。

        你今晚想先了解什么？可以直接告诉我：
        - 一个主题（比如 AI、历史、医学、摄影）
        - 一个具体问题
        - 或者说“你帮我选”

        你回复后，我会挑一篇长短适中的英文文章，并继续做：词汇、语法、文化背景和精读解析。
        """
    ).strip()


def build_plan(profile: dict, topic: str, level: str | None) -> str:
    level = level or profile.get("default_level", "B1-B2")
    length = profile.get("article_length_words", {})
    min_words = length.get("min", 600)
    target_words = length.get("target", 850)
    max_words = length.get("max", 1200)
    all_sources = list(profile.get("preferred_sources", []))
    # Shuffle sources to encourage variety each day
    random.shuffle(all_sources)
    sources = ", ".join(all_sources) or "reputable English-language sources"
    sections = profile.get("analysis_sections", [])
    sections_md = "\n".join(f"- {section}" for section in sections)
    now = datetime.now().strftime("%Y-%m-%d")

    # Build exclusion block from reading history
    history = load_read_history()
    exclusion = build_exclusion_block(history)
    read_urls = [e.get("url", "") for e in history if e.get("url")]
    read_titles = [e.get("title", "") for e in history if e.get("title")]

    plan = dedent(
        f"""
        # Daily English Lesson Plan

        - Date: {now}
        - Topic: {topic}
        - Target level: {level}
        - Target article length: {min_words}-{max_words} words (ideal around {target_words})
        - Candidate source style: {sources}
        - Articles already read: {len(history)}

        ## Article selection criteria
        1. Match the topic closely and stay understandable at {level}.
        2. Prefer one self-contained article instead of a long report.
        3. Avoid paywalled, over-technical, or too opinion-heavy pieces when possible.
        4. Prefer articles rich enough for vocabulary, grammar, and cultural discussion.
        5. **MUST NOT** select any article already in the exclusion list below.
        6. Prefer articles from different sources than recently used — rotate sources.
        7. Vary the publication year — don't always pick the latest news; classic evergreen pieces (2015–2025) are great for learning.
        8. When the user says "你定", search broadly with varied keywords. Do NOT reuse the same search query patterns.

        ## Lesson deliverables
        {sections_md}

        ## Teaching reminders
        - Explain vocabulary in context instead of isolated dictionary dumping.
        - Pick grammar points that genuinely appear in the article.
        - Add culture/background only when it helps comprehension.
        - Keep the lesson readable in one sitting.
        """
    ).strip()

    if exclusion:
        plan += "\n\n" + exclusion

    return plan


def build_guard_result(user_message: str) -> str:
    allowed = workspace_change_allowed(user_message)
    result = {
        "allowed": allowed,
        "required_prefix": REQUIRED_PREFIX,
        "rule": f'user_message.strip().startswith("{REQUIRED_PREFIX}")',
        "message": "ALLOW" if allowed else "DENY",
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Support script for Combjelly's daily English reading workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("checkin", help="Print the daily check-in prompt.")

    plan_parser = subparsers.add_parser("plan", help="Generate a lesson-plan scaffold for a topic.")
    plan_parser.add_argument("--topic", required=True, help="Tonight's topic or question.")
    plan_parser.add_argument("--level", default=None, help="Override CEFR-style level, e.g. B1-B2.")

    guard_parser = subparsers.add_parser("guard", help="Check whether a workspace-changing instruction is allowed.")
    guard_parser.add_argument("--message", required=True, help="Raw user instruction to validate.")

    args = parser.parse_args()
    profile = load_profile()

    if args.command == "checkin":
        print(build_checkin(profile))
    elif args.command == "plan":
        print(build_plan(profile, args.topic, args.level))
    elif args.command == "guard":
        print(build_guard_result(args.message))


if __name__ == "__main__":
    main()
