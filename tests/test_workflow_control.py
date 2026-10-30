import pytest
from langgraph.types import Command

from graph import mock_tools, workflow
from graph.workflow import MAX_DRAFT_ATTEMPTS, application_hash, build_graph

CITIZEN = {"age": 62, "is_widow": True, "income": 250000}


def start(thread):
    graph = build_graph()
    config = {"configurable": {"thread_id": thread}}
    return graph, config, graph.invoke({"simulated_citizen": CITIZEN}, config)


def pending(graph, config):
    return graph.get_state(config).tasks[0].interrupts[0].value


def test_interrupt_offers_options_and_a_hash_of_the_exact_form():
    graph, config, state = start("opts")
    prompt = state["__interrupt__"][0].value
    assert prompt["options"] == ["approve", "edit", "reject"]
    assert prompt["payload_hash"] == application_hash(prompt["form"])


def test_approval_without_a_hash_is_not_accepted():
    graph, config, _ = start("nohash")
    final = graph.invoke(Command(resume={"approved": True}), config)
    assert final["approval_status"] == "invalid" and final.get("submission") is None


def test_approval_of_a_different_form_is_not_accepted():
    graph, config, _ = start("wronghash")
    final = graph.invoke(Command(resume={"action": "approve", "payload_hash": "0" * 64}), config)
    assert final["approval_status"] == "invalid" and final.get("submission") is None


def test_edit_invalidates_the_earlier_approval_and_needs_a_new_one():
    graph, config, _ = start("edit")
    old_hash = pending(graph, config)["payload_hash"]
    state = graph.invoke(Command(resume={"action": "edit", "changes": {"income": 200000}}), config)
    prompt = state["__interrupt__"][0].value
    assert prompt["form"]["applicant"]["income"] == 200000
    assert prompt["payload_hash"] != old_hash
    stale = graph.invoke(Command(resume={"action": "approve", "payload_hash": old_hash}), config)
    assert stale["approval_status"] == "invalid" and stale.get("submission") is None


def test_edit_then_approval_of_the_new_form_submits():
    graph, config, _ = start("edit-ok")
    state = graph.invoke(Command(resume={"action": "edit", "changes": {"income": 200000}}), config)
    new_hash = state["__interrupt__"][0].value["payload_hash"]
    final = graph.invoke(Command(resume={"action": "approve", "payload_hash": new_hash}), config)
    assert final["submission"]["status"].startswith("submitted")
    assert final["submission"]["scheme_id"] == "SYNTH-PENSION-001"


def test_edit_that_breaks_eligibility_never_reaches_approval_again():
    graph, config, _ = start("edit-bad")
    final = graph.invoke(Command(resume={"action": "edit", "changes": {"income": 900000}}), config)
    assert "__interrupt__" not in final and final["application"] == {}
    assert final["verdicts"]["SYNTH-PENSION-001"]["verdict"] == "not_eligible"


def test_submit_refuses_a_form_that_changed_after_approval():
    approved = {"scheme_id": "SYNTH-PENSION-001", "applicant": CITIZEN}
    changed = {"scheme_id": "SYNTH-PENSION-001", "applicant": {**CITIZEN, "age": 99}}
    ok = workflow.submit_node({"application": approved, "approved_hash": application_hash(approved)})
    assert ok["submission"]["status"].startswith("submitted")
    blocked = workflow.submit_node({"application": changed, "approved_hash": application_hash(approved)})
    assert blocked == {"approved": False, "approval_status": "invalid"}


def faulty_then_correct(fail_times):
    calls = {"n": 0}
    real = mock_tools.draft_application

    def draft(profile, scheme_id):
        calls["n"] += 1
        application = real(profile, scheme_id)
        if calls["n"] <= fail_times:
            application["applicant"] = {**application["applicant"], "income": 1}
        return application

    return draft, calls


def test_self_correction_loop_redrafts_until_the_checker_passes(monkeypatch):
    draft, calls = faulty_then_correct(fail_times=2)
    monkeypatch.setattr(mock_tools, "draft_application", draft)
    graph, config, state = start("loop")
    assert calls["n"] == 3 and state["draft_attempts"] == 3
    assert state["critique"] == []
    assert state["__interrupt__"][0].value["form"]["applicant"]["income"] == 250000


def test_loop_is_bounded_and_escalates_to_a_person(monkeypatch):
    draft, calls = faulty_then_correct(fail_times=99)
    monkeypatch.setattr(mock_tools, "draft_application", draft)
    graph, config, state = start("bounded")
    assert calls["n"] == MAX_DRAFT_ATTEMPTS
    assert state["needs_human"] is True and "__interrupt__" not in state
    assert any("income" in problem for problem in state["critique"])


def test_checker_flags_wrong_scheme_and_missing_fields():
    state = {"verdicts": {"SYNTH-PENSION-001": {"verdict": "eligible"}}, "profile": CITIZEN,
             "application": {"scheme_id": "OTHER", "applicant": {"age": 62}}}
    problems = workflow.check_application(state)
    assert any("OTHER" in p for p in problems)
    state["application"] = {"scheme_id": "SYNTH-PENSION-001", "applicant": {"age": 62}}
    assert any("is_widow" in p for p in workflow.check_application(state))
