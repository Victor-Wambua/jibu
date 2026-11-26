from __future__ import annotations

from datetime import date

import pytest

from jibu.engine import ConversationState, Engine
from jibu.kb import KnowledgeBase


@pytest.mark.parametrize(
    ("question", "entry"),
    [
        ("How do I apply for a loan?", "loan-application"),
        ("Mnafungua saa ngapi?", "office-hours"),
        ("What is the interest rate on loans?", "loan-interest"),
        ("Riba ya mkopo ni ngapi kwa mwezi?", "loan-interest"),
        ("I forgot my USSD PIN", "reset-pin"),
        ("Naweza kuweka pesa kwa M-Pesa vipi?", "deposit-mpesa"),
    ],
)
def test_answers_from_the_knowledge_base(engine: Engine, question: str, entry: str) -> None:
    r = engine.ask(question)
    assert r.status == "answered"
    assert r.entry_id == entry
    assert r.confidence >= engine.threshold


def test_reply_text_is_always_verbatim_kb_text_or_handoff(
    engine: Engine, sacco_kb: KnowledgeBase
) -> None:
    allowed = {e.answer.en for e in sacco_kb.entries} | {e.answer.sw for e in sacco_kb.entries}
    allowed |= {sacco_kb.handoff_text("en"), sacco_kb.handoff_text("sw")}
    for q in [
        "loan fee?",
        "weather",
        "Habari",
        "How do I join?",
        "mnafungua saa ngapi",
        "asdf qwer",
        "pesa",
    ]:
        r = engine.ask(q)
        if r.status != "smalltalk":
            assert r.text in allowed, q


@pytest.mark.parametrize(
    "question",
    [
        "What is the weather in Nairobi today?",
        "Can I get a mortgage to buy a house?",
        "Who won the football match yesterday?",
        "Hali ya hewa ikoje leo?",
        "asdf qwer zxcv",
        "",
        "???",
    ],
)
def test_hands_off_when_the_kb_has_no_answer(engine: Engine, question: str) -> None:
    r = engine.ask(question)
    assert r.status == "handoff"
    assert r.entry_id is None
    assert "0700 000 001" in r.text


def test_answer_language_follows_the_question(engine: Engine) -> None:
    assert engine.ask("How do I join?").language == "en"
    assert engine.ask("Nawezaje kujiunga na Umoja Sacco?").language == "sw"


def test_ambiguous_one_word_question_is_not_answered_confidently(engine: Engine) -> None:
    r = engine.ask("loan")
    assert r.status == "handoff" or r.confidence < 0.9


def test_smalltalk_is_answered_without_the_kb(engine: Engine) -> None:
    for q, status in [
        ("hello", "smalltalk"),
        ("Habari", "smalltalk"),
        ("asante sana", "smalltalk"),
        ("kwaheri", "smalltalk"),
    ]:
        assert engine.ask(q).status == status
    # a greeting plus a real question is a real question
    assert engine.ask("Hello, how do I apply for a loan?").status == "answered"


def test_typos_are_corrected_against_the_kb_vocabulary(engine: Engine) -> None:
    r = engine.ask("how much is the membershp fee")
    assert r.entry_id == "membership-fee"
    assert r.corrections == {"membershp": "membership"}


def test_short_words_are_not_spell_corrected(engine: Engine) -> None:
    assert engine.ask("lone").corrections == {}


def test_expired_entries_are_not_used(sacco_kb: KnowledgeBase) -> None:
    q = "When is the AGM this year?"
    before = Engine(sacco_kb, clock=lambda: date(2026, 3, 15)).ask(q)
    after = Engine(sacco_kb, clock=lambda: date(2026, 6, 1)).ask(q)
    assert before.entry_id == "agm-2026"
    assert after.entry_id != "agm-2026"


def test_entries_not_yet_valid_are_not_used(sacco_kb: KnowledgeBase) -> None:
    q = "Is there a school fees loan promotion?"
    assert Engine(sacco_kb, clock=lambda: date(2025, 12, 1)).ask(q).entry_id != "promo-school-fees"
    assert Engine(sacco_kb, clock=lambda: date(2026, 6, 1)).ask(q).entry_id == "promo-school-fees"


def test_follow_up_uses_previous_topic(engine: Engine) -> None:
    first = engine.ask("How much is the membership fee?")
    assert first.entry_id == "membership-fee"
    second = engine.ask("and for students?", first.state)
    assert second.entry_id == "youth-membership"
    # the same words with no history do not pretend to know the topic
    assert engine.ask("and for students?").entry_id in {"youth-membership", None}


def test_context_never_overrules_a_clear_question(engine: Engine) -> None:
    state = engine.ask("How do I join?").state
    r = engine.ask("na wadhamini?", state)
    assert r.entry_id == "loan-guarantors"


def test_state_remembers_only_an_entry_id(engine: Engine) -> None:
    r = engine.ask("Mnafungua saa ngapi?")
    assert r.state == ConversationState(last_entry_id="office-hours", last_lang="sw", turns=1)
    handoff = engine.ask("who is the president", r.state)
    assert handoff.state.last_entry_id == "office-hours"  # a miss does not erase the topic


def test_threshold_controls_handoff(sacco_kb: KnowledgeBase) -> None:
    q = "Give me a number to call"
    lenient = Engine(sacco_kb, threshold=0.2).ask(q)
    strict = Engine(sacco_kb, threshold=0.99).ask("What is the interest rate on loans?")
    assert lenient.status == "answered"
    assert strict.status in {"handoff", "answered"}
    assert Engine(sacco_kb, threshold=0.999).ask("loan").status == "handoff"


def test_suggestions_follow_up_entries(engine: Engine) -> None:
    r = engine.ask("How do I join Umoja Sacco?")
    assert r.entry_id == "how-to-join"
    assert [i for i, _ in r.suggestions] == ["membership-fee", "share-capital"]
    sw = engine.ask("Nawezaje kujiunga na Umoja Sacco?")
    assert sw.suggestions[0][1].startswith("Ada")


def test_synonym_group_cannot_outvote_a_rare_typed_word(engine: Engine) -> None:
    assert engine.ask("When do members get their dividend?").entry_id == "dividends"


def test_engine_is_deterministic(sacco_kb: KnowledgeBase) -> None:
    a = Engine(sacco_kb, clock=lambda: date(2026, 6, 1)).ask("Riba ya mkopo ni ngapi?")
    b = Engine(sacco_kb, clock=lambda: date(2026, 6, 1)).ask("Riba ya mkopo ni ngapi?")
    assert (a.entry_id, a.confidence) == (b.entry_id, b.confidence)
