"""Hand-built PDFs for tests, so the repo never needs a real article.

Writes a valid PDF directly (standard Times fonts, WinAnsi text, a correct
xref) instead of adding a PDF-writing dependency. Justified lines get word
spacing (Tw) computed from the font metrics pdfminer itself uses.

SAMPLE is an invented book review laid out like a typical article: a two-line
title, centred author block, a starred footnote, single-column page then a
two-column page, a word hyphenated across the page break, a real compound
broken at a line end, a running foot beside the page number, an italic closing
statement, and a signature.

FIGURES is an invented research article with pictures: an abstract under its
heading, bold headings, a note reference set as a superscript, a full-width
figure with the two columns flowing around it (and a word hyphenated across
it), a footnote in a smaller font with a web address broken at a hyphen, a
figure at the top of the next page drawn over an older copy of itself, and a
bibliography with hanging indents.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass

from pdfminer.fontmetrics import FONT_METRICS

FONTS = {"R": "Times-Roman", "B": "Times-Bold", "I": "Times-Italic"}
PAGE_W, PAGE_H = 612, 792


SUP = "sup"  # third item of a run: set it as a superscript
SUP_SCALE, SUP_RISE = 0.6, 0.35  # superscript size and rise, as fractions of the line's font size


@dataclass
class L:
    """One line: x, baseline y, runs of (font key, text[, SUP]), and the right edge to justify to."""
    x: float
    y: float
    runs: list[tuple]
    justify_to: float | None = None
    size: float = 11


@dataclass
class Img:
    """A picture placed in the box x0..x1, y0..y1: a JPEG file as is, or raw RGB pixels (kind "rgb")."""
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str
    data: bytes
    pixels: tuple[int, int]


# An 8x4 pixel JPEG (a red to blue gradient). pdfminer passes JPEG data through
# undecoded, so the converter must write exactly these bytes.
TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300100b0c0e0c0a100e0d0e1211101318281a181616183123"
    "251d283a333d3c3933383740485c4e404457453738506d51575f626768673e4d71797064785c656763ffdb0043011112"
    "121815182f1a1a2f63423842636363636363636363636363636363636363636363636363636363636363636363636363"
    "6363636363636363636363636363ffc00011080004000803012200021101031101ffc400150001010000000000000000"
    "0000000000000006ffc40017100100030000000000000000000000000000031452ffc400150101010000000000000000"
    "0000000000000406ffc400191100010500000000000000000000000000010003145291ffda000c03010002110311003f"
    "0093b52e80544666830244876c74afffd9")
# 3x2 pixels, raw RGB: red, green, blue / white, grey, black
TINY_RGB = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255, 128, 128, 128, 0, 0, 0])


def text_width(text: str, font: str, size: float) -> float:
    widths = FONT_METRICS[FONTS[font]][1]
    return sum(widths.get(ch, 500) for ch in text) * size / 1000


def _pdf_string(text: str) -> str:
    out = []
    for b in text.encode("cp1252"):
        ch = chr(b)
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= b < 127:
            out.append(ch)
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def centred(y: float, runs, size: float = 11, centre: float = 306) -> L:
    w = sum(text_width(t, f, size) for f, t in runs)
    return L(centre - w / 2, y, runs, size=size)


def _run_size(run: tuple, size: float) -> float:
    return size * SUP_SCALE if run[2:] == (SUP,) else size


def _line_ops(line: L) -> str:
    natural = sum(text_width(r[1], r[0], _run_size(r, line.size)) for r in line.runs)
    spaces = sum(r[1].count(" ") for r in line.runs)
    tw = 0.0
    if line.justify_to is not None:
        target = line.justify_to - line.x
        assert natural <= target, f"line too long to justify: {line.runs}"
        tw = (target - natural) / spaces if spaces else 0.0
    ops = [f"BT {tw:.3f} Tw 1 0 0 1 {line.x:.2f} {line.y:.2f} Tm"]
    for run in line.runs:
        size = _run_size(run, line.size)
        rise = f"{SUP_RISE * line.size:.2f}" if run[2:] == (SUP,) else "0"
        ops.append(f"/{run[0]} {size:g} Tf {rise} Ts {_pdf_string(run[1])} Tj")
    ops.append("ET")
    return " ".join(ops)


def _image_object(img: Img) -> bytes:
    w, h = img.pixels
    if img.kind == "jpeg":
        head, data = f"/Filter /DCTDecode", img.data
    else:
        head, data = f"/Filter /FlateDecode", zlib.compress(img.data)
    return (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB "
            f"/BitsPerComponent 8 {head} /Length {len(data)} >>\nstream\n").encode("latin-1") + data + b"\nendstream"


def build_pdf(pages: list[list]) -> bytes:
    """A PDF of pages, each a list of L (text lines) and Img (pictures, drawn in list order)."""
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)

    font_ids = {k: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} /Encoding /WinAnsiEncoding >>")
                for k, name in FONTS.items()}
    fonts = " ".join(f"/{k} {i} 0 R" for k, i in font_ids.items())
    pages_id = len(objects) + 1 + 2 * len(pages)  # placeholder number, filled below
    pages_id += sum(1 for items in pages for item in items if isinstance(item, Img))
    page_ids = []
    for items in pages:
        ops, xobjects = [], []
        for item in items:
            if isinstance(item, Img):
                name = f"Im{len(xobjects)}"
                xobjects.append(f"/{name} {add(_image_object(item))} 0 R")
                ops.append(f"q {item.x1 - item.x0:.2f} 0 0 {item.y1 - item.y0:.2f} {item.x0:.2f} {item.y0:.2f} cm "
                           f"/{name} Do Q")
            else:
                ops.append(_line_ops(item))
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        images = f" /XObject << {' '.join(xobjects)} >>" if xobjects else ""
        page_ids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                            f"/Resources << /Font << {fonts} >>{images} >> /Contents {content} 0 R >>"))
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    assert add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>") == pages_id
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    return bytes(out)


# --- the invented sample article ---------------------------------------------

R1 = 540  # right edge of the single column
LC, RC = (72, 294), (320, 542)  # two columns: left and right edges


def _sample_pages() -> list[list[L]]:
    lead = 14
    p1 = [
        centred(668, [("B", "Ostrova, Lena. The Quiet Ledger: Ports, Debt, and Memory.")], size=16),
        centred(642, [("B", "Northfield: Example Academic Press, 2023")], size=16),
        centred(584, [("B", "Tomas Vire*")]),
        centred(570, [("I", "University of Somewhere, Tromsø, Norway")]),
    ]
    body1 = [
        (72, "Harbours keep records of everything except the people who work in them. Lena", True),
        (72, "Ostrova’s study of three Baltic ports sets out to correct that, reading customs", True),
        (72, "ledgers against oral histories in a careful and well-known kind of admin-", True),
        (72, "istration history turned inside out.", False),
        (86, "The argument runs in two stages. First, Ostrova shows that debt was set down in a well-", True),
        (72, "known pattern of seasonal credit that tied dockworkers to one merchant house", True),
        (72, "for years (41–43). Second, she argues that memory—not law—undid it, as", True),
        (72, "families passed down the names of creditors along with a quiet anti-", True),
        (72, "Hanseatic resentment. The ledgers, she shows, were never neu-", True),
    ]
    y = 500
    for x, text, just in body1:
        p1.append(L(x, y, [("R", text)], R1 if just else None))
        y -= lead
    p1 += [
        L(66.5, 136.6, [("R", "*")]),
        L(72, 136.4, [("B", "Tomas Vire")]),
        L(72, 122.6, [("I", "Corresponding Author")]),
        L(72, 108.6, [("R", "t.vire@example.org")]),
        L(535, 66.6, [("R", "7")]),
    ]
    left = [
        (72, "tral, and the people they named knew", True),
        (72, "it. The book is strongest where it lets", True),
        (72, "those people speak for themselves.", False),
        (86, "Its weakness is scale. Three ports", True),
        (72, "cannot carry claims made for the whole", True),
        (72, "Baltic, and the chapter on Riga leans", True),
        (72, "on one archive. Still, the reasoning", True),
    ]
    right = [
        (320, "holds and the prose is clear.", False, "R"),
        (334, "The author used AI tools for editing", True, "I"),
        (320, "and proofreading only.", False, "I"),
        (334, "Tomas Vire", False, "R"),
        (334, "University of Somewhere", False, "R"),
    ]
    p2 = []
    y = 682
    for x, text, just in left:
        p2.append(L(x, y, [("R", text)], LC[1] if just else None))
        y -= lead
    y = 682
    for x, text, just, font in right:
        p2.append(L(x, y, [(font, text)], RC[1] if just else None))
        y -= lead
    p2 += [
        L(72, 66.6, [("R", "8")]),
        L(380, 70, [("R", "Journal of Testing Studies")]),
    ]
    return [p1, p2]


def sample_pdf() -> bytes:
    return build_pdf(_sample_pages())


def _figures_pages() -> list[list]:
    lead = 14
    p1: list = [
        centred(700, [("B", "Shared Fields: Land and Memory in Two Valleys")], size=16),
        centred(668, [("B", "Ana Lindqvist")]),
        centred(654, [("I", "University of Example")]),
        L(72, 624, [("B", "ABSTRACT")]),
        L(72, 606, [("I", "This invented article tests how the converter handles its figures and headings, its")], R1),
        L(72, 592, [("I", "abstract and note references, and the hanging indents of a bibliography.")]),
        L(72, 566, [("B", "BACKGROUND")]),
    ]
    left_above = [
        [("R", "Disputes over land run through the record of")],
        [("R", "every district we studied, and most begin as")],
        [("R", "competing claims to the same field."), ("R", "1", SUP), ("R", " Elders")],
        [("R", "remember the old boundaries, while the land")],
        [("R", "registry records the new ones, and neither")],
    ]
    right_above = [
        (334, "Figure 1 shows how claims spread across the"),
        (320, "region. Most disputes cluster in the south and"),
        (320, "in the river valleys, where fields are most"),
        (320, "valuable, and fewer are found in the dry"),
        (320, "uplands, where the oldest farms lie, in the north-"),
    ]
    y = 546
    for runs, (x, text) in zip(left_above, right_above):
        p1.append(L(72, y, runs, LC[1]))
        p1.append(L(x, y, [("R", text)], RC[1]))
        y -= lead
    p1 += [
        Img(72, 300, 542, 480, "rgb", TINY_RGB, (3, 2)),
        L(72, 280, [("R", "Figure 1: Land disputes by district, 2010\u20132020")]),
        L(72, 252, [("R", "side accepts the other\u2019s map as final.")]),
        L(320, 252, [("R", "ern districts.")]),
        L(72, 150, [("R", "1 Field notes, 2021, kept by the district office; the boundary maps are online at https://example.org/land-")],
          R1, size=9),
        L(72, 139, [("R", "records/2021/ with the registry entries.")], size=9),
        L(535, 66.6, [("R", "12")]),
    ]
    p2: list = [
        Img(72, 480, 542, 700, "rgb", TINY_RGB, (3, 2)),   # an older copy, hidden under the next one
        Img(72, 480, 542, 700, "jpeg", TINY_JPEG, (8, 4)),
        L(72, 462, [("R", "Figure 2: Claims recorded per year")]),
        L(86, 430, [("R", "The second figure shows the same claims by year.")]),
        L(72, 400, [("B", "BIBLIOGRAPHY")]),
        L(72, 382, [("R", "Lindqvist, Ana. Shared Fields: Land and Memory. Northfield: Example Academic")], R1),
        L(86, 368, [("R", "Press, 2023.")]),
        L(72, 354, [("R", "Vire, Tomas. \u201cBoundary Stones.\u201d Journal of Testing Studies 4 (2022): 1\u201320.")]),
        L(72, 66.6, [("R", "13")]),
        L(380, 70, [("R", "Journal of Testing Studies")]),
    ]
    return [p1, p2]


def figures_pdf() -> bytes:
    return build_pdf(_figures_pages())
