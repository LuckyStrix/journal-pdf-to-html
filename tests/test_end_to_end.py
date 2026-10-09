"""The whole path, PDF file to HTML file, on the invented sample article."""
import re

import pytest

from pdf2html.check import compare_with_html, compare_with_pdf
from pdf2html.cli import main
from pdf2html.models import LINES, PAGE, PARAGRAPH
from pdf2html.reader import read_pdf
from pdf2html.render import render
from pdf2html.structure import build_article
from pdf2html.text import spans_text
from tests.make_pdf import sample_pdf


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    path.write_bytes(sample_pdf())
    pages, offpage = read_pdf(path)
    article = build_article(pages)
    html = render(article, journal="Journal of Testing Studies")
    return path, pages, article, html


def body_texts(article):
    return [(b.kind, b.label or " / ".join(spans_text(r) for r in b.rows)) for b in article.body]


def test_title_and_authors_are_found(sample):
    _, _, article, html = sample
    assert spans_text(article.title) == ("Ostrova, Lena. The Quiet Ledger: Ports, Debt, and Memory. "
                                         "Northfield: Example Academic Press, 2023")
    assert [spans_text(r) for r in article.authors] == ["Tomas Vire*", "University of Somewhere, Tromsø, Norway"]
    assert "<b>Tomas Vire*</b><br>" in html
    assert "<i>University of Somewhere, Troms&oslash;, Norway</i>" in html


def test_blocks_come_in_reading_order(sample):
    _, _, article, _ = sample
    kinds = [k for k, _ in body_texts(article)]
    assert kinds == [PAGE, PARAGRAPH, PARAGRAPH, LINES, PAGE, PARAGRAPH, PARAGRAPH, PARAGRAPH, LINES]
    texts = [t for _, t in body_texts(article)]
    assert texts[0] == "7" and texts[4] == "8"
    # the left column is read before the right one
    assert texts[6].startswith("Its weakness") and texts[6].endswith("the prose is clear.")


def test_page_marker_comes_before_the_page_and_footnote_ends_its_page(sample):
    _, _, _, html = sample
    order = [html.index(s) for s in ("<p>Page 7</p>", "Harbours keep", "<i>Corresponding Author</i>",
                                     "<p>Page 8</p>", "neutral, and the people")]
    assert order == sorted(order)


def test_word_hyphenated_across_the_page_break_moves_whole_to_the_new_page(sample):
    _, _, article, _ = sample
    texts = [t for _, t in body_texts(article)]
    assert texts[2].endswith("she shows, were never")
    assert texts[5].startswith("neutral, and")


def test_line_end_hyphens(sample):
    _, _, article, html = sample
    html = " ".join(html.split())  # the HTML source is wrapped
    assert "kind of administration history" in html          # syllable break: rejoined
    assert "in a well-known pattern" in html                 # compound used elsewhere: kept
    assert "anti-Hanseatic" in html                          # capital after the hyphen: kept
    assert sorted(j[2] for j in article.joins) == ["administration", "anti-Hanseatic", "neutral", "well-known"]


def test_running_foot_is_left_out_and_reported(sample):
    _, _, article, html = sample
    assert [d.text.strip() for d in article.dropped] == ["Journal of Testing Studies"]
    assert any("Journal of Testing Studies" in n for n in article.notes)
    body = html.split("<body>")[1]
    assert "Journal of Testing Studies" not in re.sub(r'alt="[^"]*"', "", body)


def test_closing_statement_is_kept_in_italics_and_signature_is_one_block(sample):
    _, _, _, html = sample
    assert "<i>The author used AI tools for editing and proofreading only.</i>" in html
    assert "    Tomas Vire<br>\n    University of Somewhere\n</p>" in html


def test_output_is_ascii_with_entities_and_charset(sample):
    _, _, _, html = sample
    html.encode("ascii")
    assert '<meta charset="utf-8">' in html
    for entity in ("&rsquo;", "&ndash;", "&mdash;", "&oslash;"):
        assert entity in html


def test_nothing_is_lost_between_pdf_article_and_html(sample):
    _, pages, article, html = sample
    assert compare_with_pdf(pages, article) == []
    assert compare_with_html(html, article) == []


def test_cli_writes_the_page_and_refuses_to_overwrite(tmp_path, capsys):
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(sample_pdf())
    assert main(["convert", str(pdf), "--journal", "Journal of Testing Studies"]) == 0
    out = tmp_path / "article.html"
    first = out.read_text(encoding="ascii")
    assert "<title>Journal of Testing Studies</title>" in first
    assert main(["convert", str(pdf)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert out.read_text(encoding="ascii") == first
    assert main(["convert", str(pdf), "--force", "--no-logo"]) == 0
    assert "<img" not in out.read_text(encoding="ascii")


def test_inspect_masks_text_by_default(tmp_path, capsys):
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(sample_pdf())
    assert main(["inspect", str(pdf)]) == 0
    shown = capsys.readouterr().out
    assert "Harbours" not in shown and "Xxxxxxxx" in shown
