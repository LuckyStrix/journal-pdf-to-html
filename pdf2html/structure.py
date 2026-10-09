"""Find an article's structure in positioned lines. This is the converter's core.

Pure: Page values in, an Article out, no file or PDF access. Everything here is a
layout rule for a typeset single-article PDF (one journal article, title on the
first page, one or two text columns, printed page numbers):

    title        lines in a bigger font at the top of the first page
    authors      the centred, narrow lines under the title
    page number  a bare number in the top or bottom margin
    running head margin text that repeats on two or more pages (left out, and reported)
    footnote     a block at the bottom of a page, set off by blank space, starting with * or a number
    paragraph    body lines; a first-line indent, a short previous line or a gap starts a new one
    signature    the short, unpunctuated lines that end the article

Hard rule for editing: text is never dropped silently. Anything left out goes in
Article.dropped, and check.py fails the conversion if the output's characters
don't match the PDF's.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

from .models import LINES, PAGE, PARAGRAPH, Article, Block, Line, Page
from .text import join_lines, normalize_spans, split_spans, spans_text, strip_bold, vocabulary

TITLE_SCALE = 1.2      # title lines are at least this many times the body font size
MARGIN = 0.12          # page numbers and running heads sit in the top or bottom 12% of the page
PAGE_NUMBER = re.compile(r"^\d{1,4}$")
FOOTNOTE_MARK = re.compile(r"^(?:[*†‡§¶]|\d{1,2}(?![\d.,:]))")
FOOTNOTE_GAP = 2.0     # x leading: blank space that sets footnotes apart from the text above
PARA_GAP = 1.6         # x leading: a bigger vertical gap inside a column starts a paragraph
INDENT = 0.6           # x font size: a first-line indent bigger than this starts a paragraph
SHORT = 1.5            # x font size: a line ending this far before the column edge ends its paragraph
CENTRED = 1.0          # x font size: how far off the text centre a centred line may sit
NARROW = 0.7           # author lines are narrower than this fraction of the text width
SHORT_LINE = 0.6       # footnote lines narrower than this fraction of the text width stay on their own lines
SIGNATURE_MAX_LINES = 4
BASELINE_TOLERANCE = 1.0  # x font size: running heads sit within a line of the page number's baseline
SENTENCE_END = (".", "!", "?", ".”", ".\"", "?”", "!”")


def body_font_size(pages: list[Page]) -> float:
    """The most common font size, weighted by characters."""
    sizes: Counter[float] = Counter()
    for page in pages:
        for line in page.lines:
            sizes[round(line.size * 2) / 2] += len(line.text.strip())
    return sizes.most_common(1)[0][0] if sizes else 10.0


def line_leading(pages: list[Page], size: float) -> float:
    """Typical distance between baselines of consecutive lines in a column."""
    gaps = []
    for page in pages:
        ordered = sorted(page.lines, key=lambda l: -l.y0)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                if b.x0 < a.x1 and a.x0 < b.x1:  # overlapping horizontally: same column
                    gap = a.y0 - b.y0
                    if 0.5 * size < gap < 3 * size:
                        gaps.append(gap)
                    break
    return statistics.median(gaps) if gaps else 1.2 * size


def _in_margin(line: Line, page: Page) -> bool:
    return line.y0 > page.height * (1 - MARGIN) or line.y1 < page.height * MARGIN


def _repeat_key(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.split())).lower()


def page_labels(found: list[str | None]) -> tuple[list[str], list[str]]:
    """Fill in page numbers that weren't printed, counting from a neighbour.

    Returns the labels and a note for every one that had to be inferred.
    """
    labels: list[str] = []
    notes = []
    for i, label in enumerate(found):
        if label is not None:
            labels.append(label)
            continue
        before = [(j, found[j]) for j in range(i - 1, -1, -1) if found[j] is not None]
        after = [(j, found[j]) for j in range(i + 1, len(found)) if found[j] is not None]
        if before:
            j, lab = before[0]
            guess = str(int(lab) + (i - j))
        elif after:
            j, lab = after[0]
            guess = str(max(1, int(lab) - (j - i)))
        else:
            guess = str(i + 1)
        labels.append(guess)
        notes.append(f"page {i + 1}: no printed page number found; labelled it {guess}")
    return labels, notes


def reading_order(lines: list[Line], centre: float, text_left: float,
                  text_right: float) -> list[tuple[Line, float, float]]:
    """Order a page's lines for reading, with each line's column edges.

    Lines that cross the text centre are full width. A run of lines that don't is
    a two-column stretch, read left column first. A stretch with nothing in the
    right column is just short full-width lines (a paragraph's last line).
    """
    def side(l: Line) -> str:
        if l.x0 >= centre - 1:
            return "R"
        if l.x1 <= centre + 1:
            return "L"
        return "F"

    out: list[tuple[Line, float, float]] = []
    region: list[Line] = []

    def flush():
        left = [l for l in region if side(l) == "L"]
        right = [l for l in region if side(l) == "R"]
        if left and right:
            for col in (left, right):
                lo, hi = min(l.x0 for l in col), max(l.x1 for l in col)
                out.extend((l, lo, hi) for l in col)
        else:
            col = left or right
            if right and not left:
                lo, hi = min(l.x0 for l in col), max(l.x1 for l in col)
            else:
                lo, hi = text_left, text_right
            out.extend((l, lo, hi) for l in col)
        region.clear()

    for line in sorted(lines, key=lambda l: (-l.y1, l.x0)):
        if side(line) == "F":
            flush()
            out.append((line, text_left, text_right))
        else:
            region.append(line)
    flush()
    return out


def split_footnotes(lines: list[Line], lead: float) -> tuple[list[Line], list[list[Line]]]:
    """Separate footnotes at the bottom of a page from the text above them.

    A footnote area is the lowest stretch of the page that has blank space across
    every column above it and starts with a footnote mark. Each line starting with
    a mark begins a new note.
    """
    ordered = sorted(lines, key=lambda l: (-l.y1, l.x0))
    for k in range(1, len(ordered)):
        top, bottom = ordered[:k], ordered[k:]
        gap = min(l.y0 for l in top) - max(l.y1 for l in bottom)
        if gap > FOOTNOTE_GAP * lead and FOOTNOTE_MARK.match(bottom[0].text.strip()):
            notes: list[list[Line]] = []
            for line in bottom:
                if not notes or FOOTNOTE_MARK.match(line.text.strip()):
                    notes.append([line])
                else:
                    notes[-1].append(line)
            return top, notes
    return ordered, []


def _italic(line: Line) -> bool:
    spans = [s for s in line.spans if s.text.strip()]
    return bool(spans) and all(s.italic for s in spans)


def paragraphs(stream: list[tuple[Line, float, float]], lead: float) -> list[list[tuple[Line, float, float]]]:
    """Group body lines (in reading order) into paragraphs."""
    paras: list[list[tuple[Line, float, float]]] = []
    prev = None
    for item in stream:
        line, left, _right = item
        new = prev is None
        if prev is not None:
            pline, pleft, pright = prev
            if line.x0 - left > INDENT * line.size:
                new = True
            elif pline.x1 < pright - SHORT * pline.size:
                new = True
            elif line.page == pline.page and left == pleft and pline.y0 - line.y0 > PARA_GAP * lead:
                new = True
            elif _italic(line) != _italic(pline):
                new = True
        if new:
            paras.append([item])
        else:
            paras[-1].append(item)
        prev = item
    return paras


def split_signature(paras: list[list[tuple[Line, float, float]]]) -> list[tuple[Line, float, float]]:
    """Remove and return the signature: one-line paragraphs at the very end that stop short of
    the column edge and don't end a sentence ("Jane Doe" / "University of Example, ...")."""
    sig: list[tuple[Line, float, float]] = []
    while paras and len(sig) < SIGNATURE_MAX_LINES and len(paras[-1]) == 1:
        line, left, right = paras[-1][0]
        text = line.text.strip()
        if line.x1 >= right - SHORT * line.size or text.endswith(SENTENCE_END):
            break
        sig.insert(0, paras.pop()[0])
    return sig


def _short_lines(lines: list[Line], width: float) -> bool:
    return all(l.width < SHORT_LINE * width for l in lines)


def build_article(pages: list[Page]) -> Article:
    size = body_font_size(pages)
    lead = line_leading(pages, size)
    all_lines = [l for p in pages for l in p.lines]
    vocab = vocabulary([l.text for l in all_lines])
    article = Article(title=[], authors=[], body=[])

    # Text area, from body-size lines away from the margins
    body_like = [l for p in pages for l in p.lines
                 if abs(l.size - size) < 0.6 and not _in_margin(l, p)] or all_lines
    text_left = Counter(round(l.x0) for l in body_like).most_common(1)[0][0] if body_like else 0.0
    text_right = max((l.x1 for l in body_like), default=pages[0].width if pages else 0.0)
    centre = (text_left + text_right) / 2
    text_width = text_right - text_left

    # Running heads: margin text repeating on two or more pages
    margin_keys: Counter[str] = Counter()
    for page in pages:
        keys = {_repeat_key(l.text) for l in page.lines
                if _in_margin(l, page) and not PAGE_NUMBER.match(l.text.strip())}
        margin_keys.update(keys)
    repeated = {k for k, n in margin_keys.items() if n >= 2 and k.strip("# ")}

    found_labels: list[str | None] = []
    content: list[list[Line]] = []
    for page in pages:
        numbers = [l for l in page.lines if _in_margin(l, page) and PAGE_NUMBER.match(l.text.strip())]
        number = numbers[0] if numbers else None
        label = number.text.strip() if number else None
        kept = []
        for line in page.lines:
            text = line.text.strip()
            if not text or line is number:
                continue
            # A running head or foot alternates between pages (journal name on even pages,
            # article title on odd ones), so in a short article it may print only once.
            # Margin text on the page number's own baseline is one either way.
            beside_number = number is not None and abs(line.y0 - number.y0) < BASELINE_TOLERANCE * line.size
            if _in_margin(line, page) and (beside_number or _repeat_key(text) in repeated):
                article.dropped.append(line)
            else:
                kept.append(line)
        found_labels.append(label)
        content.append(kept)
    labels, label_notes = page_labels(found_labels)
    article.notes.extend(label_notes)

    # Title and authors, at the top of the first page
    if content:
        first = sorted(content[0], key=lambda l: -l.y1)
        i = 0
        title_lines = []
        while i < len(first) and first[i].size >= TITLE_SCALE * size:
            title_lines.append(first[i])
            i += 1
        author_lines = []
        while i < len(first) and abs((first[i].x0 + first[i].x1) / 2 - centre) <= CENTRED * first[i].size \
                and first[i].width < NARROW * text_width:
            author_lines.append(first[i])
            i += 1
        if title_lines:
            spans, _ = join_lines([list(l.spans) for l in title_lines], vocab, article.joins)
            article.title = strip_bold(spans)
        else:
            article.notes.append("no title found: expected bigger-than-body text at the top of the first page")
        article.authors = [normalize_spans(l.spans) for l in author_lines]
        content[0] = first[i:]

    # Footnotes, then the body in reading order
    page_blocks: list[list[Block]] = [[] for _ in pages]
    page_notes: list[list[Block]] = [[] for _ in pages]
    stream: list[tuple[Line, float, float]] = []
    for idx, lines in enumerate(content):
        body, notes = split_footnotes(lines, lead)
        for note in notes:
            note = sorted(note, key=lambda l: (-l.y1, l.x0))
            if _short_lines(note, text_width):
                rows = [normalize_spans(l.spans) for l in note]
                page_notes[idx].append(Block(LINES, rows))
            else:
                spans, _ = join_lines([list(l.spans) for l in note], vocab, article.joins)
                page_notes[idx].append(Block(PARAGRAPH, [spans]))
        stream.extend(reading_order(body, centre, text_left, text_right))

    paras = paragraphs(stream, lead)
    signature = split_signature(paras)
    for para in paras:
        lines = [item[0] for item in para]
        breaks = {i for i in range(1, len(lines)) if lines[i].page != lines[i - 1].page}
        spans, offsets = join_lines([list(l.spans) for l in lines], vocab, article.joins, breaks)
        piece_pages = [lines[0].page] + [lines[i].page for i in sorted(breaks)]
        pieces = []
        for off in reversed(offsets):
            spans, tail = split_spans(spans, off)
            pieces.insert(0, tail)
        pieces.insert(0, spans)
        for pg, piece in zip(piece_pages, pieces):
            piece = normalize_spans(piece)
            if piece:
                page_blocks[pg].append(Block(PARAGRAPH, [piece]))
    if signature:
        rows = [normalize_spans(item[0].spans) for item in signature]
        page_blocks[signature[0][0].page].append(Block(LINES, rows))

    for idx, label in enumerate(labels):
        article.body.append(Block(PAGE, label=label, printed=found_labels[idx] is not None))
        article.body.extend(page_blocks[idx])
        article.body.extend(page_notes[idx])

    for line in article.dropped:
        article.notes.append(f"page {labels[line.page]}: left out running head/foot \"{' '.join(line.text.split())}\"")
    kept = [j for j in article.joins if j[2] == j[0] + j[1]]
    if kept:
        article.notes.append(f"{len(kept)} line-end hyphen(s) kept as part of the word (see --show-joins)")
    return article

