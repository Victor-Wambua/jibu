"""The browser demo's Python bridge (demo/py/jibu_demo.py) must add no logic of its own.

It only reads the engine's tables to explain a reply. These tests check that the explanation
adds up to the engine's own numbers on every labelled question, and that its evaluation output
equals a direct run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from jibu.evaluation import load_eval, make_engine, metrics, run_cases
from jibu.kb import load_kb_dir

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bridge() -> Any:
    spec = importlib.util.spec_from_file_location(
        "jibu_demo", ROOT / "demo" / "py" / "jibu_demo.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jibu_demo"] = mod
    spec.loader.exec_module(mod)
    mod.init(str(ROOT / "kb"), str(ROOT / "eval"))
    mod.set_today("2026-06-01")
    return mod


@pytest.mark.parametrize("kb_id", ["umoja-sacco", "afya-clinic"])
def test_token_explanation_adds_up_to_the_engine_coverage(bridge: Any, kb_id: str) -> None:
    ev = load_eval(ROOT / "eval" / f"{kb_id}.yaml")
    checked = 0
    for case in ev.cases:
        bridge.reset_session()
        if case.after:
            bridge.ask(kb_id, case.after)
        reply = json.loads(bridge.ask(kb_id, case.question))
        if reply["status"] == "smalltalk" or not reply["candidates"]:
            continue
        assert reply["coverage"] == pytest.approx(reply["candidates"][0]["coverage"], abs=1e-3), (
            case.question
        )
        f = reply["formula"]
        rebuilt = f["coverage"] * (
            f["base"] + f["w_rel"] * f["relative"] + f["w_margin"] * f["margin_factor"]
        )
        assert rebuilt == pytest.approx(reply["confidence"], abs=2e-3), case.question
        checked += 1
    assert checked > 20


def test_bridge_status_matches_the_engine(bridge: Any) -> None:
    kbs = load_kb_dir(ROOT / "kb")
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    engine = make_engine(kbs["umoja-sacco"], ev.as_of)
    for case in [c for c in ev.cases if not c.after][:80]:
        bridge.reset_session()
        got = json.loads(bridge.ask("umoja-sacco", case.question))
        want = engine.ask(case.question)
        assert (got["status"], got["entry_id"]) == (want.status, want.entry_id), case.question


@pytest.mark.parametrize("kb_id", ["umoja-sacco", "afya-clinic"])
def test_eval_output_equals_a_direct_run(bridge: Any, kb_id: str) -> None:
    kbs = load_kb_dir(ROOT / "kb")
    ev = load_eval(ROOT / "eval" / f"{kb_id}.yaml")
    direct = metrics(run_cases(make_engine(kbs[kb_id], ev.as_of), ev.cases))
    shown = json.loads(bridge.run_eval(kb_id))["splits"]["all"]
    for key in ("top1_accuracy", "wrong_answer_rate", "handoff_precision", "handoff_recall"):
        assert shown[key] == pytest.approx(direct[key])
    assert shown["oos_answered"] == direct["oos_answered"]


def test_handoff_queue_keeps_no_message_text(bridge: Any) -> None:
    bridge.reset_session()
    bridge.ask("umoja-sacco", "Give me a recipe for pilau")
    items = json.loads(bridge.queue())
    assert items
    assert all(i["text"] is None for i in items)
    assert "pilau" not in json.dumps(items)
