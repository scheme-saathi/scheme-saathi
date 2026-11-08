"""The memory evaluation harness: persona answers, pass/fail gates, summary figures and the CLI."""

import json

import pytest

from agents.contracts import IntakeAskInput, IntakeExtractInput
from agents.memory_service import HouseholdAllowlist
from evaluation import memory_eval
from evaluation.memory_eval import (
    Case,
    CaseResult,
    Outcome,
    PersonaIntake,
    evaluate,
    evaluate_case,
    external_cases,
    household_cases,
    persona_facts,
    schemes_that_use_memory,
    summarise,
    write_report,
)

ALLOWLIST = HouseholdAllowlist.from_policy_file()
FACTS = {"age": 70, "annual_income": 40000, "is_maharashtra_resident": True, "is_indian_citizen": True}


def outcome(questions=(), confirmations=1, verdict="eligible", prefilled=(), saved=()):
    return Outcome(list(questions), confirmations, list(prefilled), list(saved), verdict)


# The stand-in for the intake model


def test_the_persona_answers_only_from_its_own_facts():
    intake = PersonaIntake({"age": 70})
    assert intake.extract(IntakeExtractInput(request="hi"), {}).facts == {}
    assert intake.extract(IntakeExtractInput(request="70", pending_field="age"), {}).facts == {"age": 70}
    unknown = intake.extract(IntakeExtractInput(request="?", pending_field="annual_income"), {})
    assert unknown.dont_know and unknown.facts == {}
    assert intake.reply("age") == "70" and intake.reply("annual_income") == "I don't know"


def test_every_question_is_counted():
    intake = PersonaIntake({})
    intake.ask(IntakeAskInput(field="age", field_type="number", request="hi"))
    intake.ask(IntakeAskInput(field="is_widow", field_type="bool", request="hi"))
    assert intake.questions == ["age", "is_widow"]


# The cases


def test_a_household_test_case_becomes_rule_fields_and_unknowns_stay_unknown():
    facts = persona_facts(
        {
            "state": "Maharashtra",
            "profile_facts": {"respondent_age": 46, "approx_annual_household_income_inr": 120000, "household_size": None},
        }
    )
    assert facts == {
        "is_indian_citizen": True,
        "age": 46,
        "annual_income": 120000,
        "annual_family_income": 120000,
        "is_maharashtra_resident": True,
    }
    assert persona_facts({"state": "Gujarat", "profile_facts": {}}) == {
        "is_indian_citizen": True,
        "is_maharashtra_resident": False,
    }


def test_the_development_set_comes_from_the_repository_households():
    cases = household_cases()
    assert len(cases) > 10
    assert all("age" in c.facts or "annual_income" in c.facts for c in cases)
    assert len(household_cases(3)) == 3


def test_external_cases_are_read_from_a_file_and_an_empty_file_is_refused(tmp_path):
    path = tmp_path / "held_out.json"
    path.write_text(json.dumps([{"case_id": "H1", "facts": FACTS}]), encoding="utf-8")
    assert external_cases(path) == [Case("H1", FACTS)]
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        external_cases(path)


def test_only_schemes_that_ask_for_a_field_memory_may_keep_are_chosen():
    chosen = schemes_that_use_memory(ALLOWLIST, 3)
    assert 0 < len(chosen) <= 3


# The gates and the figures


def stub_sessions(monkeypatch, first, on, off):
    visits = iter([first, on, off])
    monkeypatch.setattr(memory_eval, "run_session", lambda *args, **kwargs: next(visits))


def test_a_clean_case_passes_and_counts_the_questions_saved(monkeypatch):
    stub_sessions(
        monkeypatch,
        first=outcome(["age", "annual_income"], saved=["age", "annual_income"]),
        on=outcome([], prefilled=["age", "annual_income"]),
        off=outcome(["age", "annual_income"]),
    )
    result = evaluate_case(Case("c", FACTS), "C01", ALLOWLIST)
    assert result.failures == [] and result.completed
    summary = summarise([result])
    assert (summary["questions_return_without_memory"], summary["questions_return_with_memory"]) == (2, 0)
    assert (summary["questions_saved"], summary["reduction_percent"]) == (2, 100.0)
    assert summary["prefilled_fields"] == {"age": 1, "annual_income": 1}
    assert summary["failed_runs"] == 0


def test_a_verdict_that_changes_with_memory_fails_the_run(monkeypatch):
    stub_sessions(monkeypatch, first=outcome(["age"]), on=outcome([], verdict="eligible"), off=outcome(["age"], verdict="not_eligible"))
    result = evaluate_case(Case("c", FACTS), "C01", ALLOWLIST)
    assert any("verdict changed" in f for f in result.failures)
    assert summarise([result])["failed_runs"] == 1


def test_memory_that_adds_questions_fails_the_run(monkeypatch):
    stub_sessions(monkeypatch, first=outcome(["age"]), on=outcome(["age", "annual_income"]), off=outcome(["age"]))
    assert any("more questions" in f for f in evaluate_case(Case("c", FACTS), "C01", ALLOWLIST).failures)


def test_an_inconsistent_control_fails_the_run(monkeypatch):
    stub_sessions(monkeypatch, first=outcome(["age"]), on=outcome([]), off=outcome(["annual_income"]))
    assert any("control" in f for f in evaluate_case(Case("c", FACTS), "C01", ALLOWLIST).failures)


def test_a_first_visit_that_stops_early_is_counted_but_never_compared(monkeypatch):
    stub_sessions(monkeypatch, first=outcome(["age"], confirmations=0, verdict="cant_tell"), on=None, off=None)
    result = evaluate_case(Case("c", FACTS), "C01", ALLOWLIST)
    assert not result.completed and result.return_with_memory is None
    summary = summarise([result])
    assert (summary["first_visits"], summary["first_visits_stopped_early"], summary["runs"]) == (1, 1, 0)
    assert summary["reduction_percent"] == 0.0


def test_the_summary_of_no_results_does_not_divide_by_zero():
    assert summarise([])["runs"] == 0


def test_the_report_is_written_as_json(tmp_path):
    result = CaseResult("c", "C01", outcome(["age"]), outcome([]), outcome(["age"]))
    path = write_report([result], summarise([result]), tmp_path / "runs")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["summary"]["runs"] == 1 and report["results"][0]["case_id"] == "c"


# The real graph, rule engine and memory policy


def test_a_returning_person_is_never_worse_off_and_the_verdict_never_changes():
    seen = []
    results = evaluate(
        [Case("T1", FACTS)],
        schemes_that_use_memory(ALLOWLIST),
        per_case=1,
        progress=lambda *args: seen.append(args),
    )
    summary = summarise(results)

    assert seen and seen[0][:3] == (1, 1, "T1")
    assert summary["failed_runs"] == 0
    assert summary["runs"] >= 1  # the facts settle at least one scheme, so there is something to compare
    assert summary["questions_return_with_memory"] <= summary["questions_return_without_memory"]


def test_the_command_line_runs_held_out_cases_and_prints_the_figures(tmp_path, capsys):
    path = tmp_path / "held_out.json"
    path.write_text(json.dumps([{"case_id": "H1", "facts": FACTS}]), encoding="utf-8")

    code = memory_eval.main(["--cases", str(path), "--schemes", "1", "--no-report", "--quiet"])

    assert code == 0
    assert '"failed_runs": 0' in capsys.readouterr().out


def test_the_command_line_writes_a_report_and_shows_progress(tmp_path, capsys):
    path = tmp_path / "held_out.json"
    path.write_text(json.dumps([{"case_id": "H1", "facts": FACTS}]), encoding="utf-8")

    code = memory_eval.main(["--cases", str(path), "--schemes", "1", "--out", str(tmp_path / "out")])

    printed = capsys.readouterr().out
    assert code == 0 and "[1/1] H1:" in printed and "Report:" in printed
    assert len(list((tmp_path / "out").glob("memory_eval_*.json"))) == 1


def test_the_command_line_fails_when_a_run_fails(tmp_path, monkeypatch):
    path = tmp_path / "held_out.json"
    path.write_text(json.dumps([{"case_id": "H1", "facts": FACTS}]), encoding="utf-8")
    stub_sessions(monkeypatch, first=outcome(["age"]), on=outcome([], verdict="eligible"), off=outcome(["age"], verdict="not_eligible"))
    monkeypatch.setattr(memory_eval, "schemes_that_use_memory", lambda allowlist, limit=None: ["C01"])
    assert memory_eval.main(["--cases", str(path), "--schemes", "1", "--no-report", "--quiet"]) == 1
