"""The graph's tool layer: every call goes through the FastMCP servers in servers/*.

Servers are reached over FastMCP's in-memory transport, so requests, schemas and structured
errors are exactly what an out-of-process client would see. Failed tools raise ToolCallError.
"""

import asyncio
import concurrent.futures
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any

from fastmcp import Client

from servers.rule_engine.ages import DOB_DERIVED
from observability.hooks import record_approval, record_tool_call
from servers.mock_portal.authorization import (
    CapabilityError,
    application_payload_hash,
    issue_write_capability,
)
from servers.doc_check.server import mcp as document_check_server
from servers.mock_portal.server import mcp as portal_server
from servers.rule_engine.server import mcp as rule_server
from servers.schemes_kb.server import mcp as kb_server

logger = logging.getLogger(__name__)

RULE_ENGINE = "rule-engine"
SCHEMES_KB = "schemes-kb"
MOCK_PORTAL = "mock-portal"
DOC_CHECK = "doc-check"
_SERVERS = {
    RULE_ENGINE: rule_server,
    SCHEMES_KB: kb_server,
    MOCK_PORTAL: portal_server,
    DOC_CHECK: document_check_server,
}
DEFAULT_TOOL_CALL_BUDGET = 150  # one turn can evaluate every live scheme (50) twice, plus lookups
_KNOWN_ACTORS = {
    "application", "baseline", "document_checker", "eligibility", "intake", "rule_reviewer", "supervisor"
}

# Pre-tool hook: only these agents may call a write tool. "baseline" is the single-agent
# comparison run, which is deliberately given every tool.
READ_TOOLS = {
    (RULE_ENGINE, "list_rule_schemes"),
    (RULE_ENGINE, "get_rule_fields"),
    (RULE_ENGINE, "get_field_specs"),
    (RULE_ENGINE, "evaluate_profile"),
    (RULE_ENGINE, "preview_profile"),
    (SCHEMES_KB, "search_schemes"),
    (SCHEMES_KB, "get_scheme_details"),
    (SCHEMES_KB, "get_required_documents"),
    (SCHEMES_KB, "search_scheme_evidence"),
    (MOCK_PORTAL, "get_application_status"),
    (DOC_CHECK, "compare_document_fields"),
}
WRITE_TOOLS = {(MOCK_PORTAL, "create_application"), (MOCK_PORTAL, "submit_draft")}
ALLOWED_TOOLS = READ_TOOLS | WRITE_TOOLS
WRITE_ALLOWED = {"application", "baseline"}
READ_ACCESS = {
    "intake": {
        (RULE_ENGINE, "list_rule_schemes"),
        (RULE_ENGINE, "get_rule_fields"),
        (RULE_ENGINE, "get_field_specs"),
        (SCHEMES_KB, "search_scheme_evidence"),
    },
    "eligibility": {
        (RULE_ENGINE, "list_rule_schemes"),
        (RULE_ENGINE, "evaluate_profile"),
    },
    "supervisor": {
        (SCHEMES_KB, "get_scheme_details"),  # scheme_is_closed: the note on an outgoing answer
    },
    "document_checker": {
        (SCHEMES_KB, "get_required_documents"),
        (DOC_CHECK, "compare_document_fields"),
    },
    "application": {
        (RULE_ENGINE, "list_rule_schemes"),
        (RULE_ENGINE, "get_rule_fields"),
        (RULE_ENGINE, "get_field_specs"),
    },
    "rule_reviewer": {
        (RULE_ENGINE, "list_rule_schemes"),
        (RULE_ENGINE, "get_rule_fields"),
        (RULE_ENGINE, "get_field_specs"),
        (RULE_ENGINE, "preview_profile"),
    },
}
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

    def __init__(self, graph: Any, limit: int | None = None,
                 input_guard: Callable[[Any], None] | None = None) -> None:
        self._graph = graph
        self._limit = limit
        self._input_guard = input_guard

    def _guard(self, args: tuple[Any, ...], kwargs: dict[str, Any], batch: bool = False) -> None:
        if self._input_guard is None:
            return
        value = args[0] if args else kwargs.get("input" if not batch else "inputs")
        if batch:
            for item in value:
                self._input_guard(item)
        else:
            self._input_guard(value)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        self._guard(args, kwargs)
        with tool_call_budget(self._limit):
            return self._graph.invoke(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        self._guard(args, kwargs)
        with tool_call_budget(self._limit):
            return await self._graph.ainvoke(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        self._guard(args, kwargs)
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
        self._guard(args, kwargs)
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
        self._guard(args, kwargs, batch=True)
        with tool_call_budget(self._limit):
            return self._graph.batch(*args, **kwargs)

    async def abatch(self, *args: Any, **kwargs: Any) -> Any:
        self._guard(args, kwargs, batch=True)
        with tool_call_budget(self._limit):
            return await self._graph.abatch(*args, **kwargs)


def budget_graph(
    graph: Any, limit: int | None = None, input_guard: Callable[[Any], None] | None = None
) -> BudgetedGraph:
    """Wrap a compiled graph so each execution gets an independent tool budget."""
    return BudgetedGraph(graph, limit, input_guard)


@contextmanager
def acting_as(agent: str) -> Iterator[None]:
    """Name the agent making the tool calls inside this block."""
    token = _actor.set(agent)
    try:
        yield
    finally:
        _actor.reset(token)


def run_as(agent: str, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    with acting_as(agent):
        return operation(*args, **kwargs)


def _authorize(server: str, tool: str) -> None:
    if server not in _SERVERS:
        raise ToolCallError(server, tool, "unknown_server", f"'{server}' is not an available tool server.")
    if (server, tool) not in ALLOWED_TOOLS:
        raise ToolCallError(server, tool, "forbidden", f"'{server}.{tool}' is not an allow-listed tool.")
    actor = _actor.get()
    if (server, tool) == (RULE_ENGINE, "preview_profile") and actor != "rule_reviewer":
        raise ToolCallError(server, tool, "forbidden", "Only the rule reviewer may preview draft rules.")
    if actor is None:
        if (server, tool) in WRITE_TOOLS:
            raise ToolCallError(
                server,
                tool,
                "forbidden",
                "A missing caller context may not use a write tool.",
            )
        return
    if (server, tool) in WRITE_TOOLS:
        if actor not in WRITE_ALLOWED:
            raise ToolCallError(server, tool, "forbidden", f"'{actor}' may not use a write tool.")
    elif actor != "baseline" and (server, tool) not in READ_ACCESS.get(actor, set()):
        raise ToolCallError(server, tool, "forbidden", f"'{actor}' may not use this read tool.")


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
    record_tool_call(event["server"], event["tool"], outcome, time.perf_counter() - started_at, error_code)


def audit_approval_event(action: str, outcome: str, authenticated: bool) -> None:
    record_approval(action, outcome)
    event = {
        "action": action,
        "outcome": outcome,
        "actor_type": "authenticated_household" if authenticated else "system",
    }
    logger.info("application_approval %s", json.dumps(event, sort_keys=True))


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


CLOSED_NOTE = "Applications for this scheme are closed on myScheme right now."


_closed_schemes: dict[str, bool] = {}


def scheme_is_closed(scheme_id: str) -> bool:
    """True when the scheme's myScheme page said applications are closed when it was collected.

    Only a definite answer is cached: the record's status, or "no record" (a synthetic test
    scheme). A failed lookup (an exhausted tool budget, a server error) adds no note this
    time and is tried again next time, so it can't hide the note for good (PR #67 review).
    Scheme records don't change while the app runs, and each lookup is a tool call that counts
    against a conversation's tool-call budget.
    """
    if scheme_id in _closed_schemes:
        return _closed_schemes[scheme_id]
    try:
        # A workflow step, not the calling agent's choice: eligibility may not read the KB (RT-032).
        with acting_as("supervisor"):
            details = call_tool(SCHEMES_KB, "get_scheme_details", scheme_id=scheme_id)
    except ToolCallError as error:
        if error.code == "scheme_not_found":
            _closed_schemes[scheme_id] = False
        else:
            logger.warning("Could not check whether %s is closed (%s); no note added.", scheme_id, error.code)
        return False
    closed = isinstance(details, dict) and details.get("availability_status") == "closed"
    _closed_schemes[scheme_id] = closed
    return closed


scheme_is_closed.cache_clear = _closed_schemes.clear  # type: ignore[attr-defined]


def with_closed_note(scheme_id: str, explanation: str) -> str:
    """The explanation, plus a line saying applications are closed when they are (Step 5, F6)."""
    return f"{explanation} {CLOSED_NOTE}" if scheme_is_closed(scheme_id) else explanation


def search_evidence(question: str, scheme_id: str | None = None) -> list[dict]:
    """Cited passages that answer a scheme question; empty when nothing relevant was found."""
    return call_tool(SCHEMES_KB, "search_scheme_evidence", question=question, scheme_id=scheme_id)


def required_fields(scheme_ids: list[str] | None = None, include_draft: bool = False) -> list[str]:
    candidates = search_schemes({}, scheme_ids, include_draft)
    if not candidates:
        return []
    return call_tool(RULE_ENGINE, "get_rule_fields", scheme_ids=candidates, include_draft=include_draft)


def evaluate_scheme(profile: dict, scheme_id: str, include_draft: bool = False) -> dict:
    tool = "preview_profile" if include_draft else "evaluate_profile"
    arguments = {"profile": profile, "scheme_id": scheme_id}
    return call_tool(RULE_ENGINE, tool, **arguments)


def field_specs(scheme_ids: list[str], include_draft: bool = False) -> dict[str, dict]:
    return call_tool(RULE_ENGINE, "get_field_specs", scheme_ids=scheme_ids, include_draft=include_draft)


def next_question(verdicts: dict[str, dict], declined: Collection[str] = ()) -> str | None:
    """The field missing or invalid in the most cant_tell verdicts; None once no answer can settle one.

    ``verdicts`` maps scheme IDs to rule-engine evaluations, as the eligibility step writes them.
    Only cant_tell verdicts count: a decided scheme can't be changed by another answer.
    Ties go to the alphabetically first field, as the rule engine sorts unresolved fields.
    Ages that need more than whole years (``DOB_DERIVED``) are asked as ``date_of_birth``;
    if that was declined (many people don't know it), the age field itself is asked.
    """
    ask_dob = "date_of_birth" not in declined
    counts: dict[str, int] = {}
    for evaluation in verdicts.values():
        if evaluation["verdict"] == "cant_tell":
            for field in dict.fromkeys(
                "date_of_birth" if ask_dob and f in DOB_DERIVED else f for f in evaluation["unresolved_fields"]
            ):
                if field not in declined:
                    counts[field] = counts.get(field, 0) + 1
    return max(counts, key=counts.get, default=None)


def list_documents(scheme_id: str) -> list[str]:
    return call_tool(SCHEMES_KB, "get_required_documents", scheme_id=scheme_id)


def application_status(application_id: str, household_id: str) -> dict[str, Any]:
    """The portal's current status of one application, for the household that owns it.

    It is read live and never stored. The portal answers "not found" to any other household.
    """
    return call_tool(
        MOCK_PORTAL, "get_application_status", application_id=application_id, household_id=household_id
    )


def compare_document_fields(
    document_a: dict[str, Any],
    document_b: dict[str, Any],
    fields: list[str] | None = None,
) -> dict[str, Any]:
    return call_tool(
        DOC_CHECK,
        "compare_document_fields",
        document_a=document_a,
        document_b=document_b,
        fields=fields,
    )


def draft_application(profile: dict, scheme_id: str) -> dict:
    """Pure local drafting: builds the form to approve. Nothing is written to the portal."""
    return {"scheme_id": scheme_id, "applicant": profile}


def application_form_spec(scheme_id: str) -> tuple[list[str], dict[str, str]]:
    """Required form fields and their fact names, from the scheme's reviewed rule fields."""
    fields = required_fields([scheme_id])
    return fields, {field: field for field in fields}


def create_portal_draft(
    form: dict, household_id: str | None = None
) -> dict:
    """Write: store the form on the mock portal as a draft. Nothing is submitted."""
    form_hash = application_payload_hash(form["scheme_id"], form["applicant"])
    try:
        capability = issue_write_capability(
            "create_draft", form["scheme_id"], form_hash, household_id
        )
    except CapabilityError as exc:
        raise ToolCallError(MOCK_PORTAL, "create_application", "forbidden", str(exc)) from exc
    record = call_tool(MOCK_PORTAL, "create_application", scheme_id=form["scheme_id"],
                       applicant=form["applicant"], submit=False,
                       write_capability=capability, household_id=household_id)
    return {"application_id": record["application_id"], "status": f"{record['status']} (mock)"}


def issue_submission_capability(
    form: dict,
    approved_hash: str,
    application_id: str | None = None,
    household_id: str | None = None,
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
        return issue_write_capability(action, resource, form_hash, household_id)
    except CapabilityError as exc:
        raise ToolCallError(MOCK_PORTAL, "submit_application", "forbidden", str(exc)) from exc


def submit_application(
    form: dict,
    application_id: str | None = None,
    write_capability: str | None = None,
    household_id: str | None = None,
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
                           write_capability=write_capability,
                           household_id=household_id)
    return {"status": f"{record['status']} (mock)", "scheme_id": record["scheme_id"],
            "application_id": record["application_id"]}
