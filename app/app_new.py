"""Conversational citizen portal with eligibility, documents, and mock submission."""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

import streamlit as st
import uvicorn

if __package__:
    from .api import create_api
else:
    from api import create_api

CSS_PATH = Path(__file__).with_name("style.css")
JOURNEY_STEPS = (
    "Your details",
    "Eligibility",
    "Documents",
    "Review",
    "Confirmation",
)


@st.cache_resource
def _start_local_api(port: int) -> uvicorn.Server:
    """Start one local FastAPI server and share it across Streamlit reruns."""
    server = uvicorn.Server(
        uvicorn.Config(
            create_api(),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(
        target=server.run, name="scheme-saathi-chat-api", daemon=True
    )
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError(
            f"FastAPI did not start on 127.0.0.1:{port}. "
            "Check whether the port is already in use."
        )
    return server


def _api_base_url() -> str:
    """Use a configured API URL or launch the local chat-demo API."""
    external_url = os.environ.get("SCHEME_SAATHI_API_URL")
    if external_url:
        return external_url.rstrip("/")
    port = int(os.environ.get("SCHEME_SAATHI_CHAT_API_PORT", "8766"))
    api_base = f"http://127.0.0.1:{port}"
    if _is_scheme_saathi_api(api_base):
        return api_base

    try:
        _start_local_api(port)
    except RuntimeError:
        if _is_scheme_saathi_api(api_base):
            return api_base
        raise
    return api_base


def _is_scheme_saathi_api(api_base: str) -> bool:
    """Return whether a local server already exposes the expected demo API."""
    try:
        with urlopen(f"{api_base}/health", timeout=1) as response:
            health = json.loads(response.read().decode("utf-8"))
        if not isinstance(health, dict) or health.get("status") != "ok":
            return False

        with urlopen(f"{api_base}/api/schemes", timeout=1) as response:
            schemes = json.loads(response.read().decode("utf-8"))
        return isinstance(schemes, dict) and isinstance(schemes.get("schemes"), list)
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return False


def _parse_sse(response: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    """Decode named JSON events from the API's server-sent event stream."""
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            if data_lines:
                payload = json.loads("\n".join(data_lines))
                if not isinstance(payload, dict):
                    raise RuntimeError("FastAPI returned an invalid streaming event.")
                yield event_name, payload
            event_name, data_lines = "message", []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        payload = json.loads("\n".join(data_lines))
        if not isinstance(payload, dict):
            raise RuntimeError("FastAPI returned an invalid streaming event.")
        yield event_name, payload


def _api_request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """Send a JSON API request and turn HTTP/network failures into clear UI errors."""
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(message).get("detail", message)
        except json.JSONDecodeError:
            detail = message
        raise RuntimeError(
            str(detail) or f"FastAPI request failed ({error.code})."
        ) from error
    except (URLError, OSError, http.client.HTTPException) as error:
        raise RuntimeError(f"FastAPI request failed: {error}") from error


def _send_workflow(
    api_base: str,
    path: str,
    payload: dict[str, Any],
    progress: Any,
) -> dict[str, Any]:
    """Post a workflow action and collect its streamed progress and final result."""
    request = Request(
        f"{api_base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    result = None
    try:
        with urlopen(request, timeout=300) as response:
            for event_name, event_payload in _parse_sse(response):
                if event_name == "progress":
                    progress.write(event_payload.get("label", "Working..."))
                elif event_name == "error":
                    raise RuntimeError(
                        event_payload.get("detail", "The workflow failed.")
                    )
                elif event_name == "result":
                    result = event_payload
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(message).get("detail", message)
        except json.JSONDecodeError:
            detail = message
        raise RuntimeError(
            str(detail) or f"FastAPI request failed ({error.code})."
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not connect to FastAPI: {error}") from error
    except (OSError, http.client.HTTPException) as error:
        raise RuntimeError(f"The FastAPI stream ended unexpectedly: {error}") from error

    if result is None:
        raise RuntimeError("The workflow stream ended before returning a result.")
    return result


def _upload_document(
    api_base: str,
    result: dict[str, Any],
    scheme_id: str,
    document_type: str,
    uploaded_file: Any,
) -> dict[str, Any]:
    """Upload a required PDF/image for time-limited local storage."""
    boundary = f"----SchemeSaathi{uuid4().hex}"
    filename = Path(uploaded_file.name.replace("\\", "/")).name
    filename = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    content_type = uploaded_file.type or "application/octet-stream"
    parts = []
    for name, value in (
        ("scheme_id", scheme_id),
        ("document_type", document_type),
        ("sensitive_ids_masked", "true"),
    ):
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            uploaded_file.getvalue(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    thread_id = quote(result["thread_id"], safe="")
    return _api_request(
        f"{api_base}/api/threads/{thread_id}/documents/upload",
        method="POST",
        body=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def _send_chat(
    api_base: str,
    user_input: str,
    session_id: str | None,
    progress: Any,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Send one conversational intake turn and return its reply and eligibility data."""
    payload = {"user_input": user_input, "session_id": session_id}
    request = Request(
        f"{api_base}/api/chat/legacy",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    assistant_reply = None
    received_session_id = session_id
    result = None
    try:
        with urlopen(request, timeout=300) as response:
            for event_name, event_payload in _parse_sse(response):
                if event_name == "progress":
                    progress.write(event_payload.get("label", "Working..."))
                elif event_name == "session":
                    received_session_id = event_payload.get("session_id")
                elif event_name == "assistant":
                    assistant_reply = event_payload.get("content", "")
                elif event_name == "result":
                    result = event_payload
                elif event_name == "error":
                    raise RuntimeError(
                        event_payload.get("detail", "The intake agent could not respond.")
                    )
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(message).get("detail", message)
        except json.JSONDecodeError:
            detail = message
        raise RuntimeError(
            str(detail) or f"FastAPI request failed ({error.code})."
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not connect to FastAPI: {error}") from error
    except (OSError, http.client.HTTPException) as error:
        raise RuntimeError(f"The FastAPI stream ended unexpectedly: {error}") from error

    if assistant_reply is None:
        raise RuntimeError("The FastAPI stream ended before returning a response.")
    return received_session_id, assistant_reply, result


def _render_eligibility(result: dict[str, Any]) -> None:
    """Present each reviewed-rule verdict and its source clauses in the chat."""
    names = result.get("scheme_names", {})
    verdicts = result.get("verdicts", {})
    if not verdicts:
        st.caption("No reviewed eligibility rules were available to check.")
        return

    st.markdown("**Step 2 — Eligibility check**")
    for scheme_id, verdict in verdicts.items():
        with st.container(border=True):
            st.markdown(
                f"**{names.get(scheme_id, scheme_id)}**  \n"
                f"`{scheme_id}`"
            )
            status = verdict.get("verdict", "cant_tell")
            if status == "eligible":
                st.success("May be eligible", icon=":material/check_circle:")
            elif status == "not_eligible":
                st.warning("Does not currently match", icon=":material/info:")
            else:
                st.info("Could not determine", icon=":material/help:")
            st.write(verdict.get("reason", "No explanation was returned."))
            citations = verdict.get("citations", [])
            if citations:
                with st.expander("View reviewed source clauses"):
                    for citation in citations:
                        st.markdown(
                            f"- **{citation.get('clause_id', 'Source')}:** "
                            f"{citation.get('text', '')}"
                        )


def _render_message(message: dict[str, Any]) -> None:
    """Render a saved chat turn and its associated eligibility result."""
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("result"):
            _render_eligibility(message["result"])


def _delete_uploaded_documents(
    thread_id: str | None, api_base: str | None = None
) -> bool:
    """Delete retained supporting files before clearing their workflow context."""
    if not thread_id:
        return True
    try:
        base_url = api_base or _api_base_url()
        _api_request(
            f"{base_url}/api/threads/{quote(thread_id, safe='')}/documents",
            method="DELETE",
        )
    except RuntimeError as error:
        st.error(str(error), title="Could not delete uploaded documents")
        return False
    return True


def _reset_chat() -> bool:
    """Clear chat/application data and widget values before another profile is checked."""
    application_result = st.session_state.get("application_result")
    thread_id = (
        application_result.get("thread_id")
        if isinstance(application_result, dict)
        else None
    )
    if not _delete_uploaded_documents(thread_id):
        return False

    st.session_state["chat_session_id"] = None
    st.session_state["chat_messages"] = []
    st.session_state["chat_eligibility_result"] = None
    st.session_state["application_result"] = None
    st.session_state["application_uploads"] = {}
    st.session_state["application_outcome"] = None
    st.session_state["application_editing"] = False
    st.session_state["application_edit_revision"] = 0
    for key in list(st.session_state):
        if key.startswith(
            ("edit-field-", "confirm-application-submission-")
        ):
            del st.session_state[key]
    return True


def _start_application(
    api_base: str, eligibility_result: dict[str, Any], scheme_id: str
) -> None:
    """Create the graph-backed application workflow for one eligible scheme."""
    with st.status("Preparing the application workflow...", expanded=True) as progress:
        application_result = _send_workflow(
            api_base,
            "/api/analyze",
            {
                "citizen": eligibility_result["profile"],
                "scheme_ids": [scheme_id],
            },
            progress,
        )
    st.session_state["application_result"] = application_result
    st.session_state["application_uploads"] = {}
    st.session_state["application_outcome"] = None


def _render_application_start(
    api_base: str, eligibility_result: dict[str, Any]
) -> None:
    """Offer the application steps only for schemes that passed reviewed rules."""
    eligible = [
        scheme_id
        for scheme_id, verdict in eligibility_result.get("verdicts", {}).items()
        if verdict.get("verdict") == "eligible"
    ]
    st.markdown("#### Continue to application")
    st.caption(
        "Eligibility guidance is informational. The remaining steps prepare "
        "and record a mock application; nothing is sent to a government service."
    )
    if not eligible:
        st.info("No eligible scheme is available to continue to an application.")
        return

    names = eligibility_result.get("scheme_names", {})
    st.write("Choose an eligible scheme to prepare its application:")
    for scheme_id in eligible:
        label = names.get(scheme_id, scheme_id)
        if st.button(
            f"Prepare application: {label}",
            type="primary",
            key=f"prepare-application-{scheme_id}",
        ):
            try:
                _start_application(api_base, eligibility_result, scheme_id)
            except (RuntimeError, ValueError, json.JSONDecodeError) as error:
                st.error(str(error), title="Could not start the application")
            else:
                st.rerun()


def _render_document_step(result: dict[str, Any]) -> bool:
    """Show document status and explain how to attach the next required file."""
    scheme_id = result.get("application", {}).get("scheme_id")
    required_documents = result.get("documents", {}).get(scheme_id, [])
    uploads = st.session_state["application_uploads"]
    st.markdown("#### Step 3 — Upload required documents")
    st.caption(
        "Upload a redacted copy only. Mask Aadhaar, bank-account, and other full "
        "ID numbers before upload. Copies are stored unencrypted and deleted after 30 days."
    )
    st.checkbox(
        "I confirm this document has no unmasked Aadhaar, bank-account, or other ID numbers.",
        key=f"document-sensitive-ids-masked-{result.get('thread_id', '')}",
    )
    missing = []
    document_rows = []
    for document_type in required_documents:
        existing = uploads.get(document_type)
        if existing:
            status = f"Uploaded: {existing['filename']}"
        else:
            missing.append(document_type)
            status = "Required"
        document_rows.append({"Document": document_type, "Status": status})

    if document_rows:
        st.table(document_rows)
    else:
        st.caption("No documents are required for this application.")

    if missing:
        st.info(
            "Still required: "
            + ", ".join(missing)
            + ". Attach the next document using the paperclip in the chat input below."
        )
    else:
        st.success("All required documents are recorded.")
    return not missing


def _render_workflow_fields(fields: dict[str, Any]) -> None:
    """Display every profile or draft field without a collapsed JSON viewer."""

    def field_rows(values: dict[str, Any], parent: str = "") -> list[dict[str, str]]:
        rows = []
        for field, value in values.items():
            label = str(field).replace("_", " ").title()
            label = f"{parent} - {label}" if parent else label
            if isinstance(value, dict) and value:
                rows.extend(field_rows(value, label))
                continue
            rows.append(
                {
                    "Field": label,
                    "Value": (
                        json.dumps(value, ensure_ascii=False, default=str)
                        if isinstance(value, (dict, list, tuple))
                        else str(value)
                    ),
                }
            )
        return rows

    rows = field_rows(fields)
    if rows:
        st.table(rows)
    else:
        st.caption("No fields are available.")


def _render_review_step(
    api_base: str, result: dict[str, Any], documents_complete: bool
) -> None:
    """Let the user approve, edit, or reject the reviewed application draft."""
    st.markdown("#### Step 4 — Review and decide")
    st.caption("Check your profile and exact application draft before deciding.")
    profile_col, application_col = st.columns(2, gap="small")
    with profile_col:
        st.markdown("**Profile**")
        _render_workflow_fields(result.get("profile", {}))
    with application_col:
        st.markdown("**Application draft**")
        _render_workflow_fields(result.get("application", {}))
    st.caption(
        "Approval is tied to this exact draft. Editing rechecks eligibility "
        "and creates a new draft for you to review."
    )

    if result.get("needs_human"):
        st.warning("This draft needs human review. It cannot be submitted by this demo.")
        return
    if not result.get("approval"):
        st.warning(
            "A reviewable draft is not available. Check the eligibility details "
            "or start a new chat."
        )
        return

    approval_hash = result["approval"]["payload_hash"]
    confirmed = st.checkbox(
        "I reviewed this draft and understand that this is a mock submission.",
        key=f"confirm-application-submission-{approval_hash}",
    )
    approve_col, edit_col, reject_col = st.columns(3)
    if approve_col.button(
        "Approve",
        type="primary",
        disabled=not documents_complete or not confirmed,
        key="approve-mock-application",
    ):
        _finish_application(
            api_base,
            result,
            {"action": "approve", "payload_hash": approval_hash},
        )
    if edit_col.button("Edit", key="edit-mock-application"):
        st.session_state["application_editing"] = True
        st.rerun()
    if reject_col.button("Reject", key="reject-mock-application"):
        _finish_application(api_base, result, {"action": "reject"})

    if st.session_state["application_editing"]:
        st.markdown("**Edit profile details**")
        st.caption(
            "Changing a detail runs eligibility checks again. You’ll need to "
            "review the updated draft before approving it."
        )
        profile = result.get("profile", {})
        edit_revision = st.session_state["application_edit_revision"]
        with st.form("edit-application-profile"):
            changes: dict[str, Any] = {}
            edit_columns = st.columns(2, gap="small")
            for index, (field, value) in enumerate(profile.items()):
                with edit_columns[index % len(edit_columns)]:
                    if isinstance(value, bool):
                        updated = st.checkbox(
                            field.replace("_", " ").title(),
                            value=value,
                            key=f"edit-field-{approval_hash}-{edit_revision}-{field}",
                        )
                    elif isinstance(value, int):
                        updated = st.number_input(
                            field.replace("_", " ").title(),
                            value=value,
                            step=1,
                            key=f"edit-field-{approval_hash}-{edit_revision}-{field}",
                        )
                    elif isinstance(value, float):
                        updated = st.number_input(
                            field.replace("_", " ").title(),
                            value=value,
                            key=f"edit-field-{approval_hash}-{edit_revision}-{field}",
                        )
                    elif isinstance(value, str):
                        updated = st.text_input(
                            field.replace("_", " ").title(),
                            value=value,
                            key=f"edit-field-{approval_hash}-{edit_revision}-{field}",
                        )
                    else:
                        continue
                    if updated != value:
                        changes[field] = updated
            edit_submitted = st.form_submit_button(
                "Save changes and recheck eligibility",
                disabled=not changes,
            )
        if edit_submitted:
            try:
                with st.status(
                    "Rechecking eligibility and rebuilding the draft...",
                    expanded=True,
                ) as progress:
                    updated_result = _send_workflow(
                        api_base,
                        f"/api/threads/{quote(result['thread_id'], safe='')}/decision",
                        {"action": "edit", "changes": changes},
                        progress,
                    )
            except (RuntimeError, ValueError, json.JSONDecodeError) as error:
                st.error(str(error), title="Could not update the application")
            else:
                st.session_state["application_result"] = updated_result
                st.session_state["application_outcome"] = None
                st.session_state["application_editing"] = False
                st.session_state["application_edit_revision"] += 1
                st.rerun()

        if st.button("Cancel editing", key="cancel-edit-application"):
            st.session_state["application_editing"] = False
            st.session_state["application_edit_revision"] += 1
            st.rerun()


def _finish_application(
    api_base: str, result: dict[str, Any], decision: dict[str, Any]
) -> None:
    """Submit an explicit approval/rejection and store the resulting outcome."""
    with st.status("Recording your decision...", expanded=True) as progress:
        try:
            outcome = _send_workflow(
                api_base,
                f"/api/threads/{quote(result['thread_id'], safe='')}/decision",
                decision,
                progress,
            )
        except (RuntimeError, ValueError, json.JSONDecodeError) as error:
            st.error(str(error), title="Could not record the decision")
            return
    st.session_state["application_result"] = outcome
    if outcome.get("submission"):
        st.session_state["application_outcome"] = "submitted"
    elif outcome.get("approval_status") == "rejected":
        st.session_state["application_outcome"] = "rejected"
    else:
        st.session_state["application_outcome"] = "not_submitted"
    st.rerun()


def _journey_step() -> tuple[int, str]:
    """Return the visible step in the documented five-step citizen journey."""
    outcome = st.session_state["application_outcome"]
    if outcome:
        return 5, "Confirmation"

    if not st.session_state["chat_eligibility_result"]:
        return 1, "Your details"
    if not st.session_state["application_result"]:
        return 2, "Eligibility"

    result = st.session_state["application_result"]
    if not result.get("application"):
        return 2, "Eligibility"
    scheme_id = result.get("application", {}).get("scheme_id")
    required = result.get("documents", {}).get(scheme_id, [])
    uploaded = st.session_state["application_uploads"]
    if all(document in uploaded for document in required):
        return 4, "Review"
    return 3, "Documents"


def _render_eligibility_screen(
    eligibility_result: dict[str, Any], api_base: str
) -> None:
    """Present profile facts and reviewed eligibility results as one workflow stage."""
    with st.container(key="eligibility-screen"):
        st.subheader("Eligibility results")
        st.caption(
            "Results are determined by reviewed scheme rules. The assistant explains "
            "the findings but does not decide eligibility."
        )
        assistant_explanation = next(
            (
                message["content"]
                for message in reversed(st.session_state["chat_messages"])
                if message.get("result")
            ),
            None,
        )
        if assistant_explanation:
            with st.container(border=True):
                st.markdown(assistant_explanation)
        profile_column, results_column = st.columns([0.85, 1.5], gap="medium")
        with profile_column:
            with st.container(border=True):
                st.markdown("**Details checked**")
                _render_workflow_fields(eligibility_result.get("profile", {}))
        with results_column:
            verdicts = eligibility_result.get("verdicts", {})
            if not verdicts:
                st.info("No reviewed eligibility rules were available to check.")
            for scheme_id, verdict in verdicts.items():
                with st.container(border=True):
                    name = eligibility_result.get("scheme_names", {}).get(
                        scheme_id, scheme_id
                    )
                    st.markdown(f"**{name}**")
                    status = verdict.get("verdict", "cant_tell")
                    if status == "eligible":
                        st.success("May be eligible", icon=":material/check_circle:")
                    elif status == "not_eligible":
                        st.warning(
                            "Does not currently match", icon=":material/info:"
                        )
                    else:
                        st.info("Could not determine", icon=":material/help:")
                    st.write(verdict.get("reason", "No explanation was returned."))
                    for citation in verdict.get("citations", []):
                        st.caption(
                            f"{citation.get('clause_id', 'Reviewed source')}: "
                            f"{citation.get('text', '')}"
                        )
    _render_application_start(api_base, eligibility_result)


def _render_welcome() -> None:
    """Explain the demo journey and safe-data expectations before chat starts."""
    if st.session_state["chat_messages"]:
        return

    with st.container(border=True):
        st.subheader("Find support that may fit your situation")
        st.write(
            "Describe your household and what support you need. The assistant "
            "will ask for missing details before checking reviewed scheme rules."
        )
        st.caption(
            "1. Your details  →  2. Eligibility  →  3. Documents  →  "
            "4. Review  →  5. Confirmation"
        )
        st.info(
            "This is a local demo. Supporting documents are stored unencrypted "
            "and automatically deleted after 30 days; you can also delete them sooner. "
            "Upload redacted files only. "
            "Approval creates a mock submission—not a government application. "
            "Never share Aadhaar, bank-account numbers, OTPs, or passwords."
        )
        st.markdown(
            "**Try:** “I’m 62, a widow, and our household earns ₹20,000 a month. "
            "What support may I qualify for?”"
        )


def _render_application_workflow(api_base: str, current_step: int) -> None:
    """Render the active documents, review, or confirmation workflow screen."""
    result = st.session_state["application_result"]
    if not result:
        return

    with st.container(key="application-workflow"):
        scheme_id = result.get("application", {}).get(
            "scheme_id", "Selected scheme"
        )

        outcome = st.session_state["application_outcome"]
        if current_step == 5 and (
            outcome == "submitted" or result.get("submission")
        ):
            submission = result.get("submission") or {}
            with st.container(border=True):
                st.markdown(":material/task_alt: **Application complete**")
                st.title("Your application has been recorded")
                st.write(
                    f"**Reference:** "
                    f"{submission.get('application_id', 'Unavailable')}"
                )
                st.write(
                    f"**Status:** {submission.get('status', 'submitted (mock)')}"
                )
                st.caption(f"Scheme: {scheme_id}")
                st.info(
                    "This is a local demonstration only. It is not a government "
                    "application and does not guarantee a benefit."
                )
                reference = str(submission.get("application_id", "")).strip()
                if reference:
                    try:
                        if __package__:
                            from .document_exports import (
                                application_filename,
                                create_application_docx,
                                create_application_pdf,
                            )
                        else:
                            from document_exports import (
                                application_filename,
                                create_application_docx,
                                create_application_pdf,
                            )
                    except ModuleNotFoundError as error:
                        if error.name not in {"barcode", "docx", "reportlab"}:
                            raise
                        st.error(
                            "Application downloads need the project's declared "
                            "document packages. Install them for this Streamlit "
                            f"Python with `{sys.executable} -m pip install -e .`."
                        )
                    else:
                        export_data = {
                            "reference": reference,
                            "scheme_id": str(
                                submission.get("scheme_id", scheme_id)
                            ),
                            "status": str(
                                submission.get("status", "submitted (mock)")
                            ),
                            "profile": result.get("profile", {}),
                            "application": result.get("application", {}),
                            "eligibility": st.session_state[
                                "chat_eligibility_result"
                            ]
                            or {},
                            "required_documents": result.get("documents", {}).get(
                                scheme_id, []
                            ),
                            "uploads": st.session_state["application_uploads"],
                        }
                        pdf_column, docx_column = st.columns(2, gap="small")
                        pdf_column.download_button(
                            "Download PDF",
                            data=create_application_pdf(**export_data),
                            file_name=application_filename(reference, "pdf"),
                            mime="application/pdf",
                            icon=":material/picture_as_pdf:",
                            key="download-application-pdf",
                            width="stretch",
                        )
                        docx_column.download_button(
                            "Download Word document",
                            data=create_application_docx(**export_data),
                            file_name=application_filename(reference, "docx"),
                            mime=(
                                "application/vnd.openxmlformats-officedocument."
                                "wordprocessingml.document"
                            ),
                            icon=":material/description:",
                            key="download-application-docx",
                            width="stretch",
                        )
                        st.caption(
                            "Both files include the reference barcode and masked ID "
                            "numbers. The barcode represents this demo reference only."
                        )
                        uploads = st.session_state["application_uploads"]
                        if uploads:
                            st.markdown("#### Supporting documents")
                            document_columns = st.columns(2, gap="small")
                            for index, (document_type, metadata) in enumerate(
                                uploads.items()
                            ):
                                document_url = (
                                    f"{api_base}/api/threads/"
                                    f"{quote(result['thread_id'], safe='')}/documents/"
                                    f"{quote(str(metadata.get('scheme_id', scheme_id)), safe='')}/"
                                    f"{quote(document_type, safe='')}"
                                )
                                with document_columns[
                                    index % len(document_columns)
                                ]:
                                    st.link_button(
                                        f"Download {document_type}",
                                        document_url,
                                        icon=":material/download:",
                                        width="stretch",
                                    )
                                    st.caption(
                                        f"{metadata.get('filename', document_type)} · "
                                        f"expires {metadata.get('expires_at', 'in 30 days')}"
                                    )
                            if st.button(
                                "Forget uploaded documents",
                                key="forget-uploaded-documents",
                                icon=":material/delete:",
                            ):
                                if _delete_uploaded_documents(
                                    result.get("thread_id"), api_base
                                ):
                                    st.session_state["application_uploads"] = {}
                                    st.success(
                                        "Uploaded document copies were deleted."
                                    )
                else:
                    st.error(
                        "A reference number is missing, so a downloadable "
                        "application record cannot be generated."
                    )
                if st.button(
                    "Start a new chat",
                    type="primary",
                    key="new-chat-after-submit",
                ):
                    if _reset_chat():
                        st.rerun()
            return
        if current_step == 5 and (
            outcome == "rejected" or result.get("approval_status") == "rejected"
        ):
            with st.container(border=True):
                st.markdown(":material/do_not_disturb_on: **Application closed**")
                st.title("The draft was rejected")
                st.write("Nothing was submitted.")
                st.caption(f"Scheme: {scheme_id}")
                if st.button(
                    "Start a new chat",
                    type="primary",
                    key="new-chat-after-reject",
                ):
                    if _reset_chat():
                        st.rerun()
            return
        if current_step == 5 and outcome == "not_submitted":
            with st.container(border=True):
                st.error(
                    "The application was not submitted. Review the result and start "
                    "a new chat if you want to prepare another draft."
                )
                if st.button(
                    "Start a new chat",
                    type="primary",
                    key="new-chat-after-not-submitted",
                ):
                    if _reset_chat():
                        st.rerun()
            return

        if not result.get("application"):
            st.warning(
                "The application draft could not be prepared for this profile. "
                "Review the eligibility result or start a new chat."
            )
            return

        if current_step == 3:
            st.caption(f"Selected scheme: {scheme_id}")
            with st.container(border=True):
                _render_document_step(result)
                latest_upload_message = next(
                    (
                        message["content"]
                        for message in reversed(st.session_state["chat_messages"])
                        if message["role"] == "assistant"
                        and message["content"].startswith("Document upload failed:")
                    ),
                    None,
                )
                if latest_upload_message:
                    st.error(latest_upload_message)
        elif current_step == 4:
            st.caption(f"Selected scheme: {scheme_id}")
            document_column, review_column = st.columns(
                [0.8, 2.2], gap="medium", vertical_alignment="top"
            )
            with document_column:
                with st.container(border=True):
                    _render_document_step(result)
            with review_column:
                with st.container(border=True):
                    _render_review_step(api_base, result, documents_complete=True)


def _handle_chat_submission(
    api_base: str, submission: Any, response_slot: Any
) -> None:
    """Render a submitted turn and its streaming response above the chat composer."""
    text = submission if isinstance(submission, str) else submission.text
    files = [] if isinstance(submission, str) else submission.files
    user_text = text.strip()
    display_text = "\n".join(
        [
            *([user_text] if user_text else []),
            *[f"Attached document: {upload.name}" for upload in files],
        ]
    )
    with response_slot:
        with st.chat_message("user"):
            st.markdown(display_text)

        st.session_state["chat_messages"].append(
            {"role": "user", "content": display_text}
        )
        application_result = st.session_state["application_result"]

        if files:
            with st.chat_message("assistant"):
                if len(files) > 1:
                    assistant_reply = (
                        "Attach one document at a time so it can be matched to "
                        "the next required document."
                    )
                elif not application_result or not application_result.get("application"):
                    assistant_reply = (
                        "First complete the eligibility check and choose an "
                        "eligible scheme. Then attach its required documents here."
                    )
                else:
                    scheme_id = application_result["application"]["scheme_id"]
                    mask_confirmation_key = (
                        f"document-sensitive-ids-masked-"
                        f"{application_result.get('thread_id', '')}"
                    )
                    if not st.session_state.get(mask_confirmation_key, False):
                        assistant_reply = (
                            "Before uploading, mask any full Aadhaar, bank-account, "
                            "or other ID numbers in the document, then confirm this "
                            "on the Documents screen."
                        )
                        st.warning(assistant_reply)
                    else:
                        required = application_result.get("documents", {}).get(
                            scheme_id, []
                        )
                        uploaded = st.session_state["application_uploads"]
                        next_document = next(
                            (name for name in required if name not in uploaded), None
                        )
                        if next_document is None:
                            assistant_reply = (
                                "All required documents have already been uploaded."
                            )
                        else:
                            try:
                                with st.status(
                                    f"Validating {next_document}...", expanded=True
                                ) as progress:
                                    progress.write(
                                        "Validating and saving the document."
                                    )
                                    upload_result = _upload_document(
                                        api_base,
                                        application_result,
                                        scheme_id,
                                        next_document,
                                        files[0],
                                    )
                                    st.session_state["application_uploads"][
                                        next_document
                                    ] = upload_result
                                    progress.update(
                                        label=f"{next_document} uploaded",
                                        state="complete",
                                    )
                                assistant_reply = (
                                    f"Uploaded **{next_document}** "
                                    f"({upload_result['filename']})."
                                )
                            except (RuntimeError, ValueError) as error:
                                assistant_reply = f"Document upload failed: {error}"
                                st.error(str(error), title="Upload failed")
                st.markdown(assistant_reply)
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": assistant_reply}
            )

        if user_text:
            assistant_result = None
            with st.chat_message("assistant"):
                if st.session_state["chat_eligibility_result"] is not None:
                    assistant_reply = (
                        "This eligibility check is complete. Attach a required "
                        "document here or start a new chat to check another profile."
                    )
                    st.markdown(assistant_reply)
                else:
                    try:
                        with st.status(
                            "Reviewing your details...", expanded=True
                        ) as progress:
                            (
                                session_id,
                                chat_reply,
                                assistant_result,
                            ) = _send_chat(
                                api_base,
                                user_text,
                                st.session_state["chat_session_id"],
                                progress,
                            )
                            st.session_state["chat_session_id"] = session_id
                            progress.update(
                                label=(
                                    "Eligibility check complete"
                                    if assistant_result
                                    and assistant_result.get("status")
                                    == "eligibility_checked"
                                    else "Waiting for your details"
                                ),
                                state="complete",
                            )
                        st.markdown(chat_reply)
                        if assistant_result and assistant_result.get("verdicts"):
                            _render_eligibility(assistant_result)
                        assistant_reply = chat_reply
                    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
                        assistant_reply = (
                            "I couldn’t complete that step. Please try again. "
                            f"Details: {error}"
                        )
                        st.error(str(error), title="Request failed")
                        st.markdown(assistant_reply)

            if (
                assistant_result
                and assistant_result.get("status") == "eligibility_checked"
            ):
                st.session_state["chat_eligibility_result"] = assistant_result
            st.session_state["chat_messages"].append(
                {
                    "role": "assistant",
                    "content": assistant_reply,
                    "result": (
                        assistant_result
                        if assistant_result and assistant_result.get("verdicts")
                        else None
                    ),
                }
            )


def _initialize_portal_state() -> None:
    """Set up session-only access, consent, and workflow state."""
    defaults = {
        "portal_stage": "access",
        "access_error": None,
        "show_password_help": False,
        "citizen_name": "",
        "consent_given": False,
        "consent_recorded_at": None,
        "consent_error": None,
        "chat_session_id": None,
        "chat_messages": [],
        "chat_eligibility_result": None,
        "application_result": None,
        "application_uploads": {},
        "application_outcome": None,
        "application_editing": False,
        "application_edit_revision": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _complete_access(mode: str) -> None:
    """Advance the UI prototype without sending or retaining credentials."""
    contact = str(st.session_state.get("access-contact", "")).strip()
    password = str(st.session_state.get("access-password", ""))
    name = str(st.session_state.get("access-name", "")).strip()

    if not contact or not password:
        st.session_state["access_error"] = "Enter your phone or email and password."
        return
    if mode == "Create account":
        confirmation = str(st.session_state.get("access-confirm-password", ""))
        if not name:
            st.session_state["access_error"] = "Enter your name to create an account."
            return
        if password != confirmation:
            st.session_state["access_error"] = "The passwords do not match."
            return
        if not st.session_state.get("access-terms", False):
            st.session_state["access_error"] = "Accept the demo terms to continue."
            return

    st.session_state["citizen_name"] = name or "there"
    st.session_state["access_error"] = None
    st.session_state["show_password_help"] = False
    st.session_state["portal_stage"] = "consent"
    st.session_state["access-password"] = ""
    st.session_state["access-confirm-password"] = ""
    st.session_state["access-contact"] = ""


def _render_access_page() -> None:
    """Render the login and registration entry screens for the UI prototype."""
    with st.container(key="auth-page"):
        with st.container(border=True, key="auth-shell"):
            with st.container(key="auth-brand"):
                st.markdown("### :material/account_balance: Scheme Saathi")
            st.caption("PUBLIC SUPPORT, MADE SIMPLE")
            mode = st.segmented_control(
                "Account access",
                options=["Sign in", "Create account"],
                default="Sign in",
                key="access-mode",
                label_visibility="collapsed",
            )
            if mode is None:
                mode = "Sign in"

            st.title("Welcome back" if mode == "Sign in" else "Create your account")
            st.write(
                "Sign in to explore support schemes for your household."
                if mode == "Sign in"
                else "A few details to start your guided scheme search."
            )

            with st.form(f"access-form-{mode.lower().replace(' ', '-')}"):
                if mode == "Create account":
                    st.text_input(
                        "Full name",
                        key="access-name",
                        max_chars=120,
                        placeholder="Enter your name",
                    )
                st.text_input(
                    "Phone or email",
                    key="access-contact",
                    max_chars=254,
                    placeholder="you@example.com or phone number",
                )
                st.text_input(
                    "Password",
                    type="password",
                    key="access-password",
                    max_chars=256,
                    placeholder="Enter your password",
                )
                if mode == "Create account":
                    st.text_input(
                        "Confirm password",
                        type="password",
                        key="access-confirm-password",
                        max_chars=256,
                        placeholder="Re-enter your password",
                    )
                    st.checkbox(
                        "I agree to the demo terms and privacy notice",
                        key="access-terms",
                    )
                st.form_submit_button(
                    "Sign in" if mode == "Sign in" else "Create account",
                    type="primary",
                    width="stretch",
                    on_click=_complete_access,
                    args=(mode,),
                )

            if mode == "Sign in":
                if st.button("Forgot password?", key="forgot-password"):
                    st.session_state["show_password_help"] = True
                if st.session_state["show_password_help"]:
                    st.info(
                        "Password recovery is not available in this UI prototype."
                    )
            if st.session_state["access_error"]:
                st.error(st.session_state["access_error"])
            st.caption(
                "Demo only. Do not use a real password. This is not an official "
                "government portal."
            )


def _complete_consent() -> None:
    """Record an in-session consent decision and open the chat only on acceptance."""
    if not st.session_state.get("session-consent", False):
        st.session_state["consent_error"] = (
            "Please confirm consent before continuing to the chat."
        )
        return

    st.session_state["consent_given"] = True
    st.session_state["consent_recorded_at"] = datetime.now(timezone.utc).isoformat()
    st.session_state["consent_error"] = None
    st.session_state["portal_stage"] = "chat"


def _decline_consent() -> None:
    """Return to the access screen without enabling chat."""
    st.session_state["portal_stage"] = "access"
    st.session_state["consent_given"] = False
    st.session_state["session-consent"] = False


def _render_consent_page() -> None:
    """Present a clear privacy notice before opening the guided chat."""
    with st.container(key="consent-page"):
        with st.container(key="consent-header"):
            brand_col, step_col = st.columns([3, 1], vertical_alignment="center")
            brand_col.markdown("### :material/account_balance: Scheme Saathi")
            brand_col.caption("PUBLIC SUPPORT, MADE SIMPLE")
            step_col.markdown("**BEFORE YOU BEGIN**")
            step_col.caption("Privacy and consent")

        with st.container(border=True, key="consent-shell"):
            st.markdown(":material/verified_user: PRIVACY & CONSENT")
            st.title("Your information. Your choice.")
            st.write(
                "Please review how information is used before continuing to "
                "your scheme search."
            )

            use_col, handling_col = st.columns(2, gap="medium")
            with use_col:
                with st.container(border=True, key="consent-use-card"):
                    st.markdown("**How your information is used**")
                    st.write(
                        "Details you choose to share help the service ask relevant "
                        "follow-up questions and check reviewed scheme rules."
                    )
            with handling_col:
                with st.container(border=True, key="consent-handling-card"):
                    st.markdown("**How it is handled**")
                    st.write(
                        "Your responses are processed by this application to provide "
                        "the current workflow. Redacted supporting documents are "
                        "stored locally without encryption for up to 30 days. This screen "
                        "does not submit information to a government portal."
                    )

            with st.container(key="consent-sensitive-notice"):
                st.warning(
                    "For your safety, do not enter Aadhaar numbers, bank-account "
                    "details, passwords, OTPs, or other sensitive identifiers."
                )

            st.caption(
                "Your consent choice applies to this active application session. "
                "You may withdraw it later; doing so clears the conversation and "
                "deletes supporting documents for the active application."
            )

            with st.form("session-consent-form"):
                st.checkbox(
                    "I have read this notice and agree to use my information "
                    "for this session.",
                    key="session-consent",
                )
                st.form_submit_button(
                    "Agree and continue",
                    type="primary",
                    width="stretch",
                    on_click=_complete_consent,
                )
            if st.session_state["consent_error"]:
                st.error(st.session_state["consent_error"])

            st.button(
                "I do not agree — return to sign in",
                key="decline-consent",
                on_click=_decline_consent,
                width="stretch",
            )


def _withdraw_consent() -> bool:
    """Clear the current workflow and return to the consent screen."""
    if not _reset_chat():
        return False
    st.session_state["portal_stage"] = "consent"
    st.session_state["consent_given"] = False
    st.session_state["consent_recorded_at"] = None
    st.session_state["session-consent"] = False
    return True


def _render_wizard(current_step: int) -> None:
    """Keep the five-step workflow tracker visible above each active screen."""
    with st.container(key="workflow-wizard"):
        st.caption("APPLICATION WORKFLOW")
        step_columns = st.columns(len(JOURNEY_STEPS), gap="small")
        for index, (column, label) in enumerate(
            zip(step_columns, JOURNEY_STEPS), start=1
        ):
            if index < current_step:
                state = "complete"
                marker = ":material/check_circle:"
            elif index == current_step:
                state = "current"
                marker = ":material/radio_button_checked:"
            else:
                state = "upcoming"
                marker = ":material/radio_button_unchecked:"
            with column:
                with st.container(key=f"wizard-step-{state}-{index}"):
                    st.markdown(f"{marker} **{label}**")
        st.progress(
            current_step / len(JOURNEY_STEPS),
            text=f"Step {current_step} of {len(JOURNEY_STEPS)}",
        )


def _render_api_reference() -> None:
    """Show the API reference independently from the citizen-facing workflow."""
    st.title("API reference")
    st.write(
        "The endpoints below are generated from the running FastAPI OpenAPI "
        "schema and document the service contract separately from the citizen flow."
    )
    try:
        api_base = _api_base_url()
        with urlopen(f"{api_base}/openapi.json", timeout=5) as response:
            schema = json.loads(response.read().decode("utf-8"))
    except (RuntimeError, ValueError, OSError, URLError) as error:
        st.error(str(error), title="API reference is unavailable")
        return

    if not isinstance(schema, dict) or not isinstance(schema.get("paths"), dict):
        st.error("FastAPI returned an invalid OpenAPI document.")
        return

    st.caption(f"API base URL: `{api_base}`")
    st.link_button(
        "Open interactive API docs",
        f"{api_base}/docs",
        icon=":material/open_in_new:",
    )
    grouped: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, methods in schema["paths"].items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
            } or not isinstance(operation, dict):
                continue
            tags = operation.get("tags") or ["Other"]
            grouped.setdefault(str(tags[0]), []).append(
                (method.upper(), path, operation)
            )

    for tag, operations in grouped.items():
        with st.expander(f"{tag} · {len(operations)} endpoints", expanded=True):
            for method, path, operation in operations:
                with st.container(border=True):
                    method_col, path_col = st.columns([1, 4])
                    method_col.markdown(f"**{method}**")
                    path_col.code(path, language=None)
                    summary = operation.get("summary")
                    if summary:
                        st.write(summary)


def _render_chat_page() -> None:
    """Run the consented chat intake and later application workflow."""
    st.session_state.setdefault("chat_session_id", None)
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault("chat_eligibility_result", None)
    st.session_state.setdefault("application_result", None)
    st.session_state.setdefault("application_uploads", {})
    st.session_state.setdefault("application_outcome", None)
    st.session_state.setdefault("application_editing", False)
    st.session_state.setdefault("application_edit_revision", 0)

    title_col, action_col = st.columns([4, 1], vertical_alignment="center")
    title_col.markdown("### :material/account_balance: Scheme Saathi")
    title_col.caption(
        "A guided way to explore public support · "
        f"{st.session_state['citizen_name']}"
    )
    with action_col:
        if st.button(
            "New chat",
            icon=":material/add:",
            disabled=not st.session_state["chat_messages"],
            key="new-chat",
            width="stretch",
        ):
            if _reset_chat():
                st.rerun()
        if st.button(
            "Withdraw consent",
            icon=":material/lock:",
            key="withdraw-consent",
            width="stretch",
        ):
            if _withdraw_consent():
                st.rerun()

    try:
        api_base = _api_base_url()
        health = Request(f"{api_base}/health", method="GET")
        with urlopen(health, timeout=3) as response:
            health_payload = json.loads(response.read().decode("utf-8"))
        if health_payload.get("status") != "ok":
            raise RuntimeError("FastAPI returned an unexpected health response.")
    except (RuntimeError, ValueError, OSError) as error:
        st.error(str(error), title="FastAPI is unavailable")
        st.stop()

    current_step, _ = _journey_step()
    _render_wizard(current_step)
    with st.container(key="workflow-screen"):
        if current_step == 1:
            _render_welcome()
            for message in st.session_state["chat_messages"]:
                _render_message(message)
        elif current_step == 2:
            eligibility_result = st.session_state["chat_eligibility_result"]
            if eligibility_result:
                _render_eligibility_screen(eligibility_result, api_base)
        else:
            _render_application_workflow(api_base, current_step)

    # Reserve this location before the composer so submitted messages and streamed
    # workflow updates render above the input even though the submission is handled later.
    response_slot = st.container()
    # Pin the prompt and its always-visible starter guidance to the bottom of
    # the app viewport while keeping workflow output in the main content above.
    with st.bottom:
        st.caption("Tell us what you need. We’ll ask only for missing details.")
        prompt = st.chat_input(
            "Ask about eligibility or share a requested detail...",
            max_chars=4000,
            max_upload_size=10,
            accept_file=True,
            file_type=["pdf", "png", "jpg", "jpeg"],
            submit_mode="disable",
            disabled=st.session_state["application_outcome"] is not None,
        )

    if prompt:       
        _handle_chat_submission(api_base, prompt, response_slot)
        st.rerun()


def _render_citizen_portal() -> None:
    """Route the citizen through access, consent, then the chat workflow."""
    stage = st.session_state["portal_stage"]
    if stage == "access":
        _render_access_page()
    elif stage == "consent":
        _render_consent_page()
    elif stage == "chat" and st.session_state["consent_given"]:
        _render_chat_page()
    else:
        st.session_state["portal_stage"] = "consent"
        _render_consent_page()


def main() -> None:
    """Run the citizen experience and API reference as separate Streamlit pages."""
    st.set_page_config(
        page_title="Scheme Saathi",
        page_icon=":material/account_balance:",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.html(CSS_PATH)
    _initialize_portal_state()
    page = st.navigation(
        {
            "Experience": [
                st.Page(
                    _render_citizen_portal,
                    title="Citizen portal",
                    icon=":material/volunteer_activism:",
                    default=True,
                )
            ],
            "Developer": [
                st.Page(
                    _render_api_reference,
                    title="API reference",
                    icon=":material/api:",
                )
            ],
        },
        position="top",
    )
    page.run()


if __name__ == "__main__":
    main()
