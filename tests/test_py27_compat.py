"""The Remote Script runs on Live 10's embedded Python 2.7: guard against py3-only code."""

import pathlib
import re
import subprocess
import sys

SCRIPT_DIR = pathlib.Path(__file__).parent.parent / "remote_script" / "ClaudeMPC"
FILES = sorted(SCRIPT_DIR.glob("*.py"))


def test_files_exist():
    assert {f.name for f in FILES} >= {"__init__.py", "ClaudeMPC.py", "transport.py", "commands.py", "lom.py", "ops.py"}


VERMIN = str(pathlib.Path(sys.executable).parent / "vermin")


def _vermin(targets, files):
    args = [VERMIN, "--no-tips", "--violations"] + ["-t=" + t for t in targets]
    proc = subprocess.run(args + [str(f) for f in files], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_vermin_runs_on_py27():
    # everything must run on Live 10's embedded 2.7 (py2-only `unicode` is allowed)
    _vermin(["2.7-"], FILES)


def test_pure_modules_are_py2_and_py3():
    # transport.py, lom.py and ops.py are also unit-tested under py3
    _vermin(["2.7-", "3.0-"], [SCRIPT_DIR / n for n in ("transport.py", "lom.py", "ops.py")])


def test_no_threads_or_py3_idioms():
    banned = [
        (r"^\s*(import threading|from threading|import _thread|import thread\b)", "threads"),
        (r"\bf['\"]", "f-string"),
        (r"\bnonlocal\b", "nonlocal"),
        (r"\basync\s+def\b|\bawait\b", "async"),
        (r"^\s*def .*\)\s*->", "return annotation"),
        (r"print\(.*\bend=", "print end="),
    ]
    for f in FILES:
        src = f.read_text()
        for pat, what in banned:
            assert not re.search(pat, src, re.M), f"{f.name}: {what}"
