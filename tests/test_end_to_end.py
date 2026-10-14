"""The whole path, PDF file to HTML file, on the invented sample articles."""
import re
import zlib

import pytest

from pdf2html.check import compare_with_html, compare_with_pdf
from pdf2html.cli import main
from pdf2html.models import ABSTRACT, FIGURE, FOOTNOTE, HEADING, LINES, PAGE, PARAGRAPH
from pdf2html.reader import read_pdf
from pdf2html.render import render
from pdf2html.structure import build_article
from pdf2html.text import spans_text
from tests.make_pdf import TINY_JPEG, TINY_RGB, figures_pdf, sample_pdf


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


# --- an article with figures -------------------------------------------------

@pytest.fixture(scope="module")
def figures(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "figures.pdf"
    path.write_bytes(figures_pdf())
    pages, _ = read_pdf(path)
    article = build_article(pages)
    html = render(article, journal="Journal of Testing Studies")
    return path, pages, article, html


def test_figures_come_in_page_order_with_text_flowing_around_them(figures):
    _, _, article, _ = figures
    assert [k for k, _ in body_texts(article)] == [
        PAGE, HEADING, ABSTRACT, HEADING, PARAGRAPH, PARAGRAPH, FIGURE, FOOTNOTE,
        PAGE, FIGURE, PARAGRAPH, HEADING, PARAGRAPH, PARAGRAPH]
    texts = [t for _, t in body_texts(article)]
    # the columns read on past the figure: "north-" above it, "ern" below it
    assert texts[5].endswith("in the northern districts.")
    assert texts[4].endswith("neither side accepts the other’s map as final.")


def test_figure_has_its_caption_and_an_img(figures):
    _, _, article, html = figures
    figs = [b for b in article.body if b.kind == FIGURE]
    assert [b.name for b in figs] == ["figure1", "figure2"]
    assert spans_text(figs[0].rows[0]) == "Figure 1: Land disputes by district, 2010–2020"
    assert ('<p>\n    Figure 2: Claims recorded per year\n</p>\n\n'
            '<img src="figure2.jpeg" alt="Figure 2: Claims recorded per year" style="width:100%;">') in html
    assert any("figure1: write alt text" in n for n in article.notes)


def test_picture_under_its_replacement_is_left_out_and_reported(figures):
    _, pages, article, _ = figures
    assert len(pages[1].images) == 2
    assert article.dropped_images == [pages[1].images[0]]
    assert any("page 13: left out a picture 3x2 px, hidden" in n for n in article.notes)


def test_abstract_headings_superscript_and_footnote(figures):
    _, _, _, html = figures
    assert '<h4>ABSTRACT</h4>\n\n<div class="abstract">\n    This invented article' in html
    assert "field.<sup>1</sup> Elders" in html
    assert '<div class="footnote">\n    1 Field notes' in html


def test_web_address_broken_at_a_line_end_is_rejoined_and_linked(figures):
    _, _, _, html = figures
    url = "https://example.org/land-records/2021/"
    assert f'<a href="{url}">{url}</a>' in html


def test_bibliography_entries_have_hanging_indents(figures):
    _, _, article, _ = figures
    texts = [t for _, t in body_texts(article)]
    assert texts[-2] == "Lindqvist, Ana. Shared Fields: Land and Memory. Northfield: Example Academic Press, 2023."
    assert texts[-1].startswith("Vire, Tomas.")


def test_nothing_is_lost_from_an_article_with_figures(figures):
    _, pages, article, html = figures
    assert compare_with_pdf(pages, article) == []
    assert compare_with_html(html, article) == []


def test_cli_writes_the_pictures_beside_the_page(tmp_path, capsys):
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(figures_pdf())
    assert main(["convert", str(pdf)]) == 0
    assert (tmp_path / "figure2.jpeg").read_bytes() == TINY_JPEG  # written exactly as embedded
    png = (tmp_path / "figure1.png").read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and png[16:24] == (3).to_bytes(4, "big") + (2).to_bytes(4, "big")
    idat = png.index(b"IDAT")
    rows = zlib.decompress(png[idat + 4:idat + 4 + int.from_bytes(png[idat - 4:idat], "big")])
    assert rows == b"\0" + TINY_RGB[:9] + b"\0" + TINY_RGB[9:]
    # an existing picture is never overwritten without --force, and nothing is written
    (tmp_path / "article.html").unlink()
    assert main(["convert", str(pdf)]) == 1
    assert "figure1.png already exists" in capsys.readouterr().err
    assert not (tmp_path / "article.html").exists()
    assert main(["convert", str(pdf), "--image-prefix", "lindqvist-"]) == 0
    assert 'src="lindqvist-figure1.png"' in (tmp_path / "article.html").read_text(encoding="ascii")
    assert (tmp_path / "lindqvist-figure2.jpeg").exists()


def test_two_articles_in_one_run_cannot_overwrite_each_others_pictures(tmp_path, capsys):
    for name in ("a", "b"):
        (tmp_path / f"{name}.pdf").write_bytes(figures_pdf())
    out = tmp_path / "out"
    assert main(["convert", str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf"), "--out-dir", str(out), "--force"]) == 1
    assert "already written for another article" in capsys.readouterr().err
    assert (out / "a.html").exists() and not (out / "b.html").exists()
