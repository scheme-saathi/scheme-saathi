import json
from pathlib import Path

import pytest
from langgraph.types import Command

from graph import mock_tools
from graph.workflow import build_graph

ROOT = Path(__file__).resolve().parents[1]
KHADI_OK = {"is_khadi_registered": True, "age": 40, "has_valid_id": True,
            "family_member_already_beneficiary": False, "availed_other_scheme_same_purpose": False}


@pytest.fixture
def reviewed_khadi(tmp_path, monkeypatch):
    record = json.loads((ROOT / "data/rules/C10.json").read_text())
    for rule in record["rules"]:
        rule["status"] = "reviewed"
    (tmp_path / "C10.json").write_text(json.dumps(record))
    monkeypatch.setattr(mock_tools, "RULE_DIRS", [ROOT / "data/schemes", tmp_path])


def run(citizen, scheme_ids=None, thread="t"):
    graph = build_graph()
    config = {"configurable": {"thread_id": thread}}
    payload = {"simulated_citizen": citizen, **({"scheme_ids": scheme_ids} if scheme_ids else {})}
    return graph, config, graph.invoke(payload, config)


def test_default_search_only_uses_fully_reviewed_schemes():
    assert mock_tools.search_schemes({}) == ["SYNTH-PENSION-001"]


def test_draft_rules_are_valid_but_fail_closed():
    assert mock_tools.search_schemes({}, ["C10"]) == ["C10"]
    _, _, state = run(KHADI_OK, ["C10"])
    assert state["verdicts"]["C10"]["verdict"] == "cant_tell"
    assert "__interrupt__" not in state


def test_unknown_scheme_is_rejected():
    with pytest.raises(ValueError, match="NOPE"):
        mock_tools.search_schemes({}, ["NOPE"])


def test_reviewed_scheme_is_discovered_and_asks_only_its_own_questions(reviewed_khadi):
    assert mock_tools.search_schemes({}) == ["SYNTH-PENSION-001", "C10"]
    graph, config, state = run(KHADI_OK, ["C10"])
    assert state["verdicts"]["C10"]["verdict"] == "eligible"
    assert state["questions_asked"] == 5
    assert set(state["profile"]) == set(KHADI_OK)
    h = graph.get_state(config).tasks[0].interrupts[0].value["payload_hash"]
    final = graph.invoke(Command(resume={"action": "approve", "payload_hash": h}), config)
    assert final["submission"]["scheme_id"] == "C10"


def test_reviewed_scheme_rejects_out_of_range_age(reviewed_khadi):
    _, _, state = run({**KHADI_OK, "age": 60}, ["C10"])
    assert state["verdicts"]["C10"]["verdict"] == "not_eligible"
    assert "__interrupt__" not in state


def test_no_matching_schemes_ends_without_error(monkeypatch):
    monkeypatch.setattr(mock_tools, "RULE_DIRS", [ROOT / "data/rules"])
    _, _, state = run({"age": 30})
    assert state["verdicts"] == {} and "__interrupt__" not in state
