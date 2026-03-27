#!/usr/bin/env python3
"""
mw_lookup.py — Merriam-Webster Dictionary & Learner's API lookup.

Usage:
    python3 scripts/mw_lookup.py <word>
    python3 scripts/mw_lookup.py <word> --learner
    python3 scripts/mw_lookup.py batch '["word1","word2"]'

Output: JSON with definitions, etymology, pronunciation, examples.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "config" / "profile.json"
CACHE_DIR = ROOT / "data" / "mw-cache"


def load_keys() -> dict:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return profile.get("mw_api", {})


def api_url(word: str, learner: bool = False) -> str:
    keys = load_keys()
    if learner:
        key = keys.get("learner_key", "")
        return f"https://www.dictionaryapi.com/api/v3/references/learners/json/{word}?key={key}"
    else:
        key = keys.get("dictionary_key", "")
        return f"https://www.dictionaryapi.com/api/v3/references/collegiate/json/{word}?key={key}"


def fetch(word: str, learner: bool = False) -> list:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = f"{'learner' if learner else 'dict'}_{word.lower().replace(' ', '_')}"
    cache_path = CACHE_DIR / f"{cache_key}.json"

    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = api_url(word, learner)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw-English/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return [{"error": f"HTTP {e.code}", "word": word}]
    except Exception as e:
        return [{"error": str(e), "word": word}]

    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _flatten_dt(dt_list: list) -> str:
    """Recursively extract text from MW's 'dt' definition text format."""
    parts = []
    for item in dt_list:
        if isinstance(item, list) and len(item) >= 2:
            tag, content = item[0], item[1]
            if tag == "text":
                # Strip MW markup like {bc}, {it}...{/it}, {sx|word||}, etc.
                text = str(content)
                text = text.replace("{bc}", "").replace("{/it}", "").replace("{ldquo}", """).replace("{rdquo}", """)
                # Remove {it}...patterns
                text = re.sub(r"\{it\}", "", text)
                text = re.sub(r"\{[^}]*\}", "", text)
                parts.append(text.strip())
            elif tag == "vis":
                # example sentences
                for vis_item in content:
                    if isinstance(vis_item, dict) and "t" in vis_item:
                        ex = re.sub(r"\{[^}]*\}", "", vis_item["t"]).strip()
                        parts.append(f"  例: {ex}")
    return "\n".join(parts)


def parse_entry(raw: dict) -> dict:
    """Parse a single MW dictionary entry into a clean structure."""

    result = {
        "headword": raw.get("meta", {}).get("id", "").split(":")[0],
        "functional_label": raw.get("fl", ""),
        "pronunciations": [],
        "definitions": [],
        "etymology": "",
        "examples": [],
        "short_defs": raw.get("shortdef", []),
    }

    # Pronunciations
    for hw_info in raw.get("hwi", {}).get("prs", []):
        pron = {}
        if "ipa" in hw_info:
            pron["ipa"] = hw_info["ipa"]
        if "mw" in hw_info:
            pron["mw"] = hw_info["mw"]
        if pron:
            result["pronunciations"].append(pron)

    # Etymology
    et = raw.get("et", [])
    if et:
        et_parts = []
        for item in et:
            if isinstance(item, list) and len(item) >= 2:
                text = str(item[1])
                text = re.sub(r"\{[^}]*\}", "", text).strip()
                if text:
                    et_parts.append(text)
        result["etymology"] = " ".join(et_parts)

    # Definitions
    for sense_seq in raw.get("def", []):
        for sseq in sense_seq.get("sseq", []):
            for sense_group in sseq:
                if isinstance(sense_group, list) and len(sense_group) >= 2:
                    sense_data = sense_group[1]
                    if isinstance(sense_data, dict):
                        dt = sense_data.get("dt", [])
                        def_text = _flatten_dt(dt)
                        if def_text:
                            result["definitions"].append(def_text)
                        # Extract examples from vis
                        for dt_item in dt:
                            if isinstance(dt_item, list) and len(dt_item) >= 2 and dt_item[0] == "vis":
                                for vis in dt_item[1]:
                                    if isinstance(vis, dict) and "t" in vis:
                                        ex = re.sub(r"\{[^}]*\}", "", vis["t"]).strip()
                                        if ex:
                                            result["examples"].append(ex)

    return result


def lookup(word: str, learner: bool = False) -> dict:
    raw_data = fetch(word, learner)

    if not raw_data:
        return {"word": word, "error": "no_results"}

    # MW returns strings (suggestions) if word not found exactly
    if raw_data and isinstance(raw_data[0], str):
        return {"word": word, "error": "not_found", "suggestions": raw_data[:10]}

    entries = []
    for item in raw_data:
        if isinstance(item, dict):
            parsed = parse_entry(item)
            if parsed["headword"].lower() == word.lower() or parsed["headword"].lower().startswith(word.lower()):
                entries.append(parsed)

    if not entries:
        return {"word": word, "error": "no_matching_entries"}

    # Merge into a single clean result
    result = {
        "word": word,
        "pronunciations": entries[0].get("pronunciations", []),
        "etymology": "",
        "senses": [],
        "examples": [],
    }

    seen_defs = set()
    for entry in entries:
        fl = entry.get("functional_label", "")
        if entry.get("etymology") and not result["etymology"]:
            result["etymology"] = entry["etymology"]
        for d in entry.get("definitions", []):
            key = d.strip()[:80]
            if key not in seen_defs:
                seen_defs.add(key)
                result["senses"].append({"pos": fl, "definition": d})
        for ex in entry.get("examples", []):
            if ex not in result["examples"]:
                result["examples"].append(ex)
        # Also add short defs
        for sd in entry.get("short_defs", []):
            key = sd.strip()[:80]
            if key not in seen_defs:
                seen_defs.add(key)
                result["senses"].append({"pos": fl, "definition": sd})

    return result


def batch_lookup(words: list, learner: bool = False) -> dict:
    results = {}
    for word in words:
        results[word] = lookup(word.strip(), learner)
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: mw_lookup.py <word> [--learner]")
        print("       mw_lookup.py batch '[\"word1\",\"word2\"]' [--learner]")
        sys.exit(1)

    learner = "--learner" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--learner"]

    if args[0] == "batch" and len(args) >= 2:
        words = json.loads(args[1])
        result = batch_lookup(words, learner)
    else:
        word = args[0]
        result = lookup(word, learner)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
