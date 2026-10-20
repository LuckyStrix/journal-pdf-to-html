"""A bare window: pick the PDFs and an output folder, press Start, watch the progress bar.

Each PDF is converted by the same `convert` command as the terminal, in a separate process,
so the window never freezes, Cancel stops cleanly, and nothing about converting differs.
Every article gets its own folder (output/<name>/<name>.html with its pictures beside it),
so two articles can never overwrite each other's figures.
"""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = Path.home() / "Journal pages"


def find_pdfs(source: Path) -> list[Path]:
    """The PDFs to convert: the file itself, or every PDF directly inside a folder."""
    if source.is_file():
        return [source] if source.suffix.lower() == ".pdf" else []
    return sorted(p for p in source.glob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def target_for(pdf: Path, out_dir: Path) -> Path:
    return out_dir / pdf.stem / (pdf.stem + ".html")


def build_command(pdf: Path, out_dir: Path, journal: str, force: bool) -> list[str]:
    cmd = [sys.executable, "-m", "pdf2html", "convert", str(pdf), "-o", str(target_for(pdf, out_dir))]
    if journal:
        cmd += ["--journal", journal]
    return cmd + (["--force"] if force else [])


@dataclass
class RunState:
    """What the window shows: which PDFs are done, which failed and why."""
    total: int = 0
    done: int = 0
    current: str = ""
    converted: list[str] = field(default_factory=list)
    failed: dict[str, list[str]] = field(default_factory=dict)  # PDF name -> the reasons
    notes: dict[str, list[str]] = field(default_factory=dict)  # PDF name -> things to check by hand
    finished: bool = False
    cancelled: bool = False

    @property
    def fraction(self) -> float:
        if self.finished and not self.cancelled:
            return 1.0
        # the PDF being converted counts as half done, so the bar moves even for a single PDF
        return min((self.done + (0.5 if self.current else 0)) / self.total, 1.0) if self.total else 0.0

    @property
    def status(self) -> str:
        if self.cancelled:
            return f"Stopped. {len(self.converted)} of {self.total} finished pages were saved."
        if self.finished:
            text = f"Finished: {len(self.converted)} of {self.total} converted."
            if self.failed:
                text += f" {len(self.failed)} could not be converted (see the list below)."
            return text
        if self.current:
            return f"Converting {self.current}  ({self.done + 1} of {self.total})"
        return "Starting…"

    def start(self, name: str) -> None:
        self.current = name

    def finish_one(self, name: str, returncode: int, output: str) -> None:
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        problems = [l.removeprefix("ERROR:").strip() for l in lines if l.startswith("ERROR:")]
        if returncode == 0:
            self.converted.append(name)
            notes = [l.removeprefix("note:").strip() for l in lines if l.startswith("note:")]
            if notes:
                self.notes[name] = notes
        else:
            self.failed[name] = problems or lines[-2:] or ["the converter stopped without a message"]
        self.done += 1
        self.current = ""

    def summary(self) -> str:
        out = []
        for name, reasons in self.failed.items():
            out += [f"NOT converted: {name}"] + [f"    {r}" for r in reasons]
        for name, notes in self.notes.items():
            out += [f"Check by hand: {name}"] + [f"    {n}" for n in notes]
        return "\n".join(out)


def _stop(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)


class App:
    """The window. Everything the buttons do is a method, so it can also be driven from code."""

    def __init__(self, root):
        import tkinter as tk
        from tkinter import scrolledtext, ttk

        self.root = root
        root.title("Journal PDF to HTML")
        root.minsize(640, 420)
        self.source, self.output = tk.StringVar(), tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.journal = tk.StringVar()
        self.status = tk.StringVar(value="Choose the article PDF (or a folder of them) and press Start.")
        self.events: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.state = RunState()
        self.cancelled = False

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text="Input PDF").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.source).grid(row=0, column=1, sticky="ew", padx=8)
        pick = ttk.Frame(frame)
        pick.grid(row=0, column=2)
        ttk.Button(pick, text="Choose PDF…", command=self.pick_file).pack(side="left")
        ttk.Button(pick, text="Choose folder…", command=self.pick_folder).pack(side="left", padx=(4, 0))
        ttk.Label(frame, text="Output folder").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.output).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Browse…", command=self.pick_output).grid(row=1, column=2, sticky="e")
        ttk.Label(frame, text="Journal name").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.journal).grid(row=2, column=1, sticky="ew", padx=8)
        ttk.Label(frame, text="(optional)").grid(row=2, column=2, sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w", pady=8)
        self.start = ttk.Button(buttons, text="Start", command=self.begin)
        self.cancel = ttk.Button(buttons, text="Cancel", command=self.stop, state="disabled")
        self.open_btn = ttk.Button(buttons, text="Open the pages folder", command=self.show_results, state="disabled")
        for b in (self.start, self.cancel, self.open_btn):
            b.pack(side="left", padx=(0, 8))

        self.bar = ttk.Progressbar(frame, maximum=100)
        self.bar.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.log = scrolledtext.ScrolledText(frame, height=12, state="disabled", font=("TkFixedFont", 9))
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=8)
        ttk.Label(frame, textvariable=self.status, wraplength=600).grid(row=6, column=0, columnspan=3, sticky="w")
        root.protocol("WM_DELETE_WINDOW", self.close)

    # --- choosing files ---
    def pick_file(self) -> None:
        from tkinter import filedialog

        if chosen := filedialog.askopenfilename(title="Article PDF", filetypes=[("PDF", "*.pdf")]):
            self.source.set(chosen)

    def pick_folder(self) -> None:
        from tkinter import filedialog

        if chosen := filedialog.askdirectory(title="Folder of article PDFs"):
            self.source.set(chosen)

    def pick_output(self) -> None:
        from tkinter import filedialog

        if chosen := filedialog.askdirectory(title="Where to save the pages", mustexist=False):
            self.output.set(chosen)

    # --- running ---
    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _problem(self, title: str, message: str) -> None:
        from tkinter import messagebox

        messagebox.showerror(title, message)

    def _replace_ok(self, existing: list[Path]) -> bool | None:
        """Ask before overwriting pages that may have been edited by hand. None = go back."""
        from tkinter import messagebox

        names = "\n".join(f"  {p.stem}" for p in existing[:8]) + ("\n  …" if len(existing) > 8 else "")
        return messagebox.askyesnocancel(
            "Pages already exist",
            f"These pages were already made:\n{names}\n\nReplace them? Any changes you made by hand will be lost.\n"
            "Yes = replace them.  No = skip them and convert only the new ones.  Cancel = go back.")

    def begin(self) -> None:
        src, out = Path(self.source.get().strip()), self.output.get().strip()
        pdfs = find_pdfs(src) if self.source.get().strip() and src.exists() else []
        if not pdfs:
            return self._problem("Input PDF", "Choose an article PDF, or a folder that contains PDFs.")
        if not out:
            return self._problem("Output folder", "Choose where to save the pages.")
        out_dir = Path(out)
        existing = [p for p in pdfs if target_for(p, out_dir).exists()]
        force = False
        if existing:
            answer = self._replace_ok(existing)
            if answer is None:
                return
            force = answer
            if not force:
                pdfs = [p for p in pdfs if p not in existing]
                if not pdfs:
                    return self._problem("Nothing to do", "Every page has already been made.")
        self.state, self.cancelled = RunState(total=len(pdfs)), False
        threading.Thread(target=self._worker, args=(pdfs, out_dir, self.journal.get().strip(), force), daemon=True).start()
        self.start.configure(state="disabled")
        self.cancel.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.bar.configure(value=0)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status.set("Starting…")
        self.root.after(100, self._poll)

    def _worker(self, pdfs: list[Path], out_dir: Path, journal: str, force: bool) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        kwargs = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
        for pdf in pdfs:
            if self.cancelled:
                break
            self.events.put(("start", pdf.name))
            self.proc = subprocess.Popen(build_command(pdf, out_dir, journal, force),
                                         cwd=PROJECT_DIR, env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, **kwargs)
            text = self.proc.communicate()[0].decode("utf-8", "replace")
            if self.cancelled:
                break
            self.events.put(("done", pdf.name, self.proc.returncode, text))
        self.events.put(("end",))

    def _poll(self) -> None:
        ended = False
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "start":
                    self.state.start(event[1])
                elif event[0] == "done":
                    self._append(event[3].rstrip())
                    self.state.finish_one(*event[1:])
                else:
                    ended = True
                    break
        except queue.Empty:
            pass
        self.bar.configure(value=100 * self.state.fraction)
        if ended:
            self.state.finished, self.state.cancelled = True, self.cancelled
            if summary := self.state.summary():
                self._append("\n" + summary)
            self.start.configure(state="normal")
            self.cancel.configure(state="disabled")
            self.open_btn.configure(state="normal")
            self.bar.configure(value=100 * self.state.fraction)
        else:
            self.root.after(100, self._poll)
        self.status.set(self.state.status)

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.cancelled = True
            _stop(self.proc)
            self.status.set("Stopping…")

    def show_results(self) -> None:
        target = Path(self.output.get()).resolve()
        target.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(target)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        self.stop()
        self.root.destroy()


def run() -> int:
    import tkinter as tk

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
