"""Bridge between the demo page and the real Jibu package.

Runs inside Pyodide (and natively under pytest). It adds no retrieval logic: every answer,
score, threshold decision, hand-off and evaluation number comes from the ``jibu`` package.
The only code here reads the engine's own tables to explain a reply token by token, and a test
(tests/test_demo_bridge.py) checks that this explanation adds up to the engine's own coverage.

Every public function returns a JSON string, so the page needs no Python-object proxies.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

from jibu.config import Settings
from jibu.engine import Candidate, Engine, Reply
from jibu.evalreport import KIND_LABEL, split_metrics
from jibu.evaluation import (
    EvalSet,
    Outcome,
    load_eval,
    make_engine,
    metrics,
    recommend_threshold,
    reliability,
    run_cases,
    sweep,
)
from jibu.kb import KnowledgeBase, check_kb
from jibu.service import JibuService
from jibu.text import STOP_SW_STEMS, split_words

SESSION = "demo"


class _State:
    kb_dir = Path("kb")
    eval_dir = Path("eval")
    kbs: ClassVar[dict[str, KnowledgeBase]] = {}
    evals: ClassVar[dict[str, EvalSet]] = {}
    problems: ClassVar[dict[str, list[str]]] = {}
    service: JibuService
    today: date = date(2000, 1, 1)


S = _State()


def _clock() -> date:
    return S.today


def _dump(obj: Any) -> str:
    return json.dumps(_clean(obj), ensure_ascii=False)


def _clean(obj: Any) -> Any:
    """JSON has no NaN; the evaluation reports 'n/a' ratios as NaN, so send null instead."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    return obj


# ------------------------------------------------------------------ start-up


def init(kb_dir: str = "kb", eval_dir: str = "eval") -> str:
    """Load and validate every KB with the repo's own validator, then build the service."""
    S.kb_dir, S.eval_dir = Path(kb_dir), Path(eval_dir)
    S.today = date.today()
    kbs, problems = check_kb(S.kb_dir)
    errors = [p for p in problems if p.severity == "error"]
    if errors:
        raise ValueError("\n".join(str(p) for p in errors))
    S.kbs = {kb.id: kb for kb in kbs}
    S.problems = {kb.id: [str(p) for p in kb.warnings] for kb in kbs}
    S.evals = {}
    for path in sorted(S.eval_dir.glob("*.yaml")):
        ev = load_eval(path)
        S.evals[ev.kb_id] = ev
    S.service = JibuService(S.kbs, Settings(), clock=_clock)
    return catalogue()


def catalogue() -> str:
    out = []
    for kb_id, kb in S.kbs.items():
        eng = S.service.engines[kb_id]
        ev = S.evals.get(kb_id)
        org = kb.organisation
        out.append(
            {
                "id": kb_id,
                "file": kb.path.name,
                "name": org.name,
                "description": org.description,
                "threshold": eng.threshold,
                "entries": len(kb.entries),
                "synonym_groups": len(kb.data.synonyms),
                "welcome": {"en": org.welcome.en, "sw": org.welcome.sw},
                "contact": {
                    "phone": org.contact.phone,
                    "whatsapp": org.contact.whatsapp,
                },
                "starters": {
                    "en": [list(x) for x in eng.starters("en")],
                    "sw": [list(x) for x in eng.starters("sw")],
                },
                "warnings": S.problems.get(kb_id, []),
                "eval": ({"cases": len(ev.cases), "as_of": ev.as_of.isoformat()} if ev else None),
            }
        )
    return _dump({"kbs": out, "today": S.today.isoformat()})


def set_today(iso: str) -> str:
    """Change the date the engine uses for validity windows (entries can expire)."""
    S.today = date.fromisoformat(iso)
    return _dump({"today": S.today.isoformat()})


def set_threshold(kb_id: str, value: float) -> str:
    S.service.engine(kb_id).threshold = float(value)
    return _dump({"kb": kb_id, "threshold": S.service.engine(kb_id).threshold})


def reset_session() -> str:
    S.service.sessions._data.clear()
    return _dump({"ok": True})


# ------------------------------------------------------------------ chat


def _credit(engine: Engine, key: str, entry_index: int) -> tuple[float, str, str | None]:
    """How much of a query word the winning entry explains (mirrors Engine._rank)."""
    cfg = engine.config
    q_tokens, a_tokens = engine._q_tokens[entry_index], engine._a_tokens[entry_index]
    if key in q_tokens:
        return 1.0, "question", None
    if key in a_tokens:
        return cfg.cov_answer_credit, "answer", None
    syns = engine.synonyms.get(key, ())
    for s in sorted(syns):
        if s in q_tokens:
            return cfg.cov_synonym_credit, "synonym", s
    for s in sorted(syns):
        if s in a_tokens:
            return cfg.cov_synonym_credit * cfg.cov_answer_credit, "synonym-answer", s
    return 0.0, "none", None


def explain_tokens(engine: Engine, text: str, top: Candidate | None) -> dict[str, Any]:
    """Token table for the closest entry: what matched, how, and how much it counts."""
    all_words = split_words(text)
    kept = engine.analyzer.surface(text)
    stops = [w for w in all_words if w not in kept]
    index = engine._index[top.entry_id] if top else None
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    matched = 0.0
    keys_in_order: list[str] = []
    for word in kept:
        key = engine.analyzer.stem(word)
        if key in STOP_SW_STEMS:
            stops.append(word)
            continue
        corrected: str | None = None
        if not engine._known(key) and engine.config.spellcheck:
            fixed = engine._correct(word)
            if fixed:
                corrected = fixed
                key = engine.analyzer.stem(fixed)
                if key in STOP_SW_STEMS:
                    stops.append(word)
                    continue
        keys_in_order.append(key)
        row: dict[str, Any] = {
            "word": word,
            "key": key,
            "corrected": corrected,
            "rarity": round(engine._idf(key), 3),
            "kind": "none",
            "via": None,
            "credit": 0.0,
            "repeat": key in seen,
        }
        if index is not None:
            credit, kind, via = _credit(engine, key, index)
            row.update(credit=credit, kind=kind, via=via)
        rows.append(row)
        if key not in seen:
            seen.add(key)
    unique = list(dict.fromkeys(keys_in_order))
    mass = sum(engine._idf(k) for k in unique) or 1.0
    if index is not None:
        matched = sum(engine._idf(k) * _credit(engine, k, index)[0] for k in unique)
    return {
        "tokens": rows,
        "ignored": stops,
        "coverage": matched / mass if unique and index is not None else 0.0,
    }


def _closest_question(engine: Engine, text: str, entry_id: str) -> str | None:
    """The example question that overlaps most with the typed words (Dice, as in the engine)."""
    i = engine._index[entry_id]
    keys, _ = engine._keys_for(text)
    own = frozenset(keys)
    best, best_q = -1.0, None
    for q, qk in zip(engine.entries[i].questions.all(), engine._question_keys[i], strict=True):
        if not qk or not own:
            continue
        dice = 2 * len(own & qk) / (len(own) + len(qk))
        if dice > best:
            best, best_q = dice, q
    return best_q


def _cand(engine: Engine, c: Candidate) -> dict[str, Any]:
    e = engine.kb.entry(c.entry_id)
    return {
        "id": c.entry_id,
        "question": e.questions.en[0] if e else "",
        "score": round(c.score, 3),
        "coverage": round(c.coverage, 3),
        "relative": round(c.relative_score, 3),
        "margin": round(c.margin, 3),
        "confidence": round(c.confidence, 4),
    }


def _entry_json(engine: Engine, entry_id: str) -> dict[str, Any]:
    e = engine.kb.entry(entry_id)
    assert e is not None
    return {
        "id": e.id,
        "tags": e.tags,
        "questions": {"en": e.questions.en, "sw": e.questions.sw},
        "answer": {"en": e.answer.en, "sw": e.answer.sw},
        "follow_ups": e.follow_ups,
        "valid_from": e.valid_from.isoformat() if e.valid_from else None,
        "valid_until": e.valid_until.isoformat() if e.valid_until else None,
        "active": e.active_on(S.today),
    }


def _formula(engine: Engine, top: Candidate | None) -> dict[str, float] | None:
    """The terms of confidence = coverage * (base + w_rel * relative + w_margin * margin_factor)."""
    if top is None:
        return None
    cfg = engine.config
    return {
        "coverage": round(top.coverage, 4),
        "relative": round(top.relative_score, 4),
        "margin": round(top.margin, 4),
        "margin_scale": cfg.margin_scale,
        "margin_factor": round(min(1.0, top.margin / cfg.margin_scale), 4),
        "base": cfg.conf_base,
        "w_rel": cfg.conf_rel,
        "w_margin": cfg.conf_margin,
    }


def _reason(reply: Reply, threshold: float) -> str:
    if reply.status == "smalltalk":
        return "smalltalk"
    if reply.status == "answered":
        return "answered"
    if not reply.candidates:
        return "no_overlap"
    return "below_threshold"


def ask(kb_id: str, text: str) -> str:
    """One chat turn through the real JibuService (sessions, engine, unanswered queue)."""
    engine = S.service.engine(kb_id)
    result = S.service.chat(text, SESSION, kb_id)
    reply = result.reply
    top = reply.candidates[0] if reply.candidates else None
    runner = reply.candidates[1] if len(reply.candidates) > 1 else None
    exp = explain_tokens(engine, text, top)
    out: dict[str, Any] = {
        "kb": kb_id,
        "status": reply.status,
        "text": reply.text,
        "language": reply.language,
        "detected": reply.detected,
        "confidence": round(reply.confidence, 4),
        "threshold": engine.threshold,
        "used_context": reply.used_context,
        "entry_id": reply.entry_id,
        "suggestions": [list(s) for s in reply.suggestions],
        "corrections": reply.corrections,
        "reason": _reason(reply, engine.threshold),
        "candidates": [_cand(engine, c) for c in reply.candidates],
        "gap": round(top.score - runner.score, 3) if top and runner else None,
        "runner_up": runner.entry_id if runner else None,
        "tokens": exp["tokens"],
        "ignored": exp["ignored"],
        "coverage": round(exp["coverage"], 3),
        "formula": _formula(engine, top),
        "closest_question": _closest_question(engine, text, top.entry_id) if top else None,
        "closest_entry": top.entry_id if top else None,
        "source": _entry_json(engine, reply.entry_id) if reply.entry_id else None,
        "queued": None,
        "as_of": S.today.isoformat(),
    }
    if result.unanswered_id:
        item = next(i for i in S.service.unanswered.list(None) if i.id == result.unanswered_id)
        out["queued"] = {
            "id": item.id,
            "ts": item.ts,
            "language": item.language,
            "confidence": item.confidence,
            "best_guess": item.best_guess,
        }
    return _dump(out)


def queue() -> str:
    items = S.service.unanswered.list("open")
    return _dump(
        [
            {
                "id": i.id,
                "ts": i.ts,
                "kb": i.kb,
                "language": i.language,
                "confidence": i.confidence,
                "best_guess": i.best_guess,
                "text": i.text,
            }
            for i in items
        ]
    )


# ------------------------------------------------------------------ knowledge base


def kb_detail(kb_id: str) -> str:
    kb = S.kbs[kb_id]
    engine = S.service.engine(kb_id)
    return _dump(
        {
            "id": kb_id,
            "name": kb.organisation.name,
            "threshold": engine.threshold,
            "handoff": {"en": kb.handoff_text("en"), "sw": kb.handoff_text("sw")},
            "synonyms": kb.data.synonyms,
            "warnings": S.problems.get(kb_id, []),
            "entries": [_entry_json(engine, e.id) for e in kb.entries],
            "as_of": S.today.isoformat(),
        }
    )


# ------------------------------------------------------------------ evaluation


def _outcome(o: Outcome) -> dict[str, Any]:
    c = o.case
    return {
        "n": c.index + 1,
        "kind": c.kind,
        "split": c.split,
        "question": c.question,
        "after": c.after,
        "expected": c.expect,
        "got": o.got,
        "status": o.status,
        "confidence": round(o.confidence, 3),
        "correct": o.correct,
    }


def run_eval(kb_id: str, threshold: float | None = None) -> str:
    """Run the repo's labelled set through the real engine. Date is the set's own as_of."""
    kb, ev = S.kbs[kb_id], S.evals[kb_id]
    engine = make_engine(kb, ev.as_of, threshold)
    outcomes = run_cases(engine, ev.cases)
    by_kind = {}
    for k, (ok, n) in metrics(outcomes)["by_kind"].items():
        by_kind[k] = {"label": KIND_LABEL[k], "correct": ok, "n": n}
    return _dump(
        {
            "kb": kb_id,
            "as_of": ev.as_of.isoformat(),
            "threshold": engine.threshold,
            "splits": split_metrics(outcomes),
            "by_kind": by_kind,
            "reliability": [
                {"lo": lo, "hi": hi, "n": n, "correct": ok}
                for lo, hi, n, ok in reliability(outcomes)
            ],
            "rows": [_outcome(o) for o in outcomes],
        }
    )


def run_sweep(kb_id: str, split: str | None = None) -> str:
    kb, ev = S.kbs[kb_id], S.evals[kb_id]
    split = None if split in (None, "", "all") else split
    thresholds = [round(0.30 + 0.05 * i, 2) for i in range(13)]
    rows = sweep(kb, ev, thresholds, split)
    return _dump(
        {
            "kb": kb_id,
            "split": split or "all",
            "recommended": recommend_threshold(rows),
            "rows": [
                {
                    "threshold": t,
                    "top1": m["top1_accuracy"],
                    "wrong": m["wrong_answer_rate"],
                    "missed": m["missed_rate"],
                    "precision": m["handoff_precision"],
                    "recall": m["handoff_recall"],
                    "oos_answered": m["oos_answered"],
                }
                for t, m in rows
            ],
        }
    )
