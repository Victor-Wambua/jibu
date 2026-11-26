from __future__ import annotations

import math
import random

import pytest

from jibu.bm25 import BM25

DOCS = [
    ["loan", "interest", "rate"],
    ["loan", "guarantor"],
    ["opening", "hours", "saturday"],
    ["loan", "loan", "loan", "interest"],
]


def test_idf_is_positive_and_rarer_terms_weigh_more() -> None:
    idx = BM25(DOCS)
    assert idx.idf("saturday") > idx.idf("interest") > idx.idf("loan") > 0
    assert idx.idf("unseen-term") == idx.max_idf


def test_scores_are_non_negative_and_zero_without_overlap() -> None:
    idx = BM25(DOCS)
    assert all(s >= 0 for s in idx.score({"loan": 1.0, "hours": 1.0}))
    assert idx.score({"mpesa": 1.0}) == [0.0] * len(DOCS)
    assert idx.score({}) == [0.0] * len(DOCS)


def test_matches_hand_computed_value() -> None:
    idx = BM25([["a", "b"], ["b", "c", "d"]], k1=1.2, b=0.75)
    n, df, tf, dl, avgdl = 2, 1, 1, 2, 2.5
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    expected = idf * tf * 2.2 / (tf + 1.2 * (1 - 0.75 + 0.75 * dl / avgdl))
    assert idx.score({"a": 1.0})[0] == pytest.approx(expected)


def test_term_frequency_saturates() -> None:
    def score(tf: int) -> float:
        return BM25([["x"] * tf + ["pad"], ["other"], ["other2"]]).score({"x": 1.0})[0]

    s = [score(t) for t in (1, 2, 4, 8, 16)]
    assert s == sorted(s)  # more occurrences never hurt
    assert (s[1] - s[0]) > (s[4] - s[3])  # but with diminishing returns


def test_longer_documents_score_lower_for_the_same_tf() -> None:
    idx = BM25([["loan", "a"], ["loan", "a", "b", "c", "d", "e", "f", "g"], ["z"]])
    short, long_, _ = idx.score({"loan": 1.0})
    assert short > long_


def test_query_weight_scales_contribution() -> None:
    idx = BM25(DOCS)
    assert idx.score({"loan": 0.5})[1] == pytest.approx(0.5 * idx.score({"loan": 1.0})[1])


def test_term_scores_agree_with_score() -> None:
    idx = BM25(DOCS)
    ts = idx.term_scores("interest")
    full = idx.score({"interest": 1.0})
    assert all(full[i] == pytest.approx(v) for i, v in ts.items())
    assert idx.term_scores("nope") == {}


def test_empty_index_and_bad_parameters() -> None:
    assert BM25([]).score({"a": 1.0}) == []
    with pytest.raises(ValueError):
        BM25(DOCS, b=1.5)


def test_random_corpora_keep_invariants() -> None:
    rng = random.Random(7)
    vocab = [f"t{i}" for i in range(30)]
    for _ in range(20):
        docs = [
            [rng.choice(vocab) for _ in range(rng.randint(1, 12))]
            for _ in range(rng.randint(1, 15))
        ]
        idx = BM25(docs)
        q = {rng.choice(vocab): rng.random() + 0.1 for _ in range(4)}
        scores = idx.score(q)
        assert len(scores) == len(docs)
        assert all(s >= 0 and math.isfinite(s) for s in scores)
