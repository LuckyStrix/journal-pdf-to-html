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
class Page:
    index: int
    width: float
    height: float
    lines: tuple[Line, ...]


# Block kinds
PARAGRAPH = "paragraph"  # prose, rendered as one wrapped <p>
LINES = "lines"          # short lines kept apart with <br> (footnotes, signatures)
PAGE = "page"            # printed page-number marker, rendered as <p>Page N</p>


@dataclass
class Block:
    kind: str
    rows: list[list[Span]] = field(default_factory=list)  # PARAGRAPH has exactly one row
    label: str = ""  # PAGE only: the page number
    printed: bool = True  # PAGE only: False when the number was inferred, not read from the PDF


@dataclass
class Article:
    title: list[Span]
    authors: list[list[Span]]
    body: list[Block]
    dropped: list[Line] = field(default_factory=list)  # left out on purpose (running heads), each reported
    joins: list[tuple[str, str, str]] = field(default_factory=list)  # (end of line, start of next, result)
    notes: list[str] = field(default_factory=list)  # anything a person should check
