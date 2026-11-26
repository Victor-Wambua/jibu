from __future__ import annotations

import json
from pathlib import Path

import pytest

from jibu.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_kb_check_ok_and_failing(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["kb", "check", str(ROOT / "kb")]) == 0
    out = capsys.readouterr().out
    assert "0 error(s)" in out and "umoja-sacco" in out
    bad = tmp_path / "bad.yaml"
    bad.write_text("organisation: {id: x}\n", encoding="utf-8")
    assert main(["kb", "check", str(bad)]) == 1
    assert "error" in capsys.readouterr().out


def test_ask_prints_answer_and_json(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    assert main(["ask", "Mnafungua saa ngapi?", "--org", "umoja-sacco"]) == 0
    assert "[ANSWER]" in capsys.readouterr().out
    assert main(["ask", "weather in Nairobi", "--org", "umoja-sacco", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "handoff" and data["entry_id"] is None


def test_ask_with_earlier_question_uses_context(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    main(
        [
            "ask",
            "and for students?",
            "--org",
            "umoja-sacco",
            "--after",
            "How much is the membership fee?",
            "--json",
        ]
    )
    assert json.loads(capsys.readouterr().out)["entry_id"] == "youth-membership"


def test_eval_runs_and_reports(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    assert main(["eval", "--set", "eval/umoja-sacco.yaml", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "top-1 accuracy" in out and "handoff recall" in out and "reliability" in out


def test_unanswered_without_a_log_explains_how_to_enable(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["unanswered", "--file", str(tmp_path / "none.jsonl")]) == 0
    assert "JIBU_UNANSWERED_FILE" in capsys.readouterr().out


def test_unanswered_lists_items(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from jibu.unanswered import UnansweredQueue

    path = tmp_path / "u.jsonl"
    UnansweredQueue(capture_text=True, path=path).add(
        "umoja-sacco", "Can I get a mortgage?", "en", 0.2, None
    )
    assert main(["unanswered", "--file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "mortgage" in out and "conf=0.20" in out
