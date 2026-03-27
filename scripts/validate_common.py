#!/usr/bin/env python3
"""
Shared semantic validation utilities.

Design principles:
- Structural checks (counts, section existence) stay strict but with tolerance bands
- Field presence uses "equivalent group" fuzzy matching
- Content quality uses pattern-family detection instead of exact banned strings
- Cross-entry repetition detection catches "lazy copy-paste" generation
- Truly unacceptable content (【待补全】) remains a hard gate
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Dict, List, Sequence, Tuple


# ─── Fuzzy heading / field matching ───────────────────────────────────────────

def normalize_heading(text: str) -> str:
    """Collapse whitespace, strip punctuation variants, lowercase."""
    text = re.sub(r"\s+", "", text)         # kill all whitespace
    text = re.sub(r"[/／]", "/", text)      # unify slashes
    text = text.replace("：", ":").lower()
    return text


def fuzzy_heading_match(needle: str, haystack: str, threshold: float = 0.75) -> bool:
    """Check if needle appears (or a close variant) in haystack."""
    # Exact substring first
    if needle in haystack:
        return True
    # Normalized check
    n_needle = normalize_heading(needle)
    n_haystack = normalize_heading(haystack)
    if n_needle in n_haystack:
        return True
    # Sliding window similarity over haystack
    if len(n_needle) < 2:
        return False
    window = len(n_needle) + 4  # allow a few extra chars
    for i in range(max(1, len(n_haystack) - window + 1)):
        chunk = n_haystack[i:i + window]
        ratio = SequenceMatcher(None, n_needle, chunk).ratio()
        if ratio >= threshold:
            return True
    return False


def find_heading_in_markdown(heading: str, markdown: str) -> int:
    """Find the position of a ## heading in markdown, with fuzzy matching.
    Returns the char position, or -1 if not found.
    """
    # Try exact match first
    exact = f"## {heading}"
    pos = markdown.find(exact)
    if pos >= 0:
        return pos
    # Try normalized match against all ## headings in the document
    for m in re.finditer(r"(?m)^##\s+(.+)$", markdown):
        found_heading = m.group(1).strip()
        if fuzzy_heading_match(heading, found_heading, threshold=0.78):
            return m.start()
    return -1


def extract_section_body_fuzzy(markdown: str, heading: str) -> str:
    """Extract body text under a ## heading, using fuzzy heading match."""
    # Try exact first (fast path)
    pattern = re.compile(rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##(?!#)\s+|\Z)")
    m = pattern.search(markdown)
    if m:
        return m.group(1).strip()
    # Fuzzy: find all headings, pick the best match
    headings = list(re.finditer(r"(?m)^##(?!#)\s+(.+)$", markdown))
    best_idx = -1
    best_ratio = 0.0
    n_target = normalize_heading(heading)
    for i, hm in enumerate(headings):
        n_found = normalize_heading(hm.group(1).strip())
        ratio = SequenceMatcher(None, n_target, n_found).ratio()
        if ratio > best_ratio and ratio >= 0.70:
            best_ratio = ratio
            best_idx = i
    if best_idx < 0:
        return ""
    start = headings[best_idx].end()
    end = headings[best_idx + 1].start() if best_idx + 1 < len(headings) else len(markdown)
    return markdown[start:end].strip()


# ─── Field presence: equivalent-group matching ────────────────────────────────

# Each "field" is a group of equivalent names. Any one match = field present.
FIELD_EQUIVALENTS: Dict[str, List[str]] = {
    "词库标签": ["词库标签", "词库标记", "词库来源", "标签"],
    "音标": ["音标", "发音", "IPA", "phonetic"],
    "中文释义": ["中文释义", "释义", "词义", "完整词义", "含义"],
    "原文例句": ["原文例句", "例句", "语境例句"],
    "搭配": [
        "常见搭配 / 固定短语 / 介词搭配",
        "常见搭配/固定短语/介词搭配",
        "常见搭配",
        "固定搭配",
        "搭配",
        "介词搭配",
    ],
    "多义辨析": ["多义辨析", "义项辨析", "词义辨析"],
    "词源演变": ["词源演变", "词源", "etymology", "词源分析"],
    "单词派生": ["单词派生", "派生词", "派生", "词族", "相关派生"],
    "来源": ["来源", "出处", "来源标签"],
    "拆词构词": [
        "拆词 / 构词",
        "拆词/构词",
        "拆词",
        "构词",
        "构词分析",
        "词根词缀",
        "词根词缀解析",
        "词根",
    ],
    "助记": ["助记", "记忆技巧", "记忆", "助记法"],
    "完整词义": ["完整词义", "词义", "中文释义", "释义"],
}


def field_present(field_key: str, text: str) -> bool:
    """Check if a field (by semantic group) is present in text.
    field_key is one of the keys in FIELD_EQUIVALENTS.
    """
    equivalents = FIELD_EQUIVALENTS.get(field_key, [field_key])
    for variant in equivalents:
        # Match as bold markdown field label: **label：** or **label:**
        # Also match plain text with colon
        patterns = [
            f"**{variant}：**",
            f"**{variant}:**",
            f"**{variant}",
            f"{variant}：",
            f"{variant}:",
        ]
        for pat in patterns:
            if pat in text:
                return True
    return False


def check_fields_present(required_keys: Sequence[str], text: str) -> Tuple[List[str], List[str]]:
    """Check required fields are present. Returns (missing, found)."""
    missing = []
    found = []
    for key in required_keys:
        if field_present(key, text):
            found.append(key)
        else:
            missing.append(key)
    return missing, found


# ─── Content quality: pattern-family detection ────────────────────────────────

# Instead of exact banned strings, detect PATTERNS of low-quality content.
# Each pattern has: regex, description, severity ("error" or "warning")

HARD_BANNED = [
    "【待补全】",
]

# Regex patterns that indicate template/boilerplate content.
# These catch the SPIRIT of bad content, not exact wording.
BOILERPLATE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Vague study advice with no specific content
    (re.compile(r"建立肌肉记忆"), "空泛学习建议（建立肌肉记忆）"),
    (re.compile(r"多读多背"), "空泛学习建议（多读多背）"),
    # "lock on to this meaning in the text" family — deflects instead of analyzing
    (re.compile(r"(本文|阅读时|这里).{0,6}(优先取|先锁定|先抓|先看).{0,8}(义|语境|义项)"),
     "回避多义分析，用'本文优先取X义'兜底"),
    # "another common meaning is..." without actually explaining the difference
    (re.compile(r"另一个常见(义项|含义|用法)是"),
     "多义辨析只是列举义项，没有分析差异"),
    # Generic advice to "combine with collocations and examples"
    (re.compile(r"结合(搭配|例句|语境).{0,6}(记忆|理解|学习|掌握)"),
     "空泛记忆建议（结合XX记忆）"),
    # "start from word form" without specifics
    (re.compile(r"(可以|建议).{0,4}从词(形|根|缀)入手"),
     "空泛构词建议，无具体拆解"),
    # "just link it to X" without explaining how
    (re.compile(r"(建议|可以).{0,4}(顺手|随手)联想"),
     "空泛联想建议，未说明联想什么"),
    # "grab the high-frequency meaning first"
    (re.compile(r"先抓高频(义项|义|含义)"),
     "回避深层分析（先抓高频义项）"),
    # "this word has a long history" says nothing
    (re.compile(r"该词(历史|来源).{0,4}(较久|悠久|古老)"),
     "空泛词源描述，无具体演变路径"),
    # "then gradually expanded to common extended meanings"
    (re.compile(r"(随后|后来|逐渐).{0,6}(扩展|引申|发展).{0,6}(常见|普遍|日常).{0,4}(引申义|义项|含义)"),
     "空泛语义演变描述，无具体分化路径"),
    # "don't memorize meanings separately" — correct advice but not analysis
    (re.compile(r"(义项|多义).{0,6}(别|不要|不宜).{0,6}(拆开|分开|单独).{0,4}(背|记)"),
     "学习建议代替实质分析"),
    # "don't just memorize the Chinese gloss"
    (re.compile(r"不(适合|要|能|宜).{0,4}只背.{0,6}(中文|词义|释义|词头)"),
     "学习建议代替实质分析"),
    # "build the shortest word family chain"
    (re.compile(r"建立.{0,4}最短词族链"),
     "空泛派生建议"),
]

# Patterns indicating GOOD content (used to avoid false positives on borderline cases)
SUBSTANCE_INDICATORS = re.compile(
    r"(→|←|来自|源自|演变|词根|前缀|后缀|拉丁|希腊|古英语|法语|日耳曼|"
    r"例如|如：|e\.g\.|vs\.?|区别|侧重|强调|语气|搭配|宾语)"
)


def check_content_quality(text: str, context: str = "") -> Tuple[List[str], List[str]]:
    """Check text for boilerplate/template content.
    Returns (errors, warnings).
    errors = hard-banned content (【待补全】)
    warnings = detected boilerplate patterns
    """
    errors: List[str] = []
    warnings: List[str] = []

    for banned in HARD_BANNED:
        if banned in text:
            errors.append(f"含未完成标记：{banned}")

    for pattern, description in BOILERPLATE_PATTERNS:
        for match in pattern.finditer(text):
            # Check if the surrounding context has real substance
            # (avoid false positive when boilerplate-like phrase is inside real analysis)
            start = max(0, match.start() - 60)
            end = min(len(text), match.end() + 60)
            neighborhood = text[start:end]
            substance_count = len(SUBSTANCE_INDICATORS.findall(neighborhood))
            if substance_count >= 3:
                # Enough surrounding substance — likely a real discussion, not boilerplate
                continue
            prefix = f"[{context}] " if context else ""
            warnings.append(f"{prefix}疑似空泛内容：{description}（原文：…{match.group()}…）")

    return errors, warnings


# ─── Section heading fuzzy match ──────────────────────────────────────────────

def check_sections_present(
    required: Sequence[str],
    markdown: str,
) -> Tuple[List[str], Dict[str, int]]:
    """Check required ## headings are present using fuzzy match.
    Returns (missing_headings, found_positions).
    """
    missing = []
    positions: Dict[str, int] = {}
    for heading in required:
        pos = find_heading_in_markdown(heading, markdown)
        if pos < 0:
            missing.append(heading)
        else:
            positions[heading] = pos
    return missing, positions


# ─── Cross-entry repetition detection ─────────────────────────────────────────

def _normalize_for_similarity(text: str) -> str:
    """Strip punctuation, whitespace, and common structural words to compare
    the *substance* of two field values."""
    text = re.sub(r"[，。；：、！？…\s\-—–·/\\()（）【】\[\]\"\"''\"']", "", text)
    # Remove the word itself when it appears (since every entry naturally names its word)
    text = text.lower()
    return text


def _pairwise_similarity(texts: List[str]) -> List[float]:
    """Return list of pairwise similarity ratios for a set of texts."""
    normed = [_normalize_for_similarity(t) for t in texts]
    ratios: List[float] = []
    for i in range(len(normed)):
        for j in range(i + 1, len(normed)):
            if not normed[i] or not normed[j]:
                continue
            # For very long texts, compare only the first 200 chars for speed
            a = normed[i][:200]
            b = normed[j][:200]
            ratios.append(SequenceMatcher(None, a, b).ratio())
    return ratios


def check_cross_entry_repetition(
    entries: List[Dict[str, str]],
    field_label: str,
    *,
    sim_threshold: float = 0.55,
    ratio_threshold: float = 0.35,
) -> List[str]:
    """Detect lazy repetition across entries for a specific field.

    entries: list of {word: ..., field_label: <content>}
    sim_threshold: two entries are "similar" if ratio >= this
    ratio_threshold: warn if this fraction of pairs are similar

    Returns list of warning strings (empty = OK).
    """
    texts = [(e.get("word", "?"), e.get(field_label, "")) for e in entries]
    # Filter out empty/very short content
    valid = [(w, t) for w, t in texts if len(t) > 10]
    if len(valid) < 4:
        return []  # too few entries to judge

    _, contents = zip(*valid)
    sims = _pairwise_similarity(list(contents))
    if not sims:
        return []

    high_sim_count = sum(1 for s in sims if s >= sim_threshold)
    ratio = high_sim_count / len(sims)

    warnings = []
    if ratio >= ratio_threshold:
        # Find the most repeated patterns to show in the warning
        avg_sim = sum(sims) / len(sims)
        warnings.append(
            f"{field_label} 跨词条重复度偏高：{high_sim_count}/{len(sims)} 对"
            f"（{ratio:.0%}）相似度 ≥ {sim_threshold}，均值 {avg_sim:.2f}。"
            f"请检查是否存在批量套模板。"
        )

    # Also check for exact duplicate content (stricter)
    normed_contents = [_normalize_for_similarity(t) for _, t in valid]
    dupes = Counter(normed_contents)
    for content, count in dupes.items():
        if count >= 3 and len(content) > 8:
            # Find which words share this exact content
            dupe_words = [w for w, t in valid if _normalize_for_similarity(t) == content]
            warnings.append(
                f"{field_label} 有 {count} 个词条内容完全相同：{', '.join(dupe_words[:5])}"
            )

    return warnings
