"""Command line: convert (PDF -> HTML page) and inspect (masked layout dump for troubleshooting)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import netguard
from .check import compare_with_html, compare_with_pdf
from .models import LINES, PAGE, PARAGRAPH
from .reader import read_pdf
from .render import DEFAULT_WIDTH, render
from .structure import build_article
from .text import spans_text


def mask(text: str) -> str:
    """Hide text but keep its shape: letters become x/X, digits 9."""
    text = re.sub(r"[^\W\d_]", lambda m: "X" if m.group(0).isupper() else "x", text)
    return re.sub(r"\d", "9", text)


def _summary(pages, article, offpage: int) -> list[str]:
    labels = [b.label for b in article.body if b.kind == PAGE]
    paras = sum(1 for b in article.body if b.kind == PARAGRAPH)
    lines_blocks = sum(1 for b in article.body if b.kind == LINES)
    joined = sum(1 for j in article.joins if j[2] != j[0] + j[1])
    kept = len(article.joins) - joined
    out = [
        f"  pages {labels[0]}-{labels[-1]} ({len(pages)}), " if labels else "  no pages, ",
        f"title: {'yes' if article.title else 'NOT FOUND'}, author lines: {len(article.authors)}, "
        f"paragraph pieces: {paras}, footnote/signature blocks: {lines_blocks}",
        f"  line-end hyphens: {joined} rejoined, {kept} kept",
    ]
    out = [out[0] + out[1], out[2]]
    if offpage:
        out.append(f"  left out {offpage} line(s) placed entirely off the page (never visible)")
    out += [f"  note: {n}" for n in article.notes]
    return out


def cmd_convert(args) -> int:
    if args.output and len(args.pdf) > 1:
        print("-o works with one PDF; use --out-dir for several.", file=sys.stderr)
        return 2
    status = 0
    for pdf in args.pdf:
        if not pdf.is_file():
            print(f"{pdf}: not found", file=sys.stderr)
            status = 1
            continue
        out = args.output or (args.out_dir or pdf.parent) / (pdf.stem + ".html")
        if out.exists() and not args.force:
            print(f"{out} already exists; pass --force to overwrite it.", file=sys.stderr)
            status = 1
            continue
        pages, offpage = read_pdf(pdf)
        article = build_article(pages)
        html = render(article, journal=args.journal, logo="" if args.no_logo else args.logo,
                      css=args.css, lang=args.lang, width=args.width)
        problems = compare_with_pdf(pages, article) + compare_with_html(html, article)
        print(f"{pdf} -> {out}", file=sys.stderr)
        for line in _summary(pages, article, offpage):
            print(line, file=sys.stderr)
        if args.show_joins:
            for left, right, result in article.joins:
                print(f"    {left} | {right}  ->  {result}", file=sys.stderr)
        if problems:
            for p in problems:
                print(f"  ERROR: {p}", file=sys.stderr)
            print("  Nothing written. Run `inspect` on the PDF to see how its lines were read.", file=sys.stderr)
            status = 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="ascii", newline="\n")
    return status


def cmd_inspect(args) -> int:
    show = (lambda t: t) if args.unmasked else mask
    pages, offpage = read_pdf(args.pdf)
    for page in pages:
        print(f"=== page {page.index + 1}  {page.width:.0f}x{page.height:.0f} pt")
        for line in sorted(page.lines, key=lambda l: (-l.y1, l.x0)):
            styles = "".join(("B" if s.bold else "-") + ("I" if s.italic else "-") for s in line.spans[:3])
            print(f"  x {line.x0:6.1f}-{line.x1:6.1f}  y {line.y0:6.1f}  {line.size:4.1f}pt {styles:6} "
                  f"{show(line.text.strip())[:80]}")
    article = build_article(pages)
    print("=== structure")
    print(f"  title: {show(spans_text(article.title))[:80]}")
    for row in article.authors:
        print(f"  author: {show(spans_text(row))[:80]}")
    for block in article.body:
        if block.kind == PAGE:
            print(f"  [page {block.label}{'' if block.printed else ', inferred'}]")
        else:
            for row in block.rows:
                print(f"  {block.kind:9} {show(spans_text(row))[:70]}")
    for line in _summary(pages, article, offpage):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pdf2html", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("convert", help="convert article PDFs to HTML pages")
    c.add_argument("pdf", nargs="+", type=Path)
    c.add_argument("-o", "--output", type=Path, help="output file (one PDF only); default: next to the PDF")
    c.add_argument("--out-dir", type=Path, help="folder for the HTML files")
    c.add_argument("--journal", default="", help="journal name, used for the page title and the logo's alt text")
    c.add_argument("--logo", default="logo.png", help="logo image path as the page should reference it")
    c.add_argument("--no-logo", action="store_true", help="leave the logo out")
    c.add_argument("--css", default="styles.css", help="stylesheet path as the page should reference it")
    c.add_argument("--lang", default="en", help="language of the article (the page's lang attribute)")
    c.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="wrap HTML source lines at this width")
    c.add_argument("--force", action="store_true", help="overwrite an existing HTML file")
    c.add_argument("--show-joins", action="store_true", help="list every line-end hyphen decision")
    c.set_defaults(func=cmd_convert)

    i = sub.add_parser("inspect", help="show how a PDF's lines were read, with text masked")
    i.add_argument("pdf", type=Path)
    i.add_argument("--unmasked", action="store_true", help="show the real text (don't share this output)")
    i.set_defaults(func=cmd_inspect)

    args = parser.parse_args(argv)
    netguard.enable()  # every command runs offline
    return args.func(args)
