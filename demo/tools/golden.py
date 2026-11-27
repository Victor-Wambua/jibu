"""Native reference numbers for the browser test: what `jibu eval` computes, as JSON.

The demo's smoke test compares the figures shown by the page (Python under Pyodide) with these
(Python on the host), so a difference in the runtime or a stale copy of the engine fails CI.
Uses the engine directly, not the demo bridge.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jibu.evalreport import split_metrics
from jibu.evaluation import load_eval, make_engine, run_cases
from jibu.kb import load_kb_dir

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    kbs = load_kb_dir(ROOT / "kb")
    out: dict[str, object] = {}
    for path in sorted((ROOT / "eval").glob("*.yaml")):
        ev = load_eval(path)
        outcomes = run_cases(make_engine(kbs[ev.kb_id], ev.as_of), ev.cases)
        splits = split_metrics(outcomes)
        out[ev.kb_id] = {
            name: {
                k: (None if isinstance(v, float) and v != v else v)  # JSON has no NaN
                for k, v in m.items()
                if k != "by_kind"
            }
            for name, m in splits.items()
        }
        out[ev.kb_id]["wrong_rows"] = sum(1 for o in outcomes if not o.correct)  # type: ignore[index]
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "demo" / "golden.json"
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
