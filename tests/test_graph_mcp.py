import pytest
from langgraph.types import Command

from graph import tools
from graph.workflow import build_graph
from servers.rule_engine.server import evaluate_profile, get_rule_fields, list_rule_schemes

CITIZEN = {"age": 62, "is_widow": True, "income": 250000}


@pytest.fixture
def calls(monkeypatch):
    log = []
    real = tools.call_tool

    def spy(server, tool, **args):
        log.append((server, tool))
        return real(server, tool, **args)

    monkeypatch.setattr(tools, "call_tool", spy)
    return log


def test_graph_reads_through_mcp_and_writes_only_after_approval(calls):
    graph = build_graph()
    config = {"configurable": {"thread_id": "mcp-1"}}
    graph.invoke({"simulated_citizen": CITIZEN}, config)
    assert calls and not any(tool == "create_application" for _, tool in calls)
    assert {server for server, _ in calls} <= {"schemes-kb", "rule-engine", "doc-check", "mock-portal"}
    value = graph.get_state(config).tasks[0].interrupts[0].value
    final = graph.invoke(Command(resume={"action": "approve", "payload_hash": value["payload_hash"]}), config)
    assert ("mock-portal", "create_application") in calls
    assert "submitted" in str(final)


def test_rejection_never_reaches_the_portal(calls):
    graph = build_graph()
    config = {"configurable": {"thread_id": "mcp-2"}}
    graph.invoke({"simulated_citizen": CITIZEN}, config)
    graph.invoke(Command(resume={"action": "reject"}), config)
    assert ("mock-portal", "create_application") not in calls


def test_unknown_scheme_is_a_tool_error():
    with pytest.raises(tools.ToolCallError, match="NOPE"):
        tools.required_fields(["NOPE"])


def test_rule_tools_are_read_only_and_evaluate_reviewed_rules():
    listing = list_rule_schemes()
    assert listing["ok"] and listing["access"] == "read"
    assert get_rule_fields(["C02"], include_draft=True)["ok"]
    live = evaluate_profile({"age": 40, "age_nearer_birthday": 40, "has_bank_account": True, "consents_to_auto_debit": True}, "C02")
    assert live["ok"]
    assert live["data"]["verdict"] == "eligible"
    rejected_preview = evaluate_profile(
        {"age": 40, "age_nearer_birthday": 40, "has_bank_account": True, "consents_to_auto_debit": True},
        "C02",
        include_draft=True,
    )
    assert rejected_preview["error"]["code"] == "draft_rules_not_allowed"
    with tools.acting_as("rule_reviewer"):
        preview = tools.evaluate_scheme(
            {"age": 40, "age_nearer_birthday": 40, "has_bank_account": True, "consents_to_auto_debit": True},
            "C02",
            include_draft=True,
        )
    assert preview["verdict"] == "eligible"


def test_only_the_rule_reviewer_can_preview_draft_rules():
    with tools.acting_as("eligibility"), pytest.raises(tools.ToolCallError, match="rule reviewer"):
        tools.evaluate_scheme({"age": 40}, "C02", include_draft=True)
