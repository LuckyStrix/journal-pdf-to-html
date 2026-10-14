# journal-pdf-to-html

Turns a typeset journal article (a PDF from InDesign or similar) into an HTML page in
the journal's web template. It does the job that was being done by hand: copy the text
out of the PDF, rejoin hyphenated words, mark where each printed page starts, keep
headings, the abstract, footnotes and the signature, save each figure as an image file
with its caption, and write every special character as an HTML entity. It then
**checks that no text and no picture was lost**.

```
 article.pdf                      pdf2html                                article.html
┌─────────────┐     ┌──────────────────────────────────────────┐     ┌──────────────────────┐
│ title       │     │ read lines (pdfminer.six)                │     │ <div class="title">  │
│ author      │ ──▶ │ find title, authors, columns, footnotes, │ ──▶ │ <div class="author"> │
│ 2 columns   │     │ page numbers, running heads, signature   │     │ <p>Page 101</p> ...  │
│ footnotes   │     │ rejoin hyphens, escape, check nothing    │     │                      │
└─────────────┘     │ was lost                                 │     └──────────────────────┘
                    └──────────────────────────────────────────┘
```

| Module | What it does |
|---|---|
| `reader.py` | reads the PDF into positioned, styled lines; the only part that opens the PDF |
| `structure.py` | the layout rules: title, authors, columns, paragraphs, footnotes, signature |
| `text.py` | de-hyphenation, whitespace, HTML escaping and wrapping |
| `render.py` | writes the page in the template |
| `check.py` | compares every letter and digit in the PDF with the article and the HTML |

## Before you use it

- **Check every page against the PDF before publishing.** The converter is built for
  single-article PDFs laid out like the journal's book reviews and research articles:
  a title, an author block, an abstract, one or two text columns, headings, figures,
  footnotes, a bibliography and printed page numbers. **Tables come out as text, and a
  chart drawn as lines (not as a picture) isn't saved as an image.** Block quotes and
  lists come out as ordinary paragraphs. Fix those by hand.
- **Write alt text for every figure.** Each figure's `alt` is its caption until you
  replace it with a description of what the picture shows. The report lists each one.
- **Nothing is dropped silently.** If any letter or digit printed in the PDF is
  missing from the HTML (or appears from nowhere), or any picture is neither a figure
  in the page nor reported as left out, the converter writes nothing and says so.
  Running heads and feet ("Journal of …" beside the page number) are left out on
  purpose, and so are pictures nobody can see (an old version hidden under its
  replacement, a logo repeated in the margin). Each one is listed in the report.
- **Hyphens are a judgement call.** A hyphen at a line end is removed
  ("administra-" + "tion") unless the hyphenated word appears elsewhere in the
  article, or the next part starts with a capital or a digit ("anti-" + "European").
  Run with `--show-joins` to list every decision.
- **Read [Privacy and copyright](docs/privacy-and-copyright.md)** before working with
  real articles. In short, article PDFs and generated pages stay out of git, and the
  converter runs fully offline.

## Setup

You need Python 3.11 or newer.

**Linux**

```bash
git clone https://github.com/LuckyStrix/journal-pdf-to-html.git
cd journal-pdf-to-html
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**Windows** (PowerShell, native Python, no WSL needed)

```powershell
git clone https://github.com/LuckyStrix/journal-pdf-to-html.git
cd journal-pdf-to-html
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

The commands below use `python`. On Linux that's `.venv/bin/python`, and on Windows
it's `.venv\Scripts\python`.

## Converting an article

Put the PDF in `data/` (git ignores that folder), then run:

```bash
python -m pdf2html convert "data/Article 5.pdf" --journal "Journal of Example Studies"
```

This writes `data/Article 5.html` next to the PDF, and each figure as `figure1.jpeg`,
`figure2.png`, … beside it, and prints a report:

```
data/Article 5.pdf -> data/Article 5.html
  pages 101-103 (3), title: yes, author lines: 2, headings: 4, paragraph pieces: 13, footnote/signature blocks: 5, figures: 2
  line-end hyphens: 41 rejoined, 0 kept
  note: page 102: left out a picture 619x215 px, hidden under another picture drawn over it
  note: page 101: figure1: write alt text describing the picture (it is the caption for now)
  note: page 102: left out running head/foot "Journal of Example Studies"
  wrote figure1.jpeg
  wrote figure2.jpeg
```

Read the notes. A running head that names a different article is a typesetting
error in the PDF itself, so tell whoever made it.

Figures are named after their caption ("Figure 3: …" becomes `figure3.jpeg`; a
picture with no caption becomes `image1`, …). JPEGs are saved exactly as they are
inside the PDF; other pictures are saved as PNG. If you have the author's original,
higher-resolution files you can use those instead under the same names.

Copy the page next to the site's `styles.css` and `logo.png`, open it in a browser,
and compare it with the PDF.

| Option | Default | What it does |
|---|---|---|
| `-o FILE` | next to the PDF | where to write the page (one PDF only) |
| `--out-dir DIR` | next to each PDF | folder for the pages when converting several PDFs |
| `--journal NAME` | none | page `<title>` and the logo's alt text |
| `--logo PATH` / `--no-logo` | `logo.png` | the banner image the page shows |
| `--css PATH` | `styles.css` | the stylesheet the page links to |
| `--lang CODE` | `en` | the page's language, for screen readers |
| `--image-prefix TEXT` | none | put this before each figure's file name, so several articles can share a folder |
| `--show-joins` | off | list every line-end hyphen decision |
| `--force` | off | overwrite an existing page and its figures (otherwise it refuses) |

### When something comes out wrong

```bash
python -m pdf2html inspect "data/Article 5.pdf"
```

This shows how each line was read (position, size, bold/italic) and the structure
found from them, **with the text masked** (`Xxxxx, 9999`). You can share that output
when asking for help without sharing the article. Add `--unmasked` to see the real
text yourself.

## The parts that are not obvious

- **Page markers go at the start of each page,** as a `<p>Page 102</p>` before that
  page's text, so a screen reader announces the page before reading it. When a
  paragraph runs across a page break, it's split there, as in the hand-made pages.
  A word hyphenated across the break moves whole to the new page.
- **Footnotes stay on their page.** They come after the last text of the page they
  were printed on, under a short rule in one `<div class="footnote">`, before the next
  page marker. Note references in the text are `<sup>`, and web addresses are links.
- **Figures are taken out of the text flow.** The columns are read on around a
  figure (a word hyphenated across it is rejoined), and the figure (caption, then
  `<img>`) goes at the start of its page if it is printed above all the page's text,
  otherwise after the page's text.
- **Web addresses broken across lines are rejoined without a space.** A hyphen at the
  break is kept, unless the same address appears unbroken elsewhere in the article
  without it, or the two halves make an ordinary word ("con-" / "flicts"). Each one is
  listed by `--show-joins`.
- **Every non-ASCII character becomes an entity** (`&rsquo;`, `&mdash;`, `&oslash;`).
  The template asks for that. The hand-made pages did it for some characters and not
  others, and turned curly apostrophes into straight ones. The converter keeps the
  PDF's own characters. The page also declares `<meta charset="utf-8">`.
- **Columns are found per page, not per gap.** pdfminer splits a printed line wherever
  characters are far apart, which happens at column gutters and at wide word spaces
  in justified text. Pieces on one baseline are joined back up unless the gap is a
  gutter: white space at the same place on at least four consecutive lines.
- **Running heads are recognised two ways:** text in the top or bottom margin that
  repeats on two or more pages, or that sits on the same baseline as the page
  number. The second rule matters because heads alternate between pages (journal
  name on even pages, article title on odd ones), so a three-page article may print
  each one only once.
- **The generated page never contains the PDF's file name.** Internal names like
  "Draft_v3_final" would otherwise be published with the page.
- **Converting runs offline.** Every command switches off outbound network access
  first (`netguard.py`, the same guard as in rit-press-extractor).

## Development

```bash
python -m pytest -q
```

The tests never use a real article. `tests/make_pdf.py` builds two invented
articles as PDFs in code, laid out like the real ones: a book review (title, author
block, starred footnote, two columns, a word hyphenated across the page break, a
running foot, an italic closing statement and a signature) and a research article
(abstract, headings, superscript note references, a figure the columns flow around,
a figure drawn over an older copy of itself, a small-print footnote with a web
address broken across lines, and a bibliography). The end-to-end tests convert both.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). pdfminer.six (MIT)
is the only runtime dependency.
