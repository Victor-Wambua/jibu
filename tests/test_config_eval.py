from __future__ import annotations

from pathlib import Path

import pytest

from jibu.config import ConfigError, Settings
from jibu.evaluation import (
    Case,
    EvalSetError,
    ablate,
    load_eval,
    make_engine,
    metrics,
    recommend_threshold,
    run_cases,
    sweep,
)
from jibu.kb import KnowledgeBase

ROOT = Path(__file__).resolve().parent.parent


def test_settings_defaults_are_private_and_closed() -> None:
    s = Settings.from_env({})
    assert s.store_unanswered_text is False
    assert s.admin_token is None and s.wa_app_secret is None and s.wa_send is False
    assert s.rate_limit == (30, 60.0) and s.cors_origins == ()


def test_settings_parse_environment() -> None:
    s = Settings.from_env(
        {
            "JIBU_THRESHOLD": "0.6",
            "JIBU_RATE_LIMIT": "5/10",
            "JIBU_CORS_ORIGINS": "https://a.example, https://b.example",
            "JIBU_STORE_UNANSWERED_TEXT": "true",
            "JIBU_UNANSWERED_FILE": "data/u.jsonl",
            "JIBU_WA_SEND": "1",
        }
    )
    assert s.threshold == 0.6 and s.rate_limit == (5, 10.0)
    assert s.cors_origins == ("https://a.example", "https://b.example")
    assert s.store_unanswered_text and s.unanswered_file == Path("data/u.jsonl") and s.wa_send


@pytest.mark.parametrize(
    "env",
    [
        {"JIBU_THRESHOLD": "high"},
        {"JIBU_THRESHOLD": "1.5"},
        {"JIBU_RATE_LIMIT": "fast"},
        {"JIBU_RATE_LIMIT": "0/60"},
    ],
)
def test_settings_reject_bad_values(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_eval_set_shape_and_split_rule() -> None:
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    assert len(ev.cases) >= 120
    assert sum(c.kind == "oos" for c in ev.cases) >= 20
    assert {c.kind for c in ev.cases} >= {"en", "sw", "mixed", "typo", "followup", "oos"}
    dev = [c for c in ev.cases if c.split == "dev"]
    assert 0.55 < len(dev) / len(ev.cases) < 0.65
    assert all(c.expect is None for c in ev.cases if c.kind == "oos")


def test_every_expected_entry_exists_in_the_kb(sacco_kb: KnowledgeBase) -> None:
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    ids = {e.id for e in sacco_kb.entries}
    assert {c.expect for c in ev.cases if c.in_scope} <= ids


def test_eval_questions_are_not_copies_of_kb_questions(sacco_kb: KnowledgeBase) -> None:
    """The eval set must not be answerable by string equality with the KB's own examples."""
    from jibu.text import normalise

    known = {normalise(q).strip(" ?!.") for e in sacco_kb.entries for q in e.questions.all()}
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    copies = [c.question for c in ev.cases if normalise(c.question).strip(" ?!.") in known]
    assert copies == []


@pytest.mark.parametrize(
    "body",
    [
        "kb: x\n",
        "kb: x\nas_of: 2026-01-01\ncases: [[en, a]]\n",
        "kb: x\nas_of: 2026-01-01\ncases: [[nope, a, q]]\n",
        "kb: x\nas_of: 2026-01-01\ncases: [[oos, entry, q]]\n",
        "kb: x\nas_of: 2026-01-01\ncases: [[en, a, q, earlier]]\n",
        "kb: x\nas_of: soon\ncases: [[en, a, q]]\n",
    ],
)
def test_bad_eval_files_are_rejected(tmp_path: Path, body: str) -> None:
    p = tmp_path / "e.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(EvalSetError):
        load_eval(p)


def test_metrics_on_a_tiny_set(sacco_kb: KnowledgeBase) -> None:
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    cases = [
        Case(0, "en", "office-hours", "What are your opening hours?"),
        Case(1, "oos", None, "What is the weather in Nairobi today?"),
        Case(2, "smalltalk", "@smalltalk", "hello"),
    ]
    out = run_cases(make_engine(sacco_kb, ev.as_of), cases)
    m = metrics(out)
    assert (
        m["top1_accuracy"] == 1.0 and m["handoff_recall"] == 1.0 and m["handoff_precision"] == 1.0
    )
    assert m["smalltalk_accuracy"] == 1.0


def test_sweep_is_monotone_in_answers_and_recommendation_obeys_policy(
    sacco_kb: KnowledgeBase,
) -> None:
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    rows = sweep(sacco_kb, ev, [0.3, 0.5, 0.7, 0.9], split="dev")
    tops = [m["top1_accuracy"] for _, m in rows]
    assert tops == sorted(tops, reverse=True)  # raising the bar never answers more correctly
    t = recommend_threshold(rows)
    assert dict(rows)[t]["oos_answered"] == 0


def test_ablation_covers_every_stage(sacco_kb: KnowledgeBase) -> None:
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    names = [n for n, _ in ablate(sacco_kb, ev, 0.5, split="dev")]
    assert "no stemming" in names and "no synonym expansion" in names and len(names) == 7
