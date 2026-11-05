"""The graph's tool layer: every call goes through the FastMCP servers in servers/*.

Servers are reached over FastMCP's in-memory transport, so requests, schemas and structured
errors are exactly what an out-of-process client would see. Failed tools raise ToolCallError.
"""

import asyncio
import concurrent.futures
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
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

RULE_ENGINE = "rule-engine"
SCHEMES_KB = "schemes-kb"
MOCK_PORTAL = "mock-portal"
_SERVERS = {RULE_ENGINE: rule_server, SCHEMES_KB: kb_server, MOCK_PORTAL: portal_server}

# Pre-tool hook: only these agents may call a write tool. "baseline" is the single-agent
# comparison run, which is deliberately given every tool.
WRITE_TOOLS = {(MOCK_PORTAL, "create_application"), (MOCK_PORTAL, "submit_draft")}
WRITE_ALLOWED = {"application", "baseline"}
_actor: ContextVar[str | None] = ContextVar("tool_actor", default=None)


@contextmanager
def acting_as(agent: str) -> Iterator[None]:
    """Name the agent making the tool calls inside this block."""
    token = _actor.set(agent)
    try:
        yield
    finally:
        _actor.reset(token)


def _authorize(server: str, tool: str) -> None:
    if (server, tool) in WRITE_TOOLS and _actor.get() not in WRITE_ALLOWED:
        raise ToolCallError(server, tool, "forbidden", f"'{_actor.get() or 'unknown caller'}' may not use a write tool.")


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
    _authorize(server, tool)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_call(server, tool, arguments))["data"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _call(server, tool, arguments)).result()["data"]


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
