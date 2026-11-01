"""Conversational citizen portal with eligibility, documents, and mock submission."""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from collections.abc import Iterator
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
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


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
    _start_local_api(port)
    return f"http://127.0.0.1:{port}"


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
    """Upload a required PDF/image; the API validates it and retains metadata only."""
    boundary = f"----SchemeSaathi{uuid4().hex}"
    filename = Path(uploaded_file.name.replace("\\", "/")).name
    filename = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    content_type = uploaded_file.type or "application/octet-stream"
    parts = []
    for name, value in (
        ("scheme_id", scheme_id),
        ("document_type", document_type),
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
        f"{api_base}/api/chat",
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


def _reset_chat() -> None:
    """Clear chat/application data and widget values before another profile is checked."""
    st.session_state["chat_session_id"] = None
    st.session_state["chat_messages"] = []
    st.session_state["chat_eligibility_result"] = None
    st.session_state["application_result"] = None
    st.session_state["application_uploads"] = {}
    st.session_state["application_outcome"] = None
    for key in list(st.session_state):
        if key.startswith("edit-field-") or key == "confirm-application-submission":
            del st.session_state[key]


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
    st.divider()
    st.subheader("Continue through the full workflow")
    st.caption(
        "Eligibility guidance is informational. The remaining steps prepare "
        "and record a mock application; nothing is sent to a government service."
    )
    st.progress(0.4, text="Step 2 of 5 · Eligibility")
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


def _render_document_step(api_base: str, result: dict[str, Any]) -> bool:
    """Show required documents, upload them, and report whether review can begin."""
    scheme_id = result.get("application", {}).get("scheme_id")
    required_documents = result.get("documents", {}).get(scheme_id, [])
    uploads = st.session_state["application_uploads"]
    st.markdown("#### Step 3 — Upload required documents")
    st.caption(
        "The demo validates each file, then discards its contents and keeps only "
        "upload metadata. Use redacted test files; maximum size is 10 MB."
    )
    for index, document_type in enumerate(required_documents):
        with st.container(border=True):
            st.markdown(f"**{document_type}**")
            existing = uploads.get(document_type)
            if existing:
                st.success(f"Uploaded: {existing['filename']}")
                continue
            uploaded_file = st.file_uploader(
                f"Choose {document_type}",
                type=["pdf", "png", "jpg", "jpeg"],
                max_upload_size=10,
                key=f"workflow-upload-{result['thread_id']}-{index}",
            )
            if uploaded_file and st.button(
                f"Upload {document_type}",
                key=f"workflow-upload-button-{result['thread_id']}-{index}",
                disabled=uploaded_file.size > MAX_UPLOAD_BYTES,
            ):
                try:
                    response = _upload_document(
                        api_base,
                        result,
                        scheme_id,
                        document_type,
                        uploaded_file,
                    )
                except (RuntimeError, ValueError) as error:
                    st.error(str(error), title="Upload failed")
                else:
                    uploads[document_type] = response
                    st.success(f"{document_type} uploaded.")
                    st.rerun()

    missing = [doc for doc in required_documents if doc not in uploads]
    if missing:
        st.info("Still required: " + ", ".join(missing))
    else:
        st.success("All required documents are recorded.")
    return not missing


def _render_review_step(
    api_base: str, result: dict[str, Any], documents_complete: bool
) -> None:
    """Let the user inspect the draft, edit profile facts, reject, or approve it."""
    st.markdown("#### Step 4 — Review the application draft")
    st.write("Check the profile and exact draft below before making a decision.")
    st.json(result.get("profile", {}), expanded=False)
    st.markdown("**Application draft**")
    st.json(result.get("application", {}), expanded=True)
    st.caption(
        "Approval is tied to this exact draft. Editing sends the updated facts "
        "through eligibility checks again and requires fresh review."
    )

    profile = result.get("profile", {})
    with st.expander("Edit profile facts and regenerate the draft"):
        with st.form("edit-application-profile"):
            changes: dict[str, Any] = {}
            for field, value in profile.items():
                if isinstance(value, bool):
                    updated = st.checkbox(
                        field.replace("_", " ").title(),
                        value=value,
                        key=f"edit-field-{field}",
                    )
                elif isinstance(value, int):
                    updated = st.number_input(
                        field.replace("_", " ").title(),
                        value=value,
                        step=1,
                        key=f"edit-field-{field}",
                    )
                elif isinstance(value, float):
                    updated = st.number_input(
                        field.replace("_", " ").title(),
                        value=value,
                        key=f"edit-field-{field}",
                    )
                elif isinstance(value, str):
                    updated = st.text_input(
                        field.replace("_", " ").title(),
                        value=value,
                        key=f"edit-field-{field}",
                    )
                else:
                    continue
                if updated != value:
                    changes[field] = updated
            edit_submitted = st.form_submit_button(
                "Recheck and regenerate draft",
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
                st.rerun()

    if result.get("needs_human"):
        st.warning("This draft needs human review. It cannot be submitted by this demo.")
        return
    if not result.get("approval"):
        st.warning(
            "A reviewable draft is not available. Check the eligibility details "
            "or start a new chat."
        )
        return

    confirmed = st.checkbox(
        "I reviewed this draft and understand that this is a mock submission.",
        key="confirm-application-submission",
    )
    approve_col, reject_col = st.columns(2)
    if approve_col.button(
        "Approve and submit mock application",
        type="primary",
        disabled=not documents_complete or not confirmed,
        key="approve-mock-application",
    ):
        _finish_application(
            api_base,
            result,
            {"action": "approve", "payload_hash": result["approval"]["payload_hash"]},
        )
    if reject_col.button(
        "Reject draft",
        key="reject-mock-application",
    ):
        _finish_application(api_base, result, {"action": "reject"})


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
    st.session_state["application_outcome"] = (
        "submitted" if outcome.get("submission") else "rejected"
    )
    st.rerun()


def _render_application_workflow(api_base: str) -> None:
    """Render the documents, review, and confirmation steps for the selected scheme."""
    result = st.session_state["application_result"]
    if not result:
        return

    st.divider()
    st.subheader("Your application journey")
    scheme_id = result.get("application", {}).get("scheme_id", "Selected scheme")
    st.caption(f"Selected scheme: {scheme_id}")

    outcome = st.session_state["application_outcome"]
    if outcome == "submitted" or result.get("submission"):
        submission = result.get("submission") or {}
        st.progress(1.0, text="Step 5 of 5 · Confirmation")
        st.success("Your mock application was submitted.")
        st.write(f"**Reference:** {submission.get('application_id', 'Unavailable')}")
        st.write(f"**Status:** {submission.get('status', 'submitted (mock)')}")
        st.info(
            "This is a local demonstration only. It is not a government "
            "application and does not guarantee a benefit."
        )
        if st.button("Start a new chat", type="primary", key="new-chat-after-submit"):
            _reset_chat()
            st.rerun()
        return
    if outcome == "rejected" or result.get("approval_status") == "rejected":
        st.progress(1.0, text="Step 5 of 5 · Draft rejected")
        st.info("The draft was rejected. Nothing was submitted.")
        if st.button("Start a new chat", type="primary", key="new-chat-after-reject"):
            _reset_chat()
            st.rerun()
        return

    if not result.get("application"):
        st.warning(
            "The application draft could not be prepared for this profile. "
            "Review the eligibility result or start a new chat."
        )
        return

    journey_progress = st.progress(0.6, text="Step 3 of 5 · Documents")
    documents_complete = _render_document_step(api_base, result)
    if documents_complete:
        journey_progress.progress(0.8, text="Step 4 of 5 · Review and decision")
    st.markdown("#### Step 4 — Review and decide")
    _render_review_step(api_base, result, documents_complete)


def main() -> None:
    """Run the chat intake and render later application steps from session state."""
    st.set_page_config(
        page_title="Scheme Saathi | Eligibility chat",
        page_icon=":material/account_balance:",
        layout="centered",
    )
    st.html(CSS_PATH)
    st.session_state.setdefault("chat_session_id", None)
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault("chat_eligibility_result", None)
    st.session_state.setdefault("application_result", None)
    st.session_state.setdefault("application_uploads", {})
    st.session_state.setdefault("application_outcome", None)

    title_col, action_col = st.columns([5, 1], vertical_alignment="center")
    title_col.markdown("### :material/account_balance: Scheme Saathi")
    title_col.caption("Tell us what you need. We’ll ask only for missing details.")
    if action_col.button(
        "New chat",
        icon=":material/add:",
        disabled=not st.session_state["chat_messages"],
        key="new-chat",
    ):
        _reset_chat()
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

    if st.session_state["chat_messages"]:
        for message in st.session_state["chat_messages"]:
            _render_message(message)

    # Keep the application continuation and its current step above the chat
    # composer so the next action is always visible before the input.
    eligibility_result = st.session_state["chat_eligibility_result"]
    if eligibility_result and not st.session_state["application_result"]:
        _render_application_start(api_base, eligibility_result)
    _render_application_workflow(api_base)

    # Nest the input so Streamlit lays it out inline, allowing the starter card
    # to appear directly beneath it instead of pinning the input to the viewport.
    with st.container():
        prompt = st.chat_input(
            "Ask about eligibility or share a requested detail...",
            max_chars=4000,
            submit_mode="disable",
            disabled=st.session_state["chat_eligibility_result"] is not None,
        )
        with st.container(border=True):
            st.markdown("#### Start with your question")
            st.write(
                "For example: “I’m 62, a widow, and our household earns "
                "₹20,000 a month. What support may I qualify for?”"
            )
            st.caption(
                "Share only details needed for eligibility. Never enter Aadhaar, "
                "bank-account numbers, OTPs, or passwords."
            )

    if prompt:
        st.session_state["chat_messages"].append(
            {"role": "user", "content": prompt}
        )
        _render_message({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            assistant_reply = None
            result = None
            try:
                with st.status("Reviewing your details...", expanded=True) as progress:
                    (
                        session_id,
                        assistant_reply,
                        result,
                    ) = _send_chat(
                        api_base,
                        prompt,
                        st.session_state["chat_session_id"],
                        progress,
                    )
                    st.session_state["chat_session_id"] = session_id
                    progress.update(
                        label="Eligibility check complete"
                        if result and result.get("status") == "eligibility_checked"
                        else "Waiting for your details",
                        state="complete",
                    )
            except (RuntimeError, ValueError, json.JSONDecodeError) as error:
                assistant_reply = (
                    "I couldn’t complete that step. Please try again. "
                    f"Details: {error}"
                )
                st.error(str(error), title="Request failed")

            if assistant_reply:
                st.markdown(assistant_reply)
            if result and result.get("verdicts"):
                _render_eligibility(result)

            if result and result.get("status") == "eligibility_checked":
                st.session_state["chat_eligibility_result"] = result
            st.session_state["chat_messages"].append(
                {
                    "role": "assistant",
                    "content": assistant_reply or "I could not produce a response.",
                    "result": result if result and result.get("verdicts") else None,
                }
            )
        st.rerun()

if __name__ == "__main__":
    main()
