#!/usr/bin/env python3
"""
generate_pdf.py — Convert a reading-log Markdown article to a styled PDF.

Uses weasyprint + markdown for reliable CJK rendering.

Usage:
    python3 scripts/generate_pdf.py reading-log/articles/2026-03-10-seedance-ai-hollywood.md
    python3 scripts/generate_pdf.py reading-log/articles/2026-03-10-seedance-ai-hollywood.md --out reading-log/pdfs/custom.pdf
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 确保 linuxbrew 库路径可用（WeasyPrint 的 pango 依赖）
_BREW_LIB = "/home/linuxbrew/.linuxbrew/lib"
if os.path.isdir(_BREW_LIB):
    ld = os.environ.get("LD_LIBRARY_PATH", "")
    if _BREW_LIB not in ld:
        os.environ["LD_LIBRARY_PATH"] = f"{_BREW_LIB}:{ld}" if ld else _BREW_LIB

ROOT = Path(__file__).resolve().parent.parent

# ── CSS for the PDF ──
CSS = """
@page {
    size: A4;
    margin: 2.2cm 2cm;
    @bottom-center {
        content: counter(page);
        font-size: 9pt;
        color: #9FA8DA;
    }
}

body {
    font-family: "Noto Sans CJK SC", "Noto Sans CJK", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.72;
    color: #212121;
}

h1 {
    font-size: 18pt;
    color: #1A237E;
    text-align: center;
    margin-bottom: 8pt;
    line-height: 1.3;
    page-break-after: avoid;
}

h2 {
    font-size: 13pt;
    color: #283593;
    border-top: 1px solid #9FA8DA;
    padding-top: 8pt;
    margin-top: 18pt;
    margin-bottom: 8pt;
    page-break-after: avoid;
}

h3 {
    font-size: 11pt;
    color: #283593;
    margin-top: 12pt;
    margin-bottom: 6pt;
    page-break-after: avoid;
}

p {
    text-align: justify;
    margin-bottom: 6pt;
}

blockquote {
    background: #E8EAF6;
    border-left: 3px solid #283593;
    padding: 8pt 12pt;
    margin: 8pt 0;
    font-size: 10pt;
    color: #283593;
}

code {
    font-family: "Courier New", Courier, monospace;
    background: #F5F5F5;
    padding: 1pt 3pt;
    font-size: 9pt;
}

pre {
    background: #F5F5F5;
    padding: 8pt;
    font-size: 9pt;
    overflow-x: auto;
    line-height: 1.4;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 10pt 0;
    font-size: 9.2pt;
    line-height: 1.55;
}

thead tr {
    background: #1A237E;
    color: white;
}

thead th {
    padding: 5pt 7pt;
    text-align: left;
    font-weight: bold;
}

tbody tr:nth-child(even) {
    background: #E8EAF6;
}

tbody td {
    padding: 5pt 7pt;
    border: 0.3pt solid #9FA8DA;
    vertical-align: top;
}

ul, ol {
    margin: 6pt 0 8pt 0;
    padding-left: 22pt;
}

li {
    margin-bottom: 5pt;
}

li > p {
    margin-bottom: 4pt;
}

li, blockquote, table {
    page-break-inside: avoid;
}

hr {
    border: none;
    border-top: 0.5pt solid #9FA8DA;
    margin: 10pt 0;
}

strong {
    color: #1A237E;
}

em {
    color: #546E7A;
}
"""


def md_to_pdf(md_path: Path, out_path: Path) -> None:
    """Convert a Markdown file to a styled PDF using weasyprint."""
    try:
        import markdown
        from weasyprint import HTML, CSS as WCSS
    except ImportError as e:
        print(f"ERROR: Missing dependency: {e}")
        print("Run: pip3 install weasyprint markdown --break-system-packages")
        sys.exit(1)

    md_text = md_path.read_text(encoding="utf-8")

    # Pre-process emoji headings since some fonts fail or misalign on them
    import re
    # Remove emoji from headings (e.g., "## 📐 行文结构分析" -> "## 行文结构分析")
    md_text = re.sub(r'^(#+\s)[^\w\s]+\s*', r'\1', md_text, flags=re.MULTILINE)

    # Convert markdown to HTML
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "codehilite", "toc", "sane_lists"],
        output_format="html5",
    )

    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>{md_path.stem}</title>
</head>
<body>
{html_body}
</body>
</html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full_html).write_pdf(str(out_path), stylesheets=[WCSS(string=CSS)])
    print(f"PDF saved -> {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Convert reading-log Markdown to PDF.")
    parser.add_argument("md_file", help="Path to the Markdown article file.")
    parser.add_argument("--out", default=None, help="Output PDF path (default: reading-log/pdfs/<stem>.pdf).")
    args = parser.parse_args()

    md_path = Path(args.md_file)
    if not md_path.exists():
        print(f"ERROR: File not found: {md_path}")
        sys.exit(1)

    if args.out:
        out_path = Path(args.out)
    else:
        pdf_dir = ROOT / "reading-log" / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        out_path = pdf_dir / (md_path.stem + ".pdf")

    md_to_pdf(md_path, out_path)


if __name__ == "__main__":
    main()
