import socket

import pytest

from pdf2html import netguard
from pdf2html.check import compare_with_html, compare_with_pdf
from pdf2html.cli import mask
from pdf2html.models import FIGURE, PAGE, PARAGRAPH, Article, Block, Image, Line, Page, Span
from pdf2html.reader import assemble_lines, gutters, style
from pdf2html.render import render
from pdf2html.structure import (find_caption, is_heading, page_labels, paragraphs, reading_order, split_footnotes,
                                split_signature, visible_images)
from pdf2html.text import (escape, join_lines, keep_hyphen, linked, normalize_spans, spans_html, url_continues,
                           url_hyphen, vocabulary, wrap)


def ln(text, x0, y0, x1=None, size=11.0, page=0, bold=False, italic=False):
    x1 = x0 + 5 * len(text) if x1 is None else x1
    return Line(page, x0, y0, x1, y0 + size, size, (Span(text, bold, italic),))


def spans_text(spans):
    return "".join(s.text for s in spans)


def rows(*texts):
    return [[Span(t)] for t in texts]


# --- hyphens -----------------------------------------------------------------

@pytest.mark.parametrize("left,right,vocab,keep", [
    ("admin", "istration", set(), False),
    ("well", "known", {"well-known"}, True),
    ("well", "known", {"well-known", "wellknown"}, False),
    ("anti", "European", set(), True),
    ("mid", "1990s", set(), True),
    ("ex-an", "te", set(), False),
    ("RECOMMENDA", "TIONS", set(), False),
    ("ANTI", "TRUST", {"anti-trust"}, True),
])
def test_keep_hyphen(left, right, vocab, keep):
    assert keep_hyphen(left, right, vocab) is keep


def test_vocabulary_skips_the_word_broken_at_the_line_end():
    vocab = vocabulary(["a well-known case of state-", "building"])
    assert "well-known" in vocab and "state-" not in vocab and "state" not in vocab


def test_join_lines_rejoins_and_records_each_decision():
    joins = []
    spans, _ = join_lines(rows("the admin-", "istration of a well-", "known port"), {"well-known"}, joins)
    assert "".join(s.text for s in spans) == "the administration of a well-known port"
    assert joins == [("admin-", "istration", "administration"), ("well-", "known", "well-known")]


def test_spaced_dash_at_line_end_is_not_a_hyphen():
    spans, _ = join_lines(rows("one thing -", "and another"), set())
    assert "".join(s.text for s in spans) == "one thing - and another"


def test_page_break_inside_a_hyphenated_word_moves_to_the_word_start():
    spans, offsets = join_lines(rows("is plain, Mar-", "lowe notes"), set(), breaks_before={1})
    text = "".join(s.text for s in spans)
    assert text == "is plain, Marlowe notes"
    assert text[offsets[0]:] == "Marlowe notes"


def test_page_break_between_words_starts_at_the_next_word():
    spans, offsets = join_lines(rows("two", "rooms."), set(), breaks_before={1})
    assert "".join(s.text for s in spans)[offsets[0]:] == "rooms."


@pytest.mark.parametrize("text,nxt,glued", [
    ("at https://doi.org/10.5555/", "12345678.2021.0417.", True),
    ("at https://journal.", "example.org/content/29/6/482.", True),
    ("at https://example.org/annual-", "report.", True),
    ("see https://doi.org/10.1/x.", "Eastern Sudan", False),     # the address ended with the sentence
    ("a well-", "known case", False),                           # not an address at all
])
def test_url_continues(text, nxt, glued):
    assert url_continues(text, nxt) is glued


def test_url_hyphen_follows_an_unbroken_copy_elsewhere_in_the_article():
    vocab = vocabulary(["see https://example.org/reports/harbour-conflicts-ledger/ for more"])
    assert url_hyphen("https://example.org/reports/harbour-con-", "flicts-ledger/", vocab) is False
    assert url_hyphen("https://example.org/annual-", "report.", set()) is True
    assert url_hyphen("https://www.ex-", ".org/en/", set()) is False


def test_web_address_across_lines_keeps_its_hyphen_and_gets_no_space():
    joins = []
    spans, _ = join_lines(rows("maps at https://example.org/land-", "records/2021/ and more"), set(), joins)
    assert spans_text(spans) == "maps at https://example.org/land-records/2021/ and more"
    assert joins == [("https://example.org/land-", "records/2021/", "https://example.org/land-records/2021/")]


# --- spans and HTML ----------------------------------------------------------

def test_normalize_collapses_justification_spaces():
    assert normalize_spans([Span("  rel  Lindqvist,   Anna ")]) == [Span("rel Lindqvist, Anna")]


def test_escape_writes_every_non_ascii_character_as_an_entity():
    assert escape("Harbour’s “end” — Tromsø & <x>") == \
        "Harbour&rsquo;s &ldquo;end&rdquo; &mdash; Troms&oslash; &amp; &lt;x&gt;"
    assert escape("ā") == "&#257;"


def test_spans_html_keeps_spaces_outside_tags():
    html = spans_html([Span("read "), Span("The Ledger", italic=True), Span(" now")])
    assert html == "read <i>The Ledger</i> now"


def test_superscript_and_links():
    assert spans_html([Span("field."), Span("12", sup=True), Span(" Elders")]) == "field.<sup>12</sup> Elders"
    assert linked("“https://a.org/b?c=1&d=2”.") == \
        '&ldquo;<a href="https://a.org/b?c=1&amp;d=2">https://a.org/b?c=1&amp;d=2</a>&rdquo;.'


def test_wrap_keeps_a_link_tag_on_one_line():
    html = spans_html([Span("word " * 15 + "https://example.org/a/long/address/here")])
    assert all(not l.rstrip().endswith("<a") for l in wrap(html, 60).splitlines())


def test_wrap_never_splits_tags_or_entities():
    html = spans_html([Span("word " * 30), Span("Harbour’s long title here", italic=True)])
    for line in wrap(html, 40).splitlines():
        assert line.count("<") == line.count(">")
        assert not line.rstrip().endswith("&")


# --- layout ------------------------------------------------------------------

def test_reading_order_reads_left_column_then_right():
    lines = [ln("L1", 72, 700, 290), ln("R1", 320, 700, 540), ln("L2", 72, 686, 290), ln("R2", 320, 686, 540)]
    assert [l.text for l, _, _ in reading_order(lines, 306, 72, 540)] == ["L1", "L2", "R1", "R2"]


def test_short_full_width_line_is_not_a_column():
    lines = [ln("full", 72, 700, 540), ln("short end.", 72, 686, 140), ln("next", 86, 672, 540)]
    order = reading_order(lines, 306, 72, 540)
    assert [l.text for l, _, _ in order] == ["full", "short end.", "next"]
    assert order[1][1:] == (72, 540)


def test_paragraph_starts_on_indent_and_after_a_short_line():
    stream = [(ln("a", 72, 700, 540), 72, 540), (ln("b", 72, 686, 300), 72, 540),
              (ln("c", 72, 672, 540), 72, 540), (ln("d", 86, 658, 540), 72, 540)]
    assert [[l.text for l, _, _ in p] for p in paragraphs(stream, 14)] == [["a", "b"], ["c"], ["d"]]


def test_footnote_needs_space_above_and_a_mark():
    body = [ln("text", 72, 700 - 14 * i, 540) for i in range(5)]
    note = [ln("*Name", 66, 136), ln("Corresponding Author", 72, 122)]
    top, notes = split_footnotes(body + note, 14)
    assert len(top) == 5 and [[l.text for l in n] for n in notes] == [["*Name", "Corresponding Author"]]
    unmarked = [ln("Signature", 72, 136)]
    assert split_footnotes(body + unmarked, 14)[1] == []


def test_paragraph_runs_on_across_a_figure_and_a_mid_sentence_gap():
    above, below = ln("the land", 72, 500, 290), ln("registry records.", 72, 250, 200)
    stream = [(above, 72, 294), (below, 72, 294)]
    assert len(paragraphs(stream, 14)) == 1              # "the land" stops mid-sentence
    ended, after = ln("the record.", 72, 500, 290), ln("Later on", 72, 250, 290)
    assert len(paragraphs([(ended, 72, 294), (after, 72, 294)], 14)) == 2
    assert len(paragraphs([(ended, 72, 294), (after, 72, 294)], 14, {0: [(270, 480)]})) == 1


def test_hanging_indent_under_bibliography_heading():
    stream = [(ln("BIBLIOGRAPHY", 72, 700, 160, bold=True), 72, 540),
              (ln("Doe, Jane. A Long Title That Fills", 72, 686, 540), 72, 540),
              (ln("the line.", 86, 672, 200), 72, 540),
              (ln("Roe, Rick. Short.", 72, 658, 200), 72, 540)]
    assert [[l.text for l, _, _ in p] for p in paragraphs(stream, 14)] == \
        [["BIBLIOGRAPHY"], ["Doe, Jane. A Long Title That Fills", "the line."], ["Roe, Rick. Short."]]


def test_headings_are_short_bold_or_italic_and_unpunctuated():
    assert is_heading([ln("METHODOLOGY", 72, 700, bold=True)])
    assert is_heading([ln("Conflict Theory and", 72, 700, italic=True), ln("Its Critics", 72, 686, italic=True)])
    assert not is_heading([ln("The author used AI tools.", 72, 700, italic=True)])
    assert not is_heading([ln("Plain text", 72, 700)])


def test_smaller_footnotes_need_less_space_above():
    body = [ln("text", 72, 300 - 14 * i, 540) for i in range(5)]
    note = [ln("1 A note in a smaller font", 72, 218, 540, size=9.0)]
    top, notes = split_footnotes(body + note, 14)  # 17 pt of space: less than two lines
    assert len(top) == 5 and len(notes) == 1
    same_size = [ln("1 A note in the body font", 72, 216, 540)]
    assert split_footnotes(body + same_size, 14)[1] == []


def test_footnote_numbers_must_follow_on():
    body = [ln("text", 72, 700 - 14 * i, 540) for i in range(3)]
    notes = [ln("12 Smith, Land Wars, vol.", 72, 200, 540, size=9.0), ln("2 (2019): 40-58.", 72, 190, 300, size=9.0),
             ln("13 Jones, Fields.", 72, 180, 300, size=9.0), ln("1-25, https://example.org.", 72, 170, 300, size=9.0)]
    _, found = split_footnotes(body + notes, 14)
    assert [[l.text for l in n] for n in found] == [["12 Smith, Land Wars, vol.", "2 (2019): 40-58."],
                                                    ["13 Jones, Fields.", "1-25, https://example.org."]]


# --- pictures ----------------------------------------------------------------

def img(x0, y0, x1, y1, page=0, data=b"\xff\xd8x"):
    return Image(page, x0, y0, x1, y1, (10, 10), data, "jpeg")


def test_picture_covered_by_a_later_one_is_hidden():
    old, new, beside = img(90, 556, 557, 718), img(94, 565, 557, 728), img(90, 100, 300, 200)
    seen, left_out = visible_images([Page(0, 648, 828, (), (old, new, beside))])
    assert seen == [new, beside] and left_out == [(old, "hidden under another picture drawn over it")]


def test_logo_repeated_in_the_margin_is_left_out():
    pages = [Page(i, 612, 792, (), (img(72, 740, 140, 780, page=i, data=b"logo"),)) for i in range(2)]
    seen, left_out = visible_images(pages)
    assert seen == [] and len(left_out) == 2


def test_caption_below_or_above_a_picture():
    picture = img(72, 300, 540, 480)
    lines = [ln("Figure 3: Harbour fees by decade", 72, 280, 400),
             ln("Body text that is not a caption.", 72, 250, 540)]
    caption, name = find_caption(picture, lines, 14, 540)
    assert [l.text for l in caption] == ["Figure 3: Harbour fees by decade"] and name == "figure3"
    above = [ln("Table 2. A caption that runs on and fills the", 72, 520, 540),
             ln("width of the picture", 72, 506, 200), ln("Source: Field notes", 72, 492, 200)]
    caption, name = find_caption(picture, above, 14, 540)
    assert len(caption) == 3 and name == "table2"
    assert find_caption(picture, [ln("Figure 2 shows that claims rose", 72, 280, 540)], 14, 540) == ([], "")


def test_completeness_check_catches_a_lost_picture_and_a_missing_img():
    picture = img(72, 300, 540, 480)
    pages = [Page(0, 612, 792, (), (picture,))]
    article = Article(title=[], authors=[], body=[Block(PAGE, label="1", printed=False)])
    assert any("neither in the article" in p for p in compare_with_pdf(pages, article))
    article.body.append(Block(FIGURE, [], image=picture, name="figure1"))
    assert compare_with_pdf(pages, article) == []
    html = render(article)
    assert compare_with_html(html, article) == []
    assert any("figures missing" in p for p in compare_with_html(html.replace("<img src=\"figure1", "<x "), article))


def test_signature_is_trailing_short_unpunctuated_lines():
    paras = [[(ln("Last line of text.", 320, 300, 400), 320, 542)],
             [(ln("Jane Doe", 334, 280, 380), 320, 542)],
             [(ln("University of Example, Tromsø, Norway", 334, 266, 476), 320, 542)]]
    sig = split_signature(paras)
    assert [l.text for l, _, _ in sig] == ["Jane Doe", "University of Example, Tromsø, Norway"]
    assert len(paras) == 1


def test_missing_page_numbers_are_inferred_and_noted():
    labels, notes = page_labels([None, "102", None])
    assert labels == ["101", "102", "103"] and len(notes) == 2


def test_gutter_needs_a_run_of_lines_not_one_wide_word_gap():
    # justified text: one wide gap on a single line is a word space, not a gutter
    justified = [[ln("a b c", 72, 700 - 14 * i, 300), ln("d e f", 315, 700 - 14 * i, 540)] if i == 2
                 else [ln("full line", 72, 700 - 14 * i, 540)] for i in range(6)]
    assert gutters(justified, 612) == []
    two_cols = [[ln("left", 72, 700 - 14 * i, 294), ln("right", 320, 700 - 14 * i, 540)] for i in range(6)]
    assert gutters(two_cols, 612)


def test_pieces_join_across_word_gaps_but_not_gutters():
    pieces = [ln("Harbours", 72, 700, 149), ln("keep records", 159, 700, 316), ln("of them.", 326, 700, 540)]
    assert [l.text for l in assemble_lines(pieces, 612)] == ["Harbours keep records of them."]
    cols = [p for i in range(5) for p in (ln("left", 72, 700 - 14 * i, 294), ln("right", 320, 700 - 14 * i, 540))]
    assert len(assemble_lines(cols, 612)) == 10


def test_footnote_mark_joins_its_line_without_a_space():
    joined = assemble_lines([ln("*", 66.5, 136.6, 72.0), ln("Jane Doe", 72.0, 136.4, 120.0)], 612)
    assert [l.text for l in joined] == ["*Jane Doe"]


def test_style_from_font_name():
    assert style("ABCDEF+TimesNewRomanPS-BoldItalicMT") == (True, True)
    assert style("TimesNewRomanPSMT") == (False, False)


# --- checks and privacy ------------------------------------------------------

def test_completeness_check_catches_a_dropped_paragraph():
    pages = [Page(0, 612, 792, (ln("Kept text", 72, 700), ln("The author used AI tools.", 72, 686)))]
    article = Article(title=[], authors=[], body=[Block(PAGE, label="1", printed=False),
                                                  Block(PARAGRAPH, [[Span("Kept text")]])])
    problems = compare_with_pdf(pages, article)
    assert problems and "missing" in problems[0]


def test_mask_keeps_shape_but_hides_text():
    assert mask("Marlowe, 2024") == "Xxxxxxx, 9999"


def test_netguard_blocks_outbound_connections():
    netguard.enable()
    with pytest.raises(netguard.NetworkBlocked):
        socket.create_connection(("example.org", 80))
