"""Command line: ``jibu kb check | ask | eval | unanswered | serve``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from . import __version__
from .engine import ConversationState, Engine
from .evalreport import render_ablation, render_sweep, render_text
from .evaluation import (
    EvalSetError,
    ablate,
    load_eval,
    make_engine,
    metrics,
    recommend_threshold,
    run_cases,
    sweep,
)
from .kb import KBError, KnowledgeBase, check_kb, load_kb_dir
from .unanswered import UnansweredQueue

DEFAULT_KB_DIR = "kb"


def _load_dir(path: str) -> dict[str, KnowledgeBase]:
    try:
        return load_kb_dir(path)
    except KBError as exc:
        print("Knowledge base is invalid:", file=sys.stderr)
        for p in exc.problems:
            print(f"  {p}", file=sys.stderr)
        raise SystemExit(1) from exc


def cmd_kb_check(args: argparse.Namespace) -> int:
    kbs, problems = check_kb(args.path)
    errors = [p for p in problems if p.severity == "error"]
    warnings = [p for p in problems if p.severity == "warning"]
    for p in problems:
        print(p)
    for kb in kbs:
        active = sum(1 for e in kb.entries if e.active_on(date.today()))
        print(
            f"ok  {kb.path}: {kb.organisation.name}, {len(kb.entries)} entries ({active} active today), "
            f"{len(kb.data.synonyms)} synonym groups"
        )
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def _pick_kb(args: argparse.Namespace) -> KnowledgeBase:
    kbs = _load_dir(args.kb_dir)
    org = args.org or os.environ.get("JIBU_DEFAULT_KB")
    if org:
        if org not in kbs:
            raise SystemExit(f"unknown knowledge base '{org}'. Available: {', '.join(kbs)}")
        return kbs[org]
    return next(iter(kbs.values()))


def _print_reply(
    engine: Engine, text: str, state: ConversationState, debug: bool, as_json: bool
) -> ConversationState:
    r = engine.ask(text, state)
    if as_json:
        print(
            json.dumps(
                {
                    "status": r.status,
                    "answer": r.text,
                    "language": r.language,
                    "detected": r.detected,
                    "confidence": round(r.confidence, 3),
                    "entry_id": r.entry_id,
                    "used_context": r.used_context,
                    "suggestions": [{"entry_id": i, "question": q} for i, q in r.suggestions],
                },
                ensure_ascii=False,
            )
        )
    else:
        tag = {"answered": "ANSWER", "handoff": "HANDOFF", "smalltalk": "CHAT"}[r.status]
        print(f"[{tag}] {r.text}")
        meta = f"lang={r.language} (detected {r.detected})  confidence={r.confidence:.2f}"
        if r.entry_id:
            meta += f"  entry={r.entry_id}"
        if r.used_context:
            meta += "  (used previous topic)"
        print(f"        {meta}")
        for _, q in r.suggestions:
            print(f"        - {q}")
    if debug:
        print(f"        threshold={engine.threshold:.2f}  corrections={r.corrections or '-'}")
        for c in r.candidates:
            print(
                f"        candidate {c.entry_id:26} conf={c.confidence:.2f} cov={c.coverage:.2f} "
                f"margin={c.margin:.2f} score={c.score:.2f}"
            )
    return r.state


def cmd_ask(args: argparse.Namespace) -> int:
    kb = _pick_kb(args)
    engine = Engine(kb, threshold=args.threshold)
    state = ConversationState()
    if args.question:
        for earlier in args.after or []:
            state = engine.ask(earlier, state).state
        _print_reply(engine, args.question, state, args.debug, args.json)
        return 0
    print(f"{kb.organisation.name}: type a question (empty line to quit)")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            return 0
        state = _print_reply(engine, line, state, args.debug, args.json)


def cmd_eval(args: argparse.Namespace) -> int:
    kbs = _load_dir(args.kb_dir)
    sets = [Path(args.set)] if args.set else sorted(Path("eval").glob("*.yaml"))
    if not sets:
        raise SystemExit("no evaluation sets found (looked in ./eval)")
    status = 0
    for path in sets:
        try:
            ev = load_eval(path)
        except EvalSetError as exc:
            raise SystemExit(str(exc)) from exc
        if ev.kb_id not in kbs:
            raise SystemExit(f"{path}: knowledge base '{ev.kb_id}' not found in {args.kb_dir}")
        kb = kbs[ev.kb_id]
        threshold = args.threshold
        if threshold is None:
            threshold = kb.organisation.confidence_threshold or 0.5
        engine = make_engine(kb, ev.as_of, threshold)
        outcomes = run_cases(engine, ev.cases)
        if args.json:
            print(
                json.dumps(
                    {
                        "kb": ev.kb_id,
                        "threshold": threshold,
                        "metrics": dict(metrics(outcomes)),
                    },
                    indent=2,
                    default=str,
                )
            )
            continue
        print(
            render_text(ev, kb.organisation.name, threshold, outcomes, show_failures=not args.quiet)
        )
        if args.sweep:
            ts = [round(x / 100, 2) for x in range(25, 81, 5)]
            rows = sweep(kb, ev, ts, split="dev")
            print()
            print(render_sweep(rows, threshold))
            print(
                f"\n    lowest dev threshold with no out-of-scope answer: {recommend_threshold(rows):.2f}"
            )
        if args.ablate:
            print()
            print(render_ablation(ablate(kb, ev, threshold)))
        print()
    return status


def cmd_unanswered(args: argparse.Namespace) -> int:
    path = Path(args.file) if args.file else None
    if path is None or not path.exists():
        print(
            "No unanswered log found. Set JIBU_UNANSWERED_FILE (and, to keep the redacted text,\n"
            "JIBU_STORE_UNANSWERED_TEXT=true) when running the server, or pass --file."
        )
        return 0
    q = UnansweredQueue(path=path)
    items = q.list(None if args.all else "open", args.limit)
    if not items:
        print("Nothing waiting for review.")
        return 0
    for i in items:
        text = i.text if i.text is not None else "(text not stored)"
        guess = f" closest={i.best_guess}" if i.best_guess else ""
        print(f"{i.id}  {i.ts}  {i.kb}  {i.language}  conf={i.confidence:.2f}{guess}  [{i.status}]")
        print(f"    {text}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import logging

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")

    uvicorn.run(
        "jibu.api:app_from_env", factory=True, host=args.host, port=args.port, log_level="info"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jibu", description="Answer from approved knowledge, or hand off."
    )
    p.add_argument("--version", action="version", version=f"jibu {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    kb = sub.add_parser("kb", help="knowledge base tools")
    kbsub = kb.add_subparsers(dest="kb_cmd", required=True)
    chk = kbsub.add_parser("check", help="validate knowledge base files")
    chk.add_argument("path", nargs="?", default=DEFAULT_KB_DIR, help="a .yaml file or a directory")
    chk.set_defaults(func=cmd_kb_check)

    ask = sub.add_parser("ask", help="ask one question (or chat interactively without one)")
    ask.add_argument("question", nargs="?")
    ask.add_argument("--kb-dir", default=DEFAULT_KB_DIR)
    ask.add_argument("--org", help="knowledge base id (default: first in the directory)")
    ask.add_argument("--after", action="append", help="earlier question(s) in the same session")
    ask.add_argument("--threshold", type=float)
    ask.add_argument("--debug", action="store_true", help="show candidates and scores")
    ask.add_argument("--json", action="store_true")
    ask.set_defaults(func=cmd_ask)

    ev = sub.add_parser("eval", help="run the labelled evaluation set(s)")
    ev.add_argument("--set", help="one eval file (default: every file in ./eval)")
    ev.add_argument("--kb-dir", default=DEFAULT_KB_DIR)
    ev.add_argument("--threshold", type=float)
    ev.add_argument("--sweep", action="store_true", help="threshold sweep on the dev split")
    ev.add_argument("--ablate", action="store_true", help="switch pipeline stages off one by one")
    ev.add_argument("--quiet", action="store_true", help="do not list failures")
    ev.add_argument("--json", action="store_true")
    ev.set_defaults(func=cmd_eval)

    un = sub.add_parser("unanswered", help="list questions that were handed off")
    un.add_argument("--file", default=None, help="JSONL file (default: $JIBU_UNANSWERED_FILE)")
    un.add_argument("--limit", type=int, default=50)
    un.add_argument("--all", action="store_true", help="include resolved items")
    un.set_defaults(func=cmd_unanswered)

    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "unanswered" and args.file is None:
        args.file = os.environ.get("JIBU_UNANSWERED_FILE")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
