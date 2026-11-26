from __future__ import annotations

import pytest

from jibu.privacy import mask_phone, pseudonym, redact


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("call me on 0700 000 001 please", "call me on [phone] please"),
        ("my number is +254700000001", "my number is [phone]"),
        ("0711-222-333 or 254 733 444 555", "[phone] or [phone]"),
        ("write to jane.doe@example.com", "write to [email]"),
        ("see https://example.com/a?b=1 now", "see [link] now"),
        ("M-Pesa code QGH7X2K9LM paid", "M-Pesa code [mpesa-code] paid"),
        ("my ID is 12345678", "my ID is [number]"),
        ("account 1234 5678 9012", "account [number]"),
    ],
)
def test_redacts_known_identifiers(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_leaves_ordinary_text_and_small_numbers_alone() -> None:
    assert (
        redact("I want to borrow 50000 over 12 months") == "I want to borrow 50000 over 12 months"
    )
    assert redact("What are your opening hours?") == "What are your opening hours?"


def test_truncates_and_collapses_whitespace() -> None:
    assert len(redact("word " * 200)) == 300
    assert redact("a \n\n  b") == "a b"


def test_pseudonym_is_stable_keyed_and_not_the_number() -> None:
    a = pseudonym("254700000001", b"k1" * 16)
    assert a == pseudonym("254700000001", b"k1" * 16)
    assert a != pseudonym("254700000001", b"k2" * 16)
    assert a != pseudonym("254700000002", b"k1" * 16)
    assert "254700000001" not in a


def test_mask_phone_keeps_last_three_digits_only() -> None:
    assert mask_phone("+254700000001") == "***001"
    assert mask_phone("12") == "***"
