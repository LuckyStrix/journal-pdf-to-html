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
    figure       a picture with its caption ("Figure 3: ...") just above or below it
    heading      a short paragraph set entirely in bold (or italic) that ends without a full stop
    abstract     the paragraph under an "Abstract" or "Keywords" heading

Hard rule for editing: text is never dropped silently. Anything left out goes in
Article.dropped, and check.py fails the conversion if the output's characters
don't match the PDF's.
"""
from __future__ import annotations

import hashlib
import re
import statistics
from collections import Counter

from .models import (ABSTRACT, FIGURE, FOOTNOTE, HEADING, LINES, PAGE, PARAGRAPH, Article, Block, Image,
                     Line, Page)
from .text import join_lines, normalize_spans, split_spans, spans_text, strip_bold, strip_italic, vocabulary

TITLE_SCALE = 1.2      # title lines are at least this many times the body font size
MARGIN = 0.12          # page numbers and running heads sit in the top or bottom 12% of the page
PAGE_NUMBER = re.compile(r"^\d{1,4}$")
FOOTNOTE_MARK = re.compile(r"^(?:[*†‡§¶]|\d{1,3}(?=\s|[^\W\d_]))")  # "*", "12 Smith", not "1-25,"
FOOTNOTE_GAP = 2.0     # x leading: blank space that sets footnotes apart from the text above
FOOTNOTE_GAP_SMALL = 1.0  # x leading: enough space when the notes are also set in a smaller font
SMALLER = 0.95         # x body font size: notes set below this are in a smaller font
PARA_GAP = 1.6         # x leading: a bigger vertical gap inside a column starts a paragraph
INDENT = 0.6           # x font size: a first-line indent bigger than this starts a paragraph
SHORT = 1.5            # x font size: a line ending this far before the column edge ends its paragraph
CENTRED = 1.0          # x font size: how far off the text centre a centred line may sit
NARROW = 0.7           # author lines are narrower than this fraction of the text width
SHORT_LINE = 0.6       # footnote lines narrower than this fraction of the text width stay on their own lines
SIGNATURE_MAX_LINES = 4
BASELINE_TOLERANCE = 1.0  # x font size: running heads sit within a line of the page number's baseline
SENTENCE_END = (".", "!", "?", ".”", ".\"", "?”", "!”")
HIDDEN = 0.9           # a picture with this much of its area under a later one is never seen
CAPTION_GAP = 2.5      # x leading: furthest a caption sits from its picture
CAPTION_LEADING = 1.3  # x leading: caption lines closer than this belong together
CAPTION = re.compile(r"^(figure|fig\.|map|table|chart|graph|plate|photo|image|illustration|exhibit)\s*"
                     r"(\d+[a-z]?)(?:\s*[.:\u2013\u2014-]|\s*$)", re.I)
CAPTION_MORE = re.compile(r"^(source|sources|note|notes)\b", re.I)  # a source line under the caption
HEADING_MAX_LINES = 3
ABSTRACT_HEADING = re.compile(r"^(abstract|keywords|key\s*words)$", re.I)
HANGING_HEADING = re.compile(r"^(bibliography|references|works\s+cited|sources|literature)$", re.I)


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


def _next_note(previous: str, text: str) -> bool:
    """Whether a line in the footnote area starts a new note after the note starting with previous.

    After note 12 only 13 starts a note, so a wrapped line that happens to begin
    with a number ("2 (2019): 40-58") stays part of its note.
    """
    m = FOOTNOTE_MARK.match(text.strip())
    if not m:
        return False
    before = re.match(r"\d+", previous.strip())
    return not (before and m.group(0).isdigit()) or int(m.group(0)) == int(before.group(0)) + 1


def split_footnotes(lines: list[Line], lead: float) -> tuple[list[Line], list[list[Line]]]:
    """Separate footnotes at the bottom of a page from the text above them.

    A footnote area is the lowest stretch of the page that has blank space across
    every column above it and starts with a footnote mark. The space must be
    FOOTNOTE_GAP leadings, or FOOTNOTE_GAP_SMALL when the notes are in a smaller
    font than the text above. Each line starting with a mark begins a new note.
    """
    ordered = sorted(lines, key=lambda l: (-l.y1, l.x0))
    for k in range(1, len(ordered)):
        top, bottom = ordered[:k], ordered[k:]
        gap = min(l.y0 for l in top) - max(l.y1 for l in bottom)
        smaller = max(l.size for l in bottom) < SMALLER * statistics.median(l.size for l in top)
        needed = (FOOTNOTE_GAP_SMALL if smaller else FOOTNOTE_GAP) * lead
        if gap > needed and FOOTNOTE_MARK.match(bottom[0].text.strip()):
            notes: list[list[Line]] = []
            for line in bottom:
                if not notes or _next_note(notes[-1][0].text, line.text):
                    notes.append([line])
                else:
                    notes[-1].append(line)
            return top, notes
    return ordered, []


def _italic(line: Line) -> bool:
    spans = [s for s in line.spans if s.text.strip()]
    return bool(spans) and all(s.italic for s in spans)


def _mid_sentence(line: Line) -> bool:
    """A line that stops on a letter or digit, a comma or a hyphen: the sentence goes on
    after it, so blank space below it (a baseline-grid gap) doesn't end the paragraph."""
    text = line.text.rstrip()
    return bool(text) and (text[-1].isalnum() or text[-1] in ",-‐") and not line.spans[-1].sup


def _bold(line: Line) -> bool:
    spans = [s for s in line.spans if s.text.strip()]
    return bool(spans) and all(s.bold for s in spans)


def paragraphs(stream: list[tuple[Line, float, float]], lead: float,
               holes: dict[int, list[tuple[float, float]]] | None = None) -> list[list[tuple[Line, float, float]]]:
    """Group body lines (in reading order) into paragraphs.

    holes are the (bottom, top) of each page's figures: the text runs on around
    a figure, so the space it takes up doesn't start a paragraph.

    Under a "Bibliography" or "References" heading entries have a hanging indent:
    an entry starts at the column edge and its later lines are indented.
    """
    holes = holes or {}

    def figure_between(upper: Line, lower: Line) -> bool:
        return any(lower.y1 <= bottom + 1 and top - 1 <= upper.y0 for bottom, top in holes.get(lower.page, []))

    paras: list[list[tuple[Line, float, float]]] = []
    prev = None
    hanging = False
    for item in stream:
        line, left, _right = item
        new = prev is None
        if prev is not None:
            pline, pleft, pright = prev
            indented = line.x0 - left > INDENT * line.size
            if hanging and not _bold(line):
                new = not indented or _bold(pline)
            elif indented:
                new = True
            elif pline.x1 < pright - SHORT * pline.size:
                new = True
            elif line.page == pline.page and left == pleft and pline.y0 - line.y0 > PARA_GAP * lead \
                    and not figure_between(pline, line) and not _mid_sentence(pline):
                new = True
            elif _italic(line) != _italic(pline) or _bold(line) != _bold(pline):
                new = True
        if new:
            paras.append([item])
        else:
            paras[-1].append(item)
        if _bold(line):
            hanging = bool(HANGING_HEADING.match(" ".join(l.text for l, _, _ in paras[-1]).strip()))
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


def _all_italic(lines: list[Line]) -> bool:
    return all(_italic(l) for l in lines)


def is_heading(lines: list[Line]) -> bool:
    """A short paragraph entirely in bold, or in italics, that doesn't end a sentence."""
    text = " ".join(l.text for l in lines).strip()
    if not text or len(lines) > HEADING_MAX_LINES or text.endswith(SENTENCE_END + (",", ";", ":")):
        return False
    return all(_bold(l) for l in lines) or (len(lines) <= 2 and _all_italic(lines))


def _short_lines(lines: list[Line], width: float) -> bool:
    return all(l.width < SHORT_LINE * width for l in lines)


def visible_images(pages: list[Page]) -> tuple[list[Image], list[tuple[Image, str]]]:
    """The pictures a reader sees, and the ones left out with the reason.

    Left out: a picture mostly covered by one drawn later (an old version left
    under its replacement), one off the page, and the same picture repeated in
    the margin of several pages (a logo in the running head).
    """
    seen: list[Image] = []
    left_out: list[tuple[Image, str]] = []
    margin_copies: Counter[str] = Counter()
    for page in pages:
        for img in page.images:
            if img.data and _image_in_margin(img, page):
                margin_copies[hashlib.sha1(img.data).hexdigest()] += 1
    for page in pages:
        for i, img in enumerate(page.images):
            on_page = (min(img.x1, page.width) - max(img.x0, 0)) * (min(img.y1, page.height) - max(img.y0, 0))
            if img.area <= 0 or img.x1 <= 0 or img.x0 >= page.width or img.y1 <= 0 or img.y0 >= page.height \
                    or on_page <= 0:
                left_out.append((img, "placed off the page"))
            elif any(_overlap(img, later) >= HIDDEN * img.area for later in page.images[i + 1:]):
                left_out.append((img, "hidden under another picture drawn over it"))
            elif img.data and _image_in_margin(img, page) and margin_copies[hashlib.sha1(img.data).hexdigest()] >= 2:
                left_out.append((img, "repeated in the margin of several pages"))
            else:
                seen.append(img)
    return seen, left_out


def _image_in_margin(img: Image, page: Page) -> bool:
    return img.y0 > page.height * (1 - MARGIN) or img.y1 < page.height * MARGIN


def _overlap(a: Image, b: Image) -> float:
    return max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))


def find_caption(img: Image, lines: list[Line], lead: float, text_right: float) -> tuple[list[Line], str]:
    """The caption lines of a picture and its name ("figure3"), or ([], "") if it has none.

    A caption starts with "Figure N" (or Table, Map, ...) across part of the
    picture's width, and runs down the page while each line fills the width and
    the next sits a line lower at the same x; a "Source: ..." line just after it
    belongs to it too. The caption nearest the picture, above or below it and
    within CAPTION_GAP leadings, wins.
    """
    def follow(first: Line, above: bool) -> list[Line]:
        caption = [first]
        lower = sorted((l for l in lines if l.y1 <= first.y0 and (not above or l.y0 >= img.y1)),
                       key=lambda l: -l.y0)
        for line in lower:
            last = caption[-1]
            step = last.y0 - line.y0
            full = last.x1 >= min(img.x1, text_right) - SHORT * last.size
            if step <= CAPTION_LEADING * lead and abs(line.x0 - last.x0) <= 1 and full:
                caption.append(line)
            elif step <= CAPTION_GAP * lead and CAPTION_MORE.match(line.text.strip()) and line.x0 < img.x1:
                caption.append(line)
            else:
                break
        return caption

    best: tuple[float, list[Line]] | None = None
    for line in lines:
        if not CAPTION.match(line.text.strip()) or line.x1 <= img.x0 or line.x0 >= img.x1:
            continue
        if line.y1 <= img.y0:
            caption = follow(line, above=False)
            gap = img.y0 - line.y1
        elif line.y0 >= img.y1:
            caption = follow(line, above=True)
            gap = caption[-1].y0 - img.y1
        else:
            continue
        if gap <= CAPTION_GAP * lead and (best is None or gap < best[0]):
            best = (gap, caption)
    if best is None:
        return [], ""
    m = CAPTION.match(best[1][0].text.strip())
    kind = m.group(1).lower().rstrip(".")
    return best[1], ("figure" if kind == "fig" else kind) + m.group(2).lower()


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

    # Figures: each picture a reader sees, with its caption taken out of the text flow,
    # so the columns read on around it
    images, left_out = visible_images(pages)
    for img, why in left_out:
        article.dropped_images.append(img)
        article.notes.append(f"page {labels[img.page]}: left out a picture {img.pixels[0]}x{img.pixels[1]} px, {why}")
    figures: list[list[tuple[Image, Block]]] = [[] for _ in pages]
    holes: dict[int, list[tuple[float, float]]] = {}  # per page, the space each figure takes up
    names: Counter[str] = Counter()
    uncaptioned = 0
    for img in images:
        lines = content[img.page]
        caption, name = find_caption(img, lines, lead, text_right)
        inside = [l for l in lines if l not in caption and img.x0 <= (l.x0 + l.x1) / 2 <= img.x1
                  and img.y0 <= (l.y0 + l.y1) / 2 <= img.y1]
        content[img.page] = [l for l in lines if l not in caption and l not in inside]
        if not name:
            uncaptioned += 1
            name = f"image{uncaptioned}"
        names[name] += 1
        if names[name] > 1:
            name = f"{name}-{names[name]}"
        rows = []
        if caption:
            spans, _ = join_lines([list(l.spans) for l in caption if not CAPTION_MORE.match(l.text.strip())],
                                  vocab, article.joins)
            rows.append(normalize_spans(spans))
            rows += [normalize_spans(l.spans) for l in caption if CAPTION_MORE.match(l.text.strip())]
        rows += [normalize_spans(l.spans) for l in sorted(inside, key=lambda l: (-l.y1, l.x0))]
        figures[img.page].append((img, Block(FIGURE, rows, image=img, name=name)))
        taken = caption + inside
        holes.setdefault(img.page, []).append((min([img.y0] + [l.y0 for l in taken]),
                                               max([img.y1] + [l.y1 for l in taken])))
        where = f"page {labels[img.page]}: {name}"
        if not caption:
            article.notes.append(f"{where} has no caption (\"Figure N: ...\") next to it; check where it belongs")
        if inside:
            article.notes.append(f"{where}: {len(inside)} line(s) printed over the picture kept as text after it")
        if img.problem:
            article.notes.append(f"{where} is {img.problem}; save it from the PDF by hand as {name}.png")
        article.notes.append(f"{where}: write alt text describing the picture (it is the caption for now)")

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
    page_top_figures: list[list[Block]] = [[] for _ in pages]
    page_end_figures: list[list[Block]] = [[] for _ in pages]
    stream: list[tuple[Line, float, float]] = []
    for idx, lines in enumerate(content):
        body, notes = split_footnotes(lines, lead)
        for note in notes:
            note = sorted(note, key=lambda l: (-l.y1, l.x0))
            # short lines (a corresponding-author note: name, role, email) stay apart;
            # a one-line numbered note is an ordinary footnote
            if _short_lines(note, text_width) and (len(note) > 1 or not note[0].text.strip()[:1].isdigit()):
                rows = [normalize_spans(l.spans) for l in note]
                page_notes[idx].append(Block(LINES, rows))
            else:
                spans, _ = join_lines([list(l.spans) for l in note], vocab, article.joins)
                page_notes[idx].append(Block(FOOTNOTE, [spans]))
        stream.extend(reading_order(body, centre, text_left, text_right))
        # a picture above all of the page's text goes before it, any other after it
        top = max((l.y1 for l in body), default=0.0)
        for img, block in figures[idx]:
            (page_top_figures if img.y1 >= top else page_end_figures)[idx].append(block)

    paras = paragraphs(stream, lead, holes)
    signature = split_signature(paras)
    under = ""  # text of the last heading
    abstract_italic = None
    for para in paras:
        lines = [item[0] for item in para]
        kind = PARAGRAPH
        if ABSTRACT_HEADING.match(under) and not all(_bold(l) for l in lines) \
                and abstract_italic in (None, _all_italic(lines)):
            kind = ABSTRACT
            abstract_italic = _all_italic(lines)
        elif is_heading(lines):
            kind = HEADING
        breaks = {i for i in range(1, len(lines)) if lines[i].page != lines[i - 1].page}
        spans, offsets = join_lines([list(l.spans) for l in lines], vocab, article.joins, breaks)
        text = " ".join(spans_text(spans).split())
        piece_pages = [lines[0].page] + [lines[i].page for i in sorted(breaks)]
        pieces = []
        for off in reversed(offsets):
            spans, tail = split_spans(spans, off)
            pieces.insert(0, tail)
        pieces.insert(0, spans)
        for pg, piece in zip(piece_pages, pieces):
            piece = normalize_spans(piece)
            if kind == HEADING:
                piece = strip_bold(piece)
            elif kind == ABSTRACT:
                piece = strip_italic(piece)  # the stylesheet sets the abstract in italics
            if piece:
                page_blocks[pg].append(Block(kind, [piece]))
        if kind == HEADING:
            under = text
            abstract_italic = None
        elif kind == PARAGRAPH:
            under = ""
    if signature:
        rows = [normalize_spans(item[0].spans) for item in signature]
        page_blocks[signature[0][0].page].append(Block(LINES, rows))

    for idx, label in enumerate(labels):
        article.body.append(Block(PAGE, label=label, printed=found_labels[idx] is not None))
        article.body.extend(page_top_figures[idx])
        article.body.extend(page_blocks[idx])
        article.body.extend(page_end_figures[idx])
        article.body.extend(page_notes[idx])

    for line in article.dropped:
        article.notes.append(f"page {labels[line.page]}: left out running head/foot \"{' '.join(line.text.split())}\"")
    kept = [j for j in article.joins if j[2] == j[0] + j[1]]
    if kept:
        article.notes.append(f"{len(kept)} line-end hyphen(s) kept as part of the word (see --show-joins)")
    return article

