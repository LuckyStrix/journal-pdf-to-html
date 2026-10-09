"""Completeness checks: the HTML must hold every letter and digit the PDF prints.

Comparing character counts (not order) is deliberate. Footnotes and signatures
move, and hyphens are removed, but no letter or digit may appear or disappear.
This is what catches the silent losses a hand conversion makes, such as a
dropped closing statement.
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser

from .models import PAGE, Article, Page


def alnum(text: str) -> Counter[str]:
    return Counter(c for c in text if c.isalnum())


def article_chars(article: Article, inferred_labels: bool = False) -> Counter[str]:
    out = Counter()
    for s in article.title:
        out += alnum(s.text)
    for row in article.authors:
        out += alnum("".join(s.text for s in row))
    for block in article.body:
        if block.kind == PAGE:
            if block.printed or inferred_labels:
                out += alnum(block.label)
            continue
        for row in block.rows:
            out += alnum("".join(s.text for s in row))
    return out


def _describe(counter: Counter[str]) -> str:
    shown = ", ".join(f"{c!r}x{n}" for c, n in counter.most_common(8))
    more = "" if len(counter) <= 8 else ", ..."
    return f"{sum(counter.values())} ({shown}{more})"


def compare_with_pdf(pages: list[Page], article: Article) -> list[str]:
    """Problems found comparing the article with the PDF's text; empty when nothing was lost or added."""
    source = Counter()
    for page in pages:
        for line in page.lines:
            source += alnum(line.text)
    for line in article.dropped:
        source -= alnum(line.text)
    found = article_chars(article)
    problems = []
    if missing := source - found:
        problems.append(f"characters in the PDF missing from the article: {_describe(missing)}")
    if extra := found - source:
        problems.append(f"characters in the article not in the PDF: {_describe(extra)}")
    return problems


class _BodyText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True

    def handle_data(self, data):
        if self.in_body:
            self.parts.append(data)


def compare_with_html(html: str, article: Article) -> list[str]:
    """Problems found comparing the rendered page with the article (escaping or rendering bugs)."""
    parser = _BodyText()
    parser.feed(html)
    shown = alnum("".join(parser.parts))
    markers = sum(1 for b in article.body if b.kind == PAGE)
    expected = article_chars(article, inferred_labels=True)
    for _ in range(markers):
        expected += alnum("Page")
    problems = []
    if missing := expected - shown:
        problems.append(f"characters missing from the HTML: {_describe(missing)}")
    if extra := shown - expected:
        problems.append(f"unexpected characters in the HTML: {_describe(extra)}")
    return problems
