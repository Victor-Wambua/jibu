from __future__ import annotations

from pathlib import Path

import pytest

from jibu.engine import ConversationState
from jibu.ratelimit import RateLimiter
from jibu.sessions import SessionStore
from jibu.unanswered import UnansweredQueue


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_rate_limiter_blocks_then_recovers() -> None:
    clock = Clock()
    rl = RateLimiter(3, 60, clock)
    assert [rl.check("a")[0] for _ in range(3)] == [True, True, True]
    allowed, retry = rl.check("a")
    assert not allowed and 0 < retry <= 60
    assert rl.check("b")[0]  # other keys are independent
    clock.t += 61
    assert rl.check("a")[0]


def test_rate_limiter_window_slides() -> None:
    clock = Clock()
    rl = RateLimiter(2, 10, clock)
    rl.check("a")
    clock.t += 6
    rl.check("a")
    clock.t += 5  # first hit is now 11s old, second 5s old
    assert rl.check("a")[0]
    assert not rl.check("a")[0]


def test_rate_limiter_bounds_memory_and_validates() -> None:
    rl = RateLimiter(1, 60, Clock(), max_keys=50)
    for i in range(500):
        rl.check(f"ip{i}")
    assert len(rl._hits) <= 51
    with pytest.raises(ValueError):
        RateLimiter(0, 60)


def test_sessions_expire_and_are_bounded() -> None:
    clock = Clock()
    s = SessionStore(ttl_seconds=10, max_sessions=2, clock=clock)
    s.put("a", ConversationState("x"))
    assert s.get("a").last_entry_id == "x"
    clock.t += 11
    assert s.get("a") == ConversationState()
    s.put("1", ConversationState("1"))
    s.put("2", ConversationState("2"))
    s.put("3", ConversationState("3"))
    assert len(s) == 2 and s.get("1") == ConversationState()


def test_queue_stores_no_text_by_default() -> None:
    q = UnansweredQueue()
    item = q.add("kb", "call me on 0700 000 001", "en", 0.2, "office-hours")
    assert item.text is None
    assert "0700" not in repr(q.list())


def test_queue_text_is_redacted_when_opted_in(tmp_path: Path) -> None:
    path = tmp_path / "u.jsonl"
    q = UnansweredQueue(capture_text=True, path=path)
    q.add("kb", "my number is 0700 000 001, can I get a mortgage?", "en", 0.2, None)
    assert "0700" not in path.read_text()
    assert q.list()[0].text == "my number is [phone], can I get a mortgage?"


def test_queue_resolve_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "u.jsonl"
    q = UnansweredQueue(capture_text=True, path=path)
    a = q.add("kb", "first", "en", 0.1, None)
    q.add("kb", "second", "sw", 0.3, "x")
    assert q.resolve(a.id, "added_to_kb", "new-entry", "added it") is not None
    assert q.resolve("u_nonexistent", "duplicate") is None
    with pytest.raises(ValueError):
        q.resolve(a.id, "whatever")
    reloaded = UnansweredQueue(path=path)
    assert [i.text for i in reloaded.list()] == ["second"]
    assert reloaded.list("resolved")[0].entry_id == "new-entry"


def test_queue_is_bounded() -> None:
    q = UnansweredQueue(max_items=3)
    for i in range(10):
        q.add("kb", str(i), "en", 0.0, None)
    assert len(q) == 3
