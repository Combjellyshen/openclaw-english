#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "exam-vocab"
SOURCE_URL = "https://github.com/KyleBing/english-vocabulary"
SOURCE_SUBDIR = Path("json_original/json-sentence")
LIST_FILES = {
    "cet6": ["CET6_1.json", "CET6_2.json", "CET6_3.json"],
    "sat": ["SAT_2.json", "SAT_3.json"],
    "kaoyan": ["KaoYan_1.json", "KaoYan_2.json", "KaoYan_3.json"],
}


def unique_dicts(items: List[dict], key_fields: tuple[str, ...]) -> List[dict]:
    seen = set()
    out = []
    for item in items:
        key = tuple(item.get(field, "") for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def merge_entries(entries: List[dict]) -> List[dict]:
    merged: Dict[str, dict] = {}
    for entry in entries:
        word = str(entry.get("word", "")).strip()
        if not word:
            continue
        norm = word.lower()
        current = merged.setdefault(
            norm,
            {
                "word": word,
                "us": entry.get("us", ""),
                "uk": entry.get("uk", ""),
                "translations": [],
                "phrases": [],
                "sentences": [],
            },
        )
        if not current.get("us") and entry.get("us"):
            current["us"] = entry["us"]
        if not current.get("uk") and entry.get("uk"):
            current["uk"] = entry["uk"]
        current["translations"].extend(entry.get("translations", []))
        current["phrases"].extend(entry.get("phrases", []))
        current["sentences"].extend(entry.get("sentences", []))
        current["translations"] = unique_dicts(current["translations"], ("type", "translation"))
        current["phrases"] = unique_dicts(current["phrases"], ("phrase", "translation"))
        current["sentences"] = unique_dicts(current["sentences"], ("sentence", "translation"))
    return sorted(merged.values(), key=lambda x: x["word"].lower())


def load_entries(repo_path: Path, filenames: List[str]) -> List[dict]:
    all_entries: List[dict] = []
    for filename in filenames:
        path = repo_path / SOURCE_SUBDIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing source file: {path}")
        all_entries.extend(json.loads(path.read_text(encoding="utf-8")))
    return merge_entries(all_entries)


def clone_repo() -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="english-vocabulary-"))
    subprocess.run(
        ["git", "clone", "--depth=1", SOURCE_URL, str(temp_dir)],
        check=True,
    )
    return temp_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync CET6 / SAT / 考研 vocabulary from KyleBing/english-vocabulary.")
    parser.add_argument("--repo-path", help="Use an existing local clone instead of cloning afresh.")
    args = parser.parse_args()

    cleanup_clone = False
    if args.repo_path:
        repo_path = Path(args.repo_path).expanduser().resolve()
    else:
        repo_path = clone_repo()
        cleanup_clone = True

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source": SOURCE_URL,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "lists": {},
    }

    for list_name, filenames in LIST_FILES.items():
        entries = load_entries(repo_path, filenames)
        out_path = DATA_DIR / f"{list_name}.json"
        out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["lists"][list_name] = {
            "files": filenames,
            "entry_count": len(entries),
            "output": str(out_path.relative_to(ROOT)),
        }
        print(f"Synced {list_name}: {len(entries)} entries -> {out_path}")

    (DATA_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote manifest -> {DATA_DIR / 'manifest.json'}")

    if cleanup_clone:
        shutil.rmtree(repo_path, ignore_errors=True)


if __name__ == "__main__":
    main()
