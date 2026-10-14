"""Write an Article as a page in the journal's HTML template. Pure: values in, a string out.

The layout follows the hand-made pages it replaces: logo, title, rule, author
block, rule, then the text with a "Page N" paragraph where each printed page
begins (at the start, so a screen reader announces it before that page's text),
and footnotes at the end of the page they were printed on.
"""
from __future__ import annotations

from .models import ABSTRACT, FIGURE, FOOTNOTE, HEADING, LINES, PAGE, PARAGRAPH, Article, Block
from .text import escape, spans_html, spans_text, wrap

DEFAULT_WIDTH = 90  # line length of the hand-made pages, so diffs against them stay readable


def _attr(value: str) -> str:
    return escape(value).replace('"', "&quot;")


FOOTNOTE_RULE = '<hr style="width:25%;text-align:left;margin-left:0">'


def image_src(block: Block) -> str:
    """File name of a figure's picture, next to the page. A picture that couldn't be
    written out (Image.problem) still gets one, to be saved from the PDF by hand."""
    return f"{block.name}.{block.image.ext or 'png'}"


def render(article: Article, *, journal: str = "", logo: str = "logo.png", css: str = "styles.css",
           lang: str = "en", width: int = DEFAULT_WIDTH) -> str:
    title_text = spans_text(article.title).strip()
    out = ["<!DOCTYPE html>", f'<html lang="{_attr(lang)}">', "<head>",
           '    <meta charset="utf-8">',
           '    <meta name="viewport" content="width=device-width, initial-scale=1.0">']
    if css:
        out.append(f'    <link rel="stylesheet" href="{_attr(css)}">')
    out += [f"    <title>{escape(journal or title_text or 'Article')}</title>", "</head>", "<body>", ""]
    # No file name here: internal names ("Draft_v3_final") would be published with the page.
    out += ["<!-- Converted from the typeset PDF by journal-pdf-to-html."
            " Check it against the PDF before publishing. -->", ""]
    if logo:
        out += [f'<img src="{_attr(logo)}" alt="{_attr(journal)}" style="width:100%;">', ""]
    if article.title:
        out += ['<div class="title">', wrap(spans_html(article.title), width), "</div>", "", "<hr>", ""]
    if article.authors:
        rows = [spans_html(r) for r in article.authors]
        out += ['<div class="author">']
        out += [f"    {r}<br>" for r in rows[:-1]] + [f"    {rows[-1]}", "</div>", "", "<hr>", ""]
    notes: list[str] = []  # a page's footnotes, written together in one block
    for i, block in enumerate(article.body):
        if block.kind == FOOTNOTE:
            notes.append(wrap(spans_html(block.rows[0]), width))
            if i + 1 < len(article.body) and article.body[i + 1].kind == FOOTNOTE:
                continue
            out += [FOOTNOTE_RULE, "", '<div class="footnote">', "\n    <br><br>\n".join(notes), "</div>", ""]
            notes = []
        elif block.kind == PAGE:
            out += [f"<p>Page {escape(block.label)}</p>", ""]
        elif block.kind == PARAGRAPH:
            out += ["<p>", wrap(spans_html(block.rows[0]), width), "</p>", ""]
        elif block.kind == HEADING:
            out += [f"<h4>{spans_html(block.rows[0])}</h4>", ""]
        elif block.kind == ABSTRACT:
            out += ['<div class="abstract">', wrap(spans_html(block.rows[0]), width), "</div>", ""]
        elif block.kind == FIGURE:
            for row in block.rows:
                out += ["<p>", wrap(spans_html(row), width), "</p>", ""]
            alt = " ".join(spans_text(block.rows[0]).split()) if block.rows else ""
            out += [f'<img src="{_attr(image_src(block))}" alt="{_attr(alt)}" style="width:100%;">', ""]
        elif block.kind == LINES:
            rows = [spans_html(r) for r in block.rows]
            out += ["<p>"] + [f"    {r}<br>" for r in rows[:-1]] + [f"    {rows[-1]}", "</p>", ""]
    out += ["</body>", "</html>", ""]
    return "\n".join(out)
