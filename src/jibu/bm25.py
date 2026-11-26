"""Okapi BM25 written from scratch (no search library).

score(D, Q) = sum over query terms t of
              idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * |D| / avgdl))
idf(t)      = ln(1 + (N - df + 0.5) / (df + 0.5))        (the non-negative "Lucene" variant)

Query terms carry a weight so that synonym expansions and carried-over context can count for
less than the words the customer actually typed.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence


class BM25:
    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.2, b: float = 0.75) -> None:
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError("k1 must be >= 0 and b within [0, 1]")
        self.k1 = k1
        self.b = b
        self.n_docs = len(docs)
        self.doc_len = [len(d) for d in docs]
        self.avgdl = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, doc in enumerate(docs):
            for term, tf in Counter(doc).items():
                self.postings.setdefault(term, []).append((i, tf))

    def __contains__(self, term: str) -> bool:
        return term in self.postings

    @property
    def vocabulary(self) -> frozenset[str]:
        return frozenset(self.postings)

    def df(self, term: str) -> int:
        return len(self.postings.get(term, ()))

    def idf(self, term: str) -> float:
        df = self.df(term)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    @property
    def max_idf(self) -> float:
        """idf of a term that appears in no document."""
        return self.idf("\x00unseen")

    def term_scores(self, term: str) -> dict[int, float]:
        """Per-document BM25 contribution of a single term (weight 1)."""
        out: dict[int, float] = {}
        if not self.avgdl:
            return out
        idf = self.idf(term)
        for i, tf in self.postings.get(term, ()):
            norm = self.k1 * (1.0 - self.b + self.b * self.doc_len[i] / self.avgdl)
            out[i] = idf * tf * (self.k1 + 1.0) / (tf + norm)
        return out

    def score(self, query: Mapping[str, float]) -> list[float]:
        """BM25 score of every document for a weighted bag of query terms."""
        scores = [0.0] * self.n_docs
        if not self.n_docs or not self.avgdl:
            return scores
        for term, weight in query.items():
            posting = self.postings.get(term)
            if not posting or weight <= 0:
                continue
            idf = self.idf(term)
            for i, tf in posting:
                norm = self.k1 * (1.0 - self.b + self.b * self.doc_len[i] / self.avgdl)
                scores[i] += weight * idf * tf * (self.k1 + 1.0) / (tf + norm)
        return scores
