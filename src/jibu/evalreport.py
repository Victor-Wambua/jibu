"""Text and Markdown rendering of evaluation results."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .evaluation import KINDS, EvalSet, Outcome, failures, metrics, reliability

KIND_LABEL = {
    "en": "English",
    "sw": "Swahili",
    "mixed": "Mixed / Sheng",
    "typo": "Typos",
    "followup": "Follow-ups",
    "smalltalk": "Greetings",
    "oos": "Out of scope",
}


def _pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.1f}%"


def split_metrics(outcomes: list[Outcome]) -> dict[str, dict[str, Any]]:
    return {
        "dev": metrics([o for o in outcomes if o.case.split == "dev"]),
        "test": metrics([o for o in outcomes if o.case.split == "test"]),
        "all": metrics(outcomes),
    }


def render_text(
    ev: EvalSet, kb_name: str, threshold: float, outcomes: list[Outcome], show_failures: bool = True
) -> str:
    sm = split_metrics(outcomes)
    lines = [
        f"Jibu evaluation: {kb_name}",
        f"  cases: {len(outcomes)}   as of: {ev.as_of}   confidence threshold: {threshold:.2f}",
        "",
        f"  {'':28}{'dev':>9}{'test':>9}{'all':>9}",
    ]
    rows: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("cases", lambda m: str(m["n"])),
        ("  in scope / out of scope", lambda m: f"{m['n_in_scope']}/{m['n_oos']}"),
        ("top-1 accuracy (in scope)", lambda m: _pct(m["top1_accuracy"])),
        ("wrong answer rate (in scope)", lambda m: _pct(m["wrong_answer_rate"])),
        ("handed off though answerable", lambda m: _pct(m["missed_rate"])),
        ("handoff precision", lambda m: _pct(m["handoff_precision"])),
        ("handoff recall", lambda m: _pct(m["handoff_recall"])),
        ("out-of-scope answered (count)", lambda m: str(m["oos_answered"])),
    ]
    for label, fn in rows:
        lines.append(f"  {label:28}" + "".join(f"{fn(sm[k]):>9}" for k in ("dev", "test", "all")))
    lines += ["", "  accuracy by kind (all cases):"]
    for k in KINDS:
        ok, n = sm["all"]["by_kind"][k]
        lines.append(f"    {KIND_LABEL[k]:14} {ok:>3}/{n:<3} {_pct(ok / n if n else float('nan'))}")
    lines += ["", "  reliability of answered replies (all cases):", "    confidence    n  correct"]
    for lo, hi, n, ok in reliability(outcomes):
        if n:
            lines.append(f"    {lo:.1f}-{hi:.1f}   {n:>4}  {_pct(ok / n)}")
    bad = failures(outcomes)
    if show_failures and bad:
        lines += ["", f"  failures ({len(bad)}):"]
        for o in bad:
            c = o.case
            prefix = f"[{c.split}/{c.kind}]"
            ctx = f'  (after "{c.after}")' if c.after else ""
            lines.append(
                f'    {prefix:14} "{c.question}"{ctx}\n'
                f"                   expected {c.expect or '<handoff>'}, got {o.got} (conf {o.confidence:.2f})"
            )
    return "\n".join(lines)


def render_sweep(rows: list[tuple[float, dict[str, Any]]], chosen: float) -> str:
    out = [
        "  threshold sweep (dev split):",
        "    thr   top-1   wrong  handoff-prec  handoff-recall  oos-answered",
    ]
    for t, m in rows:
        mark = "  <- chosen" if abs(t - chosen) < 1e-9 else ""
        out.append(
            f"    {t:.2f}  {_pct(m['top1_accuracy']):>6} {_pct(m['wrong_answer_rate']):>6}"
            f"  {_pct(m['handoff_precision']):>11}  {_pct(m['handoff_recall']):>13}  {m['oos_answered']:>11}{mark}"
        )
    return "\n".join(out)


def render_ablation(rows: list[tuple[str, dict[str, Any]]]) -> str:
    out = [
        "  ablation (all cases, same threshold):",
        f"    {'variant':38}{'top-1':>8}{'wrong':>8}{'oos answered':>14}",
    ]
    for name, m in rows:
        out.append(
            f"    {name:38}{_pct(m['top1_accuracy']):>8}{_pct(m['wrong_answer_rate']):>8}{m['oos_answered']:>14}"
        )
    return "\n".join(out)
