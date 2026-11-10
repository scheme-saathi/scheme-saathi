"""The Reflexion loop's playbook, lesson retrieval and reflection step (signature challenge A)."""
import importlib.util
import json
from pathlib import Path

import pytest

from agents.rule_reflector import ProposedLesson, Reflection
from evaluation import rule_extraction as rx
from evaluation.playbook import Lesson, Playbook, relevant_lessons, to_store

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "evaluation" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner, reflect_cli = _load("run_rule_extraction"), _load("reflect_rule_extraction")


def lesson(lesson_id, text="Use lt for 'below'.", keywords=("below",), status="proposed"):
    return Lesson(lesson_id=lesson_id, text=text, applies_when="limits worded 'below'", keywords=list(keywords),
                  error_type="wrong_operator", status=status)


def test_only_approved_lessons_reach_the_store():
    book = Playbook()
    book.add_proposals([lesson("L001"), lesson("L002"), lesson("L003")])
    book.review("L001", "approved", "Sharika")
    book.review("L002", "rejected", "Sharika", note="too specific")
    store = to_store(book)
    assert [l["lesson_id"] for l in relevant_lessons(store, "income below Rs 1 lakh")] == ["L001"]
    book.withdraw("L001", "Sharika", "made C25 worse")
    assert relevant_lessons(to_store(book), "income below Rs 1 lakh") == []


def test_a_lesson_needs_a_named_reviewer_and_an_edit_replaces_its_text():
    book = Playbook(lessons=[lesson("L001")])
    with pytest.raises(ValueError, match="named reviewer"):
        book.review("L001", "approved", " ")
    reviewed = book.review("L001", "approved", "Sharika", text="'Below' excludes the limit: use lt.", on="2026-11-10")
    assert (reviewed.text, reviewed.reviewed_by, reviewed.reviewed_on) == ("'Below' excludes the limit: use lt.", "Sharika", "2026-11-10")


def test_only_relevant_lessons_are_retrieved():
    book = Playbook(lessons=[
        lesson("L001", keywords=["below"], status="approved"),
        lesson("L002", text="Exclusions are eq false.", keywords=["not eligible", "excluded"], status="approved"),
        lesson("L003", text="Always cite the clause.", keywords=[], status="approved"),
    ])
    store = to_store(book)
    ids = lambda text, k=5: [l["lesson_id"] for l in relevant_lessons(store, text, k)]
    assert ids("Applicants who are income tax payers are not eligible.") == ["L002", "L003"]
    assert ids("Age between 18 and 40.") == ["L003"]                       # only the always-lesson
    assert ids("Income below 1 lakh; NRIs are excluded and not eligible.") == ["L002", "L001", "L003"]
    assert ids("Income below 1 lakh; NRIs are excluded and not eligible.", k=1) == ["L002"]
    assert ids("The belowground water table") == ["L003"]                   # a word, not a substring


def test_freezing_needs_every_lesson_reviewed_and_locks_the_playbook(tmp_path):
    book = Playbook(lessons=[lesson("L001")])
    with pytest.raises(ValueError, match="review every proposed lesson"):
        book.freeze()
    book.review("L001", "approved", "Sharika")
    version = book.freeze(on="2026-11-12")
    book.check_frozen()
    with pytest.raises(ValueError, match="frozen"):
        book.review("L001", "rejected", "Sharika")
    path = tmp_path / "playbook.json"
    book.save(path)
    changed = json.loads(path.read_text())
    changed["lessons"][0]["text"] = "edited after the freeze"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="changed after it was frozen"):
        Playbook.load(path).check_frozen()
    assert len(version) == 12


def write_playbook(tmp_path, frozen):
    book = Playbook(lessons=[lesson("L001", text="An exclusion is eq false.", keywords=[], status="approved")])
    if frozen:
        book.freeze()
    path = tmp_path / "playbook.json"
    book.save(path)
    return {"name": "rx1_test", "system": "rule_extractor", "playbook": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)}


def test_the_runner_passes_relevant_lessons_and_the_final_run_needs_a_frozen_playbook(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", Path("/"))  # config paths in tmp_path are absolute
    seen = []

    def extract(value, lessons):
        seen.append(lessons)
        return rx.gold_as_draft(rx.load_gold(value["scheme_id"]), value["clauses"])

    config = write_playbook(tmp_path, frozen=False)
    rows, summary = runner.run(config, "development", limit=2, extract=extract, quiet=True)
    assert seen == [["An exclusion is eq false."]] * 2 and rows[0]["lessons"] == ["L001"]
    assert summary["lessons_by_id"] == {"L001": 2}
    with pytest.raises(ValueError, match="not frozen"):
        runner.run(config, "held_out", limit=1, extract=extract, quiet=True, final=True)
    runner.run(write_playbook(tmp_path, frozen=True), "held_out", limit=1, extract=extract, quiet=True, final=True)


def fake_run(tmp_path, split="development"):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rows = []
    for sid in ("C09", "C03"):
        gold = rx.load_gold(sid)
        clauses = rx.source_clauses(rx.load_scheme(sid))
        draft = rx.gold_as_draft(gold, clauses)
        for rule in draft["rules"]:
            if rule["value"] is False:
                rule["value"] = True  # the polarity mistake from the baseline
        rows.append({"scheme_id": sid, "error": None, "score": rx.score(draft, gold, clauses)})
    rows.append({"scheme_id": "C07", "error": "LengthFinishReasonError", "score": {"errors": [{"type": "missing_rule"}]}})
    (run_dir / "schemes.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (run_dir / "summary.json").write_text(json.dumps({"split": split, "summary": {}}))
    return run_dir


def test_reflection_proposes_lessons_per_error_type_for_review(tmp_path):
    seen = []

    def reflect(value):
        seen.append(value)
        return Reflection(lessons=[ProposedLesson(text="An exclusion is a rule that the person is not X: eq false.",
                                                  applies_when="an exclusion clause", keywords=["not eligible"],
                                                  examples=["C09"])], doubts=["check M09 elig-6"])

    book = Playbook(lessons=[lesson("L001", status="approved")])
    proposals, report = reflect_cli.propose(fake_run(tmp_path), book, reflect=reflect, today="2026-11-10")
    assert [v.error_type for v in seen] == ["wrong_value"]  # one call per error type
    assert {e.scheme_id for e in seen[0].examples} == {"C09", "C03"}  # failed C07 call is left out
    assert seen[0].existing_lessons == ["Use lt for 'below'."]
    assert [p.lesson_id for p in proposals] == ["L002"] and book.get("L002").status == "proposed"
    assert report["doubts"] == ["wrong_value: check M09 elig-6"]
    assert relevant_lessons(to_store(book), "not eligible") == []  # not until a person approves it


def test_reflection_refuses_a_held_out_run(tmp_path):
    with pytest.raises(ValueError, match="development schemes only"):
        reflect_cli.propose(fake_run(tmp_path, split="held_out"), Playbook(), reflect=lambda v: Reflection())


def test_the_extractor_drops_exact_duplicates():
    from langchain_core.runnables import RunnableLambda
    from agents.rule_extractor import RuleExtractor

    age = {"field": "age", "op": "lt", "value": 60, "clause_id": "elig-9", "or_conditions": []}

    class FakeModel:
        def with_structured_output(self, schema):
            return RunnableLambda(lambda prompt: {"clauses": [
                {"clause_id": "elig-9", "rules": [age], "note": ""},
                {"clause_id": "elig-10", "rules": [{**age, "clause_id": "elig-10"}], "note": ""}]})

    rules = RuleExtractor(FakeModel()).extract(rx.extraction_input("C07")).rules
    assert [(r.field, r.clause_id) for r in rules] == [("age", "elig-9")]


def test_the_committed_playbook_loads_and_holds_no_unreviewed_approval():
    book = Playbook.load()
    assert all(l.reviewed_by for l in book.lessons if l.status in ("approved", "rejected", "withdrawn"))


def test_common_keywords_are_removed_and_flagged():
    kept, flags = reflect_cli.checked_keywords(["or", "Priority", "must be"])
    assert kept == ["priority"] and flags == ["common keywords removed: or, must be"]
    kept, flags = reflect_cli.checked_keywords(["all", "every", "must"])
    assert kept == [] and "every scheme" in flags[-1]
    assert reflect_cli.checked_keywords([]) == ([], [])


def test_reflection_flags_generic_lessons_and_more_extra_rule_examples(tmp_path):
    def reflect(value):
        return Reflection(lessons=[ProposedLesson(text="x", applies_when="y", keywords=["is", "not"], examples=["C09"])])
    proposals, _ = reflect_cli.propose(fake_run(tmp_path), Playbook(), reflect=reflect)
    assert proposals[0].keywords == [] and "based on one scheme only" in proposals[0].flags
    assert reflect_cli.MAX_EXAMPLES_BY_TYPE["extra_rule"] > reflect_cli.MAX_EXAMPLES


def test_unreviewed_proposals_can_be_discarded_before_reflecting_again():
    book = Playbook(lessons=[lesson("L001", status="approved"), lesson("L002"), lesson("L003")])
    assert book.discard_proposed() == ["L002", "L003"]
    assert [l.lesson_id for l in book.lessons] == ["L001"]


def test_a_runaway_extraction_is_tried_once_more():
    from langchain_core.runnables import RunnableLambda
    from agents.rule_extractor import RuleExtractor

    class LengthFinishReasonError(Exception):
        pass

    calls = []

    def answer(prompt):
        calls.append(1)
        if len(calls) == 1:
            raise LengthFinishReasonError("length limit reached")
        return {"clauses": [{"clause_id": "elig-1", "rules": [], "note": "heading"}]}

    class FakeModel:
        def with_structured_output(self, schema):
            return RunnableLambda(answer)

    RuleExtractor(FakeModel()).extract(rx.extraction_input("M14"))
    assert len(calls) == 2


def test_the_reflection_model_can_be_chosen_separately(monkeypatch):
    seen = {}
    monkeypatch.setenv("SUPERVISOR_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("REFLECTION_MODEL", "openai/gpt-4o")
    monkeypatch.setattr("agents.model_factory.create_chat_model",
                        lambda role: seen.setdefault("model", __import__("os").environ["SUPERVISOR_MODEL"]) and None)
    monkeypatch.setattr("agents.rule_reflector.RuleReflector.__init__", lambda self, model: None)
    reflect_cli.default_reflector()
    assert seen["model"] == "openai/gpt-4o"
    assert __import__("os").environ["SUPERVISOR_MODEL"] == "openai/gpt-4o-mini"  # restored


review_cli = _load("review_lessons")


def test_review_decisions_apply_edits_and_must_cover_every_proposal():
    book = Playbook(lessons=[lesson("L001"), lesson("L002")])
    with pytest.raises(ValueError, match="missing"):
        review_cli.apply(book, [{"lesson_id": "L001", "decision": "approved"}], "Sharika", "2026-11-10")
    assert all(l.status == "proposed" for l in book.lessons)  # nothing changed
    lines = review_cli.apply(book, [
        {"lesson_id": "L001", "decision": "approved", "text": "Edited.", "keywords": ["Below", " "]},
        {"lesson_id": "L002", "decision": "rejected", "note": "vague"},
    ], "Sharika", "2026-11-10")
    assert lines == ["L001: approved (edited)", "L002: rejected"]
    assert (book.get("L001").text, book.get("L001").keywords) == ("Edited.", ["below"])
    assert (book.get("L002").review_note, book.get("L002").reviewed_by) == ("vague", "Sharika")

