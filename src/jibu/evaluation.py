"""Evaluation harness: run a labelled question set through the engine and report honestly."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from .engine import ConversationState, Engine, EngineConfig
from .kb import KnowledgeBase

SMALLTALK = "@smalltalk"
KINDS = ("en", "sw", "mixed", "typo", "followup", "smalltalk", "oos")


class EvalSetError(ValueError):
    pass


@dataclass(frozen=True)
class Case:
    index: int
    kind: str
    expect: str | None  # entry id, "@smalltalk", or None for "must hand off"
    question: str
    after: str | None = None

    @property
    def split(self) -> str:
        return "dev" if self.index % 5 in (0, 1, 2) else "test"

    @property
    def in_scope(self) -> bool:
        return self.expect not in (None, SMALLTALK)


@dataclass(frozen=True)
class EvalSet:
    kb_id: str
    as_of: date
    cases: list[Case]


@dataclass(frozen=True)
class Outcome:
    case: Case
    status: str
    entry_id: str | None
    confidence: float

    @property
    def correct(self) -> bool:
        exp = self.case.expect
        if exp is None:
            return self.status == "handoff"
        if exp == SMALLTALK:
            return self.status == "smalltalk"
        return self.status == "answered" and self.entry_id == exp

    @property
    def got(self) -> str:
        return self.entry_id or ("<smalltalk>" if self.status == "smalltalk" else "<handoff>")


def load_eval(path: str | Path) -> EvalSet:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "cases" not in raw or "kb" not in raw:
        raise EvalSetError(f"{path}: expected a mapping with 'kb' and 'cases'")
    cases: list[Case] = []
    for i, row in enumerate(raw["cases"]):
        if not isinstance(row, list) or len(row) not in (3, 4):
            raise EvalSetError(f"{path}: case #{i}: expected [kind, expected, question(, after)]")
        kind, expect, q, *rest = row
        if kind not in KINDS:
            raise EvalSetError(f"{path}: case #{i}: unknown kind {kind!r}")
        if kind == "oos" and expect is not None:
            raise EvalSetError(f"{path}: case #{i}: 'oos' cases must expect null (~)")
        if (kind == "followup") != bool(rest):
            raise EvalSetError(f"{path}: case #{i}: only follow-ups carry an earlier question")
        cases.append(Case(i, kind, expect, str(q), rest[0] if rest else None))
    as_of = raw.get("as_of")
    if not isinstance(as_of, date):
        raise EvalSetError(f"{path}: 'as_of' must be a date like 2026-06-01")
    return EvalSet(str(raw["kb"]), as_of, cases)


def make_engine(
    kb: KnowledgeBase,
    as_of: date,
    threshold: float | None = None,
    config: EngineConfig | None = None,
) -> Engine:
    return Engine(kb, threshold=threshold, config=config or EngineConfig(), clock=lambda: as_of)


def run_cases(engine: Engine, cases: list[Case]) -> list[Outcome]:
    out = []
    for c in cases:
        state = ConversationState()
        if c.after:
            state = engine.ask(c.after).state
        r = engine.ask(c.question, state)
        out.append(Outcome(c, r.status, r.entry_id, r.confidence))
    return out


def _ratio(a: int, b: int) -> float:
    return a / b if b else float("nan")


def metrics(outcomes: list[Outcome]) -> dict[str, Any]:
    in_scope = [o for o in outcomes if o.case.in_scope]
    oos = [o for o in outcomes if o.case.expect is None]
    talk = [o for o in outcomes if o.case.expect == SMALLTALK]
    answered = [o for o in outcomes if o.status == "answered"]
    tp = sum(1 for o in oos if o.status == "handoff")
    fp = sum(1 for o in in_scope if o.status == "handoff")
    fn = len(oos) - tp
    by_kind: dict[str, tuple[int, int]] = {}
    for k in KINDS:
        sub = [o for o in outcomes if o.case.kind == k]
        by_kind[k] = (sum(o.correct for o in sub), len(sub))
    return {
        "n": len(outcomes),
        "n_in_scope": len(in_scope),
        "n_oos": len(oos),
        "top1_accuracy": _ratio(sum(o.correct for o in in_scope), len(in_scope)),
        "wrong_answer_rate": _ratio(
            sum(1 for o in in_scope if o.status == "answered" and not o.correct), len(in_scope)
        ),
        "missed_rate": _ratio(fp, len(in_scope)),
        "handoff_precision": _ratio(tp, tp + fp),
        "handoff_recall": _ratio(tp, tp + fn),
        "oos_answered": fn,
        "answer_precision": _ratio(
            sum(1 for o in answered if o.correct and o.case.in_scope), len(answered)
        ),
        "smalltalk_accuracy": _ratio(sum(o.correct for o in talk), len(talk)),
        "by_kind": by_kind,
    }


def reliability(
    outcomes: list[Outcome], edges: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9, 1.01)
) -> list[tuple[float, float, int, int]]:
    """Observed accuracy of answered replies per confidence bin (smalltalk excluded)."""
    rows = []
    answered = [o for o in outcomes if o.status == "answered"]
    for lo, hi in pairwise(edges):
        sub = [o for o in answered if lo <= o.confidence < hi]
        rows.append((lo, min(hi, 1.0), len(sub), sum(o.correct for o in sub)))
    return rows


def sweep(
    kb: KnowledgeBase,
    ev: EvalSet,
    thresholds: list[float],
    split: str | None = None,
    config: EngineConfig | None = None,
) -> list[tuple[float, dict[str, Any]]]:
    cases = [c for c in ev.cases if split is None or c.split == split]
    rows = []
    for t in thresholds:
        out = run_cases(make_engine(kb, ev.as_of, t, config), cases)
        rows.append((t, metrics(out)))
    return rows


def recommend_threshold(rows: list[tuple[float, dict[str, Any]]]) -> float:
    """Lowest threshold at which no out-of-scope question in the set gets an answer.

    Policy: never answer a question the knowledge base does not cover, then keep as many
    correct answers as possible. Falls back to the highest threshold tried."""
    ok = [t for t, m in rows if m["oos_answered"] == 0]
    return min(ok) if ok else max(t for t, _ in rows)


ABLATIONS: dict[str, Callable[[EngineConfig], EngineConfig]] = {
    "full pipeline": lambda c: c,
    "no stemming": lambda c: replace(c, stemming="none"),
    "English stemmer only": lambda c: replace(c, stemming="en"),
    "no spell-correction": lambda c: replace(c, spellcheck=False),
    "no synonym expansion": lambda c: replace(c, expand_synonyms=False),
    "no follow-up context": lambda c: replace(c, carry_context=False),
    "questions only (ignore answer text)": lambda c: replace(c, answer_weight=0.0),
}


def ablate(
    kb: KnowledgeBase, ev: EvalSet, threshold: float | None, split: str | None = None
) -> list[tuple[str, dict[str, Any]]]:
    cases = [c for c in ev.cases if split is None or c.split == split]
    rows = []
    for name, tweak in ABLATIONS.items():
        eng = make_engine(kb, ev.as_of, threshold, tweak(EngineConfig()))
        rows.append((name, metrics(run_cases(eng, cases))))
    return rows


def failures(outcomes: list[Outcome]) -> list[Outcome]:
    return [o for o in outcomes if not o.correct]


def confusion(outcomes: list[Outcome]) -> dict[tuple[str, str], int]:
    """(expected, got) -> count, failures only."""
    d: dict[tuple[str, str], int] = defaultdict(int)
    for o in failures(outcomes):
        d[(o.case.expect or "<handoff>", o.got)] += 1
    return dict(d)
