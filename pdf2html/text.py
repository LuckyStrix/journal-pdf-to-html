"""Pure text helpers: spans, line joining with de-hyphenation, and HTML escaping."""
from __future__ import annotations

import re
import textwrap
from html.entities import codepoint2name

from .models import Span

HYPHENS = ("-", "‐")  # hyphen-minus and the Unicode hyphen InDesign sometimes emits
SOFT_HYPHEN = "­"     # explicitly discretionary: always removed when joining
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[^\W_]+(?:[-‐'’][^\W_]+)*")
_URL_START = re.compile(r"(?:https?://|www\.)\S*$", re.I)  # a line ending inside a web address
URL = re.compile(r"https?://[^\s<>\"“”‘’]*[^\s<>\"“”‘’.,;:)\]]", re.I)


# --- spans -------------------------------------------------------------------

def merge_spans(spans: list[Span]) -> list[Span]:
    """Join neighbouring runs that share a style, dropping empty ones."""
    out: list[Span] = []
    for s in spans:
        if not s.text:
            continue
        if out and out[-1].style == s.style:
            out[-1] = out[-1].with_text(out[-1].text + s.text)
        else:
            out.append(s)
    return out


def normalize_spans(spans) -> list[Span]:
    """Collapse whitespace inside a line and trim its ends.

    Justified PDF text comes out with runs of 2-3 spaces between words.
    """
    out: list[Span] = []
    prev_space = True  # trims leading whitespace
    for s in spans:
        t = _WS.sub(" ", s.text)
        if prev_space:
            t = t.lstrip(" ")
        if t:
            out.append(s.with_text(t))
            prev_space = t.endswith(" ")
    while out and out[-1].text.endswith(" "):
        last = out.pop()
        if last.text.rstrip(" "):
            out.append(last.with_text(last.text.rstrip(" ")))
            break
    return merge_spans(out)


def spans_text(spans) -> str:
    return "".join(s.text for s in spans)


def split_spans(spans: list[Span], offset: int) -> tuple[list[Span], list[Span]]:
    """Split runs at a character offset into the joined text."""
    left: list[Span] = []
    right: list[Span] = []
    pos = 0
    for s in spans:
        end = pos + len(s.text)
        if end <= offset:
            left.append(s)
        elif pos >= offset:
            right.append(s)
        else:
            cut = offset - pos
            left.append(s.with_text(s.text[:cut]))
            right.append(s.with_text(s.text[cut:]))
        pos = end
    return left, right


def strip_bold(spans: list[Span]) -> list[Span]:
    """Drop bold from a block that is bold throughout (a heading's own style, which the CSS supplies)."""
    if spans and all(s.bold for s in spans if s.text.strip()):
        return merge_spans([Span(s.text, False, s.italic, s.sup) for s in spans])
    return spans


def strip_italic(spans: list[Span]) -> list[Span]:
    """Drop italics from a block that is italic throughout (when the stylesheet sets it in italics)."""
    if spans and all(s.italic for s in spans if s.text.strip()):
        return merge_spans([Span(s.text, s.bold, False, s.sup) for s in spans])
    return spans


# --- de-hyphenation ----------------------------------------------------------

def vocabulary(line_texts: list[str]) -> set[str]:
    """Lower-cased words that appear inside lines, i.e. not split by a line end.

    A hyphenated word found here ("well-known") was written with its hyphen, so
    the same word broken at a line end keeps it.
    """
    words: set[str] = set()
    for text in line_texts:
        tokens = text.split()
        if tokens and tokens[-1].endswith(HYPHENS + (SOFT_HYPHEN,)):
            tokens = tokens[:-1]
        for tok in tokens:
            words.update(m.group(0).lower() for m in _WORD.finditer(tok))
            if re.search(r"\w[/.]\w", tok):  # part of a web address, kept whole for url_hyphen
                words.add(_ADDRESS + tok.lower())
    return words


_ADDRESS = "address:"  # marks address pieces in a vocabulary; never a word, since words have no colon


def keep_hyphen(left: str, right: str, vocab: set[str]) -> bool:
    """Decide whether a line-end hyphen between two fragments is part of the word.

    left is the fragment before the hyphen (without it), right the one after.
    Typesetters break words with a hyphen at any syllable, so the default is to
    rejoin; every decision is listed in the report for a person to check.
    """
    if not left or not right:
        return True
    hyphenated = f"{left}-{right}".lower()
    solid = f"{left}{right}".lower()
    if left.isalpha() and right.isalpha() and left.isupper() and right.isupper() and len(right) >= 3:
        return hyphenated in vocab  # a word in capitals broken at a syllable: "RECOMMENDA-" / "TIONS"
    if not right[0].isalpha() or right[0].isupper():
        return True  # "anti-" / "European", "mid-" / "1990s"
    if any(c.isdigit() for c in left):
        return True
    return hyphenated in vocab and solid not in vocab


def _edge_word(text: str, last: bool) -> str:
    tokens = text.split()
    if not tokens:
        return ""
    tok = tokens[-1] if last else tokens[0]
    m = list(_WORD.finditer(tok))
    if not m:
        return ""
    return (m[-1] if last else m[0]).group(0)


def url_continues(text: str, nxt: str) -> bool:
    """Whether a web address broken at a line end goes on at the start of the next line.

    Typesetters break addresses after a slash, dot or hyphen without adding a
    hyphen, so the next line glues on with no space, and a hyphen there is part
    of the address. The address goes on if the line ends with "/", "-", "_" or
    "://", or the next line starts with a word that has a dot or slash inside it
    ("example.org/archive", "2021.0417;"), which ordinary words don't.
    """
    tokens = text.split()
    if not tokens or not _URL_START.search(tokens[-1]) or text.endswith(" ") or not nxt[:1].strip():
        return False
    head = nxt.split()[0]
    return tokens[-1].endswith(("/", "-", "‐", "_")) or bool(re.search(r"\w[./]\w", head))


def url_hyphen(left: str, right: str, vocab: set[str]) -> bool:
    """Whether a hyphen ending a line inside a web address belongs to the address.

    left is the address up to and including the hyphen, right what the next line
    starts with. Typesetters sometimes hyphenate an address like a word
    ("harbour-con-" / "flicts"). If the address appears unbroken elsewhere in the
    article, that settles it; otherwise the hyphen goes only when the two halves
    make a word the article uses solid and never hyphenated.
    """
    if right.startswith("."):
        return False  # no part of a domain name ends in a hyphen ("www.ex-" / ".org")
    head = re.split(r"[/.]", left[:-1])[-1]
    tail = re.split(r"[/.]", right)[0]
    if len(head) + len(tail) >= 6:
        pieces = [w[len(_ADDRESS):] for w in vocab if w.startswith(_ADDRESS)]
        if any(f"{head}-{tail}".lower() in p for p in pieces):
            return True
        if any(f"{head}{tail}".lower() in p for p in pieces):
            return False
    a, b = _edge_word(left[:-1], last=True).split("-")[-1], _edge_word(right, last=False).split("-")[0]
    return not (a and b and b[0].islower() and f"{a}{b}".lower() in vocab and f"{a}-{b}".lower() not in vocab)


def join_lines(lines: list[list[Span]], vocab: set[str], joins: list | None = None,
               breaks_before: set[int] = frozenset()) -> tuple[list[Span], list[int]]:
    """Join a paragraph's lines into one run of text.

    breaks_before holds the indexes of lines that start a new printed page. The
    returned offsets say where in the text each of those pages begins. When a word
    is hyphenated across a page break, the break moves to the start of the word,
    so the whole word goes to the new page.
    """
    out: list[Span] = []
    offsets: list[int] = []
    for i, raw in enumerate(lines):
        spans = normalize_spans(raw)
        if not spans:
            continue
        text = spans_text(out)
        start = len(text)
        if out:
            nxt = spans_text(spans)
            if url_continues(text, nxt):
                if text.endswith(HYPHENS):
                    left, right = text.split()[-1], nxt.split()[0]
                    keep = url_hyphen(left, right, vocab)
                    if not keep:
                        out, _ = split_spans(out, len(text) - 1)
                        start = len(text) - 1
                    if joins is not None:
                        joins.append((left, right, left + right if keep else left[:-1] + right))
                glued = True
            elif text.endswith(SOFT_HYPHEN):
                out, _ = split_spans(out, len(text) - 1)
                start = len(text) - 1
                glued = True
            elif text.endswith(HYPHENS) and text[-2:-1].isalnum() and nxt[:1].isalnum():
                left = _edge_word(text[:-1], last=True)
                right = _edge_word(nxt, last=False)
                if not keep_hyphen(left, right, vocab):
                    out, _ = split_spans(out, len(text) - 1)
                    start = len(text) - 1
                    if joins is not None:
                        joins.append((left + "-", right, left + right))
                elif joins is not None:
                    joins.append((left + "-", right, f"{left}-{right}"))
                glued = True
            else:
                out = merge_spans(out + [Span(" ", out[-1].bold, out[-1].italic)])
                start += 1
                glued = False
            if i in breaks_before and glued:
                start = spans_text(out).rfind(" ") + 1
        if i in breaks_before:
            offsets.append(start)
        out = merge_spans(out + spans)
    return out, offsets


# --- HTML --------------------------------------------------------------------

def escape(text: str) -> str:
    """Escape for HTML text, writing every non-ASCII character as an entity.

    The journal's template asks for entities so apostrophes, dashes and accented
    letters survive however the file is later served or edited. Doing it for
    every character avoids the half-converted mix a hand edit leaves.
    """
    out = []
    for ch in text:
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ord(ch) < 128:
            out.append(ch)
        elif ord(ch) in codepoint2name:
            out.append(f"&{codepoint2name[ord(ch)]};")
        else:
            out.append(f"&#{ord(ch)};")
    return "".join(out)


def linked(text: str) -> str:
    """Escaped text with every web address made a link to itself."""
    out, pos = [], 0
    for m in URL.finditer(text):
        url = escape(m.group(0))
        out += [escape(text[pos:m.start()]), f'<a href="{url.replace(chr(34), "&quot;")}">{url}</a>']
        pos = m.end()
    return "".join(out) + escape(text[pos:])


def spans_html(spans: list[Span]) -> str:
    """Inline HTML for styled runs, keeping spaces outside the tags."""
    parts = []
    for s in merge_spans(spans):
        body = s.text.strip(" ")
        lead = " " if s.text.startswith(" ") else ""
        trail = " " if s.text.endswith(" ") and body else ""
        html = linked(body)
        if body and s.sup:
            html = f"<sup>{html}</sup>"
        if body and s.italic:
            html = f"<i>{html}</i>"
        if body and s.bold:
            html = f"<b>{html}</b>"
        parts.append(lead + html + trail)
    return re.sub(r" {2,}", " ", "".join(parts)).strip()


def wrap(html: str, width: int, indent: str = "    ") -> str:
    """Wrap inline HTML at spaces only, so tags and entities are never split."""
    html = html.replace("<a href=", "<a\0href=")  # keep a link's opening tag on one line
    return textwrap.fill(html, width=width, initial_indent=indent, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False).replace("\0", " ")
