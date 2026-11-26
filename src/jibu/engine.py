"""The retrieval engine: question in, approved answer or a handoff out.

Pipeline for one message:

1. detect the language (en / sw / mixed) and short-circuit greetings and thanks;
2. tokenise, drop stop-words, stem, and fix likely typos against the knowledge base's own words;
3. expand with the knowledge base's synonym groups (down-weighted);
4. for short follow-ups, optionally borrow terms from the previously matched entry;
5. score every active entry with BM25 over its questions+tags and (lightly) its answer;
6. turn the top score into a confidence in [0, 1] and compare it to the threshold.

Nothing here generates text. A reply is always one of the answers written by the organisation,
a canned greeting, or the organisation's handoff message.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

from .bm25 import BM25
from .kb import Entry, KnowledgeBase
from .lang import LangResult, detect
from .text import (
    BYE_WORDS,
    GREETING_WORDS,
    SMALLTALK_FILLER,
    SMALLTALK_WORDS,
    STOP_EN,
    STOP_SW,
    STOP_SW_STEMS,
    THANKS_WORDS,
    Analyzer,
    edit_distance,
    split_words,
)

DEFAULT_THRESHOLD = 0.5

_FOLLOWUP_CUES = (
    "and",
    "what about",
    "how about",
    "then",
    "also",
    "na",
    "vipi kuhusu",
    "je kuhusu",
    "kuhusu",
    "pia",
    "kisha",
    "na kwa",
    "ama",
    "or",
)

_DEFAULT_SMALLTALK = {
    "greeting": ("Hello! How can I help?", "Habari! Naweza kukusaidia vipi?"),
    "thanks": ("You're welcome!", "Karibu!"),
    "bye": ("Goodbye!", "Kwaheri!"),
}


@dataclass(frozen=True)
class EngineConfig:
    k1: float = 1.2
    b: float = 0.75
    answer_weight: float = 0.3  # weight of the answer-text index relative to questions+tags
    synonym_weight: float = 0.6  # query weight of a synonym expansion (typed words weigh 1.0)
    context_weight: float = 0.5  # query weight of terms carried over from the last entry
    oov_idf_factor: float = 0.75  # unknown words count this fraction of the maximum idf
    stemming: str = "full"  # "none" | "en" | "full" (used by the ablation in `jibu eval`)
    spellcheck: bool = True
    expand_synonyms: bool = True
    carry_context: bool = True
    cov_answer_credit: float = 0.5  # a query word found only in the answer text counts this much
    cov_synonym_credit: float = 0.8
    question_match_weight: float = 4.0  # bonus for overlap with ONE example question (Dice)
    context_tie_ratio: float = 0.4  # candidates within this share of the top score count as ties
    context_max_terms: int = 3  # a message with at most this many content words may be a follow-up
    margin_scale: float = 0.2  # relative lead over the runner-up at which ambiguity stops hurting
    suggest_coverage: float = 0.4
    conf_base: float = (
        0.3  # confidence = coverage * (base + w_rel * rel + w_margin * margin_factor)
    )
    conf_rel: float = 0.1
    conf_margin: float = 0.6


@dataclass(frozen=True)
class ConversationState:
    """All the memory a session keeps: the last matched entry. No message text is stored."""

    last_entry_id: str | None = None
    last_lang: str = ""
    turns: int = 0


@dataclass(frozen=True)
class Candidate:
    entry_id: str
    score: float
    coverage: float
    relative_score: float
    margin: float
    confidence: float


@dataclass(frozen=True)
class Reply:
    status: str  # "answered" | "handoff" | "smalltalk"
    text: str
    language: str  # the language of the reply text: "en" or "sw"
    detected: str  # what the message looked like: en / sw / mixed / und
    confidence: float
    entry_id: str | None
    suggestions: list[tuple[str, str]]  # (entry_id, question text) offered as next steps
    used_context: bool
    candidates: list[Candidate] = field(default_factory=list)
    corrections: dict[str, str] = field(default_factory=dict)
    state: ConversationState = ConversationState()


class Engine:
    def __init__(
        self,
        kb: KnowledgeBase,
        threshold: float | None = None,
        config: EngineConfig = EngineConfig(),
        clock: Callable[[], date] = date.today,
    ) -> None:
        self.kb = kb
        self.config = config
        self.clock = clock
        self.threshold = (
            threshold
            if threshold is not None
            else (kb.organisation.confidence_threshold or DEFAULT_THRESHOLD)
        )
        entries = kb.entries
        self.entries = entries
        self._index = {e.id: i for i, e in enumerate(entries)}

        # English lexicon guards the Swahili noun rules; per-language hints feed detection.
        en_words: set[str] = set()
        sw_words: set[str] = set()
        for e in entries:
            for q in e.questions.en:
                en_words.update(split_words(q))
            for q in e.questions.sw:
                sw_words.update(split_words(q))
            en_words.update(split_words(e.answer.en))
        self.analyzer = Analyzer(en_words, config.stemming)
        self.lang_hints = dict.fromkeys(sw_words - en_words, "sw") | dict.fromkeys(
            en_words - sw_words, "en"
        )

        self._question_keys: list[list[frozenset[str]]] = [
            [frozenset(self.analyzer.keys(q)) for q in e.questions.all()] for e in entries
        ]
        self._q_tokens: list[set[str]] = []
        self._a_tokens: list[set[str]] = []
        q_docs, a_docs = [], []
        for e in entries:
            qd = self.analyzer.keys(" ".join([*e.questions.all(), *e.tags]))
            ad = self.analyzer.keys(f"{e.answer.en} {e.answer.sw}")
            q_docs.append(qd)
            a_docs.append(ad)
            self._q_tokens.append(set(qd))
            self._a_tokens.append(set(ad))
        self.bm25_q = BM25(q_docs, config.k1, config.b)
        self.bm25_a = BM25(a_docs, config.k1, config.b)

        self.synonyms: dict[str, set[str]] = {}
        for group in kb.data.synonyms:
            stems = {k for w in group for k in self.analyzer.keys(w)[:1]}
            for s in stems:
                self.synonyms.setdefault(s, set()).update(stems - {s})

        self._vocab: Counter[str] = Counter()
        for e in entries:
            for text in [*e.questions.all(), *e.tags, e.answer.en, e.answer.sw]:
                self._vocab.update(set(self.analyzer.surface(text)))
        for group in kb.data.synonyms:
            for w in group:
                self._vocab.update(self.analyzer.surface(w)[:1])

    # ------------------------------------------------------------------ helpers
    def _known(self, key: str) -> bool:
        return key in self.bm25_q or key in self.bm25_a or key in self.synonyms

    def _idf(self, key: str) -> float:
        if key in self.bm25_q:
            return self.bm25_q.idf(key)
        partners = [self.bm25_q.idf(s) for s in self.synonyms.get(key, ()) if s in self.bm25_q]
        if partners:
            return sum(partners) / len(partners)
        return self.config.oov_idf_factor * self.bm25_q.max_idf

    def _correct(self, word: str) -> str | None:
        if len(word) < 5:
            return None
        limit = 1 if len(word) < 7 else 2
        best: tuple[int, int, str] | None = None
        for cand, freq in self._vocab.items():
            if len(cand) < 4:
                continue
            d = edit_distance(word, cand, limit)
            if d <= limit:
                rank = (d, -freq, cand)
                if best is None or rank < best:
                    best = rank
        return best[2] if best else None

    def _keys_for(self, text: str) -> tuple[list[str], dict[str, str]]:
        keys: list[str] = []
        corrections: dict[str, str] = {}
        for word in self.analyzer.surface(text):
            key = self.analyzer.stem(word)
            if key in STOP_SW_STEMS:
                continue
            if not self._known(key) and self.config.spellcheck:
                fixed = self._correct(word)
                if fixed:
                    corrections[word] = fixed
                    key = self.analyzer.stem(fixed)
                    if key in STOP_SW_STEMS:
                        continue
            keys.append(key)
        return keys, corrections

    def _display(self, entry: Entry, lang: str) -> str:
        return entry.answer.get(lang)

    def question_for(self, entry: Entry, lang: str) -> str:
        return (entry.questions.sw if lang == "sw" else entry.questions.en)[0]

    def _suggest(
        self, ids: list[str], lang: str, today: date, limit: int = 3
    ) -> list[tuple[str, str]]:
        out = []
        for i in ids:
            e = self.kb.entry(i)
            if e and e.active_on(today):
                out.append((e.id, self.question_for(e, lang)))
        return out[:limit]

    def starters(self, lang: str) -> list[tuple[str, str]]:
        return self._suggest(self.kb.organisation.starters, lang, self.clock(), limit=4)

    # --------------------------------------------------------------- smalltalk
    def _smalltalk(self, text: str) -> str | None:
        words = split_words(text)
        if not any(w in SMALLTALK_WORDS for w in words):
            return None
        rest = [
            w
            for w in words
            if w not in SMALLTALK_WORDS
            and w not in SMALLTALK_FILLER
            and w not in STOP_EN
            and w not in STOP_SW
        ]
        if rest:
            return None
        if any(w in THANKS_WORDS for w in words):
            return "thanks"
        if any(w in BYE_WORDS for w in words):
            return "bye"
        if any(w in GREETING_WORDS for w in words):
            return "greeting"
        return None

    # ------------------------------------------------------------------- score
    def _rank(
        self,
        own: list[str],
        extra: dict[str, float],
        active: list[bool],
    ) -> list[Candidate]:
        cfg = self.config
        n = len(self.entries)
        total = [0.0] * n
        sq = [0.0] * n
        for k in dict.fromkeys(own):
            # A typed word and its synonyms form one "concept": the best-matching member counts,
            # so a big synonym group cannot outweigh a rare word the customer actually typed.
            options: dict[str, float] = {k: 1.0}
            if cfg.expand_synonyms:
                for syn in self.synonyms.get(k, ()):
                    options.setdefault(syn, cfg.synonym_weight)
            for index, wa, target in (
                (self.bm25_q, 1.0, sq),
                (self.bm25_a, cfg.answer_weight, total),
            ):
                best: dict[int, float] = {}
                for term, w in options.items():
                    for i, sc in index.term_scores(term).items():
                        best[i] = max(best.get(i, 0.0), w * sc)
                for i, sc in best.items():
                    target[i] += wa * sc
        for term, w in extra.items():
            for i, sc in self.bm25_q.term_scores(term).items():
                sq[i] += w * sc
        own_set = frozenset(own)
        total = [(sq[i] + total[i]) if active[i] else 0.0 for i in range(n)]
        if own_set and cfg.question_match_weight:
            for i in range(n):
                if total[i] > 0:
                    dice = max(
                        (
                            2 * len(own_set & q) / (len(own_set) + len(q))
                            for q in self._question_keys[i]
                            if q
                        ),
                        default=0.0,
                    )
                    total[i] += cfg.question_match_weight * dice * dice
        order = sorted(range(len(total)), key=lambda i: -total[i])
        if not order or total[order[0]] <= 0:
            return []

        own_unique = list(dict.fromkeys(own))
        idfs = {k: self._idf(k) for k in own_unique}
        mass = sum(idfs.values()) or 1.0
        s1 = total[order[0]]
        s2 = total[order[1]] if len(order) > 1 else 0.0
        out = []
        for rank, i in enumerate(order[:3]):
            if total[i] <= 0:
                break
            matched = 0.0
            for k in own_unique:
                if k in self._q_tokens[i]:
                    credit = 1.0
                elif k in self._a_tokens[i]:
                    credit = cfg.cov_answer_credit
                elif any(s in self._q_tokens[i] for s in self.synonyms.get(k, ())):
                    credit = cfg.cov_synonym_credit
                elif any(s in self._a_tokens[i] for s in self.synonyms.get(k, ())):
                    credit = cfg.cov_synonym_credit * cfg.cov_answer_credit
                else:
                    credit = 0.0
                matched += idfs[k] * credit
            coverage = matched / mass
            ideal = sum(self.bm25_q.idf(k) for k in own_unique if k in self.bm25_q) or 1.0
            rel = min(1.0, sq[i] / ideal)
            rival = s2 if rank == 0 else s1
            margin = max(0.0, (total[i] - rival) / total[i]) if rank == 0 else 0.0
            mfac = min(1.0, margin / cfg.margin_scale)
            conf = coverage * (cfg.conf_base + cfg.conf_rel * rel + cfg.conf_margin * mfac)
            out.append(Candidate(self.entries[i].id, total[i], coverage, rel, margin, conf))
        return out

    def _context_terms(self, state: ConversationState) -> dict[str, float]:
        if not state.last_entry_id:
            return {}
        e = self.kb.entry(state.last_entry_id)
        if e is None:
            return {}
        terms = [*e.tags, e.questions.en[0], e.questions.sw[0]]
        keys = self.analyzer.keys(" ".join(terms))
        return dict.fromkeys(keys, self.config.context_weight)

    @staticmethod
    def _has_cue(text: str) -> bool:
        t = " ".join(split_words(text))
        first = t.split(" ")[0] if t else ""
        return any(t.startswith(c + " ") or first == c for c in _FOLLOWUP_CUES)

    # --------------------------------------------------------------------- ask
    def ask(
        self,
        text: str,
        state: ConversationState | None = None,
        lang_hint: str | None = None,
    ) -> Reply:
        state = state or ConversationState()
        today = self.clock()
        det: LangResult = detect(text, self.lang_hints)
        lang = det.dominant or state.last_lang or lang_hint or "en"
        if lang_hint in {"en", "sw"} and det.lang == "und":
            lang = lang_hint
        nxt = replace(state, last_lang=lang, turns=state.turns + 1)

        kind = self._smalltalk(text)
        if kind:
            custom = getattr(self.kb.data.smalltalk, kind)
            msg = custom.get(lang) if custom else _DEFAULT_SMALLTALK[kind][1 if lang == "sw" else 0]
            starters = self.starters(lang) if kind == "greeting" else []
            return Reply("smalltalk", msg, lang, det.lang, 1.0, None, starters, False, state=nxt)

        own, corrections = self._keys_for(text)
        active = [e.active_on(today) for e in self.entries]
        cands = self._rank(own, {}, active)
        used_context = False

        if self.config.carry_context and state.last_entry_id:
            last = self.kb.entry(state.last_entry_id)
            cue = self._has_cue(text)
            short = len(set(own)) <= self.config.context_max_terms
            if last and last.active_on(today) and (cue or short):
                ctx_cands = self._rank(own, self._context_terms(state), active)
                plain_conf = cands[0].confidence if cands else 0.0
                if ctx_cands:
                    best = ctx_cands[0]
                    # Two ways context may change the answer, and no other:
                    #  rescue:    the message alone was not confident enough, context makes it so;
                    #  tie-break: the message alone fits several entries about equally well and
                    #             context picks one of them. A message that clearly points at one
                    #             entry on its own words is never overruled by the previous topic.
                    floor = self.config.context_tie_ratio * cands[0].score if cands else 0.0
                    plausible = {c.entry_id for c in cands if c.score >= floor}
                    rescue = plain_conf < self.threshold and best.confidence >= plain_conf
                    tiebreak = best.entry_id in plausible and best.confidence >= self.threshold
                    if rescue or tiebreak:
                        cands, used_context = ctx_cands, True

        top = cands[0] if cands else None
        if top and top.confidence >= self.threshold:
            entry = self.entries[self._index[top.entry_id]]
            sugg = self._suggest(entry.follow_ups, lang, today)
            return Reply(
                "answered",
                self._display(entry, lang),
                lang,
                det.lang,
                top.confidence,
                entry.id,
                sugg,
                used_context,
                cands,
                corrections,
                replace(nxt, last_entry_id=entry.id),
            )

        if top and top.coverage >= self.config.suggest_coverage:
            sugg = self._suggest([c.entry_id for c in cands], lang, today)
        else:
            sugg = self.starters(lang)
        return Reply(
            "handoff",
            self.kb.handoff_text(lang),
            lang,
            det.lang,
            top.confidence if top else 0.0,
            None,
            sugg,
            used_context,
            cands,
            corrections,
            nxt,
        )
