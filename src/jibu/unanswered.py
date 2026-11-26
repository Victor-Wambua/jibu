"""The "unanswered" queue: questions Jibu handed off, for staff to review.

Privacy defaults: with ``capture_text=False`` (the default) an item records only the time,
language, confidence and best-guess entry; the customer's words are never stored. With
``capture_text=True`` the text is stored after :func:`jibu.privacy.redact`. A JSONL file is
only written when a path is configured.
"""

from __future__ import annotations

import json
import secrets
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .privacy import redact

RESOLUTIONS = ("added_to_kb", "answered_manually", "out_of_scope", "duplicate")


@dataclass
class Unanswered:
    id: str
    ts: str
    kb: str
    language: str
    confidence: float
    best_guess: str | None
    text: str | None  # redacted, or None when text capture is off
    status: str = "open"
    resolution: str | None = None
    entry_id: str | None = None
    note: str | None = None


class UnansweredQueue:
    def __init__(
        self, capture_text: bool = False, path: Path | None = None, max_items: int = 1000
    ) -> None:
        self.capture_text = capture_text
        self.path = path
        self._items: deque[Unanswered] = deque(maxlen=max_items)
        if path and path.exists():
            self._load(path)

    def add(
        self,
        kb: str,
        text: str,
        language: str,
        confidence: float,
        best_guess: str | None,
    ) -> Unanswered:
        item = Unanswered(
            id="u_" + secrets.token_hex(4),
            ts=datetime.now(UTC).isoformat(timespec="seconds"),
            kb=kb,
            language=language,
            confidence=round(confidence, 3),
            best_guess=best_guess,
            text=redact(text) if self.capture_text else None,
        )
        self._items.append(item)
        self._append({"op": "add", **asdict(item)})
        return item

    def list(self, status: str | None = "open", limit: int = 100) -> list[Unanswered]:
        items = [i for i in reversed(self._items) if status in (None, i.status)]
        return items[:limit]

    def resolve(
        self, item_id: str, resolution: str, entry_id: str | None = None, note: str | None = None
    ) -> Unanswered | None:
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS}")
        for item in self._items:
            if item.id == item_id:
                item.status = "resolved"
                item.resolution = resolution
                item.entry_id = entry_id
                item.note = redact(note, 200) if note else None
                self._append(
                    {
                        "op": "resolve",
                        "id": item_id,
                        "resolution": resolution,
                        "entry_id": entry_id,
                        "note": item.note,
                    }
                )
                return item
        return None

    def __len__(self) -> int:
        return len(self._items)

    # -- persistence (append-only JSONL of events) --------------------------------
    def _append(self, event: dict[str, Any]) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _load(self, path: Path) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("op") == "add":
                fields = {k: v for k, v in ev.items() if k != "op"}
                self._items.append(Unanswered(**fields))
            elif ev.get("op") == "resolve":
                for item in self._items:
                    if item.id == ev.get("id"):
                        item.status = "resolved"
                        item.resolution = ev.get("resolution")
                        item.entry_id = ev.get("entry_id")
                        item.note = ev.get("note")
