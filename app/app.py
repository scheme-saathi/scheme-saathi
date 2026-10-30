from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
import tomllib
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import streamlit as st
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from graph import tools
from graph.tools import ToolCallError
from graph.workflow import build_graph


workflow = build_graph()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_THEME_PATH = PROJECT_ROOT / ".streamlit" / "scheme_saathi.toml"

NODE_LABELS = {
    "plan": "Preparing the eligibility check",
    "intake": "Checking profile details",
    "eligibility": "Evaluating reviewed scheme rules",
    "documents": "Finding required documents",
    "draft": "Preparing an application draft",
    "validate": "Validating the draft",
    "approval": "Waiting for your approval",
    "submit": "Recording the mock submission",
    "escalate": "Flagging the case for human review",
}


class AnalysisRequest(BaseModel):
    """Request data for checking a citizen profile against selected schemes."""

    citizen: dict[str, Any]
    scheme_ids: list[str] | None = None


class DecisionRequest(BaseModel):
    """Approval, rejection, or profile edits for a pending application draft."""

    action: Literal["approve", "edit", "reject"]
    payload_hash: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)


def _sse(event: str, payload: dict[str, Any]) -> str:
    """Format one event and JSON payload using the Server-Sent Events protocol."""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"


def _snapshot_payload(thread_id: str, snapshot: Any) -> dict[str, Any]:
    """Convert the saved workflow state into the result returned to the UI."""
    values = snapshot.values
    approval = next(
        (
            interrupt.value
            for task in snapshot.tasks
            for interrupt in task.interrupts
        ),
        None,
    )
    return {
        "thread_id": thread_id,
        "profile": values.get("profile", {}),
        "verdicts": values.get("verdicts", {}),
        "documents": values.get("documents", {}),
        "application": values.get("application", {}),
        "approval": approval,
        "approval_status": values.get("approval_status"),
        "submission": values.get("submission"),
        "needs_human": values.get("needs_human", False),
        "critique": values.get("critique", []),
    }


def _stream_run(run_input: Any, config: dict[str, Any], thread_id: str) -> Iterator[str]:
    """Run or resume the workflow and stream progress events followed by its result."""
    yield _sse("progress", {"node": "start", "label": "Starting the workflow"})
    for update in workflow.stream(run_input, config, stream_mode="updates"):
        for node in update:
            yield _sse(
                "progress",
                {"node": node, "label": NODE_LABELS.get(node, node.replace("_", " ").title())},
            )
    yield _sse("result", _snapshot_payload(thread_id, workflow.get_state(config)))


def _streaming_response(events: Iterator[str]) -> StreamingResponse:
    """Wrap event strings in an HTTP response that clients can consume incrementally."""
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _new_fastapi_app() -> FastAPI:
    """Create the FastAPI application without exposing it to Streamlit's app discovery."""
    return FastAPI(title="Scheme Saathi API")


def create_api() -> FastAPI:
    """Build the API routes used to check eligibility and make application decisions."""
    application = _new_fastapi_app()

    @application.get("/health")
    def health() -> dict[str, str]:
        """Report that the API is ready to receive requests."""
        return {"status": "ok"}

    @application.post("/api/analyze")
    def analyze(payload: AnalysisRequest) -> StreamingResponse:
        """Validate requested schemes, start a citizen workflow, and stream its progress."""
        try:
            tools.search_schemes({}, payload.scheme_ids)
        except ToolCallError as error:
            if error.code != "scheme_not_found":
                raise
            raise HTTPException(status_code=422, detail=str(error)) from error

        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        initial_input: dict[str, Any] = {"simulated_citizen": payload.citizen}
        if payload.scheme_ids:
            initial_input["scheme_ids"] = payload.scheme_ids
        return _streaming_response(_stream_run(initial_input, config, thread_id))

    @application.post("/api/threads/{thread_id}/decision")
    def decide(thread_id: str, payload: DecisionRequest) -> StreamingResponse:
        """Resume a pending workflow with approval, rejection, or revised profile facts."""
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = workflow.get_state(config)
        if "approval" not in snapshot.next:
            raise HTTPException(status_code=409, detail="This application is not waiting for approval.")
        if payload.action == "approve" and not payload.payload_hash:
            raise HTTPException(status_code=422, detail="Approving requires the current application hash.")

        decision: dict[str, Any] = {"action": payload.action}
        if payload.action == "approve":
            decision["payload_hash"] = payload.payload_hash
        elif payload.action == "edit":
            decision["changes"] = payload.changes
        return _streaming_response(_stream_run(Command(resume=decision), config, thread_id))

    return application


def _parse_sse(response: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    """Read an SSE response and yield each event name with its decoded JSON payload."""
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            if data_lines:
                payload = json.loads("\n".join(data_lines))
                if not isinstance(payload, dict):
                    raise RuntimeError("The API returned an invalid streaming event.")
                yield event_name, payload
            event_name = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())


def _post_stream( endpoint: str, payload: dict[str, Any], progress: Any,) -> dict[str, Any]:
    """POST to a streaming API endpoint, show progress, and return its final result."""
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    result = None
    try:
        with urlopen(request, timeout=300) as response:
            for event_name, event_payload in _parse_sse(response):
                if event_name == "progress":
                    progress.write(event_payload.get("label", "Workflow update"))
                elif event_name == "error":
                    raise RuntimeError(event_payload.get("detail", "The API reported an error."))
                elif event_name == "result":
                    result = event_payload
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail or f"API request failed with status {error.code}.") from error
    if result is None:
        raise RuntimeError("The API stream ended before returning a result.")
    return result


@st.cache_data
def _available_schemes() -> dict[str, str]:
    """Return labels for schemes whose rule sets are fully reviewed."""
    scheme_ids = tools.search_schemes({})
    labels = {scheme_id: scheme_id for scheme_id in scheme_ids}
    for directory in (PROJECT_ROOT / "data" / "schemes", PROJECT_ROOT / "data" / "rules"):
        for path in directory.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            scheme_id = record.get("scheme_id")
            if scheme_id in labels:
                labels[scheme_id] = f"{record.get('name', scheme_id)} ({scheme_id})"
    return labels


@st.cache_resource
def _start_local_api(port: int) -> uvicorn.Server:
    """Start the local FastAPI server once and wait briefly for it to become ready."""
    config = uvicorn.Config(create_api(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="scheme-saathi-api", daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError(f"FastAPI did not start on 127.0.0.1:{port}. Check whether the port is in use.")
    return server


def _api_health(base_url: str) -> tuple[bool, str]:
    """Check the API health endpoint and return a connection status and message."""
    try:
        with urlopen(f"{base_url}/health", timeout=3) as response:
            health_payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as error:
        return False, str(error)
    if health_payload.get("status") != "ok":
        return False, "The API health endpoint returned an unexpected response."
    return True, "Connected to the local FastAPI service."


def _render_verdicts(result: dict[str, Any], scheme_labels: dict[str, str]) -> None:
    """Display each scheme's verdict, evaluated rules, missing facts, and citations."""
    verdicts = result.get("verdicts", {})
    if not verdicts:
        st.info("No reviewed eligibility rules were available for the selected schemes.")
        return

    st.subheader("Eligibility results")
    for scheme_id, verdict in verdicts.items():
        with st.container(border=True):
            st.markdown(f"**{scheme_labels.get(scheme_id, scheme_id)}**")
            decision = verdict["verdict"].replace("_", " ").title()
            if verdict["verdict"] == "eligible":
                st.success(decision, icon=":material/check_circle:")
            elif verdict["verdict"] == "not_eligible":
                st.warning(decision, icon=":material/info:")
            else:
                st.info(decision, icon=":material/help:")
            st.write(verdict.get("reason", ""))

            conditions = verdict.get("conditions", [])
            if conditions:
                st.dataframe(
                    [
                        {
                            "Profile fact": condition.get("field"),
                            "Rule": condition.get("op"),
                            "Result": condition.get("outcome"),
                            "Evidence clause": condition.get("clause_id"),
                        }
                        for condition in conditions
                    ],
                    hide_index=True,
                    width="stretch",
                )
            for missing in ("missing_fields", "unresolved_fields"):
                fields = verdict.get(missing, [])
                if fields:
                    st.caption(f"{missing.replace('_', ' ').title()}: {', '.join(fields)}")
            citations = verdict.get("citations", [])
            if citations:
                with st.expander("View source clauses"):
                    for citation in citations:
                        st.markdown(f"- **{citation.get('clause_id', 'Source')}:** {citation.get('text', '')}")


def _theme_color(theme: dict[str, Any], name: str) -> str:
    """Read a CSS hex color from the app theme and reject malformed values."""
    color = theme.get(name)
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", color):
        raise ValueError(f"Invalid {name} in {APP_THEME_PATH}.")
    return color


def _render_application(result: dict[str, Any], api_base: str, scheme_labels: dict[str, str],) -> None:
    """Show the draft and controls for editing, approving, or rejecting it."""
    approval = result.get("approval")
    if not approval:
        if result.get("needs_human"):
            st.warning("This draft needs human review and was not submitted.")
            for issue in result.get("critique", []):
                st.markdown(f"- {issue}")
        elif result.get("submission"):
            st.success(f"Mock application status: {result['submission'].get('status', 'submitted')}")
        elif result.get("approval_status") == "rejected":
            st.info("The draft was rejected. Nothing was submitted.")
        elif result.get("approval_status") == "invalid":
            st.error("Approval did not match the current draft. Nothing was submitted.")
        return

    st.subheader("Review your application")
    st.info("Nothing is submitted until you approve this exact draft. This demo uses a mock submission flow.")
    st.json(approval.get("form", {}))
    st.caption("Approval fingerprint")
    st.code(approval.get("payload_hash", ""), language="text")

    thread_id = result["thread_id"]
    approve_col, reject_col = st.columns(2)
    theme = tomllib.loads(APP_THEME_PATH.read_text(encoding="utf-8"))
    approval_color = _theme_color(theme, "approvedButtonColor")
    reject_color = _theme_color(theme, "rejectButtonColor")
    st.html(
        f"""
        <style>
        .st-key-approve_and_submit button,
        .st-key-reject_draft button {{
            color: #ffffff !important;
        }}
        .st-key-approve_and_submit button {{
            background-color: {approval_color} !important;
            border-color: {approval_color} !important;
        }}
        .st-key-approve_and_submit button:hover {{
            filter: brightness(0.92);
        }}
        .st-key-reject_draft button {{
            background-color: {reject_color} !important;
            border-color: {reject_color} !important;
        }}
        .st-key-reject_draft button:hover {{
            filter: brightness(0.92);
        }}
        </style>
        """
    )
    if approve_col.button("Approve and submit",type="primary", key="approve_and_submit",  width="stretch",):
        _handle_decision(api_base,  thread_id, {"action": "approve", "payload_hash": approval.get("payload_hash")},)
        
    if reject_col.button("Reject draft", key="reject_draft", width="stretch"):
        _handle_decision(api_base, thread_id, {"action": "reject"})

    profile = result.get("profile", {})
    with st.expander("Request changes before approval"):
        with st.form(f"edit-{thread_id}"):
            age = st.number_input("Age (years)", min_value=0, max_value=130, value=int(profile.get("age", 0)))
            income = st.number_input(
                "Annual household income (INR)",
                min_value=0,
                max_value=10_000_000_000,
                value=int(profile.get("income", 0)),
                step=10_000,
            )
            is_widow = st.checkbox("I am a widow", value=bool(profile.get("is_widow", False)))
            submitted = st.form_submit_button("Recheck eligibility and update draft", type="secondary")
        if submitted:
            _handle_decision(api_base,thread_id,{"action": "edit", "changes": {"age": age, "income": income, "is_widow": is_widow}},)


def _handle_decision(api_base: str, thread_id: str, payload: dict[str, Any]) -> None:
    """Send a user's application decision, save the result, and refresh the UI."""
    with st.status("Updating the application...", expanded=True) as status:
        try:
            result = _post_stream(f"{api_base}/api/threads/{thread_id}/decision", payload, st,)
        except (URLError, RuntimeError) as error:
            status.update(label="The application could not be updated", state="error")
            st.error(str(error), title="Request failed")
            return
        st.session_state["scheme_saathi_result"] = result
        status.update(label="Application updated", state="complete")
    st.rerun()


def render_app() -> None:
    """Render the Scheme Saathi eligibility form, streamed results, and review controls."""
    st.set_page_config(page_title="Scheme Saathi", page_icon=":material/account_balance:", layout="wide",)
    st.title("Scheme Saathi")
    st.caption("A guided way to explore welfare schemes and prepare an application for your review.")

    external_api = os.environ.get("SCHEME_SAATHI_API_URL")
    if external_api:
        api_base = external_api.rstrip("/")
    else:
        try:
            api_port = int(os.environ.get("SCHEME_SAATHI_API_PORT", "8765"))
            _start_local_api(api_port)
            api_base = f"http://127.0.0.1:{api_port}"
        except (ValueError, RuntimeError) as error:
            st.error(str(error), title="Could not start FastAPI")
            st.stop()

    healthy, health_message = _api_health(api_base)
    with st.sidebar:
        st.subheader("Service")
        if healthy:
            st.success(health_message)
        else:
            st.error(health_message, title="FastAPI unavailable")
        st.caption("Your profile is sent only to the API configured for this app.")
        st.caption("Eligibility results are informational, not official benefit decisions.")

    scheme_labels = _available_schemes()
    if not scheme_labels:
        st.warning("There are no schemes with fully reviewed rules to evaluate yet.")

    with st.container(border=True):
        st.subheader("Check your eligibility")
        st.write("Enter a few details to compare your profile with schemes that have reviewed rules.")
        st.caption("The prefilled values are a synthetic example. Replace them with your own details.")
        with st.form("eligibility-form"):
            age = st.number_input("Age (years)", min_value=0, max_value=130, value=62)
            income = st.number_input(
                "Annual household income (INR)",
                min_value=0,
                max_value=10_000_000_000,
                value=250_000,
                step=10_000,
            )
            is_widow = st.checkbox("I am a widow", value=True)
            selected_schemes = st.multiselect(
                "Schemes to check",
                options=list(scheme_labels),
                default=list(scheme_labels),
                format_func=scheme_labels.__getitem__,
            )
            submitted = st.form_submit_button(
                "Check eligibility",
                type="primary",
                disabled=not healthy,
                width="stretch",
            )

    if submitted:
        if not selected_schemes:
            st.warning("Choose at least one scheme to check.")
        else:
            with st.status("Checking reviewed scheme rules...", expanded=True) as status:
                try:
                    result = _post_stream(f"{api_base}/api/analyze", {"citizen": {"age": age, "income": income, "is_widow": is_widow}, "scheme_ids": selected_schemes,},  st, )
                except (URLError, RuntimeError) as error:
                    status.update(label="Eligibility check failed", state="error")
                    st.error(str(error), title="Request failed")
                else:
                    st.session_state["scheme_saathi_result"] = result
                    status.update(label="Eligibility check complete", state="complete")

    result = st.session_state.get("scheme_saathi_result")
    if result:
        st.divider()
        _render_verdicts(result, scheme_labels)
        documents = result.get("documents", {})
        for scheme_id, required_documents in documents.items():
            if required_documents:
                st.subheader(f"Documents needed for {scheme_labels.get(scheme_id, scheme_id)}")
                for document in required_documents:
                    st.markdown(f"- {document}")
        _render_application(result, api_base, scheme_labels)


if __name__ == "__main__":
    render_app()
