"""Hand-built PDFs for tests, so the repo never needs a real article.

Writes a valid PDF directly (standard Times fonts, WinAnsi text, a correct
xref) instead of adding a PDF-writing dependency. Justified lines get word
spacing (Tw) computed from the font metrics pdfminer itself uses.

SAMPLE is an invented book review laid out like a typical article: a two-line
title, centred author block, a starred footnote, single-column page then a
two-column page, a word hyphenated across the page break, a real compound
broken at a line end, a running foot beside the page number, an italic closing
statement, and a signature.
"""
from __future__ import annotations

from dataclasses import dataclass

from pdfminer.fontmetrics import FONT_METRICS

FONTS = {"R": "Times-Roman", "B": "Times-Bold", "I": "Times-Italic"}
PAGE_W, PAGE_H = 612, 792


@dataclass
class L:
    """One line: x, baseline y, runs of (font key, text), and the right edge to justify to."""
    x: float
    y: float
    runs: list[tuple[str, str]]
    justify_to: float | None = None
    size: float = 11


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


def _line_ops(line: L) -> str:
    natural = sum(text_width(t, f, line.size) for f, t in line.runs)
    spaces = sum(t.count(" ") for _, t in line.runs)
    tw = 0.0
    if line.justify_to is not None:
        target = line.justify_to - line.x
        assert natural <= target, f"line too long to justify: {line.runs}"
        tw = (target - natural) / spaces if spaces else 0.0
    ops = [f"BT {tw:.3f} Tw 1 0 0 1 {line.x:.2f} {line.y:.2f} Tm"]
    for font, text in line.runs:
        ops.append(f"/{font} {line.size} Tf {_pdf_string(text)} Tj")
    ops.append("ET")
    return " ".join(ops)


def build_pdf(pages: list[list[L]]) -> bytes:
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)

    font_ids = {k: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} /Encoding /WinAnsiEncoding >>")
                for k, name in FONTS.items()}
    fonts = " ".join(f"/{k} {i} 0 R" for k, i in font_ids.items())
    pages_id = len(objects) + 1 + 2 * len(pages)  # placeholder number, filled below
    page_ids = []
    for lines in pages:
        stream = "\n".join(_line_ops(l) for l in lines).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                            f"/Resources << /Font << {fonts} >> >> /Contents {content} 0 R >>"))
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
