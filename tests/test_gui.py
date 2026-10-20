"""The window's logic (which PDFs, what progress, what failed) and one real run of the converter it starts."""
import subprocess

from pdf2html import gui
from tests.make_pdf import figures_pdf, sample_pdf


def test_find_pdfs_takes_a_file_or_the_pdfs_in_a_folder(tmp_path):
    (tmp_path / "b.PDF").write_bytes(b"x")
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in gui.find_pdfs(tmp_path)] == ["a.pdf", "b.PDF"]
    assert gui.find_pdfs(tmp_path / "a.pdf") == [tmp_path / "a.pdf"]
    assert gui.find_pdfs(tmp_path / "notes.txt") == []


def test_each_article_gets_its_own_folder(tmp_path):
    pdf = tmp_path / "Article 5.pdf"
    assert gui.target_for(pdf, tmp_path / "out") == tmp_path / "out" / "Article 5" / "Article 5.html"


def test_progress_counts_the_pdf_being_converted_as_half_done():
    state = gui.RunState(total=2)
    assert state.fraction == 0
    state.start("a.pdf")
    assert state.fraction == 0.25
    state.finish_one("a.pdf", 0, "note: page 1: write alt text")
    assert state.fraction == 0.5 and state.notes == {"a.pdf": ["page 1: write alt text"]}
    state.start("b.pdf")
    state.finish_one("b.pdf", 1, "  ERROR: 3 letters missing\n  Nothing written.")
    state.finished = True
    assert state.fraction == 1.0
    assert state.failed == {"b.pdf": ["3 letters missing"]}
    assert "Finished: 1 of 2 converted. 1 could not be converted" in state.status
    assert "NOT converted: b.pdf" in state.summary() and "Check by hand: a.pdf" in state.summary()


def test_the_command_the_window_runs_converts_a_real_pdf(tmp_path):
    for name, data in (("one.pdf", sample_pdf()), ("two.pdf", figures_pdf())):
        (tmp_path / name).write_bytes(data)
    out = tmp_path / "out"
    for pdf in gui.find_pdfs(tmp_path):
        done = subprocess.run(gui.build_command(pdf, out, "Journal of Testing", False),
                              cwd=gui.PROJECT_DIR, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    assert (out / "one" / "one.html").is_file() and (out / "two" / "two.html").is_file()
    assert any((out / "two").glob("figure*"))


def test_window_converts_every_pdf_and_fills_the_bar(tmp_path):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        import pytest
        pytest.skip("no display")
    root.withdraw()
    (tmp_path / "one.pdf").write_bytes(sample_pdf())
    (tmp_path / "two.pdf").write_bytes(figures_pdf())
    app = gui.App(root)
    app.source.set(str(tmp_path))
    app.output.set(str(tmp_path / "out"))
    app.begin()
    for _ in range(600):
        root.update()
        if app.state.finished:
            break
        root.after(50)
        root.update()
    root.destroy()
    assert app.state.finished and len(app.state.converted) == 2
    assert app.state.fraction == 1.0
