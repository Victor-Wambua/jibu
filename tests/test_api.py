from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jibu.api import create_app
from jibu.config import Settings
from jibu.kb import KnowledgeBase

ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def client(settings: Settings, kbs: dict[str, KnowledgeBase]) -> TestClient:
    return TestClient(create_app(settings, kbs))


def chat(client: TestClient, message: str, **extra: object) -> dict[str, Any]:
    r = client.post("/chat", json={"message": message, **extra})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_health_lists_knowledge_bases(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert {k["id"] for k in body["knowledge_bases"]} == {"umoja-sacco", "afya-clinic"}


def test_chat_answers_and_returns_a_session(client: TestClient) -> None:
    body = chat(client, "Mnafungua saa ngapi?")
    assert body["status"] == "answered"
    assert body["entry_id"] == "office-hours"
    assert body["language"] == "sw"
    assert body["handoff"] is None and body["unanswered_id"] is None
    assert len(body["session_id"]) >= 8
    assert body["reply_id"].startswith("r_")


def test_chat_handoff_includes_contact_and_queues_the_question(client: TestClient) -> None:
    body = chat(client, "Can I get a mortgage to buy a house?")
    assert body["status"] == "handoff"
    assert body["handoff"]["phone"] == "0700 000 001"
    assert body["unanswered_id"].startswith("u_")
    queue = client.get("/admin/unanswered", headers=ADMIN).json()
    assert queue["count"] == 1
    item = queue["items"][0]
    assert item["text"] is None  # privacy default: the words are not stored
    assert queue["stores_text"] is False


def test_unanswered_text_is_stored_redacted_only_when_enabled(
    settings: Settings, kbs: dict[str, KnowledgeBase]
) -> None:
    c = TestClient(create_app(replace(settings, store_unanswered_text=True), kbs))
    chat(c, "Can I get a mortgage? call 0700 000 001")
    item = c.get("/admin/unanswered", headers=ADMIN).json()["items"][0]
    assert item["text"] == "Can I get a mortgage? call [phone]"


def test_follow_up_uses_the_session(client: TestClient) -> None:
    first = chat(client, "How much is the membership fee?")
    second = chat(client, "and for students?", session_id=first["session_id"])
    assert second["entry_id"] == "youth-membership"
    assert second["suggestions"]
    # a different session has no such context
    other = chat(client, "how much does it cost?", session_id="another-session-id")
    assert other["used_context"] is False


def test_can_choose_the_knowledge_base(client: TestClient) -> None:
    body = chat(client, "Do you accept SHA?", kb="afya-clinic")
    assert body["kb"] == "afya-clinic" and body["entry_id"] == "insurance-accepted"
    assert client.post("/chat", json={"message": "hi", "kb": "nope-kb"}).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 501},
        {"message": "hi", "session_id": "short"},
        {"message": "hi", "session_id": "../../etc/passwd"},
        {"message": "hi", "lang": "fr"},
        {"message": "hi", "extra": 1},
        {"message": ["list"]},
    ],
)
def test_chat_validates_input(client: TestClient, payload: dict[str, Any]) -> None:
    assert client.post("/chat", json=payload).status_code == 422


def test_meta_exposes_welcome_starters_and_threshold(client: TestClient) -> None:
    m = client.get("/meta", params={"kb": "umoja-sacco"}).json()
    assert m["name"].startswith("Umoja Sacco") and m["threshold"] == 0.5
    assert len(m["starters"]["sw"]) == 4
    assert client.get("/meta", params={"kb": "zzz"}).status_code == 404


def test_feedback_is_recorded_per_entry_without_text(client: TestClient) -> None:
    body = chat(client, "Mnafungua saa ngapi?")
    assert client.post(
        "/feedback", json={"reply_id": body["reply_id"], "helpful": False}
    ).json() == {"recorded": True}
    assert (
        client.post("/feedback", json={"reply_id": "r_unknownunknown", "helpful": True}).status_code
        == 404
    )
    counts = client.get("/admin/unanswered", headers=ADMIN).json()["feedback"]
    assert counts == {"umoja-sacco:office-hours": {"up": 0, "down": 1}}


def test_admin_requires_the_token(
    client: TestClient, settings: Settings, kbs: dict[str, KnowledgeBase]
) -> None:
    assert client.get("/admin/unanswered").status_code == 401
    assert (
        client.get("/admin/unanswered", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert (
        client.get("/admin/unanswered", headers={"Authorization": "test-admin-token"}).status_code
        == 401
    )
    assert client.post("/admin/feedback", json={}).status_code == 401
    disabled = TestClient(create_app(replace(settings, admin_token=None), kbs))
    assert disabled.get("/admin/unanswered", headers=ADMIN).status_code == 503


def test_admin_can_resolve_an_unanswered_item(client: TestClient) -> None:
    uid = chat(client, "Can I get a mortgage to buy a house?")["unanswered_id"]
    r = client.post(
        "/admin/feedback",
        headers=ADMIN,
        json={"unanswered_id": uid, "resolution": "out_of_scope", "note": "not a sacco product"},
    )
    assert r.status_code == 200 and r.json()["item"]["status"] == "resolved"
    assert client.get("/admin/unanswered", headers=ADMIN).json()["count"] == 0
    assert client.get("/admin/unanswered?status=all", headers=ADMIN).json()["count"] == 1
    bad = client.post(
        "/admin/feedback",
        headers=ADMIN,
        json={"unanswered_id": "u_00000000", "resolution": "duplicate"},
    )
    assert bad.status_code == 404
    bad = client.post(
        "/admin/feedback", headers=ADMIN, json={"unanswered_id": uid, "resolution": "bogus"}
    )
    assert bad.status_code == 422


def test_rate_limit_is_per_ip_and_returns_retry_after(
    settings: Settings, kbs: dict[str, KnowledgeBase]
) -> None:
    now = [0.0]
    app = create_app(replace(settings, rate_limit=(3, 60.0)), kbs, rate_clock=lambda: now[0])
    c = TestClient(app)
    for _ in range(3):
        assert c.post("/chat", json={"message": "hello"}).status_code == 200
    blocked = c.post("/chat", json={"message": "hello"})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert c.get("/health").status_code == 200  # health is not limited
    now[0] += 61
    assert c.post("/chat", json={"message": "hello"}).status_code == 200


def test_forwarded_header_is_ignored_unless_proxy_is_trusted(
    settings: Settings, kbs: dict[str, KnowledgeBase]
) -> None:
    now = [0.0]

    def run(trust: bool) -> list[int]:
        app = create_app(
            replace(settings, rate_limit=(2, 60.0), trust_proxy=trust),
            kbs,
            rate_clock=lambda: now[0],
        )
        c = TestClient(app)
        codes = []
        for i in range(4):
            r = c.post(
                "/chat", json={"message": "hello"}, headers={"X-Forwarded-For": f"9.9.9.{i}"}
            )
            codes.append(r.status_code)
        return codes

    assert run(False) == [200, 200, 429, 429]  # spoofing the header gains nothing
    assert run(True) == [200, 200, 200, 200]  # behind a trusted proxy each client is separate


def test_widget_demo_and_security_headers(client: TestClient) -> None:
    w = client.get("/widget.js")
    assert w.status_code == 200 and "attachShadow" in w.text
    page = client.get("/")
    assert page.status_code == 200 and "Jibu" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert client.get("/demo.js").status_code == 200


def test_cors_only_for_configured_origins(
    settings: Settings, kbs: dict[str, KnowledgeBase]
) -> None:
    app = create_app(replace(settings, cors_origins=("https://umoja.example",)), kbs)
    c = TestClient(app)
    ok = c.options(
        "/chat",
        headers={"Origin": "https://umoja.example", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "https://umoja.example"
    no = c.options(
        "/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in no.headers


def test_widget_never_uses_innerhtml_or_eval() -> None:
    from jibu.api import WEB_DIR

    src = (WEB_DIR / "jibu-widget.js").read_text()
    assert ".innerHTML" not in src.replace("t.innerHTML = html", "")
    assert "eval(" not in src and "document.write" not in src
