"""Knowledge base files: schema, loading and validation with readable errors.

One YAML file describes one organisation (see ``kb/umoja-sacco.yaml``). Unknown keys are
rejected so that a typo such as ``anwser:`` is an error with a line number instead of a
silently empty answer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .text import Analyzer, normalise

LANGS = ("en", "sw")
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9\-]{1,62}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Bilingual(_Strict):
    en: Text
    sw: Text

    def get(self, lang: str) -> str:
        return self.sw if lang == "sw" else self.en


class Questions(_Strict):
    en: list[Question] = Field(min_length=1)
    sw: list[Question] = Field(min_length=1)

    def all(self) -> list[str]:
        return [*self.en, *self.sw]


class Contact(_Strict):
    phone: str | None = None
    whatsapp: str | None = None
    hours: Bilingual | None = None


class Organisation(_Strict):
    id: Slug
    name: Text
    description: Text | None = None
    contact: Contact = Contact()
    confidence_threshold: float | None = Field(default=None, gt=0, lt=1)
    welcome: Bilingual
    starters: list[Slug] = []


class Smalltalk(_Strict):
    greeting: Bilingual | None = None
    thanks: Bilingual | None = None
    bye: Bilingual | None = None


class Entry(_Strict):
    id: Slug
    tags: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2)]] = []
    questions: Questions
    answer: Bilingual
    follow_ups: list[Slug] = []
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> Entry:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until is earlier than valid_from")
        return self

    def active_on(self, day: date) -> bool:
        if self.valid_from and day < self.valid_from:
            return False
        return not (self.valid_until and day > self.valid_until)


class KBFile(_Strict):
    organisation: Organisation
    handoff: Bilingual
    smalltalk: Smalltalk = Smalltalk()
    synonyms: list[list[Text]] = []
    entries: list[Entry] = Field(min_length=1)


_PLACEHOLDER = re.compile(r"\{(\w+)\}")
HANDOFF_PLACEHOLDERS = {"phone", "whatsapp", "hours"}


@dataclass(frozen=True)
class Problem:
    severity: str  # "error" | "warning"
    file: str
    line: int | None
    where: str
    message: str

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{loc}: {self.severity}: {self.where + ': ' if self.where else ''}{self.message}"


class KBError(Exception):
    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


@dataclass
class KnowledgeBase:
    path: Path
    data: KBFile
    warnings: list[Problem] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.data.organisation.id

    @property
    def organisation(self) -> Organisation:
        return self.data.organisation

    @property
    def entries(self) -> list[Entry]:
        return self.data.entries

    def entry(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def handoff_text(self, lang: str) -> str:
        c = self.organisation.contact
        hours = c.hours.get(lang) if c.hours else ""
        text = self.data.handoff.get(lang)
        values = {"phone": c.phone or "", "whatsapp": c.whatsapp or "", "hours": hours}
        return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _node_line(node: yaml.Node | None, loc: Iterable[Any]) -> int | None:
    """Line number (1-based) of the deepest YAML node reachable along a pydantic error path."""
    line = node.start_mark.line + 1 if node is not None else None
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            nxt = next(
                (v for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == part),
                None,
            )
            if nxt is None:
                # an unknown key: point at the key itself
                return line
            node = nxt
        elif (
            isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value)
        ):
            node = node.value[part]
        else:
            return line
        line = node.start_mark.line + 1
    return line


def _extra_key_line(root: yaml.Node | None, loc: tuple[Any, ...]) -> int | None:
    """For "extra forbidden" errors the last path element is the offending key."""
    parent = _node_line(root, loc[:-1])
    node = root
    for part in loc[:-1]:
        if isinstance(node, yaml.MappingNode):
            node = next((v for k, v in node.value if getattr(k, "value", None) == part), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            node = node.value[part]
    if isinstance(node, yaml.MappingNode):
        for k, _ in node.value:
            if getattr(k, "value", None) == loc[-1]:
                return int(k.start_mark.line) + 1
    return parent


def _pretty_error(err: Any) -> tuple[str, str]:
    loc = ".".join(str(p) for p in err["loc"])
    msg = err["msg"]
    if err["type"] == "extra_forbidden":
        msg = "unknown key (typo?)"
    elif err["type"] == "missing":
        msg = "required field is missing"
    elif err["type"] == "string_too_short":
        msg = "must not be empty (or is too short)"
    elif err["type"] == "too_short":
        msg = "needs at least one item"
    elif err["type"] == "string_pattern_mismatch":
        msg = "must be lowercase letters, digits and hyphens (a slug), e.g. 'loan-limit'"
    return loc, msg.removeprefix("Value error, ")


def _semantic_checks(kb: KBFile, fname: str, root: yaml.Node | None) -> list[Problem]:
    out: list[Problem] = []
    ids = [e.id for e in kb.entries]
    entries_node = None
    if isinstance(root, yaml.MappingNode):
        entries_node = next(
            (v for k, v in root.value if getattr(k, "value", None) == "entries"), None
        )

    def line_of(idx: int, *rest: Any) -> int | None:
        return _node_line(entries_node, (idx, *rest))

    def add(sev: str, idx: int, msg: str, *rest: Any) -> None:
        out.append(Problem(sev, fname, line_of(idx, *rest), f"entry '{ids[idx]}'", msg))

    seen: dict[str, int] = {}
    for i, e in enumerate(kb.entries):
        if e.id in seen:
            add("error", i, f"duplicate id (first used by entry #{seen[e.id] + 1})", "id")
        seen.setdefault(e.id, i)
    id_set = set(ids)
    for i, e in enumerate(kb.entries):
        for j, f in enumerate(e.follow_ups):
            if f == e.id:
                add("error", i, "follow_ups refers to the entry itself", "follow_ups", j)
            elif f not in id_set:
                add("error", i, f"follow_ups refers to unknown entry '{f}'", "follow_ups", j)
        if not e.tags:
            add("warning", i, "no tags; tags improve matching and follow-up context")
        if len(e.questions.en) + len(e.questions.sw) < 4:
            add("warning", i, "fewer than 4 example questions; recall will be weak", "questions")
        for lang in LANGS:
            ans = e.answer.get(lang)
            if len(ans) < 12:
                add("warning", i, f"{lang} answer is very short", "answer", lang)
            if len(ans) > 700:
                add(
                    "warning",
                    i,
                    f"{lang} answer is long for chat ({len(ans)} chars)",
                    "answer",
                    lang,
                )
        if e.valid_until and e.valid_until < date.today():
            add("warning", i, f"expired on {e.valid_until}; it will not be used", "valid_until")
    for i, sid in enumerate(kb.organisation.starters):
        if sid not in id_set:
            out.append(
                Problem("error", fname, None, "organisation.starters", f"unknown entry '{sid}'")
            )
        _ = i
    owner: dict[str, str] = {}
    for i, e in enumerate(kb.entries):
        for q in e.questions.all():
            key = normalise(q).strip(" ?!.")
            if key in owner and owner[key] != e.id:
                add(
                    "warning",
                    i,
                    f"question '{q}' is also used by entry '{owner[key]}'",
                    "questions",
                )
            owner.setdefault(key, e.id)
    # Questions that differ only by stop-words ("Who can join?" / "How do I join?") look identical
    # to the retriever, so they can never be told apart.
    analyzer = Analyzer()
    keyed: dict[frozenset[str], tuple[str, str]] = {}
    for i, e in enumerate(kb.entries):
        for q in e.questions.all():
            keys = frozenset(analyzer.keys(q))
            if len(keys) < 2:
                continue
            if (
                keys in keyed
                and keyed[keys][0] != e.id
                and normalise(keyed[keys][1]) != normalise(q)
            ):
                add(
                    "warning",
                    i,
                    f"'{q}' reduces to the same keywords as '{keyed[keys][1]}' (entry "
                    f"'{keyed[keys][0]}'); reword one so they can be told apart",
                    "questions",
                )
            keyed.setdefault(keys, (e.id, q))
    for gi, group in enumerate(kb.synonyms):
        if len({normalise(w) for w in group}) < 2:
            out.append(
                Problem(
                    "error", fname, None, f"synonyms[{gi}]", "needs at least two distinct words"
                )
            )
        for w in group:
            if " " in w.strip():
                out.append(
                    Problem(
                        "warning",
                        fname,
                        None,
                        f"synonyms[{gi}]",
                        f"'{w}' has several words; only single words are expanded",
                    )
                )
    for name, text in (("handoff.en", kb.handoff.en), ("handoff.sw", kb.handoff.sw)):
        for ph in _PLACEHOLDER.findall(text):
            if ph not in HANDOFF_PLACEHOLDERS:
                out.append(
                    Problem(
                        "error",
                        fname,
                        None,
                        name,
                        f"unknown placeholder {{{ph}}}; use {sorted(HANDOFF_PLACEHOLDERS)}",
                    )
                )
    return out


def parse_kb(path: Path) -> tuple[KBFile | None, list[Problem]]:
    """Parse one file. Returns the model (or None if invalid) and every problem found."""
    fname = str(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Problem("error", fname, None, "", f"cannot read file: {exc.strerror}")]
    try:
        root = yaml.compose(raw)
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else None
        problem = getattr(exc, "problem", None) or "invalid YAML"
        return None, [Problem("error", fname, line, "", f"YAML syntax error: {problem}")]
    if not isinstance(data, dict):
        return None, [
            Problem(
                "error",
                fname,
                1,
                "",
                "top level must be a mapping with 'organisation', 'handoff', 'entries'",
            )
        ]
    try:
        kb = KBFile.model_validate(data)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            where, msg = _pretty_error(err)
            loc = tuple(err["loc"])
            line = (
                _extra_key_line(root, loc)
                if err["type"] == "extra_forbidden"
                else _node_line(root, loc)
            )
            problems.append(Problem("error", fname, line, where, msg))
        return None, problems
    problems = _semantic_checks(kb, fname, root)
    return kb, problems


def load_kb(path: str | Path) -> KnowledgeBase:
    """Load and validate one KB file; raises :class:`KBError` listing every error."""
    p = Path(path)
    data, problems = parse_kb(p)
    errors = [x for x in problems if x.severity == "error"]
    if data is None or errors:
        raise KBError(errors or problems)
    return KnowledgeBase(p, data, [x for x in problems if x.severity == "warning"])


def kb_files(path: str | Path) -> list[Path]:
    p = Path(path)
    if p.is_dir():
        return sorted([*p.glob("*.yaml"), *p.glob("*.yml")])
    return [p]


def check_kb(path: str | Path) -> tuple[list[KnowledgeBase], list[Problem]]:
    """Validate a file or every ``*.yaml`` in a directory; never raises for bad content."""
    kbs: list[KnowledgeBase] = []
    problems: list[Problem] = []
    for f in kb_files(path):
        data, probs = parse_kb(f)
        problems.extend(probs)
        if data is not None and not any(x.severity == "error" for x in probs):
            kbs.append(KnowledgeBase(f, data, [x for x in probs if x.severity == "warning"]))
    seen: dict[str, Path] = {}
    for kb in kbs:
        if kb.id in seen:
            problems.append(
                Problem(
                    "error",
                    str(kb.path),
                    None,
                    "organisation.id",
                    f"id '{kb.id}' is already used by {seen[kb.id]}",
                )
            )
        seen.setdefault(kb.id, kb.path)
    if not kb_files(path):
        problems.append(
            Problem("error", str(path), None, "", "no .yaml knowledge base files found")
        )
    return kbs, problems


def load_kb_dir(path: str | Path) -> dict[str, KnowledgeBase]:
    kbs, problems = check_kb(path)
    errors = [p for p in problems if p.severity == "error"]
    if errors:
        raise KBError(errors)
    return {kb.id: kb for kb in kbs}
