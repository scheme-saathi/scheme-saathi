"""Single-agent baseline (L11): one ReAct agent holding every tool, for comparison with the team.

It uses the same MCP tools (graph/tools.py), the same hash-bound approval gate and the same
model setting as the multi-agent design. Only the structure differs: no supervisor, no specialists.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt

from graph import tools
from graph.workflow import application_hash

MODEL_ENV = "SUPERVISOR_MODEL"
MAX_STEPS = 25
OPENROUTER_URL = "https://openrouter.ai/api/v1"
OUT_OF_STEPS = "need more steps"

SYSTEM_PROMPT = """You are Scheme Saathi, a welfare-scheme assistant. Work alone with the tools you have.
1. find_schemes to list candidate schemes.
2. check_eligibility for each candidate. Trust only this tool for eligibility; never guess.
3. For an eligible scheme, get_documents, then submit_application.
Rules: a "cant_tell" verdict must be reported as can't tell, never as eligible. Cite the clause
for each verdict. Do not ask the user for confirmation yourself: call submit_application directly, because the tool
itself pauses for human approval. Never claim a submission
happened unless the tool says so. Reply briefly with verdicts, clauses and what was submitted."""


def build_model(model_id: str | None = None) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    model_id = model_id or os.environ.get(MODEL_ENV)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not model_id or not key:
        raise RuntimeError(f"Set {MODEL_ENV} and OPENROUTER_API_KEY (see .env.example).")
    return ChatOpenAI(model=model_id, api_key=key, base_url=OPENROUTER_URL, temperature=0)


def build_tools(profile: dict[str, Any]) -> list:
    """The citizen's profile is bound here, so the model cannot invent or alter it."""

    @tool
    def find_schemes() -> list[str]:
        """List the scheme IDs that can be evaluated."""
        return tools.search_schemes(profile)

    @tool
    def check_eligibility(scheme_id: str) -> dict:
        """Evaluate the citizen against one scheme's reviewed rules. Returns verdict, conditions, citations."""
        return tools.evaluate_scheme(profile, scheme_id)

    @tool
    def get_documents(scheme_id: str) -> list[str]:
        """List the documents a scheme requires."""
        return tools.list_documents(scheme_id)

    @tool
    def submit_application(scheme_id: str) -> dict:
        """Submit the application for an eligible scheme. A person must approve the exact form first."""
        form = tools.draft_application(profile, scheme_id)
        current = application_hash(form)
        decision = interrupt({"form": form, "payload_hash": current, "options": ["approve", "reject"]})
        if (isinstance(decision, dict) and decision.get("action") == "approve"
                and decision.get("payload_hash") == current):
            return tools.submit_application(form)
        return {"status": "not submitted", "reason": "approval was rejected or did not match the form"}

    return [find_schemes, check_eligibility, get_documents, submit_application]


def build_baseline(profile: dict[str, Any], model: BaseChatModel | None = None, checkpointer=None):
    return create_react_agent(
        model or build_model(), build_tools(profile), prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer or InMemorySaver(),
    )


def run_baseline(profile: dict[str, Any], thread_id: str, model: BaseChatModel | None = None,
                 max_steps: int = MAX_STEPS, agent=None) -> tuple[Any, dict[str, Any]]:
    """Start a run. Returns (agent, result); result holds an ``__interrupt__`` when awaiting approval."""
    agent = agent or build_baseline(profile, model)
    return agent, _invoke(agent, {"messages": [HumanMessage("Check which schemes I qualify for and apply.")]},
                          thread_id, max_steps)


def resume_baseline(agent, thread_id: str, decision: dict[str, Any], max_steps: int = MAX_STEPS) -> dict[str, Any]:
    return _invoke(agent, Command(resume=decision), thread_id, max_steps)


def _invoke(agent, payload, thread_id: str, max_steps: int) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": max_steps}
    try:
        return agent.invoke(payload, config)
    except GraphRecursionError:
        return {"messages": agent.get_state(config).values.get("messages", []), "budget_exceeded": True}


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    """Metrics for the single-vs-team comparison, read from the message history."""
    messages = result.get("messages", [])
    calls = [c["name"] for m in messages if isinstance(m, AIMessage) for c in m.tool_calls]
    answer = next((m.content for m in reversed(messages) if isinstance(m, AIMessage) and not m.tool_calls), "")
    usage = [m.usage_metadata for m in messages if isinstance(m, AIMessage) and m.usage_metadata]
    return {
        "llm_calls": sum(isinstance(m, AIMessage) for m in messages),
        "tool_calls": calls,
        "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
        "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
        "budget_exceeded": bool(result.get("budget_exceeded")) or OUT_OF_STEPS in str(answer),
        "submitted": any(isinstance(m, ToolMessage) and "submitted (mock)" in str(m.content) for m in messages),
        "awaiting_approval": bool(result.get("__interrupt__")),
        "answer": answer,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-agent baseline demo.")
    parser.add_argument("--citizen", default='{"age": 62, "is_widow": true, "income": 250000}')
    parser.add_argument("--decision", choices=["approve", "reject"], default="approve")
    parser.add_argument("--thread-id", default="baseline-demo")
    args = parser.parse_args()
    profile = json.loads(args.citizen)
    agent, result = run_baseline(profile, args.thread_id)
    if result.get("__interrupt__"):
        pending = result["__interrupt__"][0].value
        print("Approval requested:", json.dumps(pending, indent=2))
        decision = {"action": args.decision, "payload_hash": pending["payload_hash"]}
        result = resume_baseline(agent, args.thread_id, decision)
    print(json.dumps(summarize(result), indent=2, default=str))


if __name__ == "__main__":
    main()
