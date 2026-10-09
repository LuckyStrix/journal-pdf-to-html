# Working notes

## The rule

No text is lost silently. `check.py` compares every letter and digit in the PDF with
the Article and with the rendered HTML, and `convert` writes nothing on a mismatch.
Anything left out on purpose (running heads) goes in `Article.dropped` and is named
in the report. Don't add a rule that discards lines without going through `dropped`.

## What the product is

`structure.py` is the core: positioned lines in, an `Article` out, with no file or PDF
access. It's pure, so it's unit-tested directly with hand-made `Line`s
(`tests/test_units.py`). `reader.py` is the only module that opens a PDF, and
`render.py` only formats.

## Things that are load-bearing

- **`reader.GUTTER_RUN`, rejoining pieces per baseline:** pdfminer splits lines at
  wide justified word spaces (Tw), not only at gutters. Without the per-page gutter
  test, Word-style PDFs came out scrambled into fake columns. Covered by
  `test_gutter_needs_a_run_of_lines_not_one_wide_word_gap` and the end-to-end tests,
  whose sample PDF is justified with Tw for exactly this reason.
- **`LAParams(all_texts=True)`:** InDesign draws running heads inside form XObjects.
  Without it they aren't read at all. Then there's nothing to report, and a wrong
  running head (one that names a different article) goes unnoticed.
- **Running head beside the page number (`BASELINE_TOLERANCE`):** heads alternate
  between even and odd pages, so in a three-page article each prints only once and
  the "repeats on two pages" rule misses them.
- **`text.join_lines` moves a page break to the start of a hyphenated word,** so
  "Mar-" / "lowe" ends up as "Marlowe" on the new page, after its page marker.
- **No PDF file name in the output** (`render.py`): internal names would be published.
- **Signature lines are "short", not "narrow":** in a two-column layout an
  affiliation line is wider than 60% of the column. It's the gap to the column's
  right edge that matters.

## Conventions

- Python 3.11 (no nested same-quote f-strings).
- PDF points, origin bottom-left: larger y is higher up the page.
- Every layout threshold is a named constant at the top of its module, in units of
  font size or line leading, with the reason next to it.
- Tests never use real articles. Extend `tests/make_pdf.py` to cover a new layout feature.

## Things that will bite you

- Real article PDFs and generated pages must never be committed. `.gitignore`
  covers them, so never `git add -f`.
- When debugging a real article, use `python -m pdf2html inspect` (masked) and share
  that, not the text.
