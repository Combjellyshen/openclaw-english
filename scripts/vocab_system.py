#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "config" / "profile.json"
EXAM_DIR = ROOT / "data" / "exam-vocab"
STATE_DIR = ROOT / "data" / "vocab-system"
NOTEBOOK_PATH = STATE_DIR / "notebook.json"
POOL_PROGRESS_PATH = STATE_DIR / "pool_progress.json"
DAILY_HISTORY_PATH = STATE_DIR / "daily_history.json"
WEEKLY_REPORTS_PATH = STATE_DIR / "weekly_reports.json"
LEARNED_WORDS_PATH = STATE_DIR / "learned_words.json"
DAILY_OUT_DIR = ROOT / "reading-log" / "vocab-drills"
WEEKLY_OUT_DIR = ROOT / "reading-log" / "weekly-vocab"
WORDBOOK_PATH = ROOT / "vocabulary" / "wordbook.json"

DEFAULT_PROFILE = {
    "timezone": "Asia/Shanghai",
    "daily_send_time": "09:00",
    "weekly_review_day": "Sunday",
    "weekly_review_time": "09:30",
    "daily_quota": {"cet6": 50, "kaoyan": 30},
    "beyond_kaoyan_rule": "sat_not_kaoyan",
    "beyond_kaoyan_min_length": 6,
    "interval_days": [1, 2, 4, 7, 14, 30],
}
LIST_LABELS = {"cet6": "六级", "sat": "SAT", "kaoyan": "考研"}
STOPWORDS = {
    "the","and","that","with","from","this","they","were","have","their","which","would","there","after",
    "about","these","those","while","where","when","what","into","also","been","than","them","some",
    "said","saying","should","could","being","through","such","more","over","then","only","other",
    "same","high","main","many","much","very","well","like","just","will","your","ours","ourselves",
    "whose","whom","here","therefore","however","because","against","before","under","again","between",
    "each","both","does","doing","done","make","made","come","comes","coming","goes","went","gone",
    "take","takes","taking","took","taken","want","wants","wanted","group","people","party","report",
    "government","powers","power","state","states","article","move","bill","rules","types","years","year",
    "large","small","great","greatly","full","fully","last","first","second","third","night","days",
}
PREFIX_HINTS = {
    "anti": "anti- 常表示“反对、对抗”",
    "inter": "inter- 常表示“在……之间、相互”",
    "trans": "trans- 常表示“跨越、转移”",
    "sub": "sub- 常表示“在下、次级”",
    "con": "con-/com- 常表示“共同、一起”",
    "pro": "pro- 常表示“向前、支持”",
    "re": "re- 常表示“再次、回返”",
    "de": "de- 常表示“向下、去除”",
    "pre": "pre- 常表示“在前、预先”",
    "post": "post- 常表示“在后、之后”",
    "mis": "mis- 常表示“错误、坏”",
    "dis": "dis- 常表示“否定、分离”",
    "auto": "auto- 常表示“自动、自我”",
    "micro": "micro- 常表示“微小”",
    "macro": "macro- 常表示“宏观、较大”",
}
SUFFIX_HINTS = {
    "tion": "-tion 常见于名词，表示动作、结果或过程",
    "sion": "-sion 常见于名词，表示动作、状态或结果",
    "ment": "-ment 常见于名词，表示结果、状态或手段",
    "ity": "-ity 常把形容词变成抽象名词",
    "ness": "-ness 常表示性质、状态",
    "ism": "-ism 常表示主义、思想或现象",
    "ist": "-ist 常表示某类人或职业/立场",
    "ive": "-ive 常见于形容词，表示“具有……性质”",
    "ous": "-ous 常见于形容词，表示“充满……的”",
    "able": "-able 常表示“能够……的”",
    "ible": "-ible 常表示“能够……的”",
    "ize": "-ize/-ise 常把词变成动词，表示“使……化”",
    "ise": "-ize/-ise 常把词变成动词，表示“使……化”",
    "ology": "-ology 常表示“……学”",
    "graphy": "-graphy 常表示“书写、记录、学科”",
}


@dataclass
class ReviewFormat:
    mode: str
    label: str
    prompt: str
    answer: str


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_OUT_DIR.mkdir(parents=True, exist_ok=True)
    WEEKLY_OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_profile() -> dict:
    profile = load_json(PROFILE_PATH, {})
    vocab_profile = profile.get("vocab_system", {})
    merged = dict(DEFAULT_PROFILE)
    merged.update(vocab_profile)
    return merged


def load_wordbook() -> Dict[str, dict]:
    raw = load_json(WORDBOOK_PATH, {})
    words = raw.get("words", []) if isinstance(raw, dict) else []
    out = {}
    for item in words:
        word = normalize(str(item.get("word", "")))
        if word:
            out[word] = item
    return out


def parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def normalize(word: str) -> str:
    return word.strip().lower()


def _dedupe_dicts(items: List[dict], keys: Tuple[str, ...]) -> List[dict]:
    out = []
    seen = set()
    for item in items:
        key = tuple(item.get(k, "") for k in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def load_exam_datasets() -> Dict[str, Dict[str, dict]]:
    datasets: Dict[str, Dict[str, dict]] = {}
    for name in LIST_LABELS:
        path = EXAM_DIR / f"{name}.json"
        entries = load_json(path, [])
        index = {}
        for entry in entries:
            word = normalize(entry.get("word", ""))
            if not word:
                continue
            entry["translations"] = _dedupe_dicts(entry.get("translations", []), ("type", "translation"))
            entry["phrases"] = _dedupe_dicts(entry.get("phrases", []), ("phrase", "translation"))
            entry["sentences"] = _dedupe_dicts(entry.get("sentences", []), ("sentence", "translation"))
            index[word] = entry
        datasets[name] = index
    return datasets


def token_candidates(token: str) -> Iterable[str]:
    token = normalize(token.strip("'\""))
    if not token:
        return []
    forms = {token}
    if token.endswith("'s"):
        forms.add(token[:-2])
    if token.endswith("ies") and len(token) > 4:
        forms.add(token[:-3] + "y")
    if token.endswith("ied") and len(token) > 4:
        forms.add(token[:-3] + "y")
    if token.endswith("ing") and len(token) > 5:
        stem = token[:-3]
        forms.add(stem)
        forms.add(stem + "e")
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            forms.add(stem[:-1])
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        forms.add(stem)
        forms.add(stem + "e")
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            forms.add(stem[:-1])
    if token.endswith("es") and len(token) > 4:
        forms.add(token[:-2])
    if token.endswith("s") and len(token) > 3:
        forms.add(token[:-1])
    if token.endswith("er") and len(token) > 4:
        forms.add(token[:-2])
    if token.endswith("est") and len(token) > 5:
        forms.add(token[:-3])
    return [f for f in forms if f]


def extract_text(raw: str) -> str:
    if "## Full Text" in raw:
        raw = raw.split("## Full Text", 1)[1]
    raw = re.sub(r"^#.*$", "", raw, flags=re.MULTILINE)
    raw = raw.replace(">", " ")
    raw = re.sub(r"`([^`]*)`", r"\1", raw)
    raw = re.sub(r"\[[^\]]+\]\([^\)]+\)", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?。？！])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def sentence_for_word(sentences: List[str], word: str) -> str:
    pat = re.compile(rf"\b{re.escape(word)}\b", re.I)
    for s in sentences:
        if pat.search(s):
            return s
    return sentences[0] if sentences else ""


def build_memory_hint(word: str) -> str:
    lower = normalize(word)
    for prefix, hint in PREFIX_HINTS.items():
        if lower.startswith(prefix) and len(lower) >= len(prefix) + 3:
            return hint
    for suffix, hint in SUFFIX_HINTS.items():
        if lower.endswith(suffix) and len(lower) >= len(suffix) + 3:
            return hint
    if len(lower) >= 9:
        return "【待补全】长难词，需按音节拆分并结合词根词缀做逻辑链助记。"
    if "-" in lower:
        return "【待补全】连字符词，需拆解两部分语义来源。"
    return "【待补全】需补充具体逻辑链或词族串联助记。"


def build_memory_mnemonic(word: str, entry: dict) -> str:
    lower = normalize(word)
    trans = translation_text(entry)
    first_phrase = entry.get("phrases", [])[:1]
    if lower.startswith("re") and len(lower) >= 5:
        return f"可以先抓住前缀 re- 的“重新 / 回返”感觉，再把 {word} 和“{trans or '该词义'}”绑定。"
    if lower.startswith("over") and len(lower) >= 6:
        return f"可以把 over- 想成“在上面看着”，帮助记住 {word} 常带“监督 / 俯视管理”的感觉。"
    if first_phrase:
        p = first_phrase[0]
        return f"先记住固定搭配 {p['phrase']}，再反推 {word} 的核心用法，会比死背词义更稳。"
    if len(lower) >= 8:
        return f"把 {word} 分成 2-3 个词块来记，并反复回到原文句子里确认它的语气和搭配。"
    return f"建议把 {word} 和它在文章中的句子一起记，而不是单独背中文释义。"


def build_word_parts(word: str) -> str:
    lower = normalize(word)
    found = []
    for prefix, hint in PREFIX_HINTS.items():
        if lower.startswith(prefix) and len(lower) >= len(prefix) + 3:
            found.append(f"前缀 {prefix}-：{hint.replace(prefix, '').lstrip('- ').strip()}")
            stem = lower[len(prefix):]
            if stem:
                found.append(f"剩余词干可先看作：{stem}")
            break
    for suffix, hint in SUFFIX_HINTS.items():
        if lower.endswith(suffix) and len(lower) >= len(suffix) + 3:
            stem = lower[:-len(suffix)]
            found.append(f"词干 + 后缀：{stem or lower} + -{suffix}")
            found.append(f"后缀作用：{hint}")
            break
    if not found and len(lower) >= 8:
        chunks = re.findall(r'.{1,4}', lower)
        found.append("可先按词块拆读：" + " / ".join(chunks))
    if not found:
        if '-' in lower:
            parts = [p for p in lower.split('-') if p]
            found.append("连字符拆解：" + " + ".join(parts))
        elif len(lower) >= 5:
            found.append(f"可先按前半 / 后半拆读：{lower[:max(2, len(lower)//2)]} / {lower[max(2, len(lower)//2):]}")
        else:
            found.append("这个词较短，优先按整体词块记忆，再结合搭配感受它的语气。")
    return "； ".join(found)


def build_etymology_note(word: str, entry: dict, wordbook_entry: dict | None = None) -> str:
    if wordbook_entry and wordbook_entry.get("etymology"):
        return str(wordbook_entry["etymology"]).strip()
    lower = normalize(word)
    for prefix, hint in PREFIX_HINTS.items():
        if lower.startswith(prefix) and len(lower) >= len(prefix) + 3:
            return f"可先从构词角度理解：{word} 带有 {prefix}- 的语义色彩（{hint.replace(prefix, '').lstrip('- ').strip()}），后续常见义项通常就沿着这条方向发展。"
    for suffix, hint in SUFFIX_HINTS.items():
        if lower.endswith(suffix) and len(lower) >= len(suffix) + 3:
            stem = lower[:-len(suffix)]
            return f"从现代英语构词看，{word} 可先理解为 {stem} + -{suffix}：先有词干义，再通过后缀发展出现在这个词性或抽象含义。"
    if len(lower) >= 6:
        return f"该词可先从词形和常见义项的演变路径理解：通常是先有一个较具体的核心义，随后在长期使用中扩展成现在更抽象或更固定的语境义。"
    return f"这是一个历史较久的短词。它往往先有非常具体的核心动作或核心物象，后来才逐渐扩展出今天这些常见引申义。"


def build_meaning_breakdown(entry: dict, wordbook_entry: dict | None = None) -> str:
    lines = []
    for idx, item in enumerate(entry.get("translations", [])[:6], start=1):
        pos = str(item.get("type", "")).strip()
        meaning = str(item.get("translation", "")).strip()
        if meaning:
            lines.append(f"义项 {idx}：{(pos + '. ') if pos else ''}{meaning}")
    if lines:
        return "； ".join(lines)
    if wordbook_entry:
        zh = str(wordbook_entry.get("meaning_zh", "")).strip()
        en = str(wordbook_entry.get("meaning_en", "")).strip()
        merged = " / ".join(x for x in [zh, en] if x)
        if merged:
            return merged
    return "（暂无详细义项）"


def build_meaning_distinction(entry: dict, wordbook_entry: dict | None = None) -> str:
    if wordbook_entry and wordbook_entry.get("differentiation"):
        return str(wordbook_entry["differentiation"]).strip()
    translations = [str(x.get("translation", "")).strip() for x in entry.get("translations", []) if str(x.get("translation", "")).strip()]
    if len(translations) >= 2:
        return "【待补全】多义词，需说明核心义→引申义的分化路径及具体语境差异。"
    if translations:
        return "【待补全】需补充与近义词的具体搭配/语气差异。"
    return "【待补全】需补充多义辨析。"


def format_ipa(entry: dict) -> str:
    parts = []
    if entry.get("uk"):
        parts.append(f"UK /{entry['uk']}/")
    if entry.get("us"):
        parts.append(f"US /{entry['us']}/")
    return "； ".join(parts) if parts else "（暂无音标）"


def notebook_default() -> dict:
    return {"cards": {}, "meta": {"created_at": datetime.now(timezone.utc).isoformat()}}


def pool_default() -> dict:
    return {"cet6": {}, "kaoyan": {}}


def daily_history_default() -> dict:
    return {"days": {}}


def export_learned_words(notebook: dict | None = None, pool_progress: dict | None = None) -> dict:
    notebook = notebook or load_json(NOTEBOOK_PATH, notebook_default())
    pool_progress = pool_progress or load_json(POOL_PROGRESS_PATH, pool_default())
    rows = []

    for pool_name in ("cet6", "kaoyan"):
        for word, meta in pool_progress.get(pool_name, {}).items():
            if meta.get("review_count", 0) <= 0:
                continue
            rows.append({
                "word": word,
                "bucket": pool_name,
                "source_lists": [pool_name],
                "reviewed": True,
                "review_count": meta.get("review_count", 0),
                "stage": meta.get("stage", 0),
                "mastery": meta.get("mastery", "new"),
                "mastered": bool(meta.get("mastered_at")),
                "first_seen": meta.get("first_seen") or meta.get("last_reviewed") or meta.get("due_date"),
                "last_reviewed": meta.get("last_reviewed"),
                "next_due": meta.get("due_date"),
                "mastered_at": meta.get("mastered_at"),
                "source_articles": [],
                "context_sentence": "",
            })

    for word, card in notebook.get("cards", {}).items():
        if card.get("review_count", 0) <= 0:
            continue
        rows.append({
            "word": word,
            "bucket": "notebook",
            "source_lists": card.get("source_lists", []) or ["notebook"],
            "reviewed": True,
            "review_count": card.get("review_count", 0),
            "stage": card.get("stage", 0),
            "mastery": card.get("mastery", "new"),
            "mastered": bool(card.get("mastered_at")),
            "first_seen": card.get("added_at") or card.get("last_reviewed") or card.get("due_date"),
            "last_reviewed": card.get("last_reviewed"),
            "next_due": card.get("due_date"),
            "mastered_at": card.get("mastered_at"),
            "source_articles": card.get("source_articles", []),
            "context_sentence": card.get("context_sentence", ""),
        })

    rows.sort(key=lambda x: (x.get("bucket", ""), x.get("word", "")))
    payload = {
        "meta": {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_total": len(rows),
            "mastered_total": sum(1 for row in rows if row.get("mastered")),
            "buckets": {
                "cet6": sum(1 for row in rows if row.get("bucket") == "cet6"),
                "kaoyan": sum(1 for row in rows if row.get("bucket") == "kaoyan"),
                "notebook": sum(1 for row in rows if row.get("bucket") == "notebook"),
            },
        },
        "words": rows,
    }
    save_json(LEARNED_WORDS_PATH, payload)
    return payload


def review_record(card: dict, quality: int, today: date, profile: dict) -> None:
    intervals = profile["interval_days"]
    quality = max(0, min(quality, 5))
    if quality >= 4:
        card["stage"] = min(card.get("stage", 0) + 1, 4)
        card["correct_streak"] = card.get("correct_streak", 0) + 1
    elif quality >= 2:
        card["stage"] = min(card.get("stage", 0) + 1, 3)
        card["correct_streak"] = max(card.get("correct_streak", 0), 0) + 1
    else:
        card["stage"] = max(card.get("stage", 0) - 1, 0)
        card["correct_streak"] = 0
    interval = intervals[min(card["stage"], len(intervals) - 1)]
    card["last_reviewed"] = today.isoformat()
    card["due_date"] = (today + timedelta(days=interval)).isoformat()
    card["review_count"] = card.get("review_count", 0) + 1
    card["mastery"] = _mastery_label(card)
    if card["stage"] >= 4 and card.get("correct_streak", 0) >= 2 and not card.get("mastered_at"):
        card["mastered_at"] = today.isoformat()


def _mastery_label(card: dict) -> str:
    stage = card.get("stage", 0)
    if stage <= 0:
        return "new"
    if stage == 1:
        return "recognizing"
    if stage == 2:
        return "spelling"
    if stage == 3:
        return "applying"
    return "mastering"


def stage_label(stage: int) -> str:
    mapping = {
        0: "初识：词义 / 搭配 / 记忆提示",
        1: "识别：辨义 / 选择 / 搭配识别",
        2: "拼写：拼写 / 填空 / 词形回忆",
        3: "应用：造句 / 改写 / 翻译",
        4: "迁移：语篇应用 / 真实表达",
    }
    return mapping.get(stage, mapping[4])


def translation_text(entry: dict) -> str:
    parts = []
    for item in entry.get("translations", [])[:4]:
        t = str(item.get("translation", "")).strip()
        tp = str(item.get("type", "")).strip()
        parts.append(f"{tp}. {t}" if tp else t)
    return "； ".join(parts)


def phrases_text(entry: dict, limit: int = 5) -> str:
    return "； ".join(
        f"{p['phrase']}（{str(p.get('translation', '')).strip()}）" for p in entry.get("phrases", [])[:limit]
    )


def sentence_text(entry: dict) -> str:
    if entry.get("sentences"):
        s = entry["sentences"][0]
        return f"{s['sentence']} / {str(s.get('translation', '')).strip()}"
    return ""


def build_review_format(word: str, entry: dict, card: dict) -> ReviewFormat:
    stage = card.get("stage", 0)
    meanings = translation_text(entry)
    phrases = phrases_text(entry)
    article_sentence = card.get("context_sentence", "")
    if stage <= 0:
        prompt = "请先完整吸收这张卡：优先看词义、搭配、原文例句、词库例句、构词提示和助记。"
        answer = f"先建立对 {word} 的整体印象，再进入辨义和拼写。"
        return ReviewFormat("meaning", stage_label(stage), prompt, answer)
    if stage == 1:
        prompt = (
            "请做一个有信息量的识别练习，而不是猜词形：\n"
            f"- 先用中文说出 **{word}** 的核心义项\n"
            f"- 再写出 1 个最值得记的搭配或短语\n"
            "- 最后补一句：它和你最容易混淆的近义表达 / 相关表达差别在哪\n"
            f"- 可参考原文语境：{article_sentence or '（暂无文章语境）'}"
        )
        answer = f"参考方向：核心义项 = {meanings or '（按卡片词义作答）'}；重点搭配 = {phrases or '（按卡片搭配作答）'}。"
        return ReviewFormat("recognition", stage_label(stage), prompt, answer)
    if stage == 2:
        masked = _mask_word(word)
        prompt = f"请根据本卡内容写出完整单词：`{masked}`\n- 词义提示：{meanings}\n- 搭配提示：{phrases or '（暂无词库短语）'}"
        answer = word
        return ReviewFormat("spelling", stage_label(stage), prompt, answer)
    if stage == 3:
        prompt = "请用这个词完成一个英文句子，或把下面中文短语译成英文：\n" + \
                 f"- 目标词：{word}\n- 可参考搭配：{phrases or '（暂无词库短语）'}\n- 原文语境：{article_sentence or '（暂无文章语境）'}"
        answer = f"参考方向：使用 {word} 完成一个符合语境的英文句子，并尽量带上文章里相近的搭配。"
        return ReviewFormat("application", stage_label(stage), prompt, answer)
    prompt = "请在 1-2 句英文中自然使用这个词，并尽量贴近真实文章 / 学术 / 政治语境：\n" + \
             f"- 目标词：{word}\n- 原文语境：{article_sentence or '（暂无文章语境）'}"
    answer = f"参考要求：自然使用 {word}，避免只做生硬填词；最好能带出一个合适搭配。"
    return ReviewFormat("transfer", stage_label(stage), prompt, answer)


def _build_options(entry: dict, word: str) -> List[str]:
    options = [word]
    text = phrases_text(entry)
    if text:
        options.append(text.split("（", 1)[0])
    if len(word) > 5:
        options.append(word[:-1])
    options.append(word + "s")
    seen = []
    for opt in options:
        if opt not in seen:
            seen.append(opt)
    return seen[:4]


def _mask_word(word: str) -> str:
    if len(word) <= 4:
        return word[0] + "_" * (len(word) - 2) + word[-1]
    return word[:2] + "_" * (len(word) - 4) + word[-2:]


def init_system() -> None:
    ensure_dirs()
    if not NOTEBOOK_PATH.exists():
        save_json(NOTEBOOK_PATH, notebook_default())
    if not POOL_PROGRESS_PATH.exists():
        save_json(POOL_PROGRESS_PATH, pool_default())
    if not DAILY_HISTORY_PATH.exists():
        save_json(DAILY_HISTORY_PATH, daily_history_default())
    if not WEEKLY_REPORTS_PATH.exists():
        save_json(WEEKLY_REPORTS_PATH, {"reports": []})
    export_learned_words()
    print("Initialized vocab system state.")


def ingest_article(source_file: Path, article_id: str | None = None, today: date | None = None) -> None:
    ensure_dirs()
    today = today or date.today()
    profile = load_profile()
    min_len = int(profile.get("beyond_kaoyan_min_length", 6))
    notebook = load_json(NOTEBOOK_PATH, notebook_default())
    datasets = load_exam_datasets()
    text = extract_text(source_file.read_text(encoding="utf-8"))
    sentences = split_sentences(text)
    added_words = set()
    for sentence in sentences:
        for token in re.findall(r"[A-Za-z][A-Za-z\-']*", sentence):
            lower = normalize(token)
            if len(lower) < min_len or lower in STOPWORDS:
                continue
            matched = None
            for cand in token_candidates(token):
                if len(cand) < min_len:
                    continue
                if cand in datasets["sat"] and cand not in datasets["kaoyan"]:
                    matched = cand
                    break
            if not matched:
                continue
            entry = datasets["sat"][matched]
            card = notebook["cards"].setdefault(
                matched,
                {
                    "word": entry["word"],
                    "source_lists": ["sat"],
                    "stage": 0,
                    "due_date": today.isoformat(),
                    "review_count": 0,
                    "correct_streak": 0,
                    "added_at": today.isoformat(),
                    "mastery": "new",
                    "source_articles": [],
                    "context_sentence": sentence,
                },
            )
            if article_id and article_id not in card["source_articles"]:
                card["source_articles"].append(article_id)
            if not card.get("context_sentence"):
                card["context_sentence"] = sentence
            if card.get("mastery") == "new" and card.get("review_count", 0) == 0:
                card["due_date"] = today.isoformat()
            added_words.add(matched)
    save_json(NOTEBOOK_PATH, notebook)
    export_learned_words(notebook=notebook)
    print(f"Notebook updated from article -> {NOTEBOOK_PATH} (new/updated sat-not-kaoyan hits: {len(added_words)})")


def _select_pool_words(pool_name: str, quota: int, today: date, profile: dict, datasets: Dict[str, Dict[str, dict]], pool_progress: dict, exclude: set[str]) -> List[str]:
    progress = pool_progress.setdefault(pool_name, {})
    due_existing = [w for w, meta in progress.items() if meta.get("due_date", today.isoformat()) <= today.isoformat() and w not in exclude]
    unseen = [w for w in datasets[pool_name].keys() if w not in progress and w not in exclude]
    rng = random.Random(f"{pool_name}-{today.isoformat()}")
    rng.shuffle(due_existing)
    rng.shuffle(unseen)
    selected = []
    for word in due_existing:
        if len(selected) >= quota:
            break
        selected.append(word)
    for word in unseen:
        if len(selected) >= quota:
            break
        selected.append(word)
    for word in selected:
        meta = progress.setdefault(
            word,
            {
                "stage": 0,
                "review_count": 0,
                "correct_streak": 0,
                "due_date": today.isoformat(),
                "first_seen": today.isoformat(),
                "mastery": "new",
            },
        )
        # passive spaced repetition for base pools
        review_record(meta, 3 if meta.get("review_count", 0) else 2, today, profile)
    return selected


def build_daily(target_date: date, out_path: Path | None = None) -> Tuple[Path, Path]:
    ensure_dirs()
    profile = load_profile()
    datasets = load_exam_datasets()
    wordbook = load_wordbook()
    notebook = load_json(NOTEBOOK_PATH, notebook_default())
    pool_progress = load_json(POOL_PROGRESS_PATH, pool_default())
    history = load_json(DAILY_HISTORY_PATH, daily_history_default())
    quotas = profile.get("daily_quota", {"cet6": 50, "kaoyan": 30})

    selected_notebook = []
    for word, card in notebook["cards"].items():
        if card.get("due_date", target_date.isoformat()) <= target_date.isoformat():
            selected_notebook.append(word)
    selected_notebook.sort(key=lambda w: (notebook["cards"][w].get("due_date", ""), w))

    exclude = set(selected_notebook)
    cet6_words = _select_pool_words("cet6", int(quotas.get("cet6", 50)), target_date, profile, datasets, pool_progress, exclude)
    exclude.update(cet6_words)
    kaoyan_words = _select_pool_words("kaoyan", int(quotas.get("kaoyan", 30)), target_date, profile, datasets, pool_progress, exclude)

    # passive progression for notebook due cards
    for word in selected_notebook:
        review_record(notebook["cards"][word], 3, target_date, profile)

    day_key = target_date.isoformat()
    day_words = {
        "cet6": cet6_words,
        "kaoyan": kaoyan_words,
        "notebook": selected_notebook,
    }
    history["days"][day_key] = day_words
    save_json(POOL_PROGRESS_PATH, pool_progress)
    save_json(NOTEBOOK_PATH, notebook)
    save_json(DAILY_HISTORY_PATH, history)
    export_learned_words(notebook=notebook, pool_progress=pool_progress)

    if out_path is None:
        out_path = DAILY_OUT_DIR / f"{day_key}-daily-vocab.md"
    meta_path = out_path.with_suffix('.json')

    lines = [
        f"# 每日词卡包（{day_key}）",
        "",
    ]

    def render_section(title: str, words: List[str], pool_name: str):
        nonlocal lines
        if not words:
            return
        lines.extend([f"## {title}", ""])
        for i, word in enumerate(words, start=1):
            if pool_name == "notebook":
                card = notebook["cards"][word]
                entry = datasets['sat'].get(word) or datasets['kaoyan'].get(word) or datasets['cet6'].get(word)
                labels = " / ".join(LIST_LABELS.get(x, x) for x in card.get("source_lists", [])) or "生词本"
            else:
                card = pool_progress[pool_name][word]
                entry = datasets[pool_name][word]
                labels = LIST_LABELS[pool_name]
            
            review = build_review_format(word, entry, card)
            wb = wordbook.get(normalize(word))
            source_label = labels if pool_name != 'notebook' else '生词本 / ' + labels
            context_sentence = card.get('context_sentence', '（暂无文章语境）')
            
            # The script previously used template-like generation. 
            # We shift towards high-density, real content delivery for PDF.
            # For the automated script, we improve the depth of the build functions.
            
            lines.extend([
                f"### {i}. {word}",
                "",
                f"- **来源：** {source_label}",
                f"- **当前阶段：** {review.label}",
                f"- **音标：** {format_ipa(entry)}",
                f"- **完整词义：** {build_meaning_breakdown(entry, wb)}",
                f"- **词组 / 搭配：** {phrases_text(entry) or '（暂无词库搭配）'}",
                "",
                "#### 多义辨析",
                "",
                f"- **辨析重点：** {build_meaning_distinction(entry, wb)}",
                "",
                "#### 例句",
                "",
                f"- **例句：** {context_sentence if context_sentence and context_sentence != '（暂无文章语境）' else (sentence_text(entry) or '（暂无例句）')}",
                "",
                "#### 来源 / 构词 / 助记",
                "",
                f"- **拆词 / 词根词缀：** {build_word_parts(word)}",
                f"- **词源演变：** {build_etymology_note(word, entry, wb)}",
                f"- **助记：** {build_memory_mnemonic(word, entry)}",
                f"- **记忆提示：** {build_memory_hint(word)}",
                "",
            ])
            lines.extend([
                "---",
                "",
            ])

    render_section("六级词", cet6_words, "cet6")
    render_section("考研词", kaoyan_words, "kaoyan")
    render_section("生词本复习", selected_notebook, "notebook")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    save_json(meta_path, {"date": day_key, "words": day_words})
    print(f"Wrote daily deck -> {out_path}")
    return out_path, meta_path


def _week_bounds(target: date) -> Tuple[date, date]:
    start = target - timedelta(days=target.weekday())
    end = start + timedelta(days=6)
    return start, end


def build_weekly(target_date: date, out_path: Path | None = None) -> Tuple[Path, Path]:
    ensure_dirs()
    notebook = load_json(NOTEBOOK_PATH, notebook_default())
    history = load_json(DAILY_HISTORY_PATH, daily_history_default())
    start, end = _week_bounds(target_date)
    week_key = f"{start.isoformat()}_to_{end.isoformat()}"
    learned = []
    for word, card in notebook["cards"].items():
        added = card.get("added_at")
        mastered = card.get("mastered_at")
        if added and start.isoformat() <= added <= end.isoformat():
            learned.append((word, card, "added"))
        elif mastered and start.isoformat() <= mastered <= end.isoformat():
            learned.append((word, card, "mastered"))
    learned.sort(key=lambda x: (x[2], x[0]))

    covered_days = [day for day in history.get("days", {}) if start.isoformat() <= day <= end.isoformat()]

    if out_path is None:
        out_path = WEEKLY_OUT_DIR / f"{end.isoformat()}-weekly-vocab.md"
    meta_path = out_path.with_suffix('.json')

    lines = [
        f"# 每周词汇综合卷（{start.isoformat()} ~ {end.isoformat()}）",
        "",
        f"- **本周覆盖天数：** {len(covered_days)}",
        f"- **本周新增 / 进入学会状态的生词：** {len(learned)}",
        "",
        "## 本周词汇清单",
        "",
    ]
    for i, (word, card, state) in enumerate(learned[:80], start=1):
        lines.extend([
            f"### {i}. {word}",
            "",
            f"- **状态：** {'本周加入生词本' if state == 'added' else '本周达到学会阈值'}",
            f"- **来源文章：** {', '.join(card.get('source_articles', [])) or '（暂无记录）'}",
            f"- **当前掌握层级：** {card.get('mastery', 'new')}",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 本周综合测试说明",
        "",
        "请围绕本周词汇完成以下任务：",
        "",
        "1. 从本周词汇中任选 10 个，写出中文义与一个英文搭配。",
        "2. 从本周词汇中任选 5 个，各写一个英文句子。",
        "3. 阅读理解任务：请用本周高频词自行总结本周文章的共同主题。",
        "4. 写作任务：使用至少 8 个本周词汇，写一段 150-200 词英文短文。",
        "",
        "## 批改提交说明",
        "",
        "你把答案发回来后，agent 会：",
        "",
        "- 批改词义、搭配、拼写、造句",
        "- 生成每周词汇掌握报告",
        "- 把结果写回生词本，继续调整遗忘曲线安排",
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
    save_json(meta_path, {
        "week": week_key,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "learned_words": [word for word, _, _ in learned],
        "covered_days": covered_days,
    })
    print(f"Wrote weekly deck -> {out_path}")
    print(f"Wrote weekly meta -> {meta_path}")
    return out_path, meta_path


def record_results(results_path: Path, target_date: date) -> None:
    ensure_dirs()
    profile = load_profile()
    notebook = load_json(NOTEBOOK_PATH, notebook_default())
    reports = load_json(WEEKLY_REPORTS_PATH, {"reports": []})
    payload = load_json(results_path, {})
    graded = payload.get("graded", [])
    summary = []
    for item in graded:
        word = normalize(item.get("word", ""))
        quality = int(item.get("quality", 0))
        if word in notebook["cards"]:
            review_record(notebook["cards"][word], quality, target_date, profile)
            summary.append({
                "word": word,
                "quality": quality,
                "stage": notebook['cards'][word].get('stage', 0),
                "next_due": notebook['cards'][word].get('due_date'),
            })
    reports["reports"].append({
        "date": target_date.isoformat(),
        "source": str(results_path),
        "graded": summary,
    })
    save_json(NOTEBOOK_PATH, notebook)
    save_json(WEEKLY_REPORTS_PATH, reports)
    export_learned_words(notebook=notebook)
    print(f"Recorded {len(summary)} graded notebook items.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent vocabulary notebook + daily/weekly deck generator.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    ingest = sub.add_parser("ingest-article")
    ingest.add_argument("source_file")
    ingest.add_argument("--article-id", default="")
    ingest.add_argument("--date", default=None)

    daily = sub.add_parser("build-daily")
    daily.add_argument("--date", default=None)
    daily.add_argument("--out", default=None)

    weekly = sub.add_parser("build-weekly")
    weekly.add_argument("--date", default=None)
    weekly.add_argument("--out", default=None)

    record = sub.add_parser("record-results")
    record.add_argument("results_file")
    record.add_argument("--date", default=None)

    sub.add_parser("export-learned")

    args = parser.parse_args()

    if args.cmd == "init":
        init_system()
    elif args.cmd == "ingest-article":
        ingest_article(Path(args.source_file), article_id=args.article_id or None, today=parse_date(args.date))
    elif args.cmd == "build-daily":
        out = Path(args.out) if args.out else None
        build_daily(parse_date(args.date), out_path=out)
    elif args.cmd == "build-weekly":
        out = Path(args.out) if args.out else None
        build_weekly(parse_date(args.date), out_path=out)
    elif args.cmd == "record-results":
        record_results(Path(args.results_file), parse_date(args.date))
    elif args.cmd == "export-learned":
        export_learned_words()
        print(f"Exported learned words -> {LEARNED_WORDS_PATH}")


if __name__ == "__main__":
    main()
