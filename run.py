#!/usr/bin/env python3
"""One command: set everything up if it isn't, then open the window.

    python3 run.py          (Linux)          run.bat  (Windows: double-click or type it)

Nothing here needs administrator rights: the Python environment lives inside this folder.
Only the first run downloads anything (one small package); after that this just opens the
window. Standard library only, so any Python 3.9+ can start it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def say(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def stop(msg: str) -> None:
    sys.exit(f"\n{msg}\n")


def run(*cmd, **kw) -> int:
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, **kw).returncode


def ensure_venv() -> None:
    if PY.exists():
        return
    say("Creating the Python environment in .venv (first run only)")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    except Exception as exc:  # Debian/Ubuntu ship venv without pip unless python3-venv is installed
        shutil.rmtree(VENV, ignore_errors=True)
        stop(f"Could not create the Python environment ({exc}).\n"
             "On Debian/Ubuntu this usually means the venv package is missing: ask whoever administers\n"
             "this computer to run: sudo apt install python3-venv")


def ensure_deps() -> None:
    if run(PY, "-c", "import pdfminer", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        return
    say("Installing the PDF reader (first run only)")
    if run(PY, "-m", "pip", "install", "-r", "requirements.txt") != 0:
        stop("Installing the PDF reader failed. Check the internet connection and run this again.")


def ensure_tk() -> None:
    if run(PY, "-c", "import tkinter", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        stop("The window toolkit (tkinter) is missing from this Python.\n"
             + ("Reinstall Python from python.org and keep \"tcl/tk and IDLE\" ticked."
                if os.name == "nt" else "Ask whoever administers this computer to run: sudo apt install python3-tk"))


def main(argv: list[str]) -> int:
    if sys.version_info < (3, 9):
        stop("Python 3.9 or newer is needed (3.11 recommended).")
    ensure_venv()
    ensure_deps()
    ensure_tk()
    if "--check" in argv:
        say("Everything is installed.")
        return 0
    say("Opening the window")
    if os.name == "nt":
        return run(PY, "-m", "pdf2html", "gui")
    os.chdir(ROOT)
    os.execv(PY, [str(PY), "-m", "pdf2html", "gui"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
