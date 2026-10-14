# Privacy and copyright

> **Not legal advice.** This explains how the tool is designed and the general
> legal picture (United States law) for this kind of work. For a decision about a
> particular article, ask the journal's editors or your institution's copyright staff.

## In short

- **Nothing leaves your computer.** The converter reads the PDF and writes one HTML
  file. It sends nothing anywhere, and it blocks its own network access while it runs.
- **Articles and pages never go into git.** PDFs, HTML, Word files, images and the
  `data/` folder are ignored, so a normal `git add` can't commit them.
- **Use it only for articles the journal has the right to publish online,** which is
  normally covered by the author's publication agreement.
- **It never changes the author's words.** It changes layout only: line breaks,
  hyphenation and character encoding. A built-in check refuses to write a page that
  is missing any text from the PDF.

---

## What the tool does with your files

| Step | What happens |
|---|---|
| `convert` | reads the PDF in memory and writes the `.html` you asked for, plus one image file per figure beside it. Nothing else is saved: no caches, logs or temporary copies. |
| `inspect` | prints the layout to your terminal with the text **masked** (`Xxxxx, 9999`) unless you add `--unmasked` |
| network | every command turns off outbound connections before it starts (`pdf2html/netguard.py`). If any library tried to go online, it would fail with an error. |

The report printed by `convert` quotes the running heads it left out and, with
`--show-joins`, the words it de-hyphenated. That output is for you. Don't paste it
into public issues.

### Drafts and personal information

- **Treat pre-publication PDFs as confidential.** An "edited copy" is unpublished
  work until the journal releases it. Keep it in `data/`, and don't put that folder in a
  shared or synced location unless the journal allows it.
- **Articles contain personal information.** Author names, affiliations and often an
  email address in a footnote all end up in the page. That's expected once the article
  is published, but the same care applies to drafts and generated pages before then.
- **Asking for help:** share the masked `inspect` output, not the PDF or the page.

---

## Copyright

### Who owns what

| Material | Usual owner | What that means here |
|---|---|---|
| The article's text | the author, unless they transferred copyright to the journal | the journal publishes it under the author's publication agreement |
| The typeset PDF layout | the journal (or its publisher) | the converter discards the layout and keeps only the text |
| The site's template, CSS and logo | the journal | the converter only *links* to `styles.css` and `logo.png`. It contains no copy of them. |
| This converter | its contributors, under Apache-2.0 | see [Licenses](#licenses) |

### Converting is copying

An HTML page made from an article is a new copy of it, and making and distributing
copies is one of the copyright owner's exclusive rights (17 U.S.C. § 106). So:

- **Convert articles the journal is publishing,** for the journal's own site. Author
  agreements normally grant the journal the right to publish the article in print and
  electronic form. If an agreement is print-only or unclear, ask before putting the
  article online.
- **Don't use it to republish other publishers' articles.** Being *able* to extract
  the text grants no right to post it.
- **Open-access articles** published under a Creative Commons licence (such as CC BY)
  may be shared, but the licence requires the attribution and the licence notice to
  stay with the article. Keep them in the page.

### Keeping the article whole

Changing format must not change the work. Author statements in particular carry
legal or ethical weight: AI-use disclosures, conflict-of-interest and funding
statements, corresponding-author notes, copyright lines and licence notices.

- **The converter never adds, removes or rewrites words.** Its changes are limited to
  line breaks, hyphenation at line ends, whitespace and character encoding. Figures
  are saved as the pictures embedded in the PDF (JPEGs byte for byte).
- **A completeness check runs on every conversion.** It counts every letter and digit
  printed in the PDF and requires exactly the same in the page. If anything is missing
  or added, nothing is written. The only exceptions are the running heads and feet the
  report lists. Those are navigation added by the typesetter, not part of the article.
- Footnotes and signatures are moved only within their own page, never removed.

### This repository

- **No article content is in the repository,** not in tests, examples or commit
  messages. The test suite builds an invented article in code (`tests/make_pdf.py`).
- **`.gitignore` blocks** `data/`, PDFs, HTML, Word and InDesign files, images and
  stylesheets. Never override it with `git add -f`.
- If you report a bug, include masked `inspect` output, never the article.

---

## Licenses

### This project

Licensed under the **Apache License 2.0** (`LICENSE`, `NOTICE`). You may use, modify
and run it for any purpose. If you redistribute it, keep the license and notice files
and mark the files you changed.

### Third-party components

| Component | License | Used for |
|---|---|---|
| pdfminer.six | MIT | reading the PDF (runtime) |
| charset-normalizer, cryptography (pdfminer.six dependencies) | MIT / Apache-2.0 or BSD | installed with pdfminer.six |
| pytest | MIT | running the tests (development only) |

None of these restricts using the converter commercially or as part of a service.
