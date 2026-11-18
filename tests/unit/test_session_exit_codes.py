"""The session exit codes are frozen: same constants in lume-ui and lume-run, and in FRONTEND.md."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ui_codes():
    text = (ROOT / "lume/lume-ui/src/app.rs").read_text()
    body = re.search(r"pub enum Exit \{(.*?)\n\}", text, re.S).group(1)
    return {m[0]: int(m[1]) for m in re.findall(r"^\s*(\w+) = (\d+),", body, re.M)}


def _run_codes():
    text = (ROOT / "lume/lume-run/src/main.rs").read_text()
    return {m[0]: int(m[1]) for m in re.findall(r"const (EXIT_\w+): i32 = (\d+);", text)}


def test_ui_codes():
    assert _ui_codes() == {"Shutdown": 0, "Launch": 64, "RetroArch": 65, "Restart": 66}


def test_run_codes():
    assert _run_codes() == {"EXIT_LAUNCH": 64, "EXIT_MENU": 65, "EXIT_RESTART": 66}


def test_both_crates_agree():
    ui, run = _ui_codes(), _run_codes()
    assert ui["Launch"] == run["EXIT_LAUNCH"]
    assert ui["RetroArch"] == run["EXIT_MENU"]
    assert ui["Restart"] == run["EXIT_RESTART"]


def test_frontend_doc_documents_the_contract():
    doc = (ROOT / "docs/FRONTEND.md").read_text()
    assert re.search(r"^\| 0 \(Desligar\) \|", doc, re.M)
    assert re.search(r"^\| 66 \(Reiniciar\) \|", doc, re.M)
    assert re.search(r"^\| outro \|", doc, re.M)
    assert "**0** para desligar, **66** para" in doc
