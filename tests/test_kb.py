from __future__ import annotations

from pathlib import Path

import pytest

from jibu.kb import KBError, KnowledgeBase, check_kb, load_kb, load_kb_dir

GOOD = """
organisation:
  id: demo-org
  name: Demo
  welcome: {en: "Hi", sw: "Habari"}
  starters: [hours]
handoff: {en: "Call {phone}", sw: "Piga {phone}"}
synonyms:
  - [open, fungua]
entries:
  - id: hours
    tags: [hours]
    questions:
      en: ["What time do you open?", "Opening hours?"]
      sw: ["Mnafungua saa ngapi?", "Saa za kazi?"]
    answer: {en: "We open at 8:00 every day.", sw: "Tunafungua saa 8:00 kila siku."}
"""


def write(tmp_path: Path, text: str, name: str = "kb.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def errors(path: Path) -> list[str]:
    _, problems = check_kb(path)
    return [str(p) for p in problems if p.severity == "error"]


def test_sample_knowledge_bases_are_valid(kbs: dict[str, KnowledgeBase]) -> None:
    assert set(kbs) == {"umoja-sacco", "afya-clinic"}
    assert len(kbs["umoja-sacco"].entries) >= 30
    for kb in kbs.values():
        for e in kb.entries:
            assert e.questions.en and e.questions.sw and e.answer.en and e.answer.sw


def test_minimal_valid_file_loads(tmp_path: Path) -> None:
    kb = load_kb(write(tmp_path, GOOD))
    assert kb.id == "demo-org"
    assert errors(tmp_path / "kb.yaml") == []


def test_unknown_key_is_reported_with_line_number(tmp_path: Path) -> None:
    bad = GOOD.replace("answer: {en", "anwser: {en")
    msgs = errors(write(tmp_path, bad))
    assert any("unknown key" in m and "anwser" in m for m in msgs)
    assert any(":16:" in m for m in msgs)  # the line of the misspelt key


def test_missing_swahili_answer(tmp_path: Path) -> None:
    bad = GOOD.replace(', sw: "Tunafungua saa 8:00 kila siku."', "")
    msgs = errors(write(tmp_path, bad))
    assert any("answer.sw" in m and "required" in m for m in msgs)


def test_empty_question_list(tmp_path: Path) -> None:
    bad = GOOD.replace('sw: ["Mnafungua saa ngapi?", "Saa za kazi?"]', "sw: []")
    assert any("questions.sw" in m for m in errors(write(tmp_path, bad)))


def test_duplicate_ids_and_dangling_follow_ups(tmp_path: Path) -> None:
    extra = """
  - id: hours
    tags: [dup]
    follow_ups: [ghost]
    questions: {en: ["Another question?"], sw: ["Swali lingine?"]}
    answer: {en: "Some answer here.", sw: "Jibu fulani hapa."}
"""
    msgs = errors(write(tmp_path, GOOD + extra))
    assert any("duplicate id" in m for m in msgs)
    assert any("unknown entry 'ghost'" in m for m in msgs)


def test_bad_slug_and_dates(tmp_path: Path) -> None:
    bad = GOOD.replace("id: hours", "id: Bad Id").replace("starters: [hours]", "starters: []")
    assert any("slug" in m for m in errors(write(tmp_path, bad)))
    dated = GOOD.replace(
        "    tags: [hours]",
        "    tags: [hours]\n    valid_from: 2026-05-01\n    valid_until: 2026-01-01",
    )
    assert any("valid_until is earlier" in m for m in errors(write(tmp_path, dated)))


def test_unknown_handoff_placeholder_and_starter(tmp_path: Path) -> None:
    bad = GOOD.replace("Call {phone}", "Call {fax}").replace(
        "starters: [hours]", "starters: [nope]"
    )
    msgs = errors(write(tmp_path, bad))
    assert any("{fax}" in m for m in msgs)
    assert any("starters" in m and "nope" in m for m in msgs)


def test_yaml_syntax_error_has_line(tmp_path: Path) -> None:
    msgs = errors(write(tmp_path, "organisation: [unclosed\nentries: {"))
    assert msgs and "YAML syntax error" in msgs[0]


def test_top_level_must_be_mapping_and_missing_file(tmp_path: Path) -> None:
    assert errors(write(tmp_path, "- just\n- a list")) != []
    assert any("cannot read" in m for m in errors(tmp_path / "missing.yaml"))
    (tmp_path / "empty-dir").mkdir()
    assert any("no .yaml" in m for m in errors(tmp_path / "empty-dir"))


def test_warnings_do_not_fail_loading(tmp_path: Path) -> None:
    weak = GOOD.replace("tags: [hours]", "tags: []")
    kb = load_kb(write(tmp_path, weak))
    assert any("no tags" in w.message for w in kb.warnings)


def test_duplicate_question_across_entries_warns(tmp_path: Path) -> None:
    extra = """
  - id: hours-copy
    tags: [xx]
    questions: {en: ["Opening hours?", "q2?", "q3?"], sw: ["Saa za kazi?", "s2?"]}
    answer: {en: "Same sort of answer.", sw: "Jibu la aina hiyo."}
"""
    _, problems = check_kb(write(tmp_path, GOOD + extra))
    assert any("also used by entry" in p.message for p in problems if p.severity == "warning")


def test_directory_with_one_bad_file_raises_listing_it(tmp_path: Path) -> None:
    write(tmp_path, GOOD, "a.yaml")
    write(tmp_path, GOOD.replace("handoff:", "handof:"), "b.yaml")
    with pytest.raises(KBError) as exc:
        load_kb_dir(tmp_path)
    assert "b.yaml" in str(exc.value)


def test_same_organisation_id_in_two_files(tmp_path: Path) -> None:
    write(tmp_path, GOOD, "a.yaml")
    write(tmp_path, GOOD, "b.yaml")
    assert any("already used" in m for m in errors(tmp_path))


def test_handoff_text_fills_contact_placeholders(sacco_kb: KnowledgeBase) -> None:
    en = sacco_kb.handoff_text("en")
    assert "0700 000 001" in en and "{" not in en
    assert "Jumatatu" in sacco_kb.handoff_text("sw")
