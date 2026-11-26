"""Tokenisation, stop-words and light stemming for English and Swahili.

Everything here is heuristic. The Swahili stemmer strips common verb prefixes
(subject + tense markers, the infinitive ``ku-``) and a handful of noun-class
prefixes, and it consults a small hand-written lemma table for irregular
singular/plural pairs. It is not a morphological analyser: it only needs to map
the surface forms that appear in a knowledge base and in customers' messages to
the *same* key, whatever that key is.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

_APOSTROPHES = re.compile(r"[’'`´]")
_TOKEN = re.compile(r"[a-z0-9]+")

_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bm[\s\-]?pesa\b"), "mpesa"),
    (re.compile(r"\bpay[\s\-]bill\b"), "paybill"),
    (re.compile(r"\bbuy[\s\-]goods\b"), "buygoods"),
    (re.compile(r"\bnext[\s\-]of[\s\-]kin\b"), "nextofkin"),
    (re.compile(r"\bshare[\s\-]capital\b"), "sharecapital"),
)

# SMS-speak that is common in WhatsApp messages. Deliberately tiny.
_SMS = {
    "pls": "please",
    "plz": "please",
    "hw": "how",
    "wat": "what",
    "wht": "what",
    "wen": "when",
    "abt": "about",
    "ur": "your",
    "u": "you",
    "r": "are",
    "dat": "that",
    "wer": "where",
    "kes": "ksh",
    "shs": "ksh",
    "bob": "ksh",
}


def normalise(text: str) -> str:
    """Lower-case, strip accents and apostrophes, collapse known multi-word terms."""
    t = unicodedata.normalize("NFKD", text).casefold()
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _APOSTROPHES.sub("", t)
    for pattern, repl in _PHRASES:
        t = pattern.sub(repl, t)
    return t


def split_words(text: str) -> list[str]:
    """Normalised raw words (no stop-word removal, no stemming, numbers dropped)."""
    out: list[str] = []
    for w in _TOKEN.findall(normalise(text)):
        w = _SMS.get(w, w)
        if w.isdigit() or len(w) < 2:
            continue
        out.append(w)
    return out


# --------------------------------------------------------------------------- #
# Stop-words
# --------------------------------------------------------------------------- #

STOP_EN = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "doing",
        "done",
        "can",
        "could",
        "will",
        "would",
        "should",
        "shall",
        "may",
        "might",
        "must",
        "i",
        "me",
        "my",
        "mine",
        "we",
        "us",
        "our",
        "ours",
        "you",
        "your",
        "yours",
        "he",
        "she",
        "it",
        "its",
        "they",
        "them",
        "their",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "about",
        "as",
        "into",
        "and",
        "or",
        "but",
        "if",
        "so",
        "than",
        "then",
        "too",
        "very",
        "just",
        "not",
        "no",
        "what",
        "whats",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "why",
        "how",
        "hows",
        "please",
        "kindly",
        "wanted",
        "want",
        "wish",
        "like",
        "need",
        "needs",
        "know",
        "tell",
        "ask",
        "asking",
        "help",
        "get",
        "got",
        "getting",
        "any",
        "some",
        "also",
        "have",
        "has",
        "had",
        "having",
        "possible",
        "able",
        "way",
        "again",
        "still",
        "really",
        "one",
        "anything",
        "something",
        "hello",
        "ok",
        "okay",
        "yes",
        "im",
        "ive",
        "id",
        "dont",
        "cant",
        "wont",
        "isnt",
        "arent",
        "doesnt",
        "didnt",
        "let",
        "lets",
        "more",
        "other",
        "out",
        "up",
        "down",
        "over",
        "under",
        "after",
        "before",
        "during",
        "while",
        "per",
        "via",
    ]
)

STOP_SW = frozenset(
    [
        "na",
        "ya",
        "wa",
        "kwa",
        "ni",
        "la",
        "za",
        "katika",
        "hii",
        "hiyo",
        "huu",
        "huo",
        "hizi",
        "hizo",
        "hili",
        "lile",
        "ile",
        "yale",
        "kile",
        "vile",
        "hawa",
        "wale",
        "huyu",
        "yule",
        "hapa",
        "pale",
        "huko",
        "kule",
        "hapo",
        "kama",
        "au",
        "ila",
        "lakini",
        "pia",
        "sana",
        "tu",
        "je",
        "ili",
        "kwamba",
        "cha",
        "vya",
        "pa",
        "mimi",
        "wewe",
        "yeye",
        "sisi",
        "nyinyi",
        "wao",
        "yangu",
        "yako",
        "yake",
        "yetu",
        "yenu",
        "yao",
        "wangu",
        "wako",
        "wake",
        "wetu",
        "wenu",
        "langu",
        "lako",
        "lake",
        "letu",
        "lenu",
        "lao",
        "changu",
        "chako",
        "chake",
        "chetu",
        "chenu",
        "vyangu",
        "vyako",
        "vyake",
        "vyetu",
        "vyao",
        "zangu",
        "zako",
        "zake",
        "zetu",
        "zao",
        "gani",
        "nini",
        "nani",
        "lini",
        "wapi",
        "vipi",
        "tafadhali",
        "naomba",
        "kuna",
        "ipo",
        "iko",
        "yupo",
        "wapo",
        "kila",
        "hadi",
        "mpaka",
        "kutoka",
        "hata",
        "bado",
        "tena",
        "hivyo",
        "ndio",
        "ndiyo",
        "sio",
        "si",
        "kuwa",
        "ana",
        "ina",
        "una",
        "nina",
        "hana",
        "hakuna",
        "ningependa",
        "ningeomba",
        "kuhusu",
        "jinsi",
        "namna",
    ]
)

# Swahili *stems* (after verb-prefix stripping) that carry no topical meaning
# in a FAQ ("I want to know ...", "can I ...", "how do I get ...").
STOP_SW_STEMS = frozenset({"taka", "weza", "jua", "uliza", "pata", "fanya", "fanye", "fanyaje"})

GREETING_WORDS = frozenset(
    [
        "hi",
        "hello",
        "hey",
        "hallo",
        "howdy",
        "morning",
        "afternoon",
        "evening",
        "good",
        "greetings",
        "habari",
        "mambo",
        "niaje",
        "sasa",
        "poa",
        "hujambo",
        "hamjambo",
        "shikamoo",
        "salamu",
        "vipi",
        "wasup",
        "sup",
        "yo",
        "heri",
        "jambo",
        "salama",
    ]
)
THANKS_WORDS = frozenset(
    ["thanks", "thank", "thx", "asante", "shukrani", "ahsante", "barikiwa", "mungu", "akubariki"]
)
BYE_WORDS = frozenset(["bye", "goodbye", "kwaheri", "cheers", "tutaonana", "baadaye"])
SMALLTALK_WORDS = GREETING_WORDS | THANKS_WORDS | BYE_WORDS
# Words that may accompany a greeting/thanks without making it a real question.
SMALLTALK_FILLER = frozenset(
    {"much", "very", "sana", "you", "so", "again", "all", "team", "sir", "madam"}
)


# --------------------------------------------------------------------------- #
# Stemming
# --------------------------------------------------------------------------- #

_EN_IRREGULAR = {
    "paid": "pay",
    "withdrawn": "withdraw",
    "withdrew": "withdraw",
    "took": "take",
    "taken": "take",
    "went": "go",
    "children": "child",
    "people": "person",
    "men": "man",
    "women": "woman",
    "lost": "lose",
    "sent": "send",
    "bought": "buy",
    "gave": "give",
    "given": "give",
}


def stem_en(word: str) -> str:
    """A small suffix stripper: plurals, -ing, -ed, -ment, -ship, -al, trailing e/y."""
    w = word
    if len(w) <= 3:
        return w
    if w in _EN_IRREGULAR:
        return _EN_IRREGULAR[w]
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith(("sses", "shes", "ches", "xes", "zes")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if w.endswith("ing") and len(w) > 5:
        w = _undouble(w[:-3])
    elif w.endswith("ed") and len(w) > 4:
        w = _undouble(w[:-2])
    elif (w.endswith("ment") and len(w) > 6) or (w.endswith("ship") and len(w) > 7):
        w = w[:-4]
    elif w.endswith("al") and len(w) > 7:
        w = w[:-2]
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    if w.endswith("y") and len(w) > 3:
        w = w[:-1] + "i"
    return w


def _undouble(w: str) -> str:
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
        return w[:-1]
    return w


# Irregular singular/plural pairs and other forms the prefix rules cannot reach.
# Hand-written; extend it as your own knowledge base needs.
_SW_LEMMAS = {
    "wanachama": "mwanachama",
    "uanachama": "mwanachama",
    "wanafunzi": "mwanafunzi",
    "watoto": "mtoto",
    "wateja": "mteja",
    "wafanyakazi": "mfanyakazi",
    "wazee": "mzee",
    "wagonjwa": "mgonjwa",
    "walimu": "mwalimu",
    "wanawake": "mwanamke",
    "wanaume": "mwanamume",
    "wazazi": "mzazi",
    "wakopaji": "mkopaji",
    "wategemezi": "mtegemezi",
    "wanafamilia": "mwanafamilia",
    "watu": "mtu",
    "vijana": "kijana",
    "wadhamini": "mdhamini",
    "marafiki": "rafiki",
    "wakurugenzi": "mkurugenzi",
    "waajiri": "mwajiri",
    "wajane": "mjane",
    "miezi": "mwezi",
    "siku": "siku",
    "ndugu": "ndugu",
}

_SW_PROTECT = frozenset(
    [
        "namba",
        "nambari",
        "nafasi",
        "anwani",
        "mapema",
        "maji",
        "mali",
        "mama",
        "baba",
        "kuku",
        "kuta",
        "kuna",
        "kuwa",
        "kila",
        "mapato",
        "nane",
        "nene",
        "nyingi",
        "nyingine",
        "nyumba",
        "nyumbani",
        "ndani",
    ]
)

_SW_JE_KEEP = frozenset({"mwenyeje", "mgeni"})

_SW_VERB_POS = re.compile(r"^(?:ni|u|a|tu|m|wa)(?:na|me|li|ta|ka)(?P<root>[a-z]{3,})$")
_SW_VERB_NEG = re.compile(r"^(?:si|hu|hatu|hamu|hawa|ha)(?:ku|ja|ta)(?P<root>[a-z]{3,})$")
_SW_VERB_1SG = re.compile(r"^na(?P<root>[a-z]{4,})$")


def _finalise_verb(root: str) -> str:
    if root.startswith("ku") and len(root) >= 6:
        root = root[2:]
    if len(root) >= 5 and root.endswith(("ia", "ea", "wa")):
        root = root[:-2] + "a"
    return root


def stem_sw(word: str) -> str:
    """Heuristic Swahili stemmer (verb prefixes, a few noun-class prefixes)."""
    w = word
    if w in _SW_LEMMAS:
        return _SW_LEMMAS[w]
    if len(w) <= 4 or w in _SW_PROTECT:
        return w
    if len(w) >= 6 and w.endswith("je") and w not in _SW_JE_KEEP:
        w = w[:-2]  # interrogative suffix: nalipaje -> nalipa, nifanyeje -> nifanye
    for pattern in (_SW_VERB_POS, _SW_VERB_NEG, _SW_VERB_1SG):
        m = pattern.match(w)
        if m:
            return _finalise_verb(m.group("root"))
    if w.startswith("ku") and len(w) >= 5:
        return _finalise_verb(w[2:])
    if len(w) >= 7 and w.endswith("iwa"):
        return w[:-3] + "a"
    if len(w) >= 7 and w.endswith("wa"):
        return w[:-2] + "a"
    if len(w) >= 6 and w.endswith(("ini", "eni")):
        return w[:-2]
    if w.startswith("mi") and len(w) >= 6:
        return "m" + w[2:]
    if w.startswith("vi") and len(w) >= 6:
        return "ki" + w[2:]
    if w.startswith("ma") and len(w) >= 6:
        return w[2:]
    if w.startswith("u") and len(w) >= 7:
        return w[1:]
    return w


# --------------------------------------------------------------------------- #
# Analyzer
# --------------------------------------------------------------------------- #


class Analyzer:
    """Turns text into index/query keys.

    ``english_lexicon`` is the set of surface words seen in the knowledge base's English
    text. A word in that set is only ever stemmed as English, which stops Swahili noun
    rules from mangling words such as "management" or "market".
    """

    def __init__(self, english_lexicon: Iterable[str] = (), stemming: str = "full") -> None:
        if stemming not in {"none", "en", "full"}:
            raise ValueError("stemming must be 'none', 'en' or 'full'")
        self.english_lexicon = frozenset(english_lexicon)
        self.stemming = stemming

    def is_stop(self, word: str) -> bool:
        return word in STOP_EN or word in STOP_SW or word in SMALLTALK_WORDS

    def surface(self, text: str) -> list[str]:
        """Content words as written (normalised), stop-words removed."""
        return [w for w in split_words(text) if not self.is_stop(w)]

    def stem(self, word: str) -> str:
        if self.stemming == "none":
            return word
        if word in self.english_lexicon or self.stemming == "en":
            return stem_en(word)
        s = stem_sw(word)
        if s == word:
            s = stem_en(word)
        return s

    def keys(self, text: str) -> list[str]:
        """Stemmed content keys, in order, duplicates kept."""
        out = []
        for w in self.surface(text):
            k = self.stem(w)
            if k and k not in STOP_SW_STEMS:
                out.append(k)
        return out


def edit_distance(a: str, b: str, limit: int) -> int:
    """Damerau-Levenshtein (optimal string alignment) with early exit above ``limit``."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]
