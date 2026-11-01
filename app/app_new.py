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
    st.session_state["application_editing"] = False
    st.session_state["application_edit_revision"] = 0
    for key in list(st.session_state):
        if key.startswith(
            ("edit-field-", "confirm-application-submission-")
        ):
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
        "The demo validates each file, then discards its contents and keeps only "
        "upload metadata. Use redacted test files; maximum size is 10 MB."
    )
    missing = []
    for document_type in required_documents:
        with st.container(border=True):
            st.markdown(f"**{document_type}**")
            existing = uploads.get(document_type)
            if existing:
                st.success(f"Uploaded: {existing['filename']}")
            else:
                missing.append(document_type)

    if missing:
        st.info(
            "Still required: "
            + ", ".join(missing)
            + ". Attach the next document using the paperclip in the chat input below."
        )
    else:
        st.success("All required documents are recorded.")
    return not missing


def _render_review_step(
    api_base: str, result: dict[str, Any], documents_complete: bool
) -> None:
    """Let the user approve, edit, or reject the reviewed application draft."""
    st.markdown("#### Step 4 — Review the application draft")
    st.write("Check the profile and exact draft below before making a decision.")
    st.json(result.get("profile", {}), expanded=False)
    st.markdown("**Application draft**")
    st.json(result.get("application", {}), expanded=True)
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
            for field, value in profile.items():
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
            "1. Share your details  →  2. Check eligibility  →  "
            "3. Add requested documents  →  4. Review the draft and "
            "approve, edit, or reject"
        )
        st.info(
            "This is a local demo. Uploads keep metadata only, and approval "
            "creates a mock submission—not a government application. Never "
            "share Aadhaar, bank-account numbers, OTPs, or passwords."
        )
        st.markdown(
            "**Try:** “I’m 62, a widow, and our household earns ₹20,000 a month. "
            "What support may I qualify for?”"
        )


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
        st.info("The draft was rejected. Nothing was submitted.")
        if st.button("Start a new chat", type="primary", key="new-chat-after-reject"):
            _reset_chat()
            st.rerun()
        return
    if outcome == "not_submitted":
        st.error(
            "The application was not submitted. Review the result and start a "
            "new chat if you want to prepare another draft."
        )
        if st.button(
            "Start a new chat",
            type="primary",
            key="new-chat-after-not-submitted",
        ):
            _reset_chat()
            st.rerun()
        return

    if not result.get("application"):
        st.warning(
            "The application draft could not be prepared for this profile. "
            "Review the eligibility result or start a new chat."
        )
        return

    documents_complete = _render_document_step(result)
    st.markdown("#### Step 4 — Review and decide")
    _render_review_step(api_base, result, documents_complete)


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
                                    "Checking the file and recording upload metadata."
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
    st.session_state.setdefault("application_editing", False)
    st.session_state.setdefault("application_edit_revision", 0)

    title_col, action_col = st.columns([4, 1], vertical_alignment="center")
    title_col.markdown("### :material/account_balance: Scheme Saathi")
    title_col.caption("A guided way to explore public support")
    if action_col.button(
        "New chat",
        icon=":material/add:",
        disabled=not st.session_state["chat_messages"],
        key="new-chat",
        width="stretch",
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

    step, label = _journey_step()
    st.progress(step / 5, text=f"Step {step} of 5 · {label}")
    _render_welcome()

    if st.session_state["chat_messages"]:
        for message in st.session_state["chat_messages"]:
            _render_message(message)

    # Keep the application continuation and its current step above the chat
    # composer so the next action is always visible before the input.
    eligibility_result = st.session_state["chat_eligibility_result"]
    if eligibility_result and not st.session_state["application_result"]:
        _render_application_start(api_base, eligibility_result)
    _render_application_workflow(api_base)

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

if __name__ == "__main__":
    main()
