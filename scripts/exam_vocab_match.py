#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "exam-vocab"
LIST_LABELS = {
    "cet6": "六级",
    "sat": "SAT",
    "kaoyan": "考研",
}
STOPWORDS = {
    "the","and","that","with","from","this","they","were","have","their","which","would","there","after",
    "about","these","those","while","where","when","what","into","also","been","than","them","some",
    "said","saying","should","could","being","through","such","more","over","into","then","only","other",
    "same","high","main","many","much","very","well","like","just","will","your","ours","ourselves",
    "whose","whom","here","therefore","however","because","against","before","under","again","between",
    "each","both","does","doing","done","make","made","come","comes","coming","goes","went","gone",
    "take","takes","taking","took","taken","want","wants","wanted","group","people","party","report",
    "government","powers","power","state","states","article","move","bill","rules","types","years","year",
    "large","small","great","greatly","full","fully","last","first","second","third","night","days",
}


def load_dataset() -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for list_name in LIST_LABELS:
        path = DATA_DIR / f"{list_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing local vocab file: {path}. Run scripts/sync_exam_vocab.py first.")
        entries = json.loads(path.read_text(encoding="utf-8"))
        for entry in entries:
            word = str(entry.get("word", "")).strip()
            if not word:
                continue
            norm = word.lower()
            merged = index.setdefault(
                norm,
                {
                    "word": word,
                    "lists": set(),
                    "us": entry.get("us", ""),
                    "uk": entry.get("uk", ""),
                    "translations": [],
                    "phrases": [],
                    "sentences": [],
                },
            )
            merged["lists"].add(list_name)
            if not merged.get("us") and entry.get("us"):
                merged["us"] = entry["us"]
            if not merged.get("uk") and entry.get("uk"):
                merged["uk"] = entry["uk"]
            merged["translations"].extend(entry.get("translations", []))
            merged["phrases"].extend(entry.get("phrases", []))
            merged["sentences"].extend(entry.get("sentences", []))
    for value in index.values():
        value["lists"] = sorted(value["lists"])
        value["translations"] = _dedupe_dicts(value["translations"], ("type", "translation"))
        value["phrases"] = _dedupe_dicts(value["phrases"], ("phrase", "translation"))
        value["sentences"] = _dedupe_dicts(value["sentences"], ("sentence", "translation"))
    return index


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


def token_candidates(token: str) -> Iterable[str]:
    token = token.lower().strip("'\"")
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


def match_text(text: str, dataset: Dict[str, dict]) -> dict:
    sentences = split_sentences(text)
    hits: Dict[str, dict] = {}
    counts_by_list = defaultdict(int)
    sentence_index = 0
    for sentence in sentences:
        sentence_index += 1
        for surface in re.findall(r"[A-Za-z][A-Za-z\-']*", sentence):
            lowered = surface.lower()
            if len(lowered) < 4 or lowered in STOPWORDS:
                continue
            for candidate in token_candidates(surface):
                if candidate in dataset:
                    entry = dataset[candidate]
                    hit = hits.setdefault(
                        candidate,
                        {
                            "word": entry["word"],
                            "lists": entry["lists"],
                            "matched_forms": set(),
                            "count": 0,
                            "first_sentence_index": sentence_index,
                            "first_sentence": sentence,
                            "translations": entry["translations"],
                            "phrases": entry["phrases"],
                            "sentences": entry["sentences"],
                            "us": entry.get("us", ""),
                            "uk": entry.get("uk", ""),
                        },
                    )
                    hit["matched_forms"].add(surface)
                    hit["count"] += 1
                    break
    for hit in hits.values():
        for list_name in hit["lists"]:
            counts_by_list[list_name] += 1
    hit_list = list(hits.values())
    hit_list.sort(key=lambda x: (-score_hit(x), x["first_sentence_index"], x["word"].lower()))
    return {
        "summary": {
            "counts_by_list": {k: counts_by_list.get(k, 0) for k in LIST_LABELS},
            "unique_hits": len(hit_list),
        },
        "hits": hit_list,
    }


def score_hit(hit: dict) -> float:
    return (
        len(hit["lists"]) * 5
        + min(hit["count"], 3)
        + (1 if hit["phrases"] else 0)
        + (1 if hit["sentences"] else 0)
        + min(len(hit["word"]), 10) / 10
    )


def render_translation(entry: dict) -> str:
    parts = []
    for item in entry[:3]:
        t = str(item.get("translation", "")).strip()
        tp = str(item.get("type", "")).strip()
        parts.append(f"{tp}. {t}" if tp else t)
    return "； ".join(parts)


def render_markdown(result: dict, max_hits: int) -> str:
    lines = []
    summary = result["summary"]
    lines.append("## 考试词库命中概览（六级 / SAT / 考研）")
    lines.append("")
    lines.append(f"- **六级命中：** {summary['counts_by_list']['cet6']}")
    lines.append(f"- **SAT 命中：** {summary['counts_by_list']['sat']}")
    lines.append(f"- **考研命中：** {summary['counts_by_list']['kaoyan']}")
    lines.append(f"- **总命中词数：** {summary['unique_hits']}")
    lines.append("")
    lines.append("> 下列为建议优先讲解的命中词，已按词库重合度、文章相关性、可拓展性综合排序。")
    lines.append("")
    for i, hit in enumerate(result["hits"][:max_hits], start=1):
        labels = " / ".join(LIST_LABELS[x] for x in hit["lists"])
        matched_forms = ", ".join(sorted(hit["matched_forms"]))
        lines.append(f"### {i}. 命中词")
        lines.append("")
        lines.append(f"**词：** {hit['word']}")
        lines.append("")
        lines.append(f"- **词库标签：** {labels}")
        lines.append(f"- **原文命中形式：** {matched_forms}")
        lines.append(f"- **原文命中句：** {hit['first_sentence']}")
        lines.append(f"- **词库义项：** {render_translation(hit['translations'])}")
        if hit.get("us") or hit.get("uk"):
            ipa = []
            if hit.get("uk"):
                ipa.append(f"UK /{hit['uk']}/")
            if hit.get("us"):
                ipa.append(f"US /{hit['us']}/")
            lines.append(f"- **音标：** {'； '.join(ipa)}")
        if hit["phrases"]:
            phrases = "； ".join(
                f"{p['phrase']}（{p.get('translation', '').strip()}）" for p in hit["phrases"][:5]
            )
            lines.append(f"- **常见搭配：** {phrases}")
        if hit["sentences"]:
            sample = hit["sentences"][0]
            lines.append(f"- **词库例句：** {sample['sentence']} / {sample.get('translation', '').strip()}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Match article text against local CET6 / SAT / 考研 wordlists.")
    parser.add_argument("text_file", help="Path to the article/source markdown file.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--max-hits", type=int, default=12)
    args = parser.parse_args()

    dataset = load_dataset()
    text = extract_text(Path(args.text_file).read_text(encoding="utf-8"))
    result = match_text(text, dataset)

    if args.format == "json":
        def convert(obj):
            if isinstance(obj, set):
                return sorted(obj)
            raise TypeError
        print(json.dumps(result, ensure_ascii=False, indent=2, default=convert))
    else:
        print(render_markdown(result, args.max_hits))


if __name__ == "__main__":
    main()
