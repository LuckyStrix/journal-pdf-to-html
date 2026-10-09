"""Read a PDF into positioned, styled lines with pdfminer.six. The only module that opens the PDF."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTAnno, LTChar, LTTextLine

from .models import Line, Page, Span
from .text import merge_spans

# pdfminer splits a printed line wherever characters are far apart, which
# happens both at column gutters and at the wide word spaces of justified text.
# Pieces on one baseline are joined back up unless the gap between them is a
# gutter: white space at the same x on at least GUTTER_RUN consecutive lines.
# Justified word gaps don't line up that consistently.
GUTTER_RUN = 4
GUTTER_BAND = (0.25, 0.75)  # gutters are looked for in this middle part of the page width
WIDE_GAP = 3.0   # x font size: no word space is this wide, so a gap like it always separates
BASELINE = 0.3   # x font size: baselines this close are the same line
WORD_GAP = 0.15  # x font size: pieces further apart than this get a space between them
BOLD = re.compile(r"bold|black|heavy|semibold|demi", re.I)
ITALIC = re.compile(r"italic|oblique|slanted", re.I)


def style(fontname: str) -> tuple[bool, bool]:
    """(bold, italic) from a font name such as 'ABCDEF+TimesNewRomanPS-BoldItalicMT'."""
    name = fontname.split("+", 1)[-1]
    return bool(BOLD.search(name)), bool(ITALIC.search(name))


def _text_lines(obj):
    if isinstance(obj, LTTextLine):
        yield obj
    elif not isinstance(obj, LTChar) and hasattr(obj, "__iter__"):
        for child in obj:
            yield from _text_lines(child)


def _pieces(tl: LTTextLine, page: int) -> Line | None:
    """One pdfminer line as a Line with styled runs, or None if it's blank."""
    spans: list[Span] = []
    boxes: list[tuple[float, float, float, float]] = []
    sizes: Counter[float] = Counter()
    cur = (False, False)
    for item in tl:
        if isinstance(item, LTChar):
            cur = style(item.fontname)
            spans.append(Span(item.get_text(), *cur))
            boxes.append((item.x0, item.y0, item.x1, item.y1))
            sizes[round(item.size, 1)] += 1
        elif isinstance(item, LTAnno) and item.get_text() != "\n":
            spans.append(Span(item.get_text(), *cur))
    if not boxes or not "".join(s.text for s in spans).strip():
        return None
    return Line(page, min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                max(b[3] for b in boxes), sizes.most_common(1)[0][0], tuple(merge_spans(spans)))


def _rows(pieces: list[Line]) -> list[list[Line]]:
    """Group pieces that share a baseline, top to bottom, each row left to right."""
    rows: list[list[Line]] = []
    for piece in sorted(pieces, key=lambda l: -l.y0):
        if rows and abs(rows[-1][0].y0 - piece.y0) < BASELINE * max(piece.size, rows[-1][0].size):
            rows[-1].append(piece)
        else:
            rows.append([piece])
    return [sorted(r, key=lambda l: l.x0) for r in rows]


def gutters(rows: list[list[Line]], page_width: float) -> list[float]:
    """x positions of column gutters: gaps at the same x on GUTTER_RUN or more consecutive lines.

    A line all on one side of x neither counts nor breaks the run (a short last
    line of a paragraph); a line with text across x breaks it (a full-width title).
    """
    lo, hi = GUTTER_BAND[0] * page_width, GUTTER_BAND[1] * page_width
    candidates = sorted({(a.x1 + b.x0) / 2 for row in rows for a, b in zip(row, row[1:])
                         if lo <= (a.x1 + b.x0) / 2 <= hi})
    found = []
    for x in candidates:
        run = best = 0
        for row in rows:
            if any(p.x0 < x < p.x1 for p in row):
                run = 0
            elif any(p.x1 <= x for p in row) and any(p.x0 >= x for p in row):
                run += 1
                best = max(best, run)
        if best >= GUTTER_RUN:
            found.append(x)
    return found


def _join(a: Line, b: Line) -> Line:
    joint = (Span(" "),) if b.x0 - a.x1 > WORD_GAP * max(a.size, b.size) else ()
    size = a.size if len(a.text) >= len(b.text) else b.size
    return Line(a.page, a.x0, min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1), size,
                tuple(merge_spans(list(a.spans + joint + b.spans))))


def assemble_lines(pieces: list[Line], page_width: float) -> list[Line]:
    """Join pdfminer's pieces into printed lines, split only at column gutters and very wide gaps."""
    rows = _rows(pieces)
    gutter_xs = gutters(rows, page_width)
    lines = []
    for row in rows:
        current = row[0]
        for piece in row[1:]:
            gap = piece.x0 - current.x1
            at_gutter = any(current.x1 <= x <= piece.x0 for x in gutter_xs)
            if at_gutter or gap > WIDE_GAP * max(current.size, piece.size):
                lines.append(current)
                current = piece
            else:
                current = _join(current, piece)
        lines.append(current)
    return lines


def read_pdf(path: Path) -> tuple[list[Page], int]:
    """Every page's lines, and how many lines lay entirely off the page (never visible, so left out)."""
    pages: list[Page] = []
    offpage = 0
    # all_texts: also read text drawn inside form objects, which InDesign uses for
    # master-page items such as running heads (they are then recognised and left out)
    for index, lt_page in enumerate(extract_pages(str(path), laparams=LAParams(all_texts=True))):
        pieces = []
        for tl in _text_lines(lt_page):
            line = _pieces(tl, index)
            if line is None:
                continue
            if line.x1 < 0 or line.x0 > lt_page.width or line.y1 < 0 or line.y0 > lt_page.height:
                offpage += 1
            else:
                pieces.append(line)
        pages.append(Page(index, lt_page.width, lt_page.height, tuple(assemble_lines(pieces, lt_page.width))))
    return pages, offpage
