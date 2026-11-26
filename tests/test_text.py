from __future__ import annotations

import pytest

from jibu.text import Analyzer, edit_distance, normalise, split_words, stem_en, stem_sw


def test_normalise_strips_accents_case_and_apostrophes() -> None:
    assert normalise("Café WHAT'S ng'ombe") == "cafe whats ngombe"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("M-Pesa", "mpesa"),
        ("m pesa", "mpesa"),
        ("pay bill", "paybill"),
        ("Next of kin", "nextofkin"),
    ],
)
def test_multiword_terms_are_joined(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_numbers_and_single_letters_are_dropped() -> None:
    assert split_words("I need 50000 for a 2 year loan") == ["need", "for", "year", "loan"]


def test_sms_speak_is_expanded() -> None:
    assert split_words("hw r u") == ["how", "are", "you"]


def test_stop_words_removed_in_both_languages() -> None:
    a = Analyzer()
    assert a.surface("What is the interest rate?") == ["interest", "rate"]
    assert a.surface("Je, riba ni kiasi gani?") == ["riba", "kiasi"]


@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("loans", "loan"),
        ("applying", "appli"),
        ("applied", "appli"),
        ("apply", "appli"),
        ("saving", "sav"),
        ("savings", "sav"),
        ("save", "sav"),
        ("membership", "member"),
        ("members", "member"),
        ("withdrawal", "withdraw"),
        ("repayment", "repai"),
        ("paid", "pay"),
        ("stopped", "stop"),
    ],
)
def test_english_stemmer(word: str, stem: str) -> None:
    assert stem_en(word) == stem


@pytest.mark.parametrize(
    ("forms", "root"),
    [
        (["kulipa", "nitalipa", "unalipa", "wanalipa", "tunalipa", "nimelipa", "sijalipa"], "lipa"),
        (["kuomba", ["nataka", "kuomba"][1], "naomba"], "omba"),
        (["mikopo"], "mkopo"),
        (["vitabu"], "kitabu"),
        (["matawi"], "tawi"),
        (["wanachama", "mwanachama", "uanachama"], "mwanachama"),
        (["tawini"], "tawi"),
        (["nalipaje", "kulipaje"], "lipa"),
        (["kulipia", "kulipwa"], "lipa"),
    ],
)
def test_swahili_stemmer_maps_forms_to_one_key(forms: list[str], root: str) -> None:
    assert {stem_sw(f) for f in forms} == {root}


def test_swahili_stemmer_leaves_short_and_protected_words_alone() -> None:
    for w in ("namba", "mali", "mama", "maji", "kuku", "pesa"):
        assert stem_sw(w) == w


def test_english_lexicon_shields_words_from_swahili_rules() -> None:
    plain = Analyzer()
    shielded = Analyzer(english_lexicon={"management"})
    assert plain.stem("management") != shielded.stem("management")
    assert shielded.stem("management") == "manag"


def test_stemming_modes() -> None:
    assert Analyzer(stemming="none").keys("loans") == ["loans"]
    assert Analyzer(stemming="full").keys("loans") == ["loan"]
    with pytest.raises(ValueError):
        Analyzer(stemming="bogus")


def test_swahili_stop_stems_are_dropped() -> None:
    assert Analyzer().keys("nataka kujua kulipa") == ["lipa"]


def test_edit_distance_handles_transposition_and_limit() -> None:
    assert edit_distance("loan", "laon", 2) == 1
    assert edit_distance("membership", "mebership", 2) == 1
    assert edit_distance("abc", "xyzxyz", 1) == 2  # early exit returns limit + 1
    assert edit_distance("same", "same", 0) == 0
