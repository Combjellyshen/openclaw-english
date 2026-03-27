#!/usr/bin/env python3
"""
Vocabulary Review System — Leitner Box + Flashcards
Usage:
  python3 scripts/vocab_review.py today        # 今日待复习词汇列表
  python3 scripts/vocab_review.py flashcard    # 生成闪卡练习（JSON）
  python3 scripts/vocab_review.py quiz         # 生成混合题型测验（Markdown）
  python3 scripts/vocab_review.py stats        # 统计信息
  python3 scripts/vocab_review.py promote <id> # 答对，升级盒子
  python3 scripts/vocab_review.py demote <id>  # 答错，降级到 Box 1
  python3 scripts/vocab_review.py add <json>   # 手动添加词条
"""

import json
import sys
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

WORDBOOK = Path(__file__).parent.parent / "vocabulary" / "wordbook.json"

# Leitner box intervals (days)
BOX_INTERVALS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14}


def load_wordbook():
    if not WORDBOOK.exists():
        return {"version": 1, "last_updated": "", "total_words": 0, "words": []}
    with open(WORDBOOK, "r", encoding="utf-8") as f:
        return json.load(f)


def save_wordbook(data):
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    data["total_words"] = len(data["words"])
    with open(WORDBOOK, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today():
    return datetime.now().strftime("%Y-%m-%d")


def due_words(data):
    """Return words due for review today."""
    today = get_today()
    due = []
    for w in data["words"]:
        next_rev = w.get("next_review", today)
        if next_rev <= today:
            due.append(w)
    return due


def cmd_today(data):
    """Show today's review queue."""
    words = due_words(data)
    if not words:
        print("🎉 今天没有待复习的词汇！")
        return

    print(f"📚 今日待复习：{len(words)} 个词\n")

    # Group by box
    boxes = {}
    for w in words:
        box = w.get("leitner_box", 1)
        boxes.setdefault(box, []).append(w)

    for box_num in sorted(boxes):
        print(f"📦 Box {box_num} ({BOX_INTERVALS[box_num]}天间隔) — {len(boxes[box_num])} 词")
        for w in boxes[box_num]:
            print(f"  • {w['word']} ({w['ipa']}) — {w['meaning_zh']}")
        print()


def cmd_flashcard(data):
    """Generate flashcard JSON for today's due words."""
    words = due_words(data)
    if not words:
        print(json.dumps({"message": "No words due today", "cards": []}, ensure_ascii=False, indent=2))
        return

    random.shuffle(words)
    cards = []
    for w in words[:20]:  # max 20 per session
        card = {
            "id": w["id"],
            "front": {
                "word": w["word"],
                "ipa": w["ipa"],
                "pos": w.get("pos", ""),
                "hint": w.get("example_sentences", [{}])[0].get("en", "") if w.get("example_sentences") else ""
            },
            "back": {
                "meaning_zh": w["meaning_zh"],
                "meaning_en": w.get("meaning_en", ""),
                "collocations": [c["phrase"] for c in w.get("collocations", [])[:3]],
                "memory_tip": w.get("memory_tip", ""),
                "example": w.get("example_sentences", [{}])[0].get("en", "") if w.get("example_sentences") else ""
            },
            "box": w.get("leitner_box", 1),
            "difficulty": w.get("difficulty", "B2")
        }
        cards.append(card)

    print(json.dumps({"date": get_today(), "total_due": len(words), "cards": cards}, ensure_ascii=False, indent=2))


def cmd_quiz(data):
    """Generate a mixed quiz in Markdown."""
    words = due_words(data)
    if not words:
        words = data["words"]  # use all words if nothing due

    if len(words) < 4:
        print("词汇量不足，至少需要 4 个词才能生成测验。")
        return

    random.shuffle(words)
    quiz_words = words[:12]

    print(f"# 📝 词汇复习测验 — {get_today()}\n")

    # Section 1: 英译中
    print("## 一、看词选义（英 → 中）\n")
    for i, w in enumerate(quiz_words[:4], 1):
        pool = [x["meaning_zh"] for x in data["words"] if x["id"] != w["id"]]
        distractors = random.sample(pool, min(3, len(pool)))
        options = distractors[:3] + [w["meaning_zh"]]
        random.shuffle(options)
        correct = chr(65 + options.index(w["meaning_zh"]))
        print(f"**{i}.** {w['word']} ({w['ipa']})")
        for j, opt in enumerate(options):
            print(f"  {chr(65+j)}) {opt}")
        print(f"  **答案**: {correct}\n")

    # Section 2: 填空
    print("## 二、语境填空\n")
    for i, w in enumerate(quiz_words[4:8], 1):
        if w.get("example_sentences"):
            sent = w["example_sentences"][0]["en"]
            # blank out the word
            blanked = sent
            for token in w["word"].split(" / "):
                for form in [token, token.lower(), token.capitalize(), token + "s", token + "ed", token + "ing"]:
                    blanked = blanked.replace(form, "______")
            print(f"**{i}.** {blanked}")
            print(f"  **答案**: {w['word']}  **释义**: {w['meaning_zh']}\n")
        else:
            colls = w.get("collocations", [])
            if colls:
                print(f"**{i}.** 用 **{w['word']}** 的正确搭配填空：We need to ______ the problem.")
                print(f"  **答案**: {colls[0]['phrase']}\n")

    # Section 3: 搭配匹配
    print("## 三、搭配匹配\n")
    match_words = [w for w in quiz_words[8:12] if w.get("collocations")]
    if match_words:
        phrases = [(w["word"], w["collocations"][0]["phrase"]) for w in match_words]
        random.shuffle(phrases)
        left = [p[0] for p in phrases]
        right = [p[1] for p in phrases]
        random.shuffle(right)
        print("将左栏的词与右栏的搭配匹配：\n")
        for i, l in enumerate(left, 1):
            print(f"  {i}. {l}")
        print()
        for i, r in enumerate(right, 1):
            print(f"  {chr(64+i)}) {r}")
        print("\n**答案**:")
        for word, phrase in phrases:
            idx_l = left.index(word) + 1
            idx_r = chr(64 + right.index(phrase) + 1)
            print(f"  {idx_l} — {idx_r} ({phrase})")

    print()


def cmd_stats(data):
    """Print statistics."""
    words = data["words"]
    if not words:
        print("词汇库为空。")
        return

    total = len(words)
    due = len(due_words(data))
    boxes = {}
    for w in words:
        box = w.get("leitner_box", 1)
        boxes[box] = boxes.get(box, 0) + 1

    difficulties = {}
    for w in words:
        d = w.get("difficulty", "?")
        difficulties[d] = difficulties.get(d, 0) + 1

    sources = {}
    for w in words:
        for s in w.get("source_articles", []):
            sources[s] = sources.get(s, 0) + 1

    print(f"📊 词汇库统计\n")
    print(f"  总词数: {total}")
    print(f"  今日待复习: {due}")
    print(f"\n  📦 Leitner 盒子分布:")
    for b in sorted(boxes):
        pct = boxes[b] / total * 100
        bar = "█" * int(pct / 5)
        print(f"    Box {b} ({BOX_INTERVALS.get(b, '?')}天): {boxes[b]} 词 {bar} {pct:.0f}%")
    print(f"\n  📈 难度分布:")
    for d in sorted(difficulties):
        print(f"    {d}: {difficulties[d]} 词")
    print(f"\n  📖 来源文章 Top 5:")
    for s, c in sorted(sources.items(), key=lambda x: -x[1])[:5]:
        print(f"    {s}: {c} 词")


def cmd_promote(data, word_id):
    """Move word to next box (correct answer)."""
    for w in data["words"]:
        if w["id"] == word_id:
            old_box = w.get("leitner_box", 1)
            new_box = min(old_box + 1, 5)
            w["leitner_box"] = new_box
            interval = BOX_INTERVALS[new_box]
            w["next_review"] = (datetime.now() + timedelta(days=interval)).strftime("%Y-%m-%d")
            w.setdefault("review_history", []).append({
                "date": get_today(),
                "result": "correct",
                "from_box": old_box,
                "to_box": new_box
            })
            save_wordbook(data)
            print(f"✅ {w['word']}: Box {old_box} → Box {new_box}, 下次复习: {w['next_review']}")
            return
    print(f"❌ 未找到词条: {word_id}")


def cmd_demote(data, word_id):
    """Move word back to Box 1 (wrong answer)."""
    for w in data["words"]:
        if w["id"] == word_id:
            old_box = w.get("leitner_box", 1)
            w["leitner_box"] = 1
            w["next_review"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            w.setdefault("review_history", []).append({
                "date": get_today(),
                "result": "wrong",
                "from_box": old_box,
                "to_box": 1
            })
            save_wordbook(data)
            print(f"🔄 {w['word']}: Box {old_box} → Box 1, 明天再复习")
            return
    print(f"❌ 未找到词条: {word_id}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    data = load_wordbook()

    if cmd == "today":
        cmd_today(data)
    elif cmd == "flashcard":
        cmd_flashcard(data)
    elif cmd == "quiz":
        cmd_quiz(data)
    elif cmd == "stats":
        cmd_stats(data)
    elif cmd == "promote":
        if len(sys.argv) < 3:
            print("用法: vocab_review.py promote <word_id>")
            return
        cmd_promote(data, sys.argv[2])
    elif cmd == "demote":
        if len(sys.argv) < 3:
            print("用法: vocab_review.py demote <word_id>")
            return
        cmd_demote(data, sys.argv[2])
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
