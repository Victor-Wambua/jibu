from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from jibu.api import create_app
from jibu.config import Settings
from jibu.kb import KnowledgeBase
from jibu.whatsapp import (
    CloudApiSender,
    LogSender,
    SeenMessages,
    parse_payload,
    sign,
    verify_challenge,
    verify_signature,
)

SECRET = "app-secret-for-tests"
VERIFY = "verify-token-for-tests"
FAKE_NUMBER = "254700000001"


def payload(*messages: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "254700000010",
                                "phone_number_id": "1000",
                            },
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


def text(mid: str, body: str, sender: str = FAKE_NUMBER) -> dict[str, Any]:
    return {
        "from": sender,
        "id": mid,
        "timestamp": "1760000000",
        "type": "text",
        "text": {"body": body},
    }


@pytest.fixture
def wa(settings: Settings, kbs: dict[str, KnowledgeBase]) -> tuple[TestClient, LogSender]:
    s = replace(settings, wa_app_secret=SECRET, wa_verify_token=VERIFY, wa_kb="umoja-sacco")
    sender = LogSender()
    return TestClient(create_app(s, kbs, wa_sender=sender)), sender


def post(
    client: TestClient, body: dict[str, Any], secret: str = SECRET, header: str | None = None
) -> httpx.Response:
    raw = json.dumps(body).encode()
    sig = header if header is not None else sign(secret, raw)
    resp: httpx.Response = client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    return resp


# ----------------------------------------------------------------- signature
def test_signature_valid_invalid_and_malformed() -> None:
    body = b'{"a":1}'
    good = sign(SECRET, body)
    assert verify_signature(SECRET, body, good)
    assert not verify_signature(SECRET, body + b" ", good)  # tampered body
    assert not verify_signature("other-secret", body, good)
    for bad in (
        None,
        "",
        "sha256=",
        "sha1=" + good[7:],
        good[7:],
        "sha256=zz",
        "sha256=" + "0" * 64,
    ):
        assert not verify_signature(SECRET, body, bad)


def test_signature_uses_constant_time_compare() -> None:
    import inspect

    from jibu import whatsapp

    assert "hmac.compare_digest" in inspect.getsource(whatsapp.verify_signature)
    assert "hmac.compare_digest" in inspect.getsource(whatsapp.verify_challenge)


# ----------------------------------------------------------------- handshake
def test_verification_challenge(wa: tuple[TestClient, LogSender]) -> None:
    c, _ = wa
    ok = c.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"},
    )
    assert ok.status_code == 200 and ok.text == "12345"
    for params in (
        {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"},
        {"hub.mode": "subscribe", "hub.verify_token": VERIFY},
        {},
    ):
        assert c.get("/webhooks/whatsapp", params=params).status_code == 403


def test_challenge_rejected_when_no_token_is_configured() -> None:
    assert verify_challenge(None, "subscribe", "x", "1") is None
    assert verify_challenge("", "subscribe", "", "1") is None


# ------------------------------------------------------------------ delivery
def test_valid_message_is_answered_through_the_sender(wa: tuple[TestClient, LogSender]) -> None:
    c, sender = wa
    r = post(c, payload(text("wamid.1", "Mnafungua saa ngapi?")))
    assert r.status_code == 200 and r.json() == {"processed": 1, "duplicates": 0, "ignored": 0}
    ((to, body),) = sender.sent
    assert to == FAKE_NUMBER and "Jumatatu" in body


def test_invalid_signature_is_rejected_and_nothing_is_sent(
    wa: tuple[TestClient, LogSender],
) -> None:
    c, sender = wa
    assert post(c, payload(text("wamid.2", "hello")), secret="wrong").status_code == 403
    assert post(c, payload(text("wamid.2", "hello")), header="").status_code == 403
    assert c.post("/webhooks/whatsapp", content=b"{}").status_code == 403  # header missing
    assert sender.sent == []


def test_replayed_message_id_is_answered_once(wa: tuple[TestClient, LogSender]) -> None:
    c, sender = wa
    body = payload(text("wamid.3", "How do I apply for a loan?"))
    first = post(c, body)
    again = post(c, body)  # Meta retries, or an attacker replays a captured request
    assert first.json()["processed"] == 1
    assert again.status_code == 200 and again.json() == {
        "processed": 0,
        "duplicates": 1,
        "ignored": 0,
    }
    assert len(sender.sent) == 1


def test_batch_with_mixed_messages(wa: tuple[TestClient, LogSender]) -> None:
    c, sender = wa
    image = {
        "from": FAKE_NUMBER,
        "id": "wamid.img",
        "timestamp": "1",
        "type": "image",
        "image": {"id": "m1"},
    }
    r = post(
        c,
        payload(
            text("wamid.a", "Can I get a mortgage?"),
            image,
            text("wamid.b", "   "),
            text("wamid.a", "dup"),
        ),
    )
    assert r.json() == {"processed": 1, "duplicates": 1, "ignored": 2}
    assert "text messages" in sender.sent[1][1]
    assert "reliable answer" in sender.sent[0][1]  # handoff goes to the same channel


def test_status_callbacks_and_junk_payloads_are_ignored(wa: tuple[TestClient, LogSender]) -> None:
    c, sender = wa
    status = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}],
    }
    assert post(c, status).json()["processed"] == 0
    assert post(c, {"object": "page"}).json()["processed"] == 0
    assert post(c, {"object": "whatsapp_business_account", "entry": "bad"}).status_code == 200
    raw = b"not json"
    r = c.post(
        "/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": sign(SECRET, raw)}
    )
    assert r.status_code == 400
    assert sender.sent == []


def test_each_sender_gets_a_separate_pseudonymous_session(wa: tuple[TestClient, LogSender]) -> None:
    c, _ = wa
    service = c.app.state.service  # type: ignore[attr-defined]
    post(c, payload(text("m1", "How much is the membership fee?")))
    post(c, payload(text("m2", "and for students?")))
    post(c, payload(text("m3", "hello", sender="254700000002")))
    assert len(service.sessions) == 2
    assert all(FAKE_NUMBER not in k for k in service.sessions._data)


def test_webhook_is_disabled_without_an_app_secret(
    settings: Settings, kbs: dict[str, KnowledgeBase]
) -> None:
    c = TestClient(create_app(settings, kbs))
    assert (
        c.post(
            "/webhooks/whatsapp", content=b"{}", headers={"X-Hub-Signature-256": sign("", b"{}")}
        ).status_code
        == 503
    )


def test_phone_numbers_are_never_logged_in_full(
    wa: tuple[TestClient, LogSender], caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    c, _ = wa
    with caplog.at_level(logging.INFO, logger="jibu.whatsapp"):
        post(c, payload(text("wamid.log", "hello")))
    assert FAKE_NUMBER not in caplog.text and "***001" in caplog.text


# ------------------------------------------------------------------- helpers
def test_parse_payload_extracts_text_and_other_types() -> None:
    msgs = parse_payload(payload(text("a", "hi"), {"from": "1", "id": "b", "type": "audio"}))
    assert [(m.message_id, m.kind, m.text) for m in msgs] == [
        ("a", "text", "hi"),
        ("b", "audio", ""),
    ]
    assert parse_payload(None) == [] and parse_payload([]) == []


def test_seen_messages_expire_and_are_bounded() -> None:
    t = [0.0]
    seen = SeenMessages(ttl=10, max_items=3, clock=lambda: t[0])
    assert seen.add_if_new("a") and not seen.add_if_new("a")
    t[0] = 11
    assert seen.add_if_new("a")  # forgotten after the ttl
    for i in range(10):
        seen.add_if_new(f"m{i}")
    assert len(seen._seen) <= 3


def test_cloud_sender_builds_the_documented_request_shape_offline() -> None:
    """Uses httpx's in-memory MockTransport: no network. NOT a check against the live Meta API."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

    sender = CloudApiSender(
        "TEST-TOKEN", "1000", httpx.Client(transport=httpx.MockTransport(handler))
    )
    sender.send_text(FAKE_NUMBER, "hello", reply_to="wamid.in")
    (req,) = seen
    assert str(req.url) == "https://graph.facebook.com/v20.0/1000/messages"
    assert req.headers["authorization"] == "Bearer TEST-TOKEN"
    sent = json.loads(req.content)
    assert sent["messaging_product"] == "whatsapp" and sent["to"] == FAKE_NUMBER
    assert sent["text"]["body"] == "hello" and sent["context"] == {"message_id": "wamid.in"}


def test_default_sender_only_logs_unless_explicitly_enabled(
    settings: Settings, kbs: dict[str, KnowledgeBase]
) -> None:
    app = create_app(replace(settings, wa_app_secret=SECRET), kbs)
    assert isinstance(app.state.whatsapp.sender, LogSender)
    armed = create_app(replace(settings, wa_app_secret=SECRET, wa_send=True), kbs)
    assert isinstance(armed.state.whatsapp.sender, LogSender)  # no token/phone id: still safe
