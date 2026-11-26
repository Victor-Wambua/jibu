"""Redaction for anything that might be written to disk or shown to staff.

By default Jibu stores no message text at all. If an organisation opts in to keeping the
"unanswered" questions so staff can improve the knowledge base, text is passed through
``redact`` first. This is pattern-based and best-effort: it removes the identifiers we know to
expect in Kenyan WhatsApp traffic, not every possible piece of personal data (names, free-text
addresses and health details are NOT detected).
"""

from __future__ import annotations

import hashlib
import hmac
import re

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"https?://\S+|www\.\S+"), "[link]"),
    # M-Pesa transaction codes: 10 upper-case letters/digits containing both (e.g. QGH7X2K9LM)
    (
        re.compile(r"\b(?=[A-Z0-9]{10}\b)(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{10}\b"),
        "[mpesa-code]",
    ),
    # Kenyan phone numbers: +254 7xx xxx xxx, 07xx xxx xxx, 01xx ..., with spaces/dashes/dots
    (
        re.compile(r"(?<!\d)(?:\+?254|0)[\s\-.]?[17]\d{2}[\s\-.]?\d{3}[\s\-.]?\d{3}(?!\d)"),
        "[phone]",
    ),
    # Long digit runs: national ID (7-8 digits), account / loan numbers, cards
    (re.compile(r"(?<!\d)\d(?:[\s\-]?\d){6,}(?!\d)"), "[number]"),
)


def redact(text: str, max_len: int = 300) -> str:
    """Mask phone numbers, e-mails, links, M-Pesa codes and long digit runs; truncate."""
    out = text.strip()
    for pattern, repl in _RULES:
        out = pattern.sub(repl, out)
    out = re.sub(r"\s+", " ", out)
    return out[:max_len]


def pseudonym(value: str, secret: bytes, length: int = 16) -> str:
    """Stable, non-reversible id for a sender (e.g. a WhatsApp number) using HMAC-SHA256."""
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()[:length]


def mask_phone(value: str) -> str:
    """For logs: keep only the last 3 digits."""
    digits = re.sub(r"\D", "", value)
    return f"***{digits[-3:]}" if len(digits) > 3 else "***"
