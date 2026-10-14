"""Plain data passed between reading the PDF, finding its structure, and writing HTML.

Coordinates are PDF points with the origin at the bottom-left of the page, so a
larger y is higher up the page.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Span:
    """A run of text in one style."""
    text: str
    bold: bool = False
    italic: bool = False
    sup: bool = False  # raised and smaller: a note reference such as the 22 in "Ostrova22"

    def with_text(self, text: str) -> "Span":
        return Span(text, self.bold, self.italic, self.sup)

    @property
    def style(self) -> tuple[bool, bool, bool]:
        return self.bold, self.italic, self.sup


@dataclass(frozen=True)
class Line:
    """One printed line: where it sits, its font size, and its styled runs."""
    page: int  # 0-based physical page index
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    spans: tuple[Span, ...]

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def width(self) -> float:
        return self.x1 - self.x0


@dataclass(frozen=True)
class Image:
    """A picture drawn on a page, in drawing order, with its file ready to write.

    data and ext are empty when the picture's format can't be written as a file a
    browser shows (problem says why); it then still gets an <img> to fill by hand.
    """
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    pixels: tuple[int, int]
    data: bytes = b""
    ext: str = ""   # "jpeg" or "png"
    problem: str = ""

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


@dataclass(frozen=True)
class Page:
    index: int
    width: float
    height: float
    lines: tuple[Line, ...]
    images: tuple[Image, ...] = ()


# Block kinds
PARAGRAPH = "paragraph"  # prose, rendered as one wrapped <p>
LINES = "lines"          # short lines kept apart with <br> (footnotes, signatures)
PAGE = "page"            # printed page-number marker, rendered as <p>Page N</p>
HEADING = "heading"      # a bold (or italic) title line inside the text, rendered as <h4>
ABSTRACT = "abstract"    # the abstract or keywords under their heading, rendered as <div class="abstract">
FOOTNOTE = "footnote"    # one numbered note; a page's notes share one <div class="footnote">
FIGURE = "figure"        # a picture: its caption rows, then the <img>


@dataclass
class Block:
    kind: str
    rows: list[list[Span]] = field(default_factory=list)  # PARAGRAPH has exactly one row
    label: str = ""  # PAGE only: the page number
    printed: bool = True  # PAGE only: False when the number was inferred, not read from the PDF
    image: Image | None = None  # FIGURE only
    name: str = ""  # FIGURE only: the image's file name without extension ("figure3")


@dataclass
class Article:
    title: list[Span]
    authors: list[list[Span]]
    body: list[Block]
    dropped: list[Line] = field(default_factory=list)  # left out on purpose (running heads), each reported
    dropped_images: list[Image] = field(default_factory=list)  # hidden under another picture, or repeated decoration
    joins: list[tuple[str, str, str]] = field(default_factory=list)  # (end of line, start of next, result)
    notes: list[str] = field(default_factory=list)  # anything a person should check
