#!/usr/bin/env python3
"""
model_dispatch.py — Model load balancer for English workspace pipelines.

Reads available providers from openclaw.json and profile.json, then assigns
models to pipeline tasks based on task weight (heavy / medium / light) with
automatic fallback on failure.

Usage:
    from model_dispatch import pick_model, MODEL_TIERS

    model = pick_model("heavy")          # for grammar analysis, polysemy
    model = pick_model("medium")         # for examples, mnemonic
    model = pick_model("light")          # for derivation, etymology lookup
    model = pick_model("heavy", exclude=["openai-codex/gpt-5.4"])  # skip a provider
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
OPENCLAW_PATH = ROOT.parent / "openclaw.json"
PROFILE_PATH = ROOT / "config" / "profile.json"

# ── Tier definitions ──
# Each tier lists models in priority order (first = preferred).
# The dispatcher tries them in order; callers can exclude specific models.

DEFAULT_TIERS: Dict[str, List[str]] = {
    "heavy": [
        "openai-codex/gpt-5.4",
        "github-copilot/claude-opus-4.6",
        "github-copilot/gemini-3.1-pro-preview",
    ],
    "medium": [
        "github-copilot/claude-sonnet-4.6",
        "openai-codex/gpt-5.4",
        "github-copilot/gemini-3.1-pro-preview",
        "github-copilot/gemini-3-flash-preview",
    ],
    "light": [
        "github-copilot/gemini-3-flash-preview",
        "openai-codex/gpt-5.3-codex",
        "github-copilot/claude-sonnet-4.6",
    ],
}

# ── Task-to-tier mapping ──
# Maps pipeline task names to their computational weight tier.

TASK_TIERS: Dict[str, str] = {
    # Close-reading subagents
    "structure_summary": "heavy",
    "grammar": "heavy",
    "insights": "heavy",
    "discussion_exam": "heavy",
    # Daily vocab field modules
    "polysemy": "heavy",
    "derivation": "medium",
    "examples": "medium",
    "mnemonic": "medium",
    "etymology": "light",
    # Weekly vocab modules
    "review_summary": "medium",
    "weekly_exam": "heavy",
    "study_plan": "light",
    # Vocab building
    "vocab_build": "heavy",
    "vocab_enrich": "medium",
}

# ── Failure tracking (in-process only) ──
_failure_counts: Dict[str, int] = {}
_failure_timestamps: Dict[str, float] = {}
FAILURE_COOLDOWN = 300  # seconds before retrying a failed provider
MAX_FAILURES_BEFORE_SKIP = 2


def _load_available_models() -> List[str]:
    """Load the list of configured model providers from openclaw.json."""
    available: List[str] = []
    if OPENCLAW_PATH.exists():
        try:
            data = json.loads(OPENCLAW_PATH.read_text(encoding="utf-8"))
            models_dict = data.get("agents", {}).get("defaults", {}).get("models", {})
            available = list(models_dict.keys())
        except Exception:
            pass
    if not available:
        # Fallback: read from profile.json
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            primary = profile.get("model", {}).get("default", "")
            fallbacks = profile.get("model", {}).get("fallback", [])
            if primary:
                available.append(primary)
            available.extend(fallbacks)
        except Exception:
            pass
    return available or ["openai-codex/gpt-5.4"]


def _is_cooled_down(model: str) -> bool:
    """Check if a previously failed model has passed its cooldown period."""
    if model not in _failure_timestamps:
        return True
    return (time.time() - _failure_timestamps[model]) > FAILURE_COOLDOWN


def report_failure(model: str) -> None:
    """Report that a model call failed, so the dispatcher can avoid it temporarily."""
    _failure_counts[model] = _failure_counts.get(model, 0) + 1
    _failure_timestamps[model] = time.time()


def report_success(model: str) -> None:
    """Report that a model call succeeded, resetting its failure count."""
    _failure_counts.pop(model, None)
    _failure_timestamps.pop(model, None)


def pick_model(
    tier: str = "heavy",
    *,
    task_name: Optional[str] = None,
    exclude: Optional[List[str]] = None,
) -> str:
    """
    Pick the best available model for a given tier or task name.

    Args:
        tier: One of "heavy", "medium", "light".
        task_name: If provided, overrides tier based on TASK_TIERS mapping.
        exclude: List of model IDs to skip (e.g., already in use by parallel tasks).

    Returns:
        A model ID string like "openai-codex/gpt-5.4".
    """
    if task_name and task_name in TASK_TIERS:
        tier = TASK_TIERS[task_name]

    tier_models = DEFAULT_TIERS.get(tier, DEFAULT_TIERS["heavy"])
    available = set(_load_available_models())
    exclude_set = set(exclude or [])

    candidates = []
    for model in tier_models:
        if model not in available:
            continue
        if model in exclude_set:
            continue
        failures = _failure_counts.get(model, 0)
        if failures >= MAX_FAILURES_BEFORE_SKIP and not _is_cooled_down(model):
            continue
        candidates.append(model)

    if not candidates:
        # All preferred models excluded or failed; try any available model
        for model in available:
            if model not in exclude_set:
                candidates.append(model)

    if not candidates:
        return "openai-codex/gpt-5.4"  # absolute fallback

    return candidates[0]


def pick_models_for_parallel(task_names: List[str]) -> Dict[str, str]:
    """
    Assign models to multiple tasks for parallel execution,
    distributing load across different providers when possible.

    Args:
        task_names: List of task names to assign models to.

    Returns:
        Dict mapping task_name -> model_id.
    """
    assignments: Dict[str, str] = {}
    used_models: Dict[str, int] = {}  # model -> count of assignments

    # Sort tasks by tier priority (heavy first, to get best models)
    sorted_tasks = sorted(task_names, key=lambda t: {"heavy": 0, "medium": 1, "light": 2}.get(TASK_TIERS.get(t, "heavy"), 0))

    for task in sorted_tasks:
        # Prefer models not yet assigned to spread load
        model = pick_model(task_name=task)
        best_model = model
        best_count = used_models.get(model, 0)

        # Try to find a less-loaded alternative in the same tier
        tier = TASK_TIERS.get(task, "heavy")
        tier_models = DEFAULT_TIERS.get(tier, DEFAULT_TIERS["heavy"])
        available = set(_load_available_models())

        for alt in tier_models:
            if alt not in available:
                continue
            alt_count = used_models.get(alt, 0)
            if alt_count < best_count:
                best_model = alt
                best_count = alt_count

        assignments[task] = best_model
        used_models[best_model] = used_models.get(best_model, 0) + 1

    return assignments


def get_fallback_chain(model: str) -> List[str]:
    """Get the fallback chain for a given model (all other available models)."""
    available = _load_available_models()
    return [m for m in available if m != model]


# ── CLI for debugging ──
if __name__ == "__main__":
    import sys

    available = _load_available_models()
    print(f"Available models ({len(available)}):")
    for m in available:
        print(f"  - {m}")
    print()

    for tier in ["heavy", "medium", "light"]:
        model = pick_model(tier)
        print(f"Tier '{tier}' -> {model}")

    print()
    tasks = list(TASK_TIERS.keys())
    parallel = pick_models_for_parallel(tasks)
    print("Parallel assignment:")
    for task, model in parallel.items():
        tier = TASK_TIERS.get(task, "?")
        print(f"  {task} ({tier}) -> {model}")
