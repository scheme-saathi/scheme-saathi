"""The graph's tool layer: every call goes through the FastMCP servers in servers/*.

Servers are reached over FastMCP's in-memory transport, so requests, schemas and structured
errors are exactly what an out-of-process client would see. Failed tools raise ToolCallError.
"""

import asyncio
import concurrent.futures
import json
import logging
import time
from collections.abc import AsyncIterator, Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any

from fastmcp import Client

from servers.mock_portal.authorization import (
    CapabilityError,
    application_payload_hash,
    issue_write_capability,
)
from servers.doc_check.server import mcp as doc_check_server  # noqa: F401  (registered for later agents)
from servers.mock_portal.server import mcp as portal_server
from servers.rule_engine.server import mcp as rule_server
from servers.schemes_kb.server import mcp as kb_server

logger = logging.getLogger(__name__)

RULE_ENGINE = "rule-engine"
SCHEMES_KB = "schemes-kb"
MOCK_PORTAL = "mock-portal"
_SERVERS = {RULE_ENGINE: rule_server, SCHEMES_KB: kb_server, MOCK_PORTAL: portal_server}
DEFAULT_TOOL_CALL_BUDGET = 40
_KNOWN_ACTORS = {"application", "baseline", "document_checker", "eligibility", "intake", "supervisor"}

# Pre-tool hook: only these agents may call a write tool. "baseline" is the single-agent
# comparison run, which is deliberately given every tool.
READ_TOOLS = {
    (RULE_ENGINE, "list_rule_schemes"),
    (RULE_ENGINE, "get_rule_fields"),
    (RULE_ENGINE, "get_field_specs"),
    (RULE_ENGINE, "evaluate_profile"),
    (SCHEMES_KB, "search_schemes"),
    (SCHEMES_KB, "get_scheme_details"),
    (SCHEMES_KB, "get_required_documents"),
    (MOCK_PORTAL, "get_application_status"),
}
WRITE_TOOLS = {(MOCK_PORTAL, "create_application"), (MOCK_PORTAL, "submit_draft")}
ALLOWED_TOOLS = READ_TOOLS | WRITE_TOOLS
WRITE_ALLOWED = {"application", "baseline"}
_actor: ContextVar[str | None] = ContextVar("tool_actor", default=None)
_tool_budget: ContextVar["_ToolCallBudget | None"] = ContextVar("tool_call_budget", default=None)


class _ToolCallBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self._lock = Lock()

    def consume(self, server: str, tool: str) -> None:
        with self._lock:
            if self.used >= self.limit:
                raise ToolCallError(
                    server,
                    tool,
                    "budget_exceeded",
                    f"The workflow exceeded its limit of {self.limit} MCP tool calls.",
                )
            self.used += 1


@contextmanager
def tool_call_budget(limit: int | None = None) -> Iterator[_ToolCallBudget]:
    """Apply a bounded MCP-call budget to a workflow invocation."""
    limit = DEFAULT_TOOL_CALL_BUDGET if limit is None else limit
    if limit < 1:
        raise ValueError("Tool-call budget must be positive.")
    existing = _tool_budget.get()
    if existing is not None:
        yield existing
        return
    budget = _ToolCallBudget(limit)
    token = _tool_budget.set(budget)
    try:
        yield budget
    finally:
        _tool_budget.reset(token)


class BudgetedGraph:
    """Apply a fresh MCP-call budget to each compiled graph execution."""

    def __init__(self, graph: Any, limit: int | None = None) -> None:
        self._graph = graph
        self._limit = limit

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        with tool_call_budget(self._limit):
            return self._graph.invoke(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        with tool_call_budget(self._limit):
            return await self._graph.ainvoke(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        limit = self._limit or DEFAULT_TOOL_CALL_BUDGET
        budget = _tool_budget.get() or _ToolCallBudget(limit)
        iterator = iter(self._graph.stream(*args, **kwargs))
        while True:
            token = _tool_budget.set(budget)
            try:
                item = next(iterator)
            except StopIteration:
                return
            finally:
                _tool_budget.reset(token)
            yield item

    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        limit = self._limit or DEFAULT_TOOL_CALL_BUDGET
        budget = _tool_budget.get() or _ToolCallBudget(limit)
        iterator = self._graph.astream(*args, **kwargs).__aiter__()
        while True:
            token = _tool_budget.set(budget)
            try:
                item = await iterator.__anext__()
            except StopAsyncIteration:
                return
            finally:
                _tool_budget.reset(token)
            yield item

    def batch(self, *args: Any, **kwargs: Any) -> Any:
        with tool_call_budget(self._limit):
            return self._graph.batch(*args, **kwargs)

    async def abatch(self, *args: Any, **kwargs: Any) -> Any:
        with tool_call_budget(self._limit):
            return await self._graph.abatch(*args, **kwargs)


def budget_graph(graph: Any, limit: int | None = None) -> BudgetedGraph:
    """Wrap a compiled graph so each execution gets an independent tool budget."""
    return BudgetedGraph(graph, limit)


@contextmanager
def acting_as(agent: str) -> Iterator[None]:
    """Name the agent making the tool calls inside this block."""
    token = _actor.set(agent)
    try:
        yield
    finally:
        _actor.reset(token)


def _authorize(server: str, tool: str) -> None:
    if server not in _SERVERS:
        raise ToolCallError(server, tool, "unknown_server", f"'{server}' is not an available tool server.")
    if (server, tool) not in ALLOWED_TOOLS:
        raise ToolCallError(server, tool, "forbidden", f"'{server}.{tool}' is not an allow-listed tool.")
    if (server, tool) in WRITE_TOOLS and _actor.get() not in WRITE_ALLOWED:
        raise ToolCallError(server, tool, "forbidden", f"'{_actor.get() or 'unknown caller'}' may not use a write tool.")


def _audit_tool_call(server: str, tool: str, outcome: str, started_at: float, error_code: str = "") -> None:
    event = {
        "actor": _actor.get() if _actor.get() in _KNOWN_ACTORS else "unknown",
        "server": server if server in _SERVERS else "unknown",
        "tool": tool if (server, tool) in ALLOWED_TOOLS else "unknown",
        "outcome": outcome,
        "error_code": error_code,
        "duration_ms": round((time.perf_counter() - started_at) * 1000),
    }
    logger.info("mcp_tool_call %s", json.dumps(event, sort_keys=True))


class ToolCallError(RuntimeError):
    def __init__(self, server: str, tool: str, code: str, message: str):
        super().__init__(f"{server}.{tool} failed ({code}): {message}")
        self.server, self.tool, self.code = server, tool, code


async def _call(server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(_SERVERS[server]) as client:
        result = await client.call_tool(tool, arguments, raise_on_error=False)
    payload = result.structured_content
    if result.is_error or not isinstance(payload, dict):
        raise ToolCallError(server, tool, "tool_error", str(result.content))
    if not payload.get("ok"):
        error = payload.get("error", {})
        raise ToolCallError(server, tool, error.get("code", "unknown"), error.get("message", ""))
    return payload


def call_tool(server: str, tool: str, **arguments: Any) -> Any:
    """Call one MCP tool and return its ``data``. Safe inside or outside a running event loop."""
    started_at = time.perf_counter()
    outcome = "error"
    error_code = "tool_error"
    try:
        _authorize(server, tool)
        budget = _tool_budget.get()
        if budget is not None:
            budget.consume(server, tool)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            result = asyncio.run(_call(server, tool, arguments))["data"]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, _call(server, tool, arguments)).result()["data"]
        outcome = "success"
        error_code = ""
        return result
    except ToolCallError as error:
        outcome = "denied" if error.code in {"unknown_server", "forbidden", "budget_exceeded"} else "error"
        error_code = (
            "budget_exceeded" if error.code == "budget_exceeded"
            else "authorization_denied" if outcome == "denied"
            else "tool_error"
        )
        raise
    except Exception:
        error_code = "transport_error"
        raise
    finally:
        _audit_tool_call(server, tool, outcome, started_at, error_code)


def search_schemes(profile: dict, scheme_ids: list[str] | None = None, include_draft: bool = False) -> list[str]:
    """Requested schemes, or every scheme whose rules are fully reviewed (any with rules in preview)."""
    return call_tool(RULE_ENGINE, "list_rule_schemes", scheme_ids=scheme_ids, include_draft=include_draft)


def required_fields(scheme_ids: list[str] | None = None, include_draft: bool = False) -> list[str]:
    candidates = search_schemes({}, scheme_ids, include_draft)
    if not candidates:
        return []
    return call_tool(RULE_ENGINE, "get_rule_fields", scheme_ids=candidates, include_draft=include_draft)


def evaluate_scheme(profile: dict, scheme_id: str, include_draft: bool = False) -> dict:
    return call_tool(RULE_ENGINE, "evaluate_profile", profile=profile, scheme_id=scheme_id,
                     include_draft=include_draft)


def field_specs(scheme_ids: list[str], include_draft: bool = False) -> dict[str, dict]:
    return call_tool(RULE_ENGINE, "get_field_specs", scheme_ids=scheme_ids, include_draft=include_draft)


def next_question(verdicts: dict[str, dict], declined: Collection[str] = ()) -> str | None:
    """The field missing or invalid in the most cant_tell verdicts; None once no answer can settle one.

    ``verdicts`` maps scheme IDs to rule-engine evaluations, as the eligibility step writes them.
    Only cant_tell verdicts count: a decided scheme can't be changed by another answer.
    Ties go to the alphabetically first field, as the rule engine sorts unresolved fields.
    """
    counts: dict[str, int] = {}
    for evaluation in verdicts.values():
        if evaluation["verdict"] == "cant_tell":
            for field in evaluation["unresolved_fields"]:
                if field not in declined:
                    counts[field] = counts.get(field, 0) + 1
    return max(counts, key=counts.get, default=None)


def list_documents(scheme_id: str) -> list[str]:
    return call_tool(SCHEMES_KB, "get_required_documents", scheme_id=scheme_id)


def draft_application(profile: dict, scheme_id: str) -> dict:
    """Pure local drafting: builds the form to approve. Nothing is written to the portal."""
    return {"scheme_id": scheme_id, "applicant": profile}


def application_form_spec(scheme_id: str) -> tuple[list[str], dict[str, str]]:
    """Required form fields and their fact names, from the scheme's reviewed rule fields."""
    fields = required_fields([scheme_id])
    return fields, {field: field for field in fields}


def create_portal_draft(form: dict) -> dict:
    """Write: store the form on the mock portal as a draft. Nothing is submitted."""
    form_hash = application_payload_hash(form["scheme_id"], form["applicant"])
    try:
        capability = issue_write_capability("create_draft", form["scheme_id"], form_hash)
    except CapabilityError as exc:
        raise ToolCallError(MOCK_PORTAL, "create_application", "forbidden", str(exc)) from exc
    record = call_tool(MOCK_PORTAL, "create_application", scheme_id=form["scheme_id"],
                       applicant=form["applicant"], submit=False,
                       write_capability=capability)
    return {"application_id": record["application_id"], "status": f"{record['status']} (mock)"}


def issue_submission_capability(
    form: dict,
    approved_hash: str,
    application_id: str | None = None,
) -> str:
    """Issue a one-use write capability only for the exact approved application form."""
    form_hash = application_payload_hash(form["scheme_id"], form["applicant"])
    if approved_hash != form_hash:
        raise ToolCallError(
            MOCK_PORTAL,
            "submit_application",
            "forbidden",
            "Approval does not match the current application form.",
        )
    action = "submit_draft" if application_id else "submit_application"
    resource = application_id or form["scheme_id"]
    try:
        return issue_write_capability(action, resource, form_hash)
    except CapabilityError as exc:
        raise ToolCallError(MOCK_PORTAL, "submit_application", "forbidden", str(exc)) from exc


def submit_application(
    form: dict,
    application_id: str | None = None,
    write_capability: str | None = None,
) -> dict:
    """The only submit. The workflow reaches it only after the exact form is approved.

    Requires a one-use capability created after approval. With ``application_id``
    it submits the existing portal draft; without, it creates and submits.
    """
    if not write_capability:
        raise ToolCallError(
            MOCK_PORTAL,
            "submit_application",
            "forbidden",
            "A one-use approval capability is required.",
        )
    if application_id:
        record = call_tool(
            MOCK_PORTAL,
            "submit_draft",
            application_id=application_id,
            write_capability=write_capability,
        )
    else:
        record = call_tool(MOCK_PORTAL, "create_application", scheme_id=form["scheme_id"],
                           applicant=form["applicant"], submit=True,
                           write_capability=write_capability)
    return {"status": f"{record['status']} (mock)", "scheme_id": record["scheme_id"],
            "application_id": record["application_id"]}
