from __future__ import annotations

import pytest

from jibu.lang import detect


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("How do I apply for a loan?", "en"),
        ("What are your opening hours", "en"),
        ("Mnafungua saa ngapi?", "sw"),
        ("Nataka kujua jinsi ya kujiunga", "sw"),
        ("Ninaweza kulipaje mkopo wangu?", "sw"),
        ("Nataka kujua how to apply for a loan", "mixed"),
        ("Naweza apply loan kama niko Mombasa?", "mixed"),
    ],
)
def test_detects_language(text: str, lang: str) -> None:
    assert detect(text).lang == lang


def test_no_signal_is_undetermined_not_guessed() -> None:
    r = detect("mpesa 1234")
    assert r.lang == "und"
    assert r.dominant == ""


def test_dominant_language_of_a_mixed_message() -> None:
    r = detect("nataka kujua how to apply")
    assert r.lang == "mixed"
    assert r.dominant in {"en", "sw"}


def test_kb_hints_break_ties_for_domain_words() -> None:
    assert detect("mikopo").lang == "sw"  # rare-prefix morphology cue
    assert detect("sacco loan", {"loan": "en"}).lang == "en"
    assert detect("sacco loan", {"loan": "sw"}).lang == "sw"
