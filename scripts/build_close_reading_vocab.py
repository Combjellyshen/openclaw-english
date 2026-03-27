#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from close_reading_common import VOCAB_REQUIRED_FIELDS, write_json
from exam_vocab_match import LIST_LABELS, extract_text, load_dataset, match_text
from mw_lookup import lookup as mw_lookup

ROOT = Path(__file__).resolve().parent.parent
WORDBOOK_PATH = ROOT / "vocabulary" / "wordbook.json"

PREFIX_HINTS = {
    "anti": "anti- 表“反对、对抗”",
    "inter": "inter- 表“在……之间、相互”",
    "trans": "trans- 表“跨越、转移”",
    "sub": "sub- 表“在下、次级”",
    "con": "con-/com- 表“共同、一起”",
    "pro": "pro- 表“向前、支持”",
    "re": "re- 表“再次、回返”",
    "de": "de- 表“向下、去除”",
    "pre": "pre- 表“在前、预先”",
    "post": "post- 表“在后、之后”",
    "mis": "mis- 表“错误、坏”",
    "dis": "dis- 表“否定、分离”",
    "auto": "auto- 表“自动、自我”",
    "micro": "micro- 表“微小”",
    "macro": "macro- 表“宏观、较大”",
}
SUFFIX_HINTS = {
    "tion": "-tion 常把动作 / 过程变成名词",
    "sion": "-sion 常把动作 / 状态变成名词",
    "ment": "-ment 常表示结果、状态或手段",
    "ity": "-ity 常把形容词变成抽象名词",
    "ness": "-ness 常表示性质、状态",
    "ism": "-ism 常表示主义、思想或现象",
    "ist": "-ist 常表示某类人或立场",
    "ive": "-ive 常见于形容词，表示“具有……性质”",
    "ous": "-ous 常见于形容词，表示“充满……的”",
    "able": "-able 常表示“能够……的”",
    "ible": "-ible 常表示“能够……的”",
    "ize": "-ize/-ise 常把词变成动词，表示“使……化”",
    "ise": "-ize/-ise 常把词变成动词，表示“使……化”",
    "ology": "-ology 常表示“……学”",
    "graphy": "-graphy 常表示“书写、记录、学科”",
}
CORE_HINTS = {
    "history",
    "memory",
    "freedom",
    "protest",
    "photograph",
    "photography",
    "image",
    "landscape",
    "exile",
    "stateless",
    "nomad",
    "violence",
    "resistance",
    "art",
    "artist",
    "political",
    "reportage",
}


def load_wordbook() -> Dict[str, dict]:
    if not WORDBOOK_PATH.exists():
        return {}
    raw = json.loads(WORDBOOK_PATH.read_text(encoding="utf-8"))
    items = raw.get("words", []) if isinstance(raw, dict) else []
    return {str(item.get("word", "")).strip().lower(): item for item in items if item.get("word")}


PENDING_MARKER = "【待补全】"


def first_nonempty(*values: str) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def pending_text(message: str) -> str:
    return f"{PENDING_MARKER}{message}"


def is_pending(value: str) -> bool:
    return PENDING_MARKER in str(value)


def merge_ipa(hit: dict, dict_result: dict, learner_result: dict, wordbook_entry: dict) -> str:
    uk = first_nonempty(hit.get("uk", ""))
    us = first_nonempty(hit.get("us", ""))
    wb_ipa = str(wordbook_entry.get("ipa", "")).strip()
    fallback = ""
    for source in (dict_result, learner_result):
        for pron in source.get("pronunciations", []):
            ipa = str(pron.get("ipa", "")).strip()
            if ipa:
                fallback = ipa
                break
        if fallback:
            break

    parts = []
    if uk:
        parts.append(f"UK /{uk}/")
    elif wb_ipa:
        parts.append(f"UK {wb_ipa}")
    elif fallback:
        parts.append(f"UK /{fallback}/")
    if us:
        parts.append(f"US /{us}/")
    elif wb_ipa:
        parts.append(f"US {wb_ipa}")
    elif fallback:
        parts.append(f"US /{fallback}/")
    return "； ".join(parts) if parts else "（暂无音标）"


def local_definitions(hit: dict) -> List[str]:
    defs = []
    for item in hit.get("translations", [])[:4]:
        pos = str(item.get("type", "")).strip()
        translation = str(item.get("translation", "")).strip()
        if translation:
            defs.append(f"{pos + '. ' if pos else ''}{translation}")
    return defs


def chinese_definition_text(hit: dict, dict_result: dict, wordbook_entry: dict) -> str:
    defs = local_definitions(hit)
    if defs:
        return "； ".join(defs)
    if wordbook_entry.get("meaning_zh"):
        return str(wordbook_entry["meaning_zh"]).strip()
    mw_defs = [str(item.get("definition", "")).strip() for item in dict_result.get("senses", [])[:3] if item.get("definition")]
    if mw_defs:
        return " / ".join(mw_defs)
    return "（暂无完整词义）"


def lists_text(hit: dict) -> str:
    lists = hit.get("lists", [])
    return " / ".join(LIST_LABELS[name] for name in lists) if lists else "未命中本地词库"


def wordbook_collocations(wordbook_entry: dict) -> List[str]:
    items = []
    for coll in wordbook_entry.get("collocations", [])[:6]:
        phrase = str(coll.get("phrase", "")).strip()
        zh = str(coll.get("meaning_zh", "")).strip()
        if phrase:
            items.append(f"{phrase}（{zh or '词书记录'}）")
    return items


def hit_collocations(hit: dict) -> List[str]:
    items = []
    for p in hit.get("phrases", [])[:6]:
        phrase = str(p.get("phrase", "")).strip()
        translation = str(p.get("translation", "")).strip()
        if phrase:
            items.append(f"{phrase}（{translation or '—'}）")
    return items


def article_phrase_candidates(hit: dict) -> List[str]:
    sentence = str(hit.get("first_sentence", "")).strip()
    if not sentence:
        return []
    tokens = re.findall(r"[A-Za-z][A-Za-z\-']*", sentence)
    surfaces = {str(x).lower() for x in hit.get("matched_forms", [])}
    surfaces.add(str(hit.get("word", "")).lower())
    out: List[str] = []
    for i, token in enumerate(tokens):
        lowered = token.lower()
        if lowered not in surfaces:
            continue
        windows = [
            tokens[max(0, i - 1): min(len(tokens), i + 2)],
            tokens[i: min(len(tokens), i + 3)],
            tokens[max(0, i - 2): i + 1],
        ]
        for chunk in windows:
            if 2 <= len(chunk) <= 4:
                phrase = " ".join(chunk).strip()
                if phrase and phrase.lower() != lowered:
                    out.append(f"{phrase}（文中表达）")
    deduped = []
    seen = set()
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]


def merged_phrase_text(hit: dict, wordbook_entry: dict) -> str:
    phrases = hit_collocations(hit)
    if not phrases:
        phrases = wordbook_collocations(wordbook_entry)
    if not phrases:
        phrases = article_phrase_candidates(hit)
    if not phrases:
        return "（暂无高质量搭配记录）"

    preposition_like = []
    fixed = []
    for phrase in phrases:
        if re.search(r"\b(of|for|to|with|in|on|at|from|into|over|under|about|against|between|through)\b", phrase):
            preposition_like.append(phrase)
        else:
            fixed.append(phrase)

    merged = []
    seen = set()
    for phrase in fixed + preposition_like:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(phrase)
    return "； ".join(merged[:6]) if merged else "（暂无高质量搭配记录）"


def priority_reason(hit: dict) -> str:
    labels = hit.get("lists", [])
    reasons = []
    if len(labels) >= 3:
        reasons.append("三库重合，考试复现率高")
    elif len(labels) == 2:
        reasons.append("双词库重合，迁移价值高")
    else:
        reasons.append("单词库命中，但在本文语义位置关键")
    count = int(hit.get("count", 0))
    if count >= 3:
        reasons.append("文中反复出现")
    sentence = str(hit.get("first_sentence", "")).lower()
    if any(token in sentence for token in CORE_HINTS):
        reasons.append("直接卡住文章核心概念")
    return "；".join(reasons)


def difficult_reason(hit: dict) -> str:
    word = str(hit.get("word", "")).lower()
    labels = set(hit.get("lists", []))
    reasons = []
    if "sat" in labels:
        reasons.append("更偏高阶书面词")
    if "cet6" not in labels:
        reasons.append("不属于基础六级高频层")
    if len(word) >= 9 or "-" in word:
        reasons.append("词形更复杂")
    if any(word.endswith(suffix) for suffix in SUFFIX_HINTS):
        reasons.append("抽象义或书面义更强")
    sentence = str(hit.get("first_sentence", "")).lower()
    if any(token in sentence for token in CORE_HINTS):
        reasons.append("直接卡住本文关键表达")
    if not reasons:
        reasons.append("在本文里理解门槛明显高于普通信息词")
    return "；".join(reasons)


def base_etymology_text(word: str, dict_result: dict, learner_result: dict, wordbook: Dict[str, dict]) -> str:
    wb = wordbook.get(word.lower(), {})
    ety = first_nonempty(dict_result.get("etymology", ""), learner_result.get("etymology", ""))
    if ety:
        return f"MW：{ety}"
    if wb.get("etymology"):
        return str(wb["etymology"]).strip()

    lower = word.lower()
    for prefix, hint in PREFIX_HINTS.items():
        if lower.startswith(prefix) and len(lower) >= len(prefix) + 3:
            stem = lower[len(prefix):]
            return f"构词推测：{hint}；{word} 可先看作 {prefix}- + {stem}，词义通常沿着这个前缀方向展开。"
    for suffix, hint in SUFFIX_HINTS.items():
        if lower.endswith(suffix) and len(lower) >= len(suffix) + 3:
            stem = lower[:-len(suffix)]
            return f"构词推测：{stem} + -{suffix}；{hint}。"
    return pending_text("词源链不足，需要联网补词源或补做构词分析。")


def morphology_text(word: str, dict_result: dict, learner_result: dict, wordbook_entry: dict) -> str:
    ety = etymology_raw(word, dict_result, learner_result, wordbook_entry).lower()
    lower = word.lower()

    if any(token in ety for token in ["manu ten", "manutenere", "hold in the hand"]):
        return "词根词缀：manu- 是“手”，ten/tain 是“握住”；maintain 本质上有“用手托住、不让它掉下去”的感觉，所以才会发展出维持、坚持。"
    if any(token in ety for token in ["attribuere", "tribuere", "bestow"]):
        return "词根词缀：at-/ad- 表“向、加到”，trib 是“分配、给予”；attribute 原先就是“把东西归给某个来源”，所以动词是归因/署名，名词是归属到某对象身上的属性。"
    if any(token in ety for token in ["aequival", "equal power", "valere"]):
        return "词根词缀：equi- 表“相等”，val 表“力量、价值”；equivalent 不是表面一样，而是在价值、作用或表达效果上能对齐。"
    if any(token in ety for token in ["extra ordinem", "extraordinarius", "ordin"]):
        return "词根词缀：extra- 表“在外、超出”，ordin/order 表“秩序、顺序”；extraordinary 字面就是“出了常规秩序”，所以既可指非凡，也可指非常规的特别安排。"
    if any(token in ety for token in ["invadere", "enter with hostile intent"]):
        return "词根词缀：in- 表“进入”，vad/vade 表“走、闯”；invasion 就是“强行闯进去”，所以从军事入侵自然延伸到对隐私、身体、空间的侵犯。"
    if any(token in ety for token in ["possid", "have possession", "take possession", "potis", "sedere"]):
        return "词根词缀：词形背后可抓 potis（有能力）+ sed/sid（坐、停留）这组来源，合起来有“坐定并占住”的感觉；所以 possess 从占有一路延伸到具备，再到被某种东西控制。"
    if any(token in ety for token in ["profiteri", "public declaration"]):
        return "词根词缀：pro- 有“向前、公开”色彩，fess/fiteri 和“承认、说出”有关；profession 本来就是把身份或信念正式说出来，后来才固定成公开认领的职业身份。"
    if any(token in ety for token in ["committere", "entrust", "delegated authority"]):
        return "词根词缀：com- 表“共同”，mit/miss 有“送出、派出”色彩；commission 里保留的是“把任务或权力交出去”的感觉，所以会连到委托、委员会、佣金。"
    if any(token in ety for token in ["spont", "own accord"]):
        return "词根词缀：spont- 这一块本身就带“出于自身意愿”的意思；spontaneous 的重点不是外力推动，而是事情从内部自己冒出来。"
    if any(token in ety for token in ["contempor", "tempor", "same period of time"]):
        return "词根词缀：con-/com- 表“共同”，tempor 是“时间”；contemporary 就是“跟某个对象处在同一时间层”，所以既能指同时代，也能指当代。"

    parts = []
    for prefix, hint in PREFIX_HINTS.items():
        if lower.startswith(prefix) and len(lower) >= len(prefix) + 3:
            parts.append(f"前缀 {prefix}-：{hint}")
            break
    for suffix, hint in SUFFIX_HINTS.items():
        if lower.endswith(suffix) and len(lower) >= len(suffix) + 3:
            parts.append(f"后缀 -{suffix}：{hint}")
            break

    if parts:
        return "词根词缀：" + "；".join(parts) + "。"
    return f"词根词缀：{pending_text(f'{word} 需要单独补做词根词缀解析。')}"


def etymology_text(word: str, dict_result: dict, learner_result: dict, wordbook: Dict[str, dict]) -> str:
    wb = wordbook.get(word.lower(), {})
    ety_text = base_etymology_text(word, dict_result, learner_result, wordbook)
    morph_text = morphology_text(word, dict_result, learner_result, wb)
    return f"{ety_text}；{morph_text}"


def normalize_definition_text(text: str) -> str:
    text = re.sub(r"^[a-z]+\.\s*", "", str(text).strip(), flags=re.I)
    text = text.replace("；", "; ").replace("/", " / ")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ;，,")


def split_definition_candidates(text: str) -> List[str]:
    text = normalize_definition_text(text)
    if not text:
        return []
    parts = re.split(r"[;；]|\s/\s|，(?=[^\d])|,(?=[A-Za-z\u4e00-\u9fff])", text)
    out = []
    for part in parts:
        part = normalize_definition_text(part)
        if len(part) >= 2:
            out.append(part)
    return out


def ordered_unique(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for item in items:
        key = normalize_definition_text(item).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(normalize_definition_text(item))
    return out


def collect_definition_candidates(hit: dict, dict_result: dict, wordbook_entry: dict) -> List[str]:
    defs: List[str] = []
    for item in local_definitions(hit):
        defs.extend(split_definition_candidates(item))
    if wordbook_entry.get("meaning_zh"):
        defs.extend(split_definition_candidates(str(wordbook_entry["meaning_zh"])))
    for sense in dict_result.get("senses", [])[:4]:
        defs.extend(split_definition_candidates(str(sense.get("definition", ""))))
    return ordered_unique(defs)[:6]


def context_hint(hit: dict) -> str:
    sentence = str(hit.get("first_sentence", "")).strip()
    if not sentence:
        return "本文这个句子"
    forms = sorted([str(x) for x in hit.get("matched_forms", [])] + [str(hit.get("word", ""))], key=len, reverse=True)
    for form in forms:
        if not form:
            continue
        m = re.search(rf"\b{re.escape(form)}\b", sentence, flags=re.I)
        if not m:
            continue
        before = re.findall(r"[A-Za-z][A-Za-z\-']*", sentence[:m.start()])[-3:]
        after = re.findall(r"[A-Za-z][A-Za-z\-']*", sentence[m.end():])[:5]
        snippet = " ".join(before + [form] + after).strip()
        if snippet:
            return snippet
    return sentence[:80]


def etymology_raw(word: str, dict_result: dict, learner_result: dict, wordbook_entry: dict) -> str:
    return first_nonempty(dict_result.get("etymology", ""), learner_result.get("etymology", ""), wordbook_entry.get("etymology", ""))


def distinction_text(word: str, hit: dict, dict_result: dict, wordbook_entry: dict) -> str:
    learner_result = mw_lookup(word, learner=True)
    defs = collect_definition_candidates(hit, dict_result, wordbook_entry)
    wb_diff = str(wordbook_entry.get("differentiation", "")).strip()
    ety = etymology_raw(word, dict_result, learner_result, wordbook_entry).lower()
    clue = context_hint(hit)
    joined_defs = " | ".join(defs).lower()
    lower = word.lower()

    if lower.startswith("possess") or ((any(token in ety for token in ["have possession", "take possession", "able + sedere", "to sit"]) or "possid" in ety) and any(token in joined_defs for token in ["占有", "拥有", "控制", "具备", "迷住"])):
        return f"这个词的核心不是单纯“有”，而是“把某物纳入自己的范围里”。所以第一层是实物或法律上的“占有、拥有”；往抽象处走，就成了“具备某种能力、气质或叙事力量”；再往心理方向走，才会出现“被某种情绪/观念控制、迷住”这种用法。它们的联系都在“某种东西牢牢落在谁的支配范围内”。本文里它落在“{clue}”这个位置，说的是“具有、带有”，更接近 have / carry，不是 own 那种所有权，也不是 be possessed by 那种被控制。"

    if any(token in ety for token in ["hold in the hand", "manu ten", "manutenere"]) or ("维持" in joined_defs and ("主张" in joined_defs or "assert" in joined_defs)):
        return f"它的核心动作是“抓住不放、让东西别掉下去”。因此一条线发展成“维持、保持某种状态”；另一条线发展成“坚持、主张某个观点”，因为你是在把立场抓牢。两义不是分裂的：一个抓住的是局面，一个抓住的是判断。本文里它出现在“{clue}”这类位置，讲的是维持一种形象或状态，不是 repair，也不是公开声称；和 keep 相比更正式、更带持续经营的意味。"

    if any(token in ety for token in ["enter with hostile intent", "attack", "violence", "invadere"]) or ("入侵" in joined_defs and ("侵犯" in joined_defs or "侵袭" in joined_defs)):
        return f"这个词的核心是“强行进入别人的边界”。放在国家和军队语境里，就是军事上的“入侵”；对象换成 privacy、body、market 之类非军事对象时，就会变成“侵犯 / 侵袭 / 侵入”。区别不在轻重完全一样，而在越界对象不同：territory 最硬，rights 更抽象，body 更偏生理。本文里“{clue}”显然是历史事件中的军事义，不是抽象的侵犯。"

    if any(token in ety for token in ["equal power", "aequival", "equal"]) or ("等价" in joined_defs or "相等" in joined_defs):
        return f"它背后的核心是“在价值、力量或作用上能对齐”。所以先有数量/价值上的“等值”，再延伸出功能上的“等效”，最后才会有语言里的“对应说法”。这些义项都不是要求长得一样，而是要求在某个维度上能替代。本文里“{clue}”说的是语言对应义：英语里找不到一个能完全对上 saudade 的词；它更接近 equivalent，而不是 identical。"

    if any(token in ety for token in ["attribuere", "bestow", "assign"]) or (("归因" in joined_defs or "归于" in joined_defs) and ("属性" in joined_defs or "特质" in joined_defs)):
        return f"这个词的核心动作是“把东西分配/归到某个来源名下”。作动词时，是把原因、责任或署名归给某个对象，所以有 attribute A to B；作名词时，attribute 是被归在某人或某物身上的特征。两义的联系是同一个“归属”动作：一个处理因果或署名归属，一个处理性质归属。本文里“{clue}”是把照片署名归到 PP 名下，不是在说某种属性。"

    if any(token in ety for token in ["delegated authority", "grant of authority", "entrust", "committere"]) or ("委托" in joined_defs and ("委员会" in joined_defs or "佣金" in joined_defs)):
        return f"这个词的核心是“把任务或权力托付出去”。于是有三条常见分支：委托任务本身叫 commission；受托而形成的机构也叫 commission；在代办关系里拿到的报酬则叫 commission。它们共享的是同一个委托关系，只是分别看任务、机构和报酬。本文里“{clue}”说的是受托项目 / 委约任务，不是委员会，也不是提成。"

    if any(token in ety for token in ["public declaration", "profiteri"]) or ("职业" in joined_defs and ("表白" in joined_defs or "声明" in joined_defs)):
        return f"它最早和“公开表明、正式宣称”有关，后来才固定成一个人公开认领并长期从事的 calling，所以 profession 才会有“职业/专业”这个义项。两义的联系在“正式认领”：不是随手做一下，而是把身份说出来并长期承担。本文里“{clue}”讲的是摄影这个行当怎么运作，接近 trade / field，不是表白。"

    if any(token in ety for token in ["out of course", "out of order", "extra ordinem"]) or ("非凡" in joined_defs and ("临时" in joined_defs or "特别" in joined_defs)):
        return f"它的核心是“脱离常规顺序”。落在评价里，就是“非同寻常、特别出众”；落在制度或程序里，就是“特别安排、非常规的”。联系一直没变：都不是日常轨道上的普通状态。本文里“{clue}”是评价义，强调照片不寻常；如果说 extraordinary meeting，那就变成程序上的“特别会议”。"

    if any(token in ety for token in ["own accord", "by one's own agency", "spont"]) or ("自发" in joined_defs and ("自然" in joined_defs or "无意识" in joined_defs)):
        return f"这个词的核心是“力量从内部发出，不是外面推着走”。所以在人和社会行动里，它是“自发的”；放到表情、反应、语气里，会变成“自然流露、非刻意安排”；放到生理或物理里，则是“无外部触发而自行发生”。三类义项的联系都在“起点在内部”。本文里“{clue}”说的是群众自己涌出的抗议，不是官方组织的，也不是 automatic 那种机械自动。"

    if any(token in ety for token in ["same period of time", "contempor", "tempor"]) or ("当代" in joined_defs and ("同时代" in joined_defs or "同一时期" in joined_defs)):
        return f"它的核心其实很简单，就是“处在同一个时间层”。因此既可以指“同时代的人/事”，也可以在以现在为参照时直接译成“当代的”。这两个义项不是分开的：所谓 contemporary，本质上就是和某个参照时代并行存在。本文里“{clue}”更接近“当时的当代小说”，不是专指某种美学流派。"

    if lower == "reprisal" or ("retaliatory act" in joined_defs and ("restitution" in joined_defs or "国际法" in joined_defs or "force short of war" in joined_defs)):
        return f"这个词的核心不是一般性的“惩罚”，而是“对先前行为作出的回击 / 回报”。所以最常见的一层是 retaliation：别人先动手，你这边随后报复，这就是 reprisal。再往历史和法律语境里走，它会专指国家层面的报复性措施，甚至带有“武装但未到全面战争”的含义；更早一些的义项里，它还可以指“把东西拿回来、要求补偿”。这些义项的联系都在“对先前损失作出反向回应”。本文里“{clue}”说的是家人可能遭到报复，不是普通 punishment，也不是抽象的赔偿。"

    if lower == "mythology" or ("myth" in lower and "神话" in joined_defs):
        return f"这个词的核心是“围绕某个对象形成的一整套神话叙事”。第一层当然是文化里的神话体系；第二层是研究这些神话的 mythology；再往比喻义走，就会变成一个人围绕自己建立起来的传奇形象、传说气场。区别在对象不同：前者是文化故事系统，后者是公众想象中的人设光环。本文里“{clue}”显然是比喻义，说的是寇德卡通过沉默维持自己的传奇感。"

    if lower == "nomadic" or ("游牧" in joined_defs and "流浪" in joined_defs):
        return f"这个词的核心是“没有固定定居点，而是随着生计或处境不断移动”。放在民族志语境里，它就是字面上的“游牧的”；放到现代生活方式里，则常引申为“长期流动、没有稳定基地的”。两义的联系很直接：都强调不扎根。本文里“{clue}”说的是生活方式的引申义，不是在讲字面上的牧业迁徙。"

    if lower == "unknown" or (lower.startswith("un") and "未知" in joined_defs):
        return f"这个词的核心是“知识或身份尚未被确定”。当对象是事实、地区、风险时，它偏“未知的”；当对象是人时，则更像“身份不明的、无人知晓的”。区别不在词本身，而在“未知”的是哪一层：信息未知，还是身份未知。本文里“{clue}”说的是 photographer 的身份没有公开，不是世界上没人认识这类人。"

    if lower == "countless" or ("无数" in joined_defs and "数不尽" in joined_defs):
        return f"它的核心很直白，就是“多到没法一一数出来”。这个词有两种常见力度：一种是接近字面量，真在强调数量巨大；另一种是修辞性夸张，用来放大场景密度。两者的联系都在“计数失去意义”。本文里“{clue}”更接近前者和轻微夸张之间：不是严格数学意义上的不可数，而是在说胶片卷多得惊人。"

    if lower == "distance" or ("距离" in joined_defs and ("远方" in joined_defs or "疏远" in joined_defs)):
        return f"这个词的核心是“两个点之间被拉开的间隔”。先是物理空间上的距离；再可以延伸成时间上的间隔；再进一步才会变成关系上的疏离感。它们的联系都是“中间隔着一段东西”。本文里“{clue}”里的 middle distance 是视觉构图术语，说的是画面中景位置，不是心理距离。"

    if lower == "imperious" or ("专横" in joined_defs and ("迫切" in joined_defs or "傲慢" in joined_defs)):
        return f"这个词的核心是“像发号施令的人那样压过别人”。所以最常见的是“专横、颐指气使”；在少数上下文里，它也能转成“要求立刻服从、迫切到不容商量”。联系都在那种向下压的命令感。本文里“{clue}”写的是俄军指挥官的神态，重点是冷硬和居高临下，不是 urgent 那种“紧急”。"

    if lower == "moment" or ("片刻" in joined_defs and "瞬间" in joined_defs):
        return f"它的核心是“一个被切出来的时间点”。最基本的是片刻 / 瞬间；进一步可以指某个关键时刻；再抽象一点，of moment 会变成“重要的、有分量的”。这些义项并不散：都是在给时间点加不同权重。本文里“{clue}”就是最基础的时间点义，表示“从那一刻起”。"

    if lower == "upheaval" or ("剧变" in joined_defs and ("隆起" in joined_defs or "动荡" in joined_defs)):
        return f"这个词的核心动作是“原本平稳的东西被猛地掀起来、翻起来”。所以它既可以保留较具体的“隆起、翻动”感觉，也很自然地转成社会政治上的“剧变、动荡”。区别只在对象：地面、结构被掀起，或秩序、社会被掀翻。本文里“{clue}”说的是布拉格之春后的政治剧变，不是字面的地表起伏。"

    if lower == "affectation" or ("做作" in joined_defs and ("矫揉造作" in joined_defs or "装模作样" in joined_defs)):
        return f"这个词的核心不是普通的“风格”，而是“刻意做出来给别人看的姿态”。因此它既可以指某个具体的做作举动或腔调，也可以指更抽象的矫饰气质。两义的联系都在“不是自然流露，而是人为摆出来”。本文里“{clue}”是在否认那种“把睡地板当浪漫姿态表演”的读法，不是在说真实审美风格。"

    return pending_text(f"多义辨析未完成：{word} 还需要按“核心义→分化路径→区别与联系→本文义”补全；语境片段：{clue}")


def example_text(hit: dict, dict_result: dict, learner_result: dict, wordbook_entry: dict) -> str:
    sentence = str(hit.get("first_sentence", "")).strip()
    if sentence:
        return sentence
    for source in (learner_result, dict_result):
        examples = source.get("examples", [])
        if examples:
            return str(examples[0]).strip()
    examples = wordbook_entry.get("example_sentences", [])
    if examples:
        return str(examples[0].get("en", "")).strip() or "（暂无高质量例句）"
    return "（暂无高质量例句）"


def derivation_text(word: str, dict_result: dict, wordbook_entry: dict) -> str:
    lower = word.lower()
    families = []
    for item in wordbook_entry.get("word_family", []):
        text = re.sub(r"\s*\([^)]*\)", "", str(item)).strip()
        if text:
            families.append(text)
    seen = set()
    ordered = []
    for item in families:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    if ordered:
        family_text = "； ".join(ordered[:4])
        if len(ordered) >= 2:
            return f"可顺着这个词的词族一起记：{family_text}。不要把它当孤立词条背，最好看它在词族里是动作、性质还是结果名词。"
        return f"词族里优先记这个相关形式：{family_text}。注意它和原词的词性变化，会带来句法位置的变化。"

    if lower == "maintain":
        return "maintain → maintenance（维护；保养）→ maintainable（可维持的）。记的时候不要只背动词，要顺手把“动作—结果/状态—可……性”这一串一起带上。"
    if lower == "attribute":
        return "attribute → attribution（归因；署名）→ attributable（可归因于……的）→ attributive（定语性的）。这组很适合一起记，因为它们都围着“归属/归因”打转。"
    if lower == "equivalent":
        return "equivalent → equivalence（等值；等效关系）→ equivalently（等价地）→ equivalency（等值状态）。核心别丢：都是在讲“某个维度上能对齐”。"
    if lower == "invasion":
        return "invade（入侵）→ invasion（入侵行为）→ invader（入侵者）→ invasive（侵入性的）。这组能把“动作—事件—施动者—性质”四层关系串起来。"
    if lower == "reprisal":
        return "reprisal 常见复数形式是 reprisals，表示“一连串报复措施”。顺带对照近义派生链 retaliate → retaliation → retaliatory，会更容易看清“报复动作—报复行为—报复性的”这条线。"
    if lower == "mythology":
        return "myth（神话）→ mythical / mythic（神话般的）→ mythology（神话体系 / 神话叙事）→ mythologize（神话化）。这组很适合拿来看“故事—性质—体系—神话化动作”的扩展。"
    if lower == "nomadic":
        return "nomad（游牧者）→ nomadic（游牧的；流动的）→ nomadism（游牧生活 / 流动生活）。重点是看它怎样从“人”扩到“生活方式/状态”。"
    if lower == "unknown":
        return "know（知道）→ known（已知的）→ unknown（未知的）→ knowingly（明知地）→ knowledge（知识）。这组很适合拿来分清“知道这件事”“已知状态”“未知状态”。"
    if lower == "distance":
        return "distance（距离）→ distant（遥远的）→ distantly（远远地）→ distancing（拉开距离；疏离化）。要一起看名词、形容词和动词化用法怎么切换。"
    if lower == "countless":
        return "count（计数）→ countable（可数的）→ countless（多到数不过来）。这个词族很短，但正好能看清“可被计数”怎么翻成“多到失去计数意义”。"
    if lower == "imperious":
        return "imperious（专横的）→ imperiously（专横地）→ imperiousness（专横）。记的时候重点不是堆形式，而是把那种居高临下的语气一并带住。"
    if lower == "upheaval":
        return "upheave（掀起；翻起）→ upheaval（剧变；动荡）。这组直接展示了“动作”怎么固化成“事件/局面”。"
    if lower == "affectation":
        return "affect（装出；做作地模仿）→ affected（做作的）→ affectation（矫饰；装模作样）。这组能把“动作—性质—结果性名词”连起来。"
    if lower == "moment":
        return "moment（片刻）→ momentary（瞬间的）→ momentous（重大的）。这组特别适合看同一个词根怎么分成“时间短”与“分量重”两条线。"

    return pending_text(f"单词派生未完成：{word} 需要补做词族 / 派生链分析。")


def build_item(hit: dict, wordbook: Dict[str, dict], source_label: str, reason_text: str) -> dict:
    word = str(hit.get("word", "")).strip()
    dict_result = mw_lookup(word)
    learner_result = mw_lookup(word, learner=True)
    wb = wordbook.get(word.lower(), {})
    phrase_text = merged_phrase_text(hit, wb)

    item = {
        "word": word,
        "来源": source_label,
        "词库标签": lists_text(hit),
        "入选理由": reason_text,
        "音标": merge_ipa(hit, dict_result, learner_result, wb),
        "中文释义": chinese_definition_text(hit, dict_result, wb),
        "原文例句": example_text(hit, dict_result, learner_result, wb),
        "常见搭配 / 固定短语 / 介词搭配": phrase_text,
        "多义辨析": distinction_text(word, hit, dict_result, wb),
        "词源演变": etymology_text(word, dict_result, learner_result, wordbook),
        "单词派生": derivation_text(word, dict_result, wb),
        "source_forms": sorted(hit.get("matched_forms", [])),
        "count": int(hit.get("count", 0)),
    }
    missing = [field for field in VOCAB_REQUIRED_FIELDS if not str(item.get(field, "")).strip()]
    item["missing_fields"] = missing
    item["needs_web_enrichment"] = bool(not first_nonempty(dict_result.get("etymology", ""), learner_result.get("etymology", "")))
    item["has_pending_content"] = any(is_pending(item.get(field, "")) for field in ["多义辨析", "词源演变", "单词派生"])
    item["needs_deep_enrichment"] = item["has_pending_content"] or bool(missing)
    return item


def select_hits(result: dict, count: int) -> List[dict]:
    hits = list(result.get("hits", []))
    return hits[:count]


def score_difficult_hit(hit: dict) -> float:
    word = str(hit.get("word", "")).lower()
    labels = set(hit.get("lists", []))
    sentence = str(hit.get("first_sentence", "")).lower()

    score = 0.0
    if "sat" in labels:
        score += 2.5
    if "cet6" not in labels:
        score += 1.5
    if "kaoyan" not in labels:
        score += 0.8
    if len(labels) == 1:
        score += 1.2
    score += min(len(word), 14) / 2.5
    if "-" in word:
        score += 1.5
    if any(word.startswith(prefix) for prefix in PREFIX_HINTS):
        score += 0.5
    if any(word.endswith(suffix) for suffix in SUFFIX_HINTS):
        score += 0.8
    if int(hit.get("count", 0)) <= 2:
        score += 0.5
    if any(token in sentence for token in CORE_HINTS):
        score += 1.0
    return score


def select_difficult_hits(result: dict, blocked_words: set[str], count: int) -> List[dict]:
    hits = [
        hit for hit in result.get("hits", [])
        if str(hit.get("word", "")).strip().lower() not in blocked_words
    ]
    hits.sort(key=lambda x: (-score_difficult_hit(x), x["first_sentence_index"], str(x["word"]).lower()))
    selected: List[dict] = []
    seen = set(blocked_words)
    for hit in hits:
        word = str(hit.get("word", "")).strip().lower()
        if not word or word in seen:
            continue
        selected.append(hit)
        seen.add(word)
        if len(selected) >= count:
            break
    return selected


def _format_inline_field(label: str, content: str) -> str:
    """Format a multi-paragraph field as a single bullet with <br> line breaks.

    Python-Markdown cannot reliably keep multi-paragraph continuation inside
    <li>.  By collapsing newlines into <br> tags the whole field stays in one
    list item, keeping the bullet marker and indentation consistent with the
    short fields above it.  Strips ===END=== enrichment markers.
    """
    text = re.sub(r"\s*===END===\s*$", "", content).strip()
    text = text.replace("\n\n", "<br><br>").replace("\n", "<br>")
    return f"- **{label}：** {text}"


def render_entry(item: dict, idx: int, include_source: bool) -> List[str]:
    lines = [f"### {idx}. {item['word']}", ""]
    if include_source:
        lines.append(f"- **来源：** {item['来源']}")
    lines.extend([
        f"- **词库标签：** {item['词库标签']}",
        f"- **音标：** {item['音标']}",
        f"- **中文释义：** {item['中文释义']}",
        f"- **原文例句：** {item['原文例句']}",
        f"- **常见搭配 / 固定短语 / 介词搭配：** {item['常见搭配 / 固定短语 / 介词搭配']}",
    ])
    for field in ["多义辨析", "词源演变", "单词派生"]:
        lines.append(_format_inline_field(field, item[field]))
    lines.extend(["", "---", ""])
    return lines


def render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    focus_items = payload["focus_items"]
    hard_items = payload["hard_items"]
    lines: List[str] = []

    lines.extend([
        "## 考试词库命中概览",
        "",
        f"- **六级命中：** {summary['counts_by_list']['cet6']}",
        f"- **SAT 命中：** {summary['counts_by_list']['sat']}",
        f"- **考研命中：** {summary['counts_by_list']['kaoyan']}",
        f"- **总命中词数：** {summary['unique_hits']}",
        "",
        "真正值得优先讲的，不是最生僻的词，而是既卡住文章主线、又能迁移到考试和写作里的词。",
        "",
    ])

    for item in focus_items:
        lines.append(f"- **{item['word']}**｜{item['词库标签']}｜{item['入选理由']}")

    lines.extend([
        "",
        "## 重点词汇",
        "",
        "这组按“词库命中价值 + 文章主线相关性”来排，负责把最该先讲的词讲透。",
        "",
    ])
    for idx, item in enumerate(focus_items, start=1):
        lines.extend(render_entry(item, idx, include_source=False))

    lines.extend([
        "## 文章难词补充",
        "",
        "下面额外补 10 个文章难词。这组不和上面的重点词汇共用名额，挑选标准看的是本文理解门槛、表达密度和迁移价值，而不是词库重合度。",
        "",
    ])
    for idx, item in enumerate(hard_items, start=1):
        lines.extend(render_entry(item, idx, include_source=True))

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the close-reading vocabulary section from local vocab + MW API.")
    parser.add_argument("article_file", help="Path to the original article markdown/text file.")
    parser.add_argument("--count", type=int, default=10, help="How many priority wordlist-hit words to keep (default: 10).")
    parser.add_argument("--extra-hard-count", type=int, default=10, help="How many extra article-difficult words to add (default: 10).")
    parser.add_argument("--out-md", default=None, help="Output markdown path.")
    parser.add_argument("--out-json", default=None, help="Output JSON path.")
    args = parser.parse_args()

    dataset = load_dataset()
    wordbook = load_wordbook()
    article_path = Path(args.article_file)
    raw = article_path.read_text(encoding="utf-8")
    text = extract_text(raw)
    matched = match_text(text, dataset)
    focus_hits = select_hits(matched, args.count)
    blocked = {str(hit.get("word", "")).strip().lower() for hit in focus_hits}
    hard_hits = select_difficult_hits(matched, blocked, args.extra_hard_count)

    focus_items = [build_item(hit, wordbook, "词库命中重点词", priority_reason(hit)) for hit in focus_hits]
    hard_items = [build_item(hit, wordbook, "文章难词", difficult_reason(hit)) for hit in hard_hits]

    payload = {
        "article_file": str(article_path),
        "summary": matched["summary"],
        "focus_items": focus_items,
        "hard_items": hard_items,
    }

    if args.out_json:
        write_json(Path(args.out_json), payload)
    if args.out_md:
        Path(args.out_md).write_text(render_markdown(payload), encoding="utf-8")

    if not args.out_md and not args.out_json:
        print(render_markdown(payload))


if __name__ == "__main__":
    main()
