"""WhatsApp Cloud API webhook adapter.

STATUS: written from Meta's public webhook documentation and tested only against payloads shaped
like the documented examples. It has NOT been verified against the live Meta API. The real HTTP
sender (:class:`CloudApiSender`) is never called by the test-suite; the default sender only logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import Settings
from .engine import Reply
from .privacy import mask_phone, pseudonym
from .service import JibuService

log = logging.getLogger("jibu.whatsapp")

GRAPH_URL = "https://graph.facebook.com/v20.0"
MAX_INPUT_CHARS = 500
MAX_REPLY_CHARS = 3800  # WhatsApp text bodies are limited to 4096 characters


# --------------------------------------------------------------------------- #
# Webhook verification
# --------------------------------------------------------------------------- #


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Check ``X-Hub-Signature-256: sha256=<hex>`` over the *raw* request body, in constant time."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(
        expected.encode("ascii"), header[len("sha256=") :].strip().encode("utf-8", "replace")
    )


def sign(app_secret: str, body: bytes) -> str:
    """Compute the header value Meta would send (used by tests and the local replay tool)."""
    return "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_challenge(
    verify_token: str | None, mode: str | None, token: str | None, challenge: str | None
) -> str | None:
    """GET handshake: return the challenge to echo, or None to reject."""
    if not verify_token or mode != "subscribe" or token is None or challenge is None:
        return None
    if not hmac.compare_digest(verify_token.encode("utf-8"), token.encode("utf-8")):
        return None
    return challenge


# --------------------------------------------------------------------------- #
# Payload parsing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Incoming:
    message_id: str
    sender: str
    kind: str  # "text" or the WhatsApp message type (image, audio, ...)
    text: str


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def parse_payload(payload: Any) -> list[Incoming]:
    """Extract user messages from a webhook payload; status callbacks are ignored."""
    out: list[Incoming] = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return out
    for entry in _dicts(payload.get("entry")):
        for change in _dicts(entry.get("changes")):
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            for msg in _dicts(value.get("messages")):
                mid, sender, kind = msg.get("id"), msg.get("from"), msg.get("type")
                if not (isinstance(mid, str) and isinstance(sender, str) and isinstance(kind, str)):
                    continue
                body = ""
                if kind == "text":
                    t = msg.get("text")
                    body = t.get("body", "") if isinstance(t, dict) else ""
                    if not isinstance(body, str):
                        continue
                out.append(Incoming(mid, sender, kind, body))
    return out


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #


class Sender(Protocol):
    def send_text(self, to: str, body: str, reply_to: str | None = None) -> None: ...


class LogSender:
    """Default sender: logs the reply (with the number masked) and sends nothing."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_text(self, to: str, body: str, reply_to: str | None = None) -> None:
        self.sent.append((to, body))
        log.info("would send to %s: %s", mask_phone(to), body.replace("\n", " ")[:120])


class CloudApiSender:
    """Sends via the WhatsApp Cloud API. NOT verified against the live API; never used in tests."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        client: httpx.Client | None = None,
        base_url: str = GRAPH_URL,
    ) -> None:
        self.url = f"{base_url}/{phone_number_id}/messages"
        self.headers = {"Authorization": f"Bearer {access_token}"}
        self.client = client or httpx.Client(timeout=10.0)

    def build_payload(self, to: str, body: str, reply_to: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        return payload

    def send_text(self, to: str, body: str, reply_to: str | None = None) -> None:
        resp = self.client.post(
            self.url, headers=self.headers, json=self.build_payload(to, body, reply_to)
        )
        resp.raise_for_status()


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #


class SeenMessages:
    """Remembers message ids for a while so Meta's retries are not answered twice."""

    def __init__(
        self,
        ttl: float = 3600.0,
        max_items: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl, self.max, self.clock = ttl, max_items, clock
        self._seen: OrderedDict[str, float] = OrderedDict()

    def add_if_new(self, message_id: str) -> bool:
        now = self.clock()
        while self._seen and (
            len(self._seen) >= self.max or now - next(iter(self._seen.values())) > self.ttl
        ):
            self._seen.popitem(last=False)
        if message_id in self._seen and now - self._seen[message_id] <= self.ttl:
            return False
        self._seen[message_id] = now
        return True


_NON_TEXT = "Samahani, ninasoma ujumbe wa maandishi tu. / Sorry, I can only read text messages."
_RELATED = {"en": "Related questions:", "sw": "Maswali mengine:"}


def format_reply(reply: Reply) -> str:
    text = reply.text
    if reply.suggestions and reply.status != "smalltalk":
        lines = "\n".join(f"- {q}" for _, q in reply.suggestions)
        text = f"{text}\n\n{_RELATED[reply.language]}\n{lines}"
    return text[:MAX_REPLY_CHARS]


@dataclass(frozen=True)
class WebhookResult:
    processed: int = 0
    duplicates: int = 0
    ignored: int = 0


class WhatsAppAdapter:
    def __init__(
        self,
        service: JibuService,
        settings: Settings,
        sender: Sender | None = None,
        seen: SeenMessages | None = None,
    ) -> None:
        self.service = service
        self.settings = settings
        self.sender: Sender = sender or self._default_sender(settings)
        self.seen = seen or SeenMessages()
        self.kb_id = settings.wa_kb

    @staticmethod
    def _default_sender(settings: Settings) -> Sender:
        if settings.wa_send and settings.wa_access_token and settings.wa_phone_number_id:
            return CloudApiSender(settings.wa_access_token, settings.wa_phone_number_id)
        return LogSender()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.wa_app_secret)

    def handle(self, raw_body: bytes, signature: str | None) -> tuple[int, WebhookResult | None]:
        """Returns (http_status, result). Signature is checked before the body is even parsed."""
        secret = self.settings.wa_app_secret
        if not secret:
            return 503, None
        if not verify_signature(secret, raw_body, signature):
            return 403, None
        try:
            payload = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError):
            return 400, None
        processed = duplicates = ignored = 0
        for msg in parse_payload(payload):
            if not self.seen.add_if_new(msg.message_id):
                duplicates += 1
                continue
            try:
                if msg.kind != "text":
                    self.sender.send_text(msg.sender, _NON_TEXT, msg.message_id)
                    ignored += 1
                    continue
                text = msg.text.strip()[:MAX_INPUT_CHARS]
                if not text:
                    ignored += 1
                    continue
                key = pseudonym(msg.sender, self.settings.hash_secret)
                result = self.service.chat(text, f"wa:{key}", self.kb_id)
                self.sender.send_text(msg.sender, format_reply(result.reply), msg.message_id)
                processed += 1
            except Exception:
                log.exception("failed to handle message %s", msg.message_id)
        return 200, WebhookResult(processed, duplicates, ignored)
