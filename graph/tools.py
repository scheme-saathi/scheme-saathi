"""The graph's tool layer: every call goes through the FastMCP servers in servers/*.

Servers are reached over FastMCP's in-memory transport, so requests, schemas and structured
errors are exactly what an out-of-process client would see. Failed tools raise ToolCallError.
"""

import asyncio
import concurrent.futures
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from fastmcp import Client

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
    record = call_tool(MOCK_PORTAL, "create_application", scheme_id=form["scheme_id"],
                       applicant=form["applicant"], submit=False)
    return {"application_id": record["application_id"], "status": f"{record['status']} (mock)"}


def submit_application(form: dict, application_id: str | None = None) -> dict:
    """The only submit. The workflow reaches it only after the exact form is approved.

    With ``application_id`` it submits the draft already on the portal; without, it creates and submits.
    """
    if application_id:
        record = call_tool(MOCK_PORTAL, "submit_draft", application_id=application_id)
    else:
        record = call_tool(MOCK_PORTAL, "create_application", scheme_id=form["scheme_id"],
                           applicant=form["applicant"], submit=True)
    return {"status": f"{record['status']} (mock)", "scheme_id": record["scheme_id"],
            "application_id": record["application_id"]}
