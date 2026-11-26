"""Language detection for short chat messages: English, Swahili, or a mix of both.

A function-word heuristic, not a classifier. Kenyan chat routinely code-switches
("nataka kujua how to apply for a loan"), so "mixed" is a first-class result.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .text import split_words

EN_MARKERS = frozenset(
    [
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "do",
        "does",
        "did",
        "can",
        "could",
        "will",
        "would",
        "should",
        "i",
        "my",
        "me",
        "we",
        "our",
        "you",
        "your",
        "it",
        "its",
        "to",
        "of",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "and",
        "or",
        "but",
        "if",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "who",
        "whats",
        "hows",
        "please",
        "much",
        "many",
        "have",
        "has",
        "had",
        "this",
        "that",
        "there",
        "here",
        "about",
        "not",
        "any",
        "need",
        "want",
        "get",
        "apply",
        "open",
        "hello",
        "hi",
        "thanks",
        "thank",
        "pay",
        "money",
    ]
)

SW_MARKERS = frozenset(
    [
        "na",
        "ya",
        "wa",
        "kwa",
        "ni",
        "la",
        "za",
        "katika",
        "je",
        "nini",
        "gani",
        "vipi",
        "lini",
        "wapi",
        "nani",
        "kuna",
        "hakuna",
        "mimi",
        "wewe",
        "yeye",
        "sisi",
        "wao",
        "yangu",
        "yako",
        "yake",
        "yetu",
        "kama",
        "au",
        "lakini",
        "pia",
        "sana",
        "tu",
        "ili",
        "kwamba",
        "hii",
        "hiyo",
        "huu",
        "huo",
        "hizi",
        "hizo",
        "hapa",
        "pale",
        "naweza",
        "nataka",
        "ninataka",
        "nitaweza",
        "naomba",
        "tafadhali",
        "asante",
        "habari",
        "mambo",
        "hujambo",
        "karibu",
        "kiasi",
        "ngapi",
        "saa",
        "mnafungua",
        "mnafunga",
        "mna",
        "una",
        "ana",
        "nina",
        "hana",
        "bado",
        "pesa",
    ]
)

# Prefix patterns that are very rarely English: subject+tense verb forms and "ku-" infinitives.
_SW_VERB = re.compile(
    r"^(?:ni|u|a|tu|m|wa)(?:na|me|li|ta)[a-z]{3,}$|^ku[a-z]{4,}$|^(?:si|ha)[a-z]{5,}$"
)
_SW_NOUN = re.compile(r"^(?:mi|ma|vi|wa|mw|ki|ch|ny)[a-z]{4,}$")

_WORD_WEIGHT = 1.0
_MORPH_WEIGHT = 0.6
_KB_WEIGHT = 0.7


@dataclass(frozen=True)
class LangResult:
    lang: str  # "en" | "sw" | "mixed" | "und"
    en: float
    sw: float

    @property
    def dominant(self) -> str:
        """The language to answer in. "und"/ties fall back to the empty string."""
        if self.lang in {"en", "sw"}:
            return self.lang
        if self.sw > self.en:
            return "sw"
        if self.en > self.sw:
            return "en"
        return ""


def detect(text: str, kb_hints: Mapping[str, str] | None = None) -> LangResult:
    """Score a message. ``kb_hints`` maps a word to "en"/"sw" if only seen in that language
    in the knowledge base's questions; it helps with domain words like "mkopo" or "loan"."""
    en = sw = 0.0
    for w in split_words(text):
        if w in EN_MARKERS:
            en += _WORD_WEIGHT
        elif w in SW_MARKERS:
            sw += _WORD_WEIGHT
        elif kb_hints and w in kb_hints:
            if kb_hints[w] == "sw":
                sw += _KB_WEIGHT
            else:
                en += _KB_WEIGHT
        elif _SW_VERB.match(w):
            sw += _MORPH_WEIGHT
        elif _SW_NOUN.match(w) and len(w) > 5:
            sw += _MORPH_WEIGHT * 0.5
    if en == 0 and sw == 0:
        return LangResult("und", en, sw)
    low, high = sorted((en, sw))
    if low >= 1.0 and low / high >= 0.25:
        return LangResult("mixed", en, sw)
    return LangResult("sw" if sw > en else "en", en, sw)
