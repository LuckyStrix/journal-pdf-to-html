"""Read a PDF into positioned, styled lines with pdfminer.six. The only module that opens the PDF."""
from __future__ import annotations

import re
import struct
import zlib
from collections import Counter
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTAnno, LTChar, LTImage, LTTextLine
from pdfminer.pdftypes import PDFStream, resolve1
from pdfminer.psparser import PSLiteral

from .models import Image, Line, Page, Span
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
GUESSED_SPACE = 0.2  # x font size: on a page that draws its own spaces, a gap pdfminer guessed was a
                     # space must be this wide; narrower ones are letter-spacing ("h o u s e") or kerning
SUP_SIZE = 0.8   # x line font size: a superscript is smaller than this...
SUP_RISE = 0.2   # x line font size: ...and its baseline sits at least this much higher
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


def _baseline(ch: LTChar) -> float:
    a, b, c, d, e, f = ch.matrix
    return f if b == 0 and c == 0 else ch.y0  # upright text: the glyph origin's y


def _pieces(tl: LTTextLine, page: int, draws_spaces: bool) -> Line | None:
    """One pdfminer line as a Line with styled runs, or None if it's blank.

    draws_spaces: the page draws its word spaces as characters, so the spaces
    pdfminer guesses from gaps are only trusted when the gap is word-sized.
    """
    chars = [item for item in tl if isinstance(item, LTChar)]
    if not chars:
        return None
    sizes: Counter[float] = Counter(round(ch.size, 1) for ch in chars)
    size = sizes.most_common(1)[0][0]
    main = [ch for ch in chars if round(ch.size, 1) == size]
    base = Counter(round(_baseline(ch), 1) for ch in main).most_common(1)[0][0]
    middle = Counter(round((ch.y0 + ch.y1) / 2, 1) for ch in main).most_common(1)[0][0]

    def raised(ch: LTChar) -> bool:
        # InDesign raises a superscript by moving the glyph (its baseline moves);
        # Word uses text rise, which only moves the glyph's box
        rise = max(_baseline(ch) - base, (ch.y0 + ch.y1) / 2 - middle)
        return ch.size < SUP_SIZE * size and rise > SUP_RISE * size

    items = list(tl)

    def guessed_space(i: int) -> bool:
        before = next((x for x in reversed(items[:i]) if isinstance(x, LTChar)), None)
        after = next((x for x in items[i + 1:] if isinstance(x, LTChar)), None)
        return not draws_spaces or before is None or after is None \
            or after.x0 - before.x1 >= GUESSED_SPACE * size

    spans: list[Span] = []
    boxes: list[tuple[float, float, float, float]] = []
    cur = (False, False, False)
    for i, item in enumerate(items):
        if isinstance(item, LTChar):
            cur = (*style(item.fontname), raised(item))
            spans.append(Span(item.get_text(), *cur))
            boxes.append((item.x0, item.y0, item.x1, item.y1))
        elif isinstance(item, LTAnno) and item.get_text() != "\n" and guessed_space(i):
            spans.append(Span(item.get_text(), *cur[:2]))  # a space is never superscript
    if not "".join(s.text for s in spans).strip():
        return None
    return Line(page, min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                max(b[3] for b in boxes), size, tuple(merge_spans(spans)))


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


# --- pictures ----------------------------------------------------------------

def _name(obj) -> str:
    obj = resolve1(obj)
    return obj.name if isinstance(obj, PSLiteral) else str(obj or "")


def _png(width: int, height: int, bits: int, colour: int, rows: bytes, palette: bytes = b"") -> bytes:
    """A PNG file from packed rows (PDF and PNG both pad each row to a whole byte)."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    stride = (width * bits * channels + 7) // 8
    raw = b"".join(b"\0" + rows[i * stride:(i + 1) * stride] for i in range(height))
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bits, colour, 0, 0, 0))
    if palette:
        out += chunk(b"PLTE", palette)
    return out + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _colour_space(cs) -> tuple[str, int, bytes]:
    """(kind, components, palette) for a PDF colour space; kind is gray, rgb, cmyk, indexed or ''."""
    cs = resolve1(cs)
    if isinstance(cs, list) and cs:
        kind = _name(cs[0])
        if kind == "ICCBased":
            n = resolve1(resolve1(cs[1]).get("N", 3))
            return {1: "gray", 3: "rgb", 4: "cmyk"}.get(n, ""), n, b""
        if kind == "Indexed" and len(cs) == 4:
            base, _, _ = _colour_space(cs[1])
            lookup = resolve1(cs[3])
            table = lookup.get_data() if isinstance(lookup, PDFStream) else bytes(lookup, "latin-1") \
                if isinstance(lookup, str) else bytes(lookup)
            if base == "gray":
                table = bytes(v for g in table for v in (g, g, g))
            elif base != "rgb":
                return "", 1, b""
            return "indexed", 1, table[:768]
        if kind in ("CalRGB", "CalGray"):
            return ("rgb", 3, b"") if kind == "CalRGB" else ("gray", 1, b"")
        return "", 0, b""
    kind = _name(cs)
    return {"DeviceGray": ("gray", 1, b""), "DeviceRGB": ("rgb", 3, b""),
            "DeviceCMYK": ("cmyk", 4, b"")}.get(kind, ("", 0, b""))


def image_file(stream: PDFStream) -> tuple[bytes, str, str]:
    """(file bytes, extension, problem) for an image XObject.

    JPEGs are written exactly as embedded. Other pictures are decoded and written
    as PNG. Formats a browser can't show give empty bytes and say why.
    """
    filters = [_name(f) for f, _ in stream.get_filters()]
    if resolve1(stream.get("ImageMask")):
        return b"", "", "a one-colour stencil mask, not a picture file"
    if "JPXDecode" in filters:
        return b"", "", "JPEG 2000, which browsers don't show"
    if "JBIG2Decode" in filters or "CCITTFaxDecode" in filters:
        return b"", "", "fax-compressed black and white, which browsers don't show"
    if filters and filters[-1] == "DCTDecode":
        return stream.get_data(), "jpeg", ""
    width, height = resolve1(stream.get("Width")), resolve1(stream.get("Height"))
    bits = resolve1(stream.get("BitsPerComponent", 8))
    kind, n, palette = _colour_space(stream.get("ColorSpace"))
    data = stream.get_data()
    if not kind or bits not in (1, 2, 4, 8, 16) or (kind != "gray" and bits < 8 and kind != "indexed") \
            or (kind in ("cmyk", "indexed") and bits == 16):
        return b"", "", f"an uncommon colour format ({kind or 'special'}, {bits}-bit)"
    stride = (width * bits * n + 7) // 8
    data = data[:stride * height].ljust(stride * height, b"\0")
    decode = resolve1(stream.get("Decode"))
    if kind == "gray" and decode and [float(v) for v in decode] == [1.0, 0.0]:
        data = bytes(255 - b for b in data) if bits == 8 else bytes(b ^ 0xFF for b in data)
    if kind == "cmyk":  # a plain conversion; good enough for a screen
        data = bytes(v for i in range(0, len(data), 4)
                     for v in (255 - min(255, data[i] + data[i + 3]), 255 - min(255, data[i + 1] + data[i + 3]),
                               255 - min(255, data[i + 2] + data[i + 3])))
        kind = "rgb"
    if kind == "indexed":
        return _png(width, height, bits, 3, data, palette), "png", ""
    colour = 0 if kind == "gray" else 2
    alpha = resolve1(stream.get("SMask"))
    if isinstance(alpha, PDFStream) and bits == 8 and resolve1(alpha.get("Width")) == width \
            and resolve1(alpha.get("Height")) == height and resolve1(alpha.get("BitsPerComponent", 8)) == 8:
        mask = alpha.get_data()[:width * height].ljust(width * height, b"\xff")
        step = 1 if colour == 0 else 3
        data = bytes(v for i in range(width * height) for v in (*data[i * step:(i + 1) * step], mask[i]))
        colour = 4 if colour == 0 else 6
    return _png(width, height, bits, colour, data), "png", ""


def _images(obj, page: int):
    for child in obj:
        if isinstance(child, LTImage):
            data, ext, problem = image_file(child.stream)
            yield Image(page, child.x0, child.y0, child.x1, child.y1, tuple(child.srcsize), data, ext, problem)
        elif not isinstance(child, (LTChar, LTTextLine)) and hasattr(child, "__iter__"):
            yield from _images(child, page)


def read_pdf(path: Path) -> tuple[list[Page], int]:
    """Every page's lines, and how many lines lay entirely off the page (never visible, so left out)."""
    pages: list[Page] = []
    offpage = 0
    # all_texts: also read text drawn inside form objects, which InDesign uses for
    # master-page items such as running heads (they are then recognised and left out)
    for index, lt_page in enumerate(extract_pages(str(path), laparams=LAParams(all_texts=True))):
        pieces = []
        text_lines = list(_text_lines(lt_page))
        draws_spaces = any(isinstance(ch, LTChar) and ch.get_text() == " " for tl in text_lines for ch in tl)
        for tl in text_lines:
            line = _pieces(tl, index, draws_spaces)
            if line is None:
                continue
            if line.x1 < 0 or line.x0 > lt_page.width or line.y1 < 0 or line.y0 > lt_page.height:
                offpage += 1
            else:
                pieces.append(line)
        pages.append(Page(index, lt_page.width, lt_page.height, tuple(assemble_lines(pieces, lt_page.width)),
                          tuple(_images(lt_page, index))))
    return pages, offpage
