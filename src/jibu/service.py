"""Glue shared by the HTTP API and the WhatsApp adapter: engines, sessions, queues."""

from __future__ import annotations

import json
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .config import Settings
from .engine import Engine, EngineConfig, Reply
from .kb import KnowledgeBase
from .sessions import SessionStore
from .unanswered import UnansweredQueue


class UnknownKB(KeyError):
    pass


@dataclass(frozen=True)
class ChatResult:
    reply_id: str
    kb: str
    reply: Reply
    unanswered_id: str | None


class JibuService:
    def __init__(
        self,
        kbs: dict[str, KnowledgeBase],
        settings: Settings,
        clock: Callable[[], date] = date.today,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if not kbs:
            raise ValueError("at least one knowledge base is required")
        self.settings = settings
        self.kbs = kbs
        self.default_kb = settings.default_kb or next(iter(kbs))
        if self.default_kb not in kbs:
            raise ValueError(f"JIBU_DEFAULT_KB '{self.default_kb}' is not a loaded knowledge base")
        self.engines = {
            kid: Engine(kb, settings.threshold, EngineConfig(), clock) for kid, kb in kbs.items()
        }
        self.sessions = SessionStore(settings.session_ttl, clock=time_fn)
        self.unanswered = UnansweredQueue(settings.store_unanswered_text, settings.unanswered_file)
        self._replies: OrderedDict[str, tuple[str, str | None]] = OrderedDict()
        self.feedback_counts: dict[str, dict[str, int]] = {}

    def engine(self, kb_id: str | None) -> Engine:
        try:
            return self.engines[kb_id or self.default_kb]
        except KeyError:
            raise UnknownKB(kb_id) from None

    def chat(
        self, message: str, session_key: str, kb_id: str | None = None, lang_hint: str | None = None
    ) -> ChatResult:
        engine = self.engine(kb_id)
        kid = engine.kb.id
        key = f"{kid}:{session_key}"
        reply = engine.ask(message, self.sessions.get(key), lang_hint)
        self.sessions.put(key, reply.state)
        unanswered_id = None
        if reply.status == "handoff":
            best = reply.candidates[0].entry_id if reply.candidates else None
            item = self.unanswered.add(kid, message, reply.language, reply.confidence, best)
            unanswered_id = item.id
        reply_id = "r_" + secrets.token_urlsafe(8)
        self._replies[reply_id] = (kid, reply.entry_id)
        while len(self._replies) > 5000:
            self._replies.popitem(last=False)
        return ChatResult(reply_id, kid, reply, unanswered_id)

    def record_feedback(self, reply_id: str, helpful: bool) -> bool:
        """Thumbs up/down on a reply. Stores only the reply's entry id and the verdict."""
        found = self._replies.get(reply_id)
        if found is None:
            return False
        kid, entry_id = found
        bucket = self.feedback_counts.setdefault(
            f"{kid}:{entry_id or 'handoff'}", {"up": 0, "down": 0}
        )
        bucket["up" if helpful else "down"] += 1
        path: Path | None = self.settings.feedback_file
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            event = {
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "kb": kid,
                "entry_id": entry_id,
                "helpful": helpful,
            }
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        return True
