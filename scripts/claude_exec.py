#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Max prompt length to pass as CLI argument (128 KB); beyond this use temp file
_ARG_MAX_SAFE = 128 * 1024


def fail(message: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2), file=sys.stderr)
    raise SystemExit(code)


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_text:
        return args.prompt_text
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    fail("必须提供 --prompt-text 或 --prompt-file")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a prompt through local Claude Code and capture stdout.")
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--prompt-text", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--workdir", default=str(ROOT))
    parser.add_argument("--model", default="", help="Model override, e.g. 'sonnet' or full ID")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    prompt = read_prompt(args)
    claude = shutil.which("claude")
    if not claude:
        fail("找不到 claude 命令")

    # For long prompts, write to a temp file and redirect stdin from file
    # to avoid both OS ARG_MAX limits and pipe deadlocks with large I/O.
    use_file = len(prompt.encode("utf-8")) > _ARG_MAX_SAFE

    base_cmd = [
        claude,
        "--permission-mode",
        "bypassPermissions",
        "--no-session-persistence",
        "--print",
    ]
    if args.model:
        base_cmd.extend(["--model", args.model])

    if use_file:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(prompt)
            prompt_file = f.name
        try:
            cmd = list(base_cmd)
            with open(prompt_file, "r", encoding="utf-8") as stdin_f:
                proc = subprocess.run(
                    cmd,
                    cwd=args.workdir,
                    stdin=stdin_f,
                    capture_output=True,
                    text=True,
                    timeout=args.timeout,
                )
        finally:
            Path(prompt_file).unlink(missing_ok=True)
    else:
        cmd = base_cmd + [prompt]
        proc = subprocess.run(
            cmd,
            cwd=args.workdir,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    if proc.returncode != 0:
        fail(f"Claude 执行失败（code={proc.returncode}）：{stderr or stdout or '(no output)'}", code=proc.returncode)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(stdout + "\n", encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "command": cmd[:4] + (["<file>"] if use_file else ["<prompt>"]),
        "workdir": args.workdir,
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
        "out": args.out or None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
