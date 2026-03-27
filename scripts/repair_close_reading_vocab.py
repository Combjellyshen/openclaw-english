#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from build_close_reading_vocab import morphology_text, mw_lookup, render_markdown


FIELDS = ["focus_items", "hard_items"]
PENDING = "【待补全】"


def load_wordbook() -> dict:
    path = Path("/home/bot/.openclaw/workspace-english/vocabulary/wordbook.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def clean_etymology_text(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"[；;]?\s*词根词缀：\s*【待补全】[^；\n]*", "", text)
    text = re.sub(r"[；;]?\s*【待补全】[^；\n]*", "", text)
    text = re.sub(r"[；;]{2,}", "；", text).strip("；; ")
    return text


def repair_item(item: dict, wordbook: dict) -> bool:
    word = str(item.get("word", "")).strip()
    if not word:
        return False
    original_ety = str(item.get("词源演变", "")).strip()
    ety = clean_etymology_text(original_ety)
    changed = ety != original_ety
    if "词根词缀：" not in ety:
        dict_result = mw_lookup(word)
        learner_result = mw_lookup(word, learner=True)
        morph = morphology_text(word, dict_result, learner_result, wordbook.get(word.lower(), {}))
        morph = clean_etymology_text(morph)
        if ety:
            item["词源演变"] = f"{ety}；{morph}"
        else:
            item["词源演变"] = morph
        changed = True
    else:
        item["词源演变"] = ety
    item["has_pending_content"] = any(PENDING in str(item.get(k, "")) for k in ["多义辨析", "词源演变", "单词派生"])
    item["needs_deep_enrichment"] = item["has_pending_content"]
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair close-reading vocab etymology/root-affix fields to satisfy validator.")
    parser.add_argument("json_file")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args()

    src = Path(args.json_file)
    data = json.loads(src.read_text(encoding="utf-8"))
    wordbook = load_wordbook()
    changed = 0
    for bucket in FIELDS:
        for item in data.get(bucket, []):
            if repair_item(item, wordbook):
                changed += 1

    out_json = Path(args.out_json) if args.out_json else src
    out_md = Path(args.out_md) if args.out_md else src.with_suffix('.md')
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(data), encoding="utf-8")
    print(json.dumps({"ok": True, "changed": changed, "out_json": str(out_json), "out_md": str(out_md)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
