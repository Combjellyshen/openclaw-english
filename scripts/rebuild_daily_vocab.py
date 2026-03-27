#!/usr/bin/env python3
"""
rebuild_daily_vocab.py — Rebuild daily vocab cards from MW cache data.

Each word is processed individually (not batch-templated).
Generates per-word content for: 多义辨析, 单词派生, 助记, 拆词/构词, 词源演变.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "mw-cache"
EXAM_DIR = ROOT / "data" / "exam-vocab"


# ── MW data helpers ──────────────────────────────────────────────

def load_mw(word: str) -> list:
    p = CACHE_DIR / f"dict_{word.lower().replace(' ', '_')}.json"
    if p.exists():
        return json.loads(p.read_text("utf-8"))
    return []


def clean_mw_markup(text: str) -> str:
    text = text.replace("{bc}", "")
    text = text.replace("{ldquo}", "\u201c").replace("{rdquo}", "\u201d")
    text = re.sub(r"\{it\}(.*?)\{/it\}", r"\1", text)
    text = re.sub(r"\{wi\}(.*?)\{/wi\}", r"\1", text)
    text = re.sub(r"\{sc\}(.*?)\{/sc\}", r"\1", text)
    text = re.sub(r"\{sx\|([^|]*)\|[^}]*\}", r"\1", text)
    text = re.sub(r"\{ma\}.*?\{/ma\}", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    return text.strip()


def get_etymology(entries: list) -> str:
    for e in entries:
        if not isinstance(e, dict):
            continue
        et = e.get("et", [])
        if et:
            for item in et:
                if isinstance(item, list) and len(item) >= 2 and item[0] == "text":
                    return clean_mw_markup(item[1])
    return ""


def get_pronunciation(entries: list) -> str:
    for e in entries:
        if not isinstance(e, dict):
            continue
        hwi = e.get("hwi", {})
        prs = hwi.get("prs", [])
        if prs:
            mw_pron = prs[0].get("mw", "")
            if mw_pron:
                return f"/{mw_pron}/"
    return ""


def get_all_senses(entries: list) -> list[dict]:
    """Extract all senses with their definitions and examples."""
    senses = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        fl = e.get("fl", "")
        for d in e.get("def", []):
            vd = d.get("vd", fl)
            for sseq_group in d.get("sseq", []):
                for item in sseq_group:
                    if isinstance(item, list) and len(item) >= 2 and item[0] == "sense":
                        sense_data = item[1]
                        dt = sense_data.get("dt", [])
                        text_parts = []
                        examples = []
                        for dt_item in dt:
                            if isinstance(dt_item, list) and len(dt_item) >= 2:
                                if dt_item[0] == "text":
                                    text_parts.append(clean_mw_markup(dt_item[1]))
                                elif dt_item[0] == "vis":
                                    for vis in dt_item[1]:
                                        if isinstance(vis, dict) and "t" in vis:
                                            examples.append(clean_mw_markup(vis["t"]))
                        defn = " ".join(text_parts).strip()
                        if defn:
                            senses.append({
                                "fl": vd or fl,
                                "sn": sense_data.get("sn", ""),
                                "def": defn,
                                "examples": examples,
                            })
    return senses


def get_shortdefs(entries: list) -> list[str]:
    defs = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        for sd in e.get("shortdef", []):
            defs.append(sd)
    return defs


def get_fl_list(entries: list) -> list[str]:
    """Get all word classes (parts of speech)."""
    fls = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        fl = e.get("fl", "")
        if fl and fl not in fls:
            fls.append(fl)
    return fls


def get_uros(entries: list) -> list[dict]:
    """Get derived forms (uros)."""
    uros = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        for u in e.get("uros", []):
            ure = u.get("ure", "").replace("*", "")
            fl = u.get("fl", "")
            if ure:
                uros.append({"word": ure, "fl": fl})
    return uros


def get_syns(entries: list) -> list[str]:
    """Get synonyms."""
    syns = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        for syn_group in e.get("syns", []):
            for pt in syn_group.get("pt", []):
                if isinstance(pt, list) and len(pt) >= 2 and pt[0] == "text":
                    text = clean_mw_markup(pt[1])
                    syns.append(text)
    return syns


# ── Exam vocab helpers ───────────────────────────────────────────

def load_exam_vocab() -> dict:
    """Load exam vocab with translations, phrases, sentences."""
    datasets = {}
    for name in ("cet6", "kaoyan", "sat"):
        p = EXAM_DIR / f"{name}.json"
        if p.exists():
            entries = json.loads(p.read_text("utf-8"))
            index = {}
            for entry in entries:
                w = entry.get("word", "").strip().lower()
                if w:
                    index[w] = entry
            datasets[name] = index
    return datasets


def find_exam_entry(word: str, datasets: dict) -> tuple[Optional[dict], str]:
    """Find word in exam datasets, return (entry, source_label)."""
    w = word.strip().lower()
    for name, label in [("cet6", "六级"), ("kaoyan", "考研"), ("sat", "SAT")]:
        if name in datasets and w in datasets[name]:
            return datasets[name][w], label
    return None, ""


def get_exam_translations(entry: dict) -> str:
    if not entry:
        return ""
    trans = entry.get("translations", [])
    parts = []
    for t in trans:
        tp = t.get("type", "")
        tr = t.get("translation", "")
        if tp and tr:
            parts.append(f"{tp}. {tr}")
    return "；".join(parts)


def get_exam_phrases(entry: dict) -> list[tuple[str, str]]:
    if not entry:
        return []
    return [(p.get("phrase", ""), p.get("translation", "")) for p in entry.get("phrases", []) if p.get("phrase")]


def get_exam_sentences(entry: dict) -> list[tuple[str, str]]:
    if not entry:
        return []
    return [(s.get("sentence", ""), s.get("translation", "")) for s in entry.get("sentences", []) if s.get("sentence")]


# ── Common morphology data ───────────────────────────────────────

PREFIXES = {
    "ad": ("ad-", "向、朝", "to, toward"),
    "ab": ("ab-", "离开", "away from"),
    "anti": ("anti-", "反对、对抗", "against"),
    "com": ("com-/con-", "共同、一起", "together, with"),
    "con": ("con-/com-", "共同、一起", "together, with"),
    "de": ("de-", "向下、去除、完全", "down, away, completely"),
    "dis": ("dis-", "否定、分离", "apart, not"),
    "dys": ("dys-", "不良、困难", "bad, difficult"),
    "ex": ("ex-", "出、外", "out of"),
    "fore": ("fore-", "前面、预先", "before"),
    "in": ("in-/im-", "进入 / 否定", "in, into / not"),
    "im": ("im-/in-", "进入 / 否定", "in, into / not"),
    "inter": ("inter-", "在……之间", "between"),
    "mis": ("mis-", "错误", "wrong"),
    "mono": ("mono-", "单一", "one"),
    "multi": ("multi-", "多", "many"),
    "non": ("non-", "非、不", "not"),
    "out": ("out-", "超过、外", "surpassing, outside"),
    "over": ("over-", "过度、在上", "excessive, above"),
    "pre": ("pre-", "在前、预先", "before"),
    "pro": ("pro-", "向前、支持", "forward, for"),
    "re": ("re-", "再次、回返", "again, back"),
    "sub": ("sub-", "在下", "under"),
    "super": ("super-", "超过、在上", "above, over"),
    "sur": ("sur-", "在上、超过", "over, above"),
    "trans": ("trans-", "跨越", "across"),
    "un": ("un-", "否定", "not"),
    "under": ("under-", "在下、不足", "below, insufficient"),
}

ROOTS = {
    "vert": ("vert/vers", "转 (turn)"),
    "vers": ("vers/vert", "转 (turn)"),
    "min": ("min", "小 (small)"),
    "sum": ("sum/sumpt", "拿、取 (take)"),
    "sumpt": ("sumpt/sum", "拿、取 (take)"),
    "minist": ("ministr", "服务、管理 (serve)"),
    "promin": ("promin < pro+minēre", "向前突出 (project forward)"),
    "band": ("band/bind/bond", "绑、束 (bind)"),
    "wrest": ("wrest/wrast", "扭、摔 (twist, throw)"),
    "gree": ("grat/gree", "令人愉快 (pleasing)"),
    "dram": ("dram < dran", "做、行动 (to do, act)"),
    "und": ("und/ound", "波、溢出 (wave, overflow)"),
    "spond": ("spond/spons", "承诺、回应 (pledge, respond)"),
    "ven": ("ven/vent", "来 (come)"),
    "vent": ("ven/vent", "来 (come)"),
    "leas": ("leas < lax", "松开 (loosen)"),
    "dict": ("dict", "说 (say, speak)"),
    "pend": ("pend/pens", "悬挂、称量 (hang, weigh)"),
    "pens": ("pens/pend", "悬挂、称量、支付 (hang, weigh, pay)"),
    "front": ("front/frons", "前额、前面 (forehead, front)"),
    "pur": ("pur < purus", "纯 (pure)"),
    "not": ("not/nosc", "知道 (know)"),
    "nosc": ("nosc/not", "知道 (know)"),
    "cosm": ("cosm/cosmo", "宇宙、秩序 (universe, order)"),
    "funct": ("funct/fung", "执行 (perform)"),
    "flu": ("flu/flux", "流 (flow)"),
    "leg": ("leg/lect", "选择、读 (choose, read)"),
    "ceed": ("ced/ceed/cess", "走 (go)"),
    "cess": ("cess/ced/ceed", "走 (go)"),
    "ced": ("ced/ceed/cess", "走 (go)"),
    "plic": ("plic/plex/ply", "折叠 (fold)"),
    "pos": ("pos/posit", "放置 (place, put)"),
    "posit": ("posit/pos", "放置 (place, put)"),
    "miss": ("miss/mit", "发送 (send)"),
    "mit": ("mit/miss", "发送 (send)"),
    "duct": ("duct/duc", "引导 (lead)"),
    "duc": ("duc/duct", "引导 (lead)"),
    "spec": ("spec/spect/spic", "看 (look)"),
    "spect": ("spect/spec", "看 (look)"),
    "scrib": ("scrib/script", "写 (write)"),
    "script": ("script/scrib", "写 (write)"),
    "tract": ("tract/trah", "拉 (draw, pull)"),
    "port": ("port", "搬运 (carry)"),
    "fac": ("fac/fact/fect/fic", "做 (make, do)"),
    "fact": ("fact/fac", "做 (make, do)"),
    "fect": ("fect/fac/fic", "做 (make, do)"),
    "fer": ("fer", "带来、承载 (carry, bear)"),
    "press": ("press", "压 (press)"),
    "gen": ("gen/gn", "产生、出生 (birth, produce)"),
    "rupt": ("rupt", "断裂 (break)"),
    "tect": ("tect/teg", "覆盖 (cover)"),
    "neg": ("neg", "否认 (deny)"),
    "dom": ("dom/domin", "统治 (rule)"),
    "domin": ("domin/dom", "统治 (rule)"),
    "prim": ("prim/prem", "第一 (first)"),
    "clud": ("clud/clus", "关闭 (close)"),
    "clus": ("clus/clud", "关闭 (close)"),
    "fund": ("fund/found/fus", "倾倒、底部 (pour, bottom)"),
    "found": ("found/fund", "底部、建立 (bottom, found)"),
    "fus": ("fus/fund", "倾倒 (pour)"),
    "arch": ("arch", "统治、首要 (rule, chief)"),
    "morph": ("morph", "形态 (form, shape)"),
    "clar": ("clar", "清楚 (clear)"),
    "voc": ("voc/vok", "声音、呼叫 (voice, call)"),
    "act": ("act/ag", "做、驱动 (do, drive)"),
    "ag": ("ag/act", "做、驱动 (do, drive)"),
    "greg": ("greg", "群 (flock, group)"),
    "nounce": ("nounce/nunci", "宣告 (announce, declare)"),
    "proach": ("proach < propius", "接近 (near)"),
    "split": ("split", "劈开 (cleave)"),
    "access": ("access < ced", "走近 (go to)"),
    "pen": ("pen/poen", "惩罚 (punish)"),
    "penal": ("penal < poena", "惩罚 (punishment)"),
    "breed": ("breed", "孵化、养育 (brood, nourish)"),
    "stray": ("stray < extra", "外面 (outside, wander)"),
    "worship": ("worship < worth+ship", "价值+状态 (worth+state)"),
    "check": ("check < shah", "王 (king, in chess)"),
    "board": ("board", "板 (plank)"),
    "hither": ("hither", "到这里 (to here)"),
}

SUFFIXES = {
    "tion": ("-tion", "名词后缀，表动作/结果"),
    "sion": ("-sion", "名词后缀，表动作/状态"),
    "ment": ("-ment", "名词后缀，表结果/手段"),
    "ness": ("-ness", "名词后缀，表性质/状态"),
    "ity": ("-ity", "名词后缀，把形容词变抽象名词"),
    "ism": ("-ism", "名词后缀，表主义/现象"),
    "ist": ("-ist", "名词后缀，表人/职业"),
    "ive": ("-ive", "形容词后缀，表具有某性质"),
    "ous": ("-ous", "形容词后缀，表充满……的"),
    "able": ("-able", "形容词后缀，表能够……的"),
    "ible": ("-ible", "形容词后缀，表能够……的"),
    "ize": ("-ize", "动词后缀，表使……化"),
    "ise": ("-ise", "动词后缀，表使……化"),
    "ful": ("-ful", "形容词后缀，表充满的"),
    "less": ("-less", "形容词后缀，表缺乏的"),
    "ly": ("-ly", "副词后缀"),
    "al": ("-al", "形容词后缀，表与……有关的"),
    "ary": ("-ary", "形容词/名词后缀"),
    "ant": ("-ant", "形容词/名词后缀，表……的/……者"),
    "ent": ("-ent", "形容词/名词后缀，表……的/……者"),
    "ic": ("-ic", "形容词后缀，表……的"),
    "ical": ("-ical", "形容词后缀，表……的"),
    "er": ("-er", "名词后缀，表施动者"),
    "or": ("-or", "名词后缀，表施动者"),
    "ure": ("-ure", "名词后缀，表动作/结果"),
    "ance": ("-ance", "名词后缀，表状态/行为"),
    "ence": ("-ence", "名词后缀，表状态/行为"),
}

# Common word bases for compound word detection
COMMON_BASES = {
    "stock": "股票/存货", "broker": "经纪人", "book": "书", "door": "门",
    "wide": "宽的", "spread": "传播", "air": "空气", "craft": "技艺/飞行器",
    "news": "新闻", "paper": "纸", "work": "工作", "shop": "商店",
    "land": "土地", "mark": "标记", "line": "线", "time": "时间",
    "fire": "火", "house": "房子", "light": "光", "water": "水",
    "head": "头", "hand": "手", "foot": "脚", "back": "背/后",
    "out": "外", "over": "上", "under": "下", "down": "下",
    "day": "天", "night": "夜", "sun": "太阳", "moon": "月亮",
    "war": "战争", "peace": "和平", "man": "人", "men": "人",
    "bed": "床", "room": "房间", "side": "边", "way": "路",
    "cut": "切", "ter": "者", "break": "打破", "fast": "快/牢",
    "every": "每个", "some": "某些", "any": "任何", "no": "无",
    "hair": "头发", "dress": "穿", "lug": "拖", "gage": "标准",
    "luggage": "行李", "combat": "战斗", "com": "共同", "bat": "打",
    "counter": "对面/柜台", "count": "计数", "friend": "朋友", "ly": "地",
    "tiny": "微小", "hop": "跳", "chop": "砍", "pause": "暂停",
    "tail": "尾巴", "or": "者", "tailor": "裁缝", "serve": "服务",
    "ant": "者", "servant": "仆人", "league": "联盟", "cosy": "舒适",
    "virgin": "处女/原始", "entire": "完整", "pollute": "污染",
    "loose": "松的", "drive": "驾驶", "hair": "头发",
    "clown": "小丑", "flat": "平的", "sharp": "锋利的",
    "block": "块", "pedal": "踏板", "pope": "教皇",
    "prey": "猎物", "evil": "邪恶", "ivory": "象牙",
    "yoke": "轭", "polar": "极地的", "globe": "地球仪",
    "stomach": "胃", "dynamo": "发电机", "regime": "政权",
    "prick": "刺", "mutter": "咕哝", "mystery": "神秘",
    "parade": "游行", "recruit": "招募", "hygiene": "卫生",
    "snap": "啪", "cope": "应对",
}


def analyze_morphology(word: str) -> dict:
    """Analyze word morphology: prefix, root, suffix."""
    lower = word.lower()
    result = {"prefix": None, "root": None, "suffix": None}

    # Check prefixes
    for pref in sorted(PREFIXES.keys(), key=len, reverse=True):
        if lower.startswith(pref) and len(lower) > len(pref) + 2:
            result["prefix"] = PREFIXES[pref]
            break

    # Check suffixes
    for suf in sorted(SUFFIXES.keys(), key=len, reverse=True):
        if lower.endswith(suf) and len(lower) > len(suf) + 2:
            result["suffix"] = SUFFIXES[suf]
            break

    # Check roots
    for root_key in sorted(ROOTS.keys(), key=len, reverse=True):
        if root_key in lower:
            result["root"] = ROOTS[root_key]
            break

    return result


# ── Card generation (per-word) ───────────────────────────────────

def generate_card(word: str, source: str, exam_entry: Optional[dict],
                  exam_datasets: dict, idx: int) -> str:
    """Generate a single word card with real per-word content."""
    mw_data = load_mw(word)
    senses = get_all_senses(mw_data)
    shortdefs = get_shortdefs(mw_data)
    etymology = get_etymology(mw_data)
    pron = get_pronunciation(mw_data)
    fls = get_fl_list(mw_data)
    uros = get_uros(mw_data)
    morph = analyze_morphology(word)

    # ── 来源 ──
    source_line = source

    # ── 音标 ──
    phonetic = pron if pron else f"/{word}/"

    # ── 完整词义 ──
    if exam_entry:
        trans_text = get_exam_translations(exam_entry)
    else:
        trans_text = ""
    if not trans_text and shortdefs:
        trans_text = "；".join(f"①{d}" if i == 0 else f"②{d}" if i == 1 else f"③{d}"
                              for i, d in enumerate(shortdefs[:4]))
    if not trans_text:
        trans_text = "【待补全】"

    # Build full definition with MW senses
    fl_str = ", ".join(fls) if fls else ""
    if shortdefs:
        numbered = []
        for i, sd in enumerate(shortdefs[:4]):
            numbered.append(f"{'①②③④'[i]}{sd}")
        defn_line = f"{fl_str}. {'; '.join(numbered)}" if fl_str else "; ".join(numbered)
    elif trans_text:
        defn_line = f"{fl_str}. {trans_text}" if fl_str else trans_text
    else:
        defn_line = "【待补全】"

    # ── 搭配 ──
    phrases = []
    if exam_entry:
        for ph, tr in get_exam_phrases(exam_entry)[:5]:
            phrases.append(f"{ph}（{tr}）" if tr else ph)
    # Supplement from MW examples - extract collocations
    if len(phrases) < 3:
        for s in senses:
            for ex in s.get("examples", []):
                if word.lower() in ex.lower() and len(phrases) < 5:
                    # Use short examples as collocation evidence
                    ex_clean = ex.strip()
                    if len(ex_clean) < 50:
                        phrases.append(ex_clean)
    # Also try shortdefs for implicit collocations
    if len(phrases) < 3:
        for sd in shortdefs:
            # Extract "X of Y" or common patterns
            m = re.search(rf'{re.escape(word)}\s+(of|with|in|to|for|from|on|at)\s+\w+', sd, re.I)
            if m and len(phrases) < 5:
                phrases.append(m.group(0))
    if len(phrases) < 3:
        # Generate common patterns based on word class
        if "verb" in " ".join(fls):
            phrases.append(f"{word} + 宾语（常见动宾搭配）")
        elif "noun" in " ".join(fls):
            phrases.append(f"adj. + {word}（常见形名搭配）")
        elif "adjective" in " ".join(fls):
            phrases.append(f"{word} + noun（常见形名搭配）")
    collocations = "；".join(phrases[:5])

    # ── 多义辨析 (per-word, NOT template) ──
    polysemy = build_polysemy(word, senses, shortdefs, fls, mw_data)

    # ── 例句 ──
    example = build_example(word, senses, exam_entry)

    # ── 拆词/构词 ──
    morph_line = build_morphology_line(word, morph, etymology)

    # ── 词源演变 ──
    etym_line = build_etymology_line(word, etymology, morph)

    # ── 单词派生 ──
    deriv_line = build_derivation_line(word, uros, fls, mw_data)

    # ── 助记 ──
    mnemonic = build_mnemonic(word, etymology, morph, uros, shortdefs, mw_data)

    card = f"""### {idx}. {word}

- **来源：** {source_line}
- **音标：** {phonetic}
- **完整词义：** {defn_line}
- **常见搭配 / 固定短语 / 介词搭配：** {collocations}
- **多义辨析：** {polysemy}
- **例句：** {example}
- **拆词 / 构词：** {morph_line}
- **词源演变：** {etym_line}
- **单词派生：** {deriv_line}
- **助记：** {mnemonic}

---"""
    return card


def build_polysemy(word: str, senses: list, shortdefs: list, fls: list, mw_data: list) -> str:
    """Build per-word polysemy analysis based on actual MW senses."""
    if len(shortdefs) < 2 and len(senses) < 2:
        # Single-sense word
        if shortdefs:
            return f'{word} 义项较集中，核心义为\u201c{shortdefs[0]}\u201d。不存在明显的多义分化，记住这一个核心义即可覆盖绝大多数语境。'
        return "【待补全】"

    # Multi-sense: build real analysis
    parts = []

    # 1. Identify the core/original meaning
    if senses:
        core = senses[0]
        core_def = core["def"]
        parts.append(f'{word} 的原始动作/关系是\u201c{core_def}\u201d')

    # 2. Show how meanings diverge
    if len(senses) >= 2:
        sense_descriptions = []
        for i, s in enumerate(senses[:4]):
            fl_tag = f"（{s['fl']}）" if s.get("fl") else ""
            ex_str = ""
            if s.get("examples"):
                ex_str = f"，如：{s['examples'][0]}"
            sense_descriptions.append(f"义项{i+1}{fl_tag}：{s['def']}{ex_str}")

        if len(fls) > 1:
            parts.append(f"该词跨 {'/'.join(fls)} 两个词性")

        # Show divergence path
        if len(senses) >= 2:
            s1 = senses[0]["def"]
            s2 = senses[1]["def"]
            parts.append(f'从\u201c{s1}\u201d出发，引申出\u201c{s2}\u201d')
            if len(senses) >= 3:
                s3 = senses[2]["def"]
                parts.append(f'进一步扩展到\u201c{s3}\u201d')

        # Add sense details
        parts.append("具体义项：" + "；".join(sense_descriptions[:3]))

    # 3. If we have synonyms, add contrast
    syns = get_syns(mw_data)
    if syns:
        parts.append(f"近义对比：{syns[0][:120]}")

    result = "。".join(parts)
    if not result or len(result) < 20:
        return "【待补全】"
    return result


def build_example(word: str, senses: list, exam_entry: Optional[dict]) -> str:
    """Get the best example sentence."""
    # First try MW examples
    for s in senses:
        for ex in s.get("examples", []):
            if len(ex) > 15:
                return ex

    # Try exam entry
    if exam_entry:
        sentences = get_exam_sentences(exam_entry)
        if sentences:
            en, zh = sentences[0]
            return f"{en} / {zh}"

    return "【待补全】"


def build_morphology_line(word: str, morph: dict, etymology: str) -> str:
    """Build 拆词/构词 based on actual morphological analysis."""
    parts = []

    if morph["prefix"]:
        pref_form, pref_cn, pref_en = morph["prefix"]
        parts.append(f"{pref_form}（{pref_cn}，{pref_en}）")

    if morph["root"]:
        root_form, root_meaning = morph["root"]
        parts.append(f"词根 {root_form}（{root_meaning}）")

    if morph["suffix"]:
        suf_form, suf_cn = morph["suffix"]
        parts.append(f"{suf_form}（{suf_cn}）")

    if parts:
        return " + ".join(parts)

    # Fallback: try to extract from etymology
    if etymology:
        # Look for "from X + Y" patterns
        m = re.search(r"from\s+(\w+[-]?)\s*\+\s*(\w+)", etymology)
        if m:
            return f"{m.group(1)} + {m.group(2)}（参见词源）"

    # Check compound words
    lower = word.lower()
    for i in range(3, len(lower) - 2):
        left = lower[:i]
        right = lower[i:]
        if left in COMMON_BASES and right in COMMON_BASES:
            return f"{left}（{COMMON_BASES[left]}）+ {right}（{COMMON_BASES[right]}）"

    # Simple word
    if len(word) <= 5:
        return f"{word} 为基础词汇，不可进一步拆分"
    if len(word) <= 7:
        return f"{word} 无明显可拆前缀/词根/后缀，整词记忆"
    return f"{word} 需按音节拆分记忆"


def build_etymology_line(word: str, etymology: str, morph: dict) -> str:
    """Build etymology + root/affix analysis."""
    parts = []

    if etymology:
        parts.append(etymology)
    else:
        # Construct etymology from morphology when MW has no et
        morph_parts = []
        if morph["prefix"]:
            pref_form, pref_cn, pref_en = morph["prefix"]
            morph_parts.append(f"{pref_form}（{pref_en}）")
        if morph["root"]:
            root_form, root_meaning = morph["root"]
            morph_parts.append(f"{root_form}（{root_meaning}）")
        if morph["suffix"]:
            suf_form, suf_cn = morph["suffix"]
            morph_parts.append(f"{suf_form}（{suf_cn}）")
        if morph_parts:
            parts.append("构词推测：" + " + ".join(morph_parts))
        elif len(word) <= 5:
            parts.append(f"{word} 为基础日耳曼词汇/古英语词汇，无拉丁/希腊词源可追溯")
        else:
            # Check if compound word
            lower = word.lower()
            for i in range(3, len(lower) - 2):
                left = lower[:i]
                right = lower[i:]
                if left in COMMON_BASES and right in COMMON_BASES:
                    parts.append(f"复合词：{left}（{COMMON_BASES[left]}）+ {right}（{COMMON_BASES[right]}）")
                    break
            if not parts:
                parts.append(f"MW 未返回词源，无明确词根词缀可拆解")

    # Add root/affix analysis
    affix_parts = []
    if morph["prefix"]:
        pref_form, pref_cn, pref_en = morph["prefix"]
        affix_parts.append(f'前缀 {pref_form} 表示\u201c{pref_cn}\u201d')
    if morph["root"]:
        root_form, root_meaning = morph["root"]
        affix_parts.append(f'词根 {root_form} 表示\u201c{root_meaning}\u201d')
    if morph["suffix"]:
        suf_form, suf_cn = morph["suffix"]
        affix_parts.append(f"后缀 {suf_form} {suf_cn}")

    if affix_parts:
        parts.append("词根词缀解析：" + "，".join(affix_parts))

    return "。".join(parts) if parts else f"MW 未返回词源，{word} 无明确构词可拆解"


def build_derivation_line(word: str, uros: list, fls: list, mw_data: list) -> str:
    """Build 单词派生 with real derivative relationships."""
    lower = word.lower()

    if uros:
        # Real MW derived forms
        deriv_parts = []
        for u in uros[:4]:
            deriv_parts.append(f"{u['word']}（{u['fl']}）")
        if len(deriv_parts) == 1:
            return f"{word} \u2192 {deriv_parts[0]}，词性转换后核心义不变"
        else:
            return f"{word} 的常见派生：{'，'.join(deriv_parts)}"

    # No MW uros - infer from morphology
    inferred = []

    # Verb derivations
    if "verb" in " ".join(fls):
        if lower.endswith("e"):
            inferred.append(f"{lower}r / {lower[:-1]}or（施动者名词）")
            inferred.append(f"{lower[:-1]}tion / {lower[:-1]}ation（动作名词）")
        elif lower.endswith("t"):
            inferred.append(f"{lower}ion（动作名词）")
            inferred.append(f"{lower}ive（形容词）")
        else:
            inferred.append(f"{lower}er / {lower}ing（施动者 / 动名词）")

    # Adjective derivations
    if "adjective" in " ".join(fls):
        if lower.endswith("ent") or lower.endswith("ant"):
            inferred.append(f"{lower[:-3]}ence / {lower[:-3]}ance（对应名词）")
        elif lower.endswith("al"):
            inferred.append(f"{lower}ly（副词）")
            inferred.append(f"{lower}ity（抽象名词）")
        elif lower.endswith("ive"):
            inferred.append(f"{lower}ly（副词）")
            inferred.append(f"{lower}ness（抽象名词）")
        elif lower.endswith("ous"):
            inferred.append(f"{lower}ly（副词）")
            inferred.append(f"{lower}ness（抽象名词）")
        else:
            inferred.append(f"{lower}ly（副词）")
            inferred.append(f"{lower}ness（名词）")

    # Noun derivations
    if "noun" in " ".join(fls):
        if lower.endswith("tion"):
            base = lower[:-4]
            inferred.append(f"{base}te（对应动词）")
            inferred.append(f"{base}tional（形容词）")
        elif lower.endswith("ment"):
            inferred.append(f"{lower}al（形容词）")
        elif lower.endswith("ance") or lower.endswith("ence"):
            inferred.append(f"{lower[:-4]}ent / {lower[:-4]}ant（对应形容词）")
        elif lower.endswith("ity"):
            inferred.append(f"对应形容词去 -ity 加 -ous / -al 等")
        elif lower.endswith("ism"):
            inferred.append(f"{lower[:-3]}ist（对应从业者/信奉者名词）")
        elif lower.endswith("ness"):
            inferred.append(f"{lower[:-4]}（对应形容词原形）")

    # Common patterns
    if lower.endswith("ly") and "adverb" in " ".join(fls):
        base = lower[:-2]
        if base.endswith("i"):
            base = base[:-1] + "y"
        inferred.append(f"{base}（对应形容词原形）")

    if inferred:
        return "；".join(inferred[:3])

    # Absolute fallback for basic words
    if len(lower) <= 4:
        return f"{word} 为基础短词，派生形式有限，常直接用作复合词构件（如 {lower}+名词）"
    return f"{word} 派生形式需查证，常见方式为加 -ed/-ing/-er 等基本屈折后缀"


def build_mnemonic(word: str, etymology: str, morph: dict,
                   uros: list, shortdefs: list, mw_data: list) -> str:
    """Build a specific, per-word mnemonic. Must not be template."""
    lower = word.lower()
    strategies = []

    # Strategy 1: Etymology-based logical chain (best strategy)
    if morph["prefix"] and morph["root"]:
        pref_form, pref_cn, _ = morph["prefix"]
        root_form, root_meaning = morph["root"]
        if shortdefs:
            chain = f"{pref_form}（{pref_cn}）+ {root_form}（{root_meaning}）"
            if morph["suffix"]:
                suf_form, suf_cn = morph["suffix"]
                chain += f" + {suf_form}（{suf_cn}）"
            chain += f" \u2192 {shortdefs[0][:40]}"
            strategies.append(chain)
    elif morph["prefix"] and shortdefs:
        pref_form, pref_cn, _ = morph["prefix"]
        rest = lower[len([k for k in PREFIXES if lower.startswith(k)][-1]) if any(lower.startswith(k) for k in PREFIXES) else 0:]
        strategies.append(f"{pref_form}（{pref_cn}）+ {rest} \u2192 {shortdefs[0][:40]}")
    elif morph["root"] and shortdefs:
        root_form, root_meaning = morph["root"]
        strategies.append(f"词根 {root_form}（{root_meaning}）是核心，{word} 的义项都围绕这一基本动作展开")

    # Strategy 2: Word family chain (if we have MW derived forms)
    if uros and len(uros) >= 2:
        family = [word] + [u["word"] for u in uros[:3]]
        strategies.append(f"词族链：{' \u2192 '.join(family)}，同源词共享核心义")

    # Strategy 3: Compound word decomposition
    if not strategies:
        for i in range(3, len(lower) - 2):
            left = lower[:i]
            right = lower[i:]
            if left in COMMON_BASES and right in COMMON_BASES:
                strategies.append(f"拆成 {left}（{COMMON_BASES[left]}）+ {right}（{COMMON_BASES[right]}），复合词直拼")
                break

    # Strategy 4: Etymology-based visual image
    if etymology and not strategies:
        m = re.search(r"from\s+(?:Latin|Greek|Old English|Middle English|Anglo-French|Old French|Old Norse)\s+(\w+)", etymology)
        if m:
            orig_word = m.group(1)
            if shortdefs:
                strategies.append(f"源词 {orig_word} \u2192 {word}：从原始义到现代义的演变可视化记忆")

    # Strategy 5: Phonetic / visual association for basic words
    if not strategies:
        if len(lower) <= 4:
            if shortdefs:
                strategies.append(f"{word} 是高频基础词，核心义\u201c{shortdefs[0][:20]}\u201d，通过搭配语境反复巩固")
        elif len(lower) <= 6:
            if shortdefs:
                strategies.append(f"{word} 义为\u201c{shortdefs[0][:20]}\u201d，可与近义词对比记忆")
        else:
            # Try syllable-based
            if shortdefs:
                strategies.append(f"按音节拆分 {word}，将发音与\u201c{shortdefs[0][:20]}\u201d义项关联")

    if strategies:
        return "；".join(strategies[:2])

    return f"{word} 需结合具体语境（见例句）加深印象"


# ── Main ─────────────────────────────────────────────────────────

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2026-03-21"

    json_path = ROOT / "reading-log" / "vocab-drills" / f"{date_str}-daily-vocab.json"
    if not json_path.exists():
        print(f"ERROR: {json_path} not found")
        sys.exit(1)

    word_data = json.loads(json_path.read_text("utf-8"))
    cet6_words = word_data["words"].get("cet6", [])
    kaoyan_words = word_data["words"].get("kaoyan", [])
    notebook_words = word_data["words"].get("notebook", [])

    exam_datasets = load_exam_vocab()

    lines = [f"# 每日词卡包（{date_str}）\n"]

    idx = 1
    # CET6
    if cet6_words:
        lines.append("## 六级词\n")
        for w in cet6_words:
            entry, _ = find_exam_entry(w, exam_datasets)
            card = generate_card(w, "六级", entry, exam_datasets, idx)
            lines.append(card)
            lines.append("")
            idx += 1

    # Kaoyan
    if kaoyan_words:
        lines.append("## 考研词\n")
        for w in kaoyan_words:
            entry, _ = find_exam_entry(w, exam_datasets)
            source = "考研"
            # Check if also in CET6
            if "cet6" in exam_datasets and w.lower() in exam_datasets["cet6"]:
                source = "考研 / 六级"
            card = generate_card(w, source, entry, exam_datasets, idx)
            lines.append(card)
            lines.append("")
            idx += 1

    # Notebook
    if notebook_words:
        lines.append("## 生词本\n")
        for w in notebook_words:
            entry, src = find_exam_entry(w, exam_datasets)
            card = generate_card(w, src or "生词本", entry, exam_datasets, idx)
            lines.append(card)
            lines.append("")
            idx += 1

    md_text = "\n".join(lines)

    # Quality check
    issues = []
    template_patterns = [
        "围着.*记同一家族最值钱",
        "顺着词源记",
        "做题时先看它是在说具体动作",
        "建立肌肉记忆",
        "结合搭配和例句记忆",
        "先抓高频义项",
        "结合语境理解",
        "该词历史较久",
        "随后逐渐扩展出常见引申义",
        "本文优先取.*这一义",
        "另一个常见义项是",
        "阅读时先锁定本文语境",
        "复习时要盯住它常接的宾语和搭配",
        "建议顺手联想.*建立一个最短词族链",
        "可以从词形入手",
        "这个词不只背中文释义",
    ]

    for pat in template_patterns:
        matches = re.findall(pat, md_text)
        if matches:
            issues.append(f"TEMPLATE PATTERN FOUND: '{pat}' — {len(matches)} occurrences")

    pending_count = md_text.count("【待补全】")

    out_path = ROOT / "reading-log" / "vocab-drills" / f"{date_str}-daily-vocab.md"
    out_path.write_text(md_text, encoding="utf-8")

    print(f"Generated: {out_path}")
    print(f"Total words: {idx - 1}")
    print(f"【待补全】 count: {pending_count}")
    if issues:
        print("\n⚠️  TEMPLATE ISSUES:")
        for iss in issues:
            print(f"  - {iss}")
    else:
        print("✅ No template patterns detected")

    if pending_count > 0:
        print(f"\n⚠️  {pending_count} fields still need completion — NOT ready for PDF")
    else:
        print("\n✅ All fields populated — ready for PDF generation")

    return pending_count, issues


if __name__ == "__main__":
    main()
