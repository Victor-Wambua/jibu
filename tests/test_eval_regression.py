"""CI gate: fails if retrieval quality drops below the floors recorded here.

Floors sit a few points under the measured numbers (see README) so that harmless noise does not
break the build but a real regression does. Raise them when the engine improves; never lower them
to make a failing change pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jibu.evaluation import load_eval, make_engine, metrics, run_cases
from jibu.kb import load_kb_dir

ROOT = Path(__file__).resolve().parent.parent

FLOORS = {
    "umoja-sacco": {
        "top1": 0.65,
        "oos_recall": 0.90,
        "max_wrong": 0.09,
        "min_cases": 120,
        "min_oos": 20,
    },
    "afya-clinic": {
        "top1": 0.80,
        "oos_recall": 0.95,
        "max_wrong": 0.05,
        "min_cases": 30,
        "min_oos": 8,
    },
}


@pytest.mark.parametrize("name", sorted(FLOORS))
def test_retrieval_quality_floor(name: str) -> None:
    kbs = load_kb_dir(ROOT / "kb")
    ev = load_eval(ROOT / "eval" / f"{name}.yaml")
    m = metrics(run_cases(make_engine(kbs[ev.kb_id], ev.as_of), ev.cases))
    f = FLOORS[name]
    assert m["n"] >= f["min_cases"] and m["n_oos"] >= f["min_oos"]
    assert m["top1_accuracy"] >= f["top1"], f"top-1 {m['top1_accuracy']:.3f} fell below {f['top1']}"
    assert m["handoff_recall"] >= f["oos_recall"], "out-of-scope questions are being answered"
    assert m["wrong_answer_rate"] <= f["max_wrong"], "too many confidently wrong answers"
    assert m["smalltalk_accuracy"] == 1.0


def test_held_out_split_is_not_far_below_the_tuning_split() -> None:
    kbs = load_kb_dir(ROOT / "kb")
    ev = load_eval(ROOT / "eval" / "umoja-sacco.yaml")
    out = run_cases(make_engine(kbs[ev.kb_id], ev.as_of), ev.cases)
    dev = metrics([o for o in out if o.case.split == "dev"])
    test = metrics([o for o in out if o.case.split == "test"])
    assert test["top1_accuracy"] >= dev["top1_accuracy"] - 0.15
