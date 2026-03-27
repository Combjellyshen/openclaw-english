#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List

from task_run_common import manifest_lock, read_json, record_event, utc_now_iso, write_json

ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = ROOT / "reading-log" / "runs"
OPENCLAW_CONFIG = ROOT.parent / "openclaw.json"
MODEL_ROUTING_PATH = ROOT / "config" / "model_routing.json"

# ── Model routing ──
_model_routing_cache: Dict[str, Any] | None = None


def _load_model_routing() -> Dict[str, Any]:
    global _model_routing_cache
    if _model_routing_cache is not None:
        return _model_routing_cache
    try:
        _model_routing_cache = json.loads(MODEL_ROUTING_PATH.read_text(encoding="utf-8"))
    except Exception:
        _model_routing_cache = {}
    return _model_routing_cache


def resolve_model(task: str, pipeline: str = "") -> str:
    """Resolve model for a pipeline task.

    Lookup priority:
      1. stage_models["{pipeline}.{task}"]
      2. stage_models["{task}"]
      3. fallback (from config, default "")

    Returns "" (= system default / opus) or "sonnet".
    """
    cfg = _load_model_routing()
    stage_models = cfg.get("stage_models", {})
    if pipeline:
        key = f"{pipeline}.{task}"
        if key in stage_models:
            return stage_models[key] or ""
    if task in stage_models:
        return stage_models[task] or ""
    return cfg.get("fallback", "")


CLOSE_STAGE_BY_MODULE = {
    "structure_summary": "structure_summary_done",
    "grammar": "grammar_done",
    "insights": "insights_done",
    "discussion_exam": "discussion_exam_done",
}


class CmdError(RuntimeError):
    pass


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2), file=sys.stderr)
    raise SystemExit(1)


def run_cmd(cmd: List[str], *, cwd: Path = ROOT, timeout: int = 3600) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise CmdError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(cmd)}")
    return proc.stdout.strip()


def latest_run(base: Path) -> Path | None:
    if not base.exists():
        return None
    candidates = [child for child in base.iterdir() if child.is_dir() and (child / "manifest.json").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: ((p / "manifest.json").stat().st_mtime, p.name))


def resolve_run_dir(kind: str, run_dir: str | None, latest: bool) -> Path:
    if run_dir:
        return Path(run_dir)
    if latest:
        base = {
            "daily-vocab": RUNS_ROOT / "daily-vocab",
            "weekly-vocab": RUNS_ROOT / "weekly-vocab",
            "close-reading": RUNS_ROOT,
        }[kind]
        found = latest_run(base)
        if found is None:
            fail(f"找不到 {kind} 的 run")
        return found
    fail("必须提供 --run-dir 或 --latest")


def manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def load_manifest(run_dir: Path) -> Dict[str, Any]:
    return read_json(manifest_path(run_dir), {})


def save_manifest(run_dir: Path, manifest: Dict[str, Any]) -> None:
    write_json(manifest_path(run_dir), manifest)


def set_stage(run_dir: Path, stage: str, status: str, note: str | None = None, **extra: Any) -> None:
    with manifest_lock(run_dir):
        manifest = load_manifest(run_dir)
        stages = manifest.setdefault("stages", {})
        current = stages.setdefault(stage, {})
        current.update({"status": status, "updated_at": utc_now_iso()})
        if note:
            current["note"] = note
        if extra:
            current.update(extra)
        if status == "failed":
            manifest["status"] = "blocked"
        elif status == "running":
            manifest["status"] = "running"
        save_manifest(run_dir, manifest)
    record_event(run_dir, "stage", f"{stage} -> {status}", stage=stage, note=note or "")


def field_names(modules: Iterable[Dict[str, Any]]) -> List[str]:
    return [m["name"] for m in modules]


# Max parallel Claude calls — matches openclaw maxConcurrentSessions
MAX_PARALLEL = 3


def maybe_filter(modules: List[Dict[str, Any]], only: List[str]) -> List[Dict[str, Any]]:
    if not only:
        return modules
    want = set(only)
    missing = [name for name in want if name not in field_names(modules)]
    if missing:
        fail("未知模块：" + "、".join(sorted(missing)))
    return [module for module in modules if module["name"] in want]


def run_claude_prompt(prompt_path: str, out_path: str, timeout: int, prompt_override: str | None = None, model: str = "") -> None:
    cmd = [
        "python3",
        str(ROOT / "scripts" / "claude_exec.py"),
        "--out",
        out_path,
        "--workdir",
        str(ROOT),
        "--timeout",
        str(timeout),
    ]
    if model:
        cmd.extend(["--model", model])
    if prompt_override is not None:
        cmd.extend(["--prompt-text", prompt_override])
    else:
        cmd.extend(["--prompt-file", prompt_path])
    run_cmd(cmd, timeout=timeout + 60)


def run_with_format_retry(prompt_path: str, out_path: str, timeout: int, attach_cmd: List[str], strict_hint: str, model: str = "") -> None:
    try:
        run_claude_prompt(prompt_path, out_path, timeout, model=model)
        run_cmd(attach_cmd, timeout=1200)
        return
    except Exception as first_error:
        prompt_text = Path(prompt_path).read_text(encoding="utf-8")
        retry_prompt = prompt_text.rstrip() + "\n\n最后再强调一次：你上一次的输出没有严格按格式。现在只输出最终 Markdown 正文，不要解释、不总结、不说“已写入”或“已完成”。首个非空行必须是：\n" + strict_hint + "\n"
        run_claude_prompt(prompt_path, out_path, timeout, prompt_override=retry_prompt, model=model)
        run_cmd(attach_cmd, timeout=1200)


def maybe_build_pdf(md_path: str, pdf_path: str) -> None:
    cmd = [
        "python3",
        str(ROOT / "scripts" / "generate_pdf.py"),
        md_path,
        "--out",
        pdf_path,
    ]
    run_cmd(cmd, timeout=1800)


def _get_telegram_bot_token() -> str:
    try:
        cfg = json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
        return cfg.get("channels", {}).get("telegram", {}).get("botToken", "")
    except Exception:
        return ""


def _extract_chat_id(delivery_target: str) -> str:
    if not delivery_target:
        return ""
    if ":" in delivery_target:
        channel, target = delivery_target.split(":", 1)
        if channel == "telegram":
            return target
    return delivery_target


def deliver_pdf_via_telegram(pdf_path: str, caption: str, delivery_target: str) -> None:
    bot_token = _get_telegram_bot_token()
    if not bot_token:
        raise CmdError("telegram botToken 未配置，无法自动发送 PDF")
    chat_id = _extract_chat_id(delivery_target)
    if not chat_id:
        raise CmdError(f"无法解析 delivery_target: {delivery_target}")
    pdf = Path(pdf_path)
    if not pdf.exists():
        raise CmdError(f"PDF 不存在，无法发送：{pdf}")

    boundary = "----OpenClawBoundary7MA4YWxkTrZu0gW"
    data = bytearray()

    def add_text(name: str, value: str) -> None:
        data.extend(f"--{boundary}\r\n".encode())
        data.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        data.extend(value.encode("utf-8"))
        data.extend(b"\r\n")

    add_text("chat_id", chat_id)
    add_text("caption", caption)

    data.extend(f"--{boundary}\r\n".encode())
    data.extend(
        f'Content-Disposition: form-data; name="document"; filename="{pdf.name}"\r\n'.encode()
    )
    data.extend(b"Content-Type: application/pdf\r\n\r\n")
    data.extend(pdf.read_bytes())
    data.extend(b"\r\n")
    data.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendDocument",
        data=bytes(data),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise CmdError(f"Telegram sendDocument 失败：{e}")
    if not payload.get("ok"):
        raise CmdError(f"Telegram sendDocument 返回失败：{payload}")


def ensure_daily_run(args: argparse.Namespace) -> Path:
    if args.create:
        run_cmd([
            "python3", str(ROOT / "scripts" / "daily_vocab_pipeline.py"), "start-run",
            "--date", args.date,
            "--trigger", args.trigger,
            "--requested-by", args.requested_by,
            "--agent", "claude",
            "--delivery-target", args.delivery_target,
            *( ["--force"] if args.force else [] ),
        ])
    run_dir = resolve_run_dir("daily-vocab", args.run_dir, args.latest or args.create)
    manifest = load_manifest(run_dir)
    if manifest.get("stages", {}).get("skeleton_built", {}).get("status") != "done":
        run_cmd(["python3", str(ROOT / "scripts" / "daily_vocab_pipeline.py"), "build-skeleton", "--run-dir", str(run_dir)], timeout=1800)
    return run_dir


def _run_single_module(run_dir: Path, module: Dict[str, Any], pipeline_cmd: str, attach_flag: str, timeout: int, pipeline_kind: str = "") -> str | None:
    """Run a single Claude module. Returns None on success, error string on failure."""
    stage = module["stage"]
    name = module["name"]
    label = module.get("label", name)
    tmp_out = str(run_dir / "artifacts" / f"claude_{name}.md")
    model = resolve_model(name, pipeline_kind)
    try:
        set_stage(run_dir, stage, "running", note=f"Claude writing {name}" + (f" [model={model}]" if model else ""))
        attach_cmd = [
            "python3", str(ROOT / "scripts" / pipeline_cmd), attach_flag,
            "--run-dir", str(run_dir),
        ]
        if attach_flag == "attach-field":
            attach_cmd.extend(["--field", name, "--file", tmp_out])
        elif attach_flag == "attach-module":
            if pipeline_cmd == "weekly_vocab_pipeline.py":
                attach_cmd.extend(["--module", name, "--file", tmp_out])
            else:
                attach_cmd.extend(["--name", name, "--file", tmp_out])
        first_heading = module.get("required_headings", [label])[0] if "required_headings" in module else label
        run_with_format_retry(module["prompt_path"], tmp_out, timeout, attach_cmd, f"## {first_heading}", model=model)
        return None
    except Exception as e:
        set_stage(run_dir, stage, "failed", note=str(e))
        return f"{name} 失败：{e}"


def _run_modules_parallel(run_dir: Path, modules: List[Dict[str, Any]], pipeline_cmd: str, attach_flag: str, timeout: int, kind: str) -> None:
    """Run multiple independent Claude modules in parallel (up to MAX_PARALLEL)."""
    pending = []
    for module in modules:
        manifest = load_manifest(run_dir)
        stage = module["stage"]
        current = manifest.get("stages", {}).get(stage, {}).get("status")
        if current == "done":
            continue
        pending.append(module)

    if not pending:
        return

    # If only 1 module, run directly without thread overhead
    if len(pending) == 1:
        err = _run_single_module(run_dir, pending[0], pipeline_cmd, attach_flag, timeout, pipeline_kind=kind)
        if err:
            fail(f"{kind} / {err}")
        return

    errors: List[str] = []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(pending))) as pool:
        futures = {
            pool.submit(_run_single_module, run_dir, mod, pipeline_cmd, attach_flag, timeout, kind): mod
            for mod in pending
        }
        for future in as_completed(futures):
            mod = futures[future]
            try:
                err = future.result()
                if err:
                    errors.append(err)
            except Exception as e:
                errors.append(f"{mod['name']} 异常：{e}")

    if errors:
        fail(f"{kind} 失败：" + "; ".join(errors))


def run_daily(args: argparse.Namespace) -> None:
    run_dir = ensure_daily_run(args)
    manifest = load_manifest(run_dir)
    modules = maybe_filter(list(manifest.get("field_modules", [])), args.only)

    _run_modules_parallel(run_dir, modules, "daily_vocab_pipeline.py", "attach-field", args.timeout, "daily-vocab")

    if not args.modules_only:
        manifest = load_manifest(run_dir)
        if manifest.get("stages", {}).get("assembled", {}).get("status") != "done":
            run_cmd(["python3", str(ROOT / "scripts" / "daily_vocab_pipeline.py"), "assemble", "--run-dir", str(run_dir)], timeout=600)
        if manifest.get("stages", {}).get("validated", {}).get("status") != "done":
            run_cmd(["python3", str(ROOT / "scripts" / "daily_vocab_pipeline.py"), "validate", "--run-dir", str(run_dir)], timeout=600)
        manifest = load_manifest(run_dir)
        if args.build_pdf and manifest.get("stages", {}).get("pdf_built", {}).get("status") != "done":
            maybe_build_pdf(manifest["paths"]["assembled_markdown"], manifest["paths"]["pdf"])
            run_cmd([
                "python3", str(ROOT / "scripts" / "daily_vocab_pipeline.py"), "mark-pdf",
                "--run-dir", str(run_dir),
                "--file", manifest["paths"]["pdf"],
            ], timeout=300)
        manifest = load_manifest(run_dir)
        if args.build_pdf and manifest.get("stages", {}).get("pdf_built", {}).get("status") == "done" and manifest.get("stages", {}).get("delivered", {}).get("status") != "done":
            deliver_pdf_via_telegram(
                manifest["paths"]["pdf"],
                "今日词卡已完成。",
                manifest.get("delivery_target", args.delivery_target),
            )
            run_cmd([
                "python3", str(ROOT / "scripts" / "daily_vocab_pipeline.py"), "mark-delivered",
                "--run-dir", str(run_dir),
                "--note", f"sent to {manifest.get('delivery_target', args.delivery_target)}",
            ], timeout=300)

    print(run_cmd(["python3", str(ROOT / "scripts" / "daily_vocab_pipeline.py"), "status", "--run-dir", str(run_dir)], timeout=300))


def ensure_weekly_run(args: argparse.Namespace) -> Path:
    if args.create:
        run_cmd([
            "python3", str(ROOT / "scripts" / "weekly_vocab_pipeline.py"), "start-run",
            "--date", args.date,
            "--trigger", args.trigger,
            "--requested-by", args.requested_by,
            "--agent", "claude",
            "--delivery-target", args.delivery_target,
            *( ["--force"] if args.force else [] ),
        ])
    run_dir = resolve_run_dir("weekly-vocab", args.run_dir, args.latest or args.create)
    manifest = load_manifest(run_dir)
    if manifest.get("stages", {}).get("skeleton_built", {}).get("status") != "done":
        run_cmd(["python3", str(ROOT / "scripts" / "weekly_vocab_pipeline.py"), "build-skeleton", "--run-dir", str(run_dir)], timeout=1800)
    return run_dir


def run_weekly(args: argparse.Namespace) -> None:
    run_dir = ensure_weekly_run(args)
    manifest = load_manifest(run_dir)
    modules = maybe_filter(list(manifest.get("modules", [])), args.only)

    _run_modules_parallel(run_dir, modules, "weekly_vocab_pipeline.py", "attach-module", args.timeout, "weekly-vocab")

    if not args.modules_only:
        manifest = load_manifest(run_dir)
        if manifest.get("stages", {}).get("assembled", {}).get("status") != "done":
            run_cmd(["python3", str(ROOT / "scripts" / "weekly_vocab_pipeline.py"), "assemble", "--run-dir", str(run_dir)], timeout=600)
        if manifest.get("stages", {}).get("validated", {}).get("status") != "done":
            run_cmd(["python3", str(ROOT / "scripts" / "weekly_vocab_pipeline.py"), "validate", "--run-dir", str(run_dir)], timeout=600)
        manifest = load_manifest(run_dir)
        if args.build_pdf and manifest.get("stages", {}).get("pdf_built", {}).get("status") != "done":
            maybe_build_pdf(manifest["paths"]["assembled_markdown"], manifest["paths"]["pdf"])
            run_cmd([
                "python3", str(ROOT / "scripts" / "weekly_vocab_pipeline.py"), "mark-pdf",
                "--run-dir", str(run_dir),
                "--file", manifest["paths"]["pdf"],
            ], timeout=300)

    print(run_cmd(["python3", str(ROOT / "scripts" / "weekly_vocab_pipeline.py"), "status", "--run-dir", str(run_dir)], timeout=300))


def run_close_reading(args: argparse.Namespace) -> None:
    run_dir = resolve_run_dir("close-reading", args.run_dir, args.latest)
    manifest = load_manifest(run_dir)
    if not manifest:
        fail(f"找不到 close-reading manifest：{manifest_path(run_dir)}")

    stages = manifest.get("stages", {})
    if stages.get("source_attached", {}).get("status") != "done":
        fail("close-reading 尚未 attach-source，无法继续。")

    if stages.get("exam_matched", {}).get("status") != "done" or stages.get("vocab_built", {}).get("status") != "done":
        vocab_md = str(run_dir / "artifacts" / "claude_vocab.md")
        vocab_json = str(run_dir / "artifacts" / "claude_vocab.json")
        try:
            set_stage(run_dir, "exam_matched", "running", note="building vocab + exam match")
            run_cmd([
                "python3", str(ROOT / "scripts" / "build_close_reading_vocab.py"),
                manifest["paths"]["original_article"],
                "--out-md", vocab_md,
                "--out-json", vocab_json,
            ], timeout=max(args.timeout, 1800))
            try:
                run_cmd([
                    "python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "attach-vocab",
                    "--run-dir", str(run_dir),
                    "--md-file", vocab_md,
                    "--json-file", vocab_json,
                ], timeout=1200)
            except Exception:
                enriched_json = str(run_dir / "artifacts" / "claude_vocab.enriched.json")
                enriched_md = str(run_dir / "artifacts" / "claude_vocab.enriched.md")
                run_cmd([
                    "python3", str(ROOT / "scripts" / "enrich_close_reading_vocab.py"),
                    vocab_json,
                    "--out-json", enriched_json,
                    "--out-md", enriched_md,
                    "--timeout", str(max(args.timeout, 1800)),
                ], timeout=max(args.timeout, 1800) + 120)
                run_cmd([
                    "python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "attach-vocab",
                    "--run-dir", str(run_dir),
                    "--md-file", enriched_md,
                    "--json-file", enriched_json,
                ], timeout=1200)
        except Exception as e:
            set_stage(run_dir, "exam_matched", "failed", note=str(e))
            set_stage(run_dir, "vocab_built", "failed", note=str(e))
            fail(f"close-reading / vocab 失败：{e}")
        manifest = load_manifest(run_dir)

    # Ensure notebook_ingested is marked done (assemble requires it)
    if manifest.get("stages", {}).get("notebook_ingested", {}).get("status") != "done":
        try:
            run_cmd([
                "python3", str(ROOT / "scripts" / "vocab_system.py"), "ingest-article",
                manifest["paths"]["original_article"],
                "--article-id", manifest.get("run_id", "auto"),
            ], timeout=600)
        except Exception:
            pass  # ingest is best-effort; mark done regardless to unblock pipeline
        set_stage(run_dir, "notebook_ingested", "done", note="auto-marked by claude_pipeline_runner")
        manifest = load_manifest(run_dir)

    modules = maybe_filter(list(manifest.get("subagent_tasks", [])), args.only)
    # Map close-reading module names to their pipeline stage names
    for mod in modules:
        if "stage" not in mod:
            mod["stage"] = CLOSE_STAGE_BY_MODULE[mod["name"]]

    _run_modules_parallel(run_dir, modules, "close_reading_pipeline.py", "attach-module", args.timeout, "close-reading")

    if not args.modules_only:
        manifest = load_manifest(run_dir)
        if manifest.get("stages", {}).get("assembled", {}).get("status") != "done":
            run_cmd(["python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "assemble", "--run-dir", str(run_dir)], timeout=900)
        if manifest.get("stages", {}).get("validated", {}).get("status") != "done":
            run_cmd(["python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "validate", "--run-dir", str(run_dir)], timeout=900)
        manifest = load_manifest(run_dir)
        if args.build_pdf and manifest.get("stages", {}).get("pdf_built", {}).get("status") != "done":
            maybe_build_pdf(manifest["paths"]["article_markdown"], manifest["paths"]["pdf"])
            run_cmd([
                "python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "mark-pdf",
                "--run-dir", str(run_dir),
                "--file", manifest["paths"]["pdf"],
            ], timeout=300)
        manifest = load_manifest(run_dir)
        if args.update_index and manifest.get("stages", {}).get("pdf_built", {}).get("status") == "done" and manifest.get("stages", {}).get("index_updated", {}).get("status") != "done":
            run_cmd([
                "python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "append-index",
                "--run-dir", str(run_dir),
            ], timeout=300)

    print(run_cmd(["python3", str(ROOT / "scripts" / "close_reading_pipeline.py"), "status", "--run-dir", str(run_dir)], timeout=300))


def common_run_args(p: argparse.ArgumentParser, *, allow_create: bool) -> None:
    p.add_argument("--run-dir", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--only", action="append", default=[])
    p.add_argument("--modules-only", action="store_true")
    p.add_argument("--build-pdf", action="store_true")
    p.add_argument("--timeout", type=int, default=1800)
    if allow_create:
        p.add_argument("--create", action="store_true")
        p.add_argument("--date", default="")
        p.add_argument("--trigger", default="manual", choices=["manual", "cron"])
        p.add_argument("--requested-by", default="Combjelly")
        p.add_argument("--delivery-target", default="telegram:-1003726107069")
        p.add_argument("--force", action="store_true")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run English pipelines with local Claude while keeping status in manifest/events.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("daily-vocab", help="Drive the daily vocab pipeline with Claude.")
    common_run_args(p, allow_create=True)

    p = sub.add_parser("weekly-vocab", help="Drive the weekly vocab pipeline with Claude.")
    common_run_args(p, allow_create=True)

    p = sub.add_parser("close-reading", help="Drive close-reading module generation with Claude.")
    common_run_args(p, allow_create=False)
    p.add_argument("--update-index", action="store_true")

    args = parser.parse_args()
    if args.cmd == "daily-vocab":
        if args.create and not args.date:
            fail("daily-vocab --create 时必须提供 --date")
        run_daily(args)
    elif args.cmd == "weekly-vocab":
        if args.create and not args.date:
            fail("weekly-vocab --create 时必须提供 --date")
        run_weekly(args)
    elif args.cmd == "close-reading":
        run_close_reading(args)


if __name__ == "__main__":
    main()
