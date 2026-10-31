from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from graph import baseline, tools

CITIZEN = {"age": 62, "is_widow": True, "income": 250000}
SCHEME = "SYNTH-PENSION-001"


class ScriptedModel(BaseChatModel):
    """Replays fixed replies so the agent loop can be tested without an API key."""

    script: list[AIMessage]
    position: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, *args: Any, **kwargs: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self.script[min(self.position, len(self.script) - 1)]
        reply = reply.model_copy(update={"id": None, "tool_calls": [
            {**c, "id": f"{c['id']}-{self.position}"} for c in reply.tool_calls]})
        self.position += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])


def call(name: str, args: dict | None = None, ident: str = "1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": ident}],
                     usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


def happy_script() -> list[AIMessage]:
    return [call("find_schemes", ident="a"), call("check_eligibility", {"scheme_id": SCHEME}, "b"),
            call("get_documents", {"scheme_id": SCHEME}, "c"), call("submit_application", {"scheme_id": SCHEME}, "d"),
            AIMessage(content=f"Eligible for {SCHEME}; submitted.")]


def test_baseline_pauses_for_approval_and_nothing_is_written_yet(monkeypatch):
    written = []
    monkeypatch.setattr(tools, "submit_application", lambda form: written.append(form) or {"status": "x"})
    _, result = baseline.run_baseline(CITIZEN, "b1", ScriptedModel(script=happy_script()))
    assert result["__interrupt__"] and not written
    pending = result["__interrupt__"][0].value
    assert pending["form"]["scheme_id"] == SCHEME and len(pending["payload_hash"]) == 64


def test_approval_with_the_right_hash_submits_through_the_portal():
    agent, result = baseline.run_baseline(CITIZEN, "b2", ScriptedModel(script=happy_script()))
    pending = result["__interrupt__"][0].value
    final = baseline.resume_baseline(agent, "b2", {"action": "approve", "payload_hash": pending["payload_hash"]})
    summary = baseline.summarize(final)
    assert "submitted (mock)" in str(final["messages"])
    assert summary["tool_calls"] == ["find_schemes", "check_eligibility", "get_documents", "submit_application"]
    assert summary["llm_calls"] == 5 and summary["input_tokens"] == 40 and not summary["budget_exceeded"]


@pytest.mark.parametrize("decision", [{"action": "reject"}, {"action": "approve", "payload_hash": "0" * 64},
                                      {"approved": True}])
def test_rejected_or_mismatched_approval_never_submits(monkeypatch, decision):
    written = []
    monkeypatch.setattr(tools, "submit_application", lambda form: written.append(form) or {"status": "x"})
    agent, _ = baseline.run_baseline(CITIZEN, "b3", ScriptedModel(script=happy_script()))
    final = baseline.resume_baseline(agent, "b3", decision)
    assert not written and "not submitted" in str(final["messages"])


def test_the_step_budget_stops_a_looping_agent():
    looping = ScriptedModel(script=[call("find_schemes")])
    _, result = baseline.run_baseline(CITIZEN, "b4", looping, max_steps=6)
    assert baseline.summarize(result)["budget_exceeded"]


def test_the_agent_cannot_change_the_profile():
    names = [t.name for t in baseline.build_tools(CITIZEN)]
    assert names == ["find_schemes", "check_eligibility", "get_documents", "submit_application"]
    for t in baseline.build_tools(CITIZEN):
        assert "profile" not in t.args and "include_draft" not in t.args


def test_missing_model_settings_give_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SUPERVISOR_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="SUPERVISOR_MODEL"):
        baseline.build_model()
