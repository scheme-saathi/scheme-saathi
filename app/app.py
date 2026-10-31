"""Streamlit citizen portal for the Scheme Saathi demo."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from html import escape
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
STATES = [
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Puducherry",
]
STEPS = {
    "intake": (1, "Your details"),
    "eligibility": (2, "Eligibility"),
    "documents": (3, "Documents"),
    "review": (4, "Review"),
    "success": (5, "Confirmation"),
}


@st.cache_resource
def _start_local_api(port: int) -> uvicorn.Server:
    """Run the local API alongside Streamlit when no external API is configured."""
    server = uvicorn.Server(
        uvicorn.Config(
            create_api(),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(
        target=server.run, name="scheme-saathi-api", daemon=True
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
    external_url = os.environ.get("SCHEME_SAATHI_API_URL")
    if external_url:
        return external_url.rstrip("/")
    port = int(os.environ.get("SCHEME_SAATHI_API_PORT", "8765"))
    _start_local_api(port)
    return f"http://127.0.0.1:{port}"


def _api_request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 300,
) -> Any:
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(message).get("detail", message)
        except json.JSONDecodeError:
            detail = message
        raise RuntimeError(str(detail) or f"API request failed ({error.code}).") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not connect to FastAPI: {error}") from error


def _parse_sse(response: Any) -> Iterator[tuple[str, dict[str, Any]]]:
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


def _post_stream(
    api_base: str, path: str, payload: dict[str, Any], progress: Any
) -> dict[str, Any]:
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
                    progress.write(event_payload.get("label", "Workflow update"))
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
        raise RuntimeError(str(detail) or f"API request failed ({error.code}).") from error
    except URLError as error:
        raise RuntimeError(f"Could not connect to FastAPI: {error}") from error
    if result is None:
        raise RuntimeError("The FastAPI stream ended before returning a result.")
    return result


def _upload_file(
    api_base: str,
    thread_id: str,
    scheme_id: str,
    document_type: str,
    uploaded_file: Any,
) -> dict[str, Any]:
    boundary = f"----SchemeSaathi{uuid4().hex}"
    filename = Path(uploaded_file.name.replace("\\", "/")).name
    filename = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    content_type = uploaded_file.type or "application/octet-stream"
    fields = {
        "scheme_id": scheme_id,
        "document_type": document_type,
    }
    parts: list[bytes] = []
    for name, value in fields.items():
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
    return _api_request(
        f"{api_base}/api/threads/{quote(thread_id, safe='')}/documents/upload",
        method="POST",
        body=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


@st.cache_data(ttl=60)
def _load_schemes(api_base: str) -> list[dict[str, Any]]:
    return _api_request(f"{api_base}/api/schemes")["schemes"]


def _initialize_state() -> None:
    defaults = {
        "page": "welcome",
        "citizen": {},
        "selected_schemes": [],
        "result": None,
        "selected_scheme": None,
        "uploads": {},
        "submitted_at": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _set_page(page: str) -> None:
    st.session_state["page"] = page


def _run_analysis(
    api_base: str, citizen: dict[str, Any], scheme_ids: list[str]
) -> bool:
    with st.status("Checking reviewed scheme rules...", expanded=True) as status:
        try:
            result = _post_stream(
                api_base,
                "/api/analyze",
                {"citizen": citizen, "scheme_ids": scheme_ids},
                status,
            )
        except (RuntimeError, ValueError, json.JSONDecodeError) as error:
            status.update(label="Eligibility check failed", state="error")
            st.error(str(error), title="Request failed")
            return False
        st.session_state["result"] = result
        st.session_state["citizen"] = citizen
        st.session_state["selected_schemes"] = scheme_ids
        st.session_state["selected_scheme"] = None
        st.session_state["uploads"] = {}
        status.update(label="Eligibility check complete", state="complete")
    return True


def _render_header() -> None:
    brand, audience = st.columns([4, 1], vertical_alignment="center")
    brand.markdown("#### :material/account_balance: Scheme Saathi")
    brand.caption("A simpler way to discover public support")
    audience.badge("Citizen portal", icon=":material/person:")
    page = st.session_state["page"]
    if page in STEPS:
        step, label = STEPS[page]
        st.progress(step / len(STEPS), text=f"Step {step} of 5 · {label}")


def _render_welcome() -> None:
    with st.container(key="welcome-page"):
        introduction, overview = st.columns([1.08, 0.92], gap="large")
        with introduction:
            st.badge(
                "WELFARE SCHEME NAVIGATOR",
                icon=":material/verified_user:",
                color="green",
            )
            st.markdown(
                '<div class="welcome-title">Find support that fits your life.</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="welcome-description">Discover public benefit '
                "schemes that may match your circumstances. Get a clear, "
                "step-by-step view of your options.</div>",
                unsafe_allow_html=True,
            )
            if st.button(
                "Explore eligible schemes",
                type="primary",
                icon=":material/arrow_forward:",
                key="start-scheme-search",
            ):
                _set_page("intake")
                st.rerun()
            st.caption(
                ":material/lock: Your details stay in this demo session | "
                "No government application is submitted"
            )

        with overview:
            with st.container(border=True, key="welcome-overview"):
                st.markdown("##### A clear path to support")
                st.caption("A guided experience, from your details to next steps.")
                steps = [
                    (
                        "person",
                        "Tell us about yourself",
                        "A few details help us understand your needs.",
                    ),
                    (
                        "fact_check",
                        "See what may fit",
                        "Compare your profile with reviewed scheme rules.",
                    ),
                    (
                        "description",
                        "Prepare with confidence",
                        "Review required documents and your application.",
                    ),
                ]
                for index, (icon, title, description) in enumerate(steps, start=1):
                    icon_column, detail_column = st.columns(
                        [0.16, 0.84], vertical_alignment="top"
                    )
                    icon_column.markdown(
                        f'<div class="journey-step">{index}</div>',
                        unsafe_allow_html=True,
                    )
                    detail_column.markdown(
                        f"**:material/{icon}: {title}**  \n"
                        f"<span class='journey-description'>{description}</span>",
                        unsafe_allow_html=True,
                    )
                    if index < len(steps):
                        st.html('<div class="journey-connector"></div>')
                st.caption(
                    ":material/info: Eligibility guidance is informational, "
                    "not an official decision."
                )


def _render_intake(api_base: str, schemes: list[dict[str, Any]]) -> None:
    citizen = st.session_state["citizen"]
    scheme_options = {
        scheme["scheme_id"]: f"{scheme['name']} ({scheme['scheme_id']})"
        for scheme in schemes
    }
    default_schemes = [
        scheme_id
        for scheme_id in st.session_state["selected_schemes"]
        if scheme_id in scheme_options
    ] or list(scheme_options)

    st.subheader("Tell us about yourself")
    st.write("The annual income used by scheme rules is calculated from your monthly income.")
    with st.form("citizen-intake"):
        first, second = st.columns(2)
        name = first.text_input(
            "Full name",
            value=citizen.get("name", ""),
            max_chars=120,
            key="intake_name",
        )
        age = second.number_input(
            "Age (years)",
            min_value=0,
            max_value=130,
            value=int(citizen.get("age", 35)),
            key="intake_age",
        )
        state_default = citizen.get("state", "Maharashtra")
        state_index = STATES.index(state_default) if state_default in STATES else 0
        state = first.selectbox(
            "State or union territory",
            STATES,
            index=state_index,
            key="intake_state",
        )
        monthly_income = second.number_input(
            "Monthly household income (INR)",
            min_value=0,
            max_value=100_000_000,
            value=int(citizen.get("monthly_income", 25000)),
            step=1000,
            key="intake_income",
        )
        genders = ["Prefer not to say", "Female", "Male", "Other"]
        gender_value = citizen.get("gender", genders[0])
        gender_index = genders.index(gender_value) if gender_value in genders else 0
        gender = first.selectbox(
            "Gender",
            genders,
            index=gender_index,
            key="intake_gender",
        )
        employment_options = [
            "Employed",
            "Self-employed",
            "Unemployed",
            "Student",
            "Other",
        ]
        employment_value = citizen.get("employment_status", "Employed")
        employment_index = (
            employment_options.index(employment_value)
            if employment_value in employment_options
            else 0
        )
        employment = second.selectbox(
            "Employment status",
            employment_options,
            index=employment_index,
            key="intake_employment",
        )
        status_col, additional_col = st.columns(2)
        is_widow = status_col.checkbox(
            "I am a widow or widower",
            value=bool(citizen.get("is_widow", False)),
            key="intake_widow",
        )
        has_disability = additional_col.checkbox(
            "I have a disability",
            value=bool(citizen.get("disability", False)),
            key="intake_disability",
        )
        minority_status = status_col.checkbox(
            "I belong to a minority community",
            value=bool(citizen.get("minority_status", False)),
            key="intake_minority",
        )
        selected_schemes = st.multiselect(
            "Schemes to check",
            options=list(scheme_options),
            default=default_schemes,
            format_func=scheme_options.__getitem__,
            key="intake_schemes",
        )
        submitted = st.form_submit_button(
            "Check eligibility",
            type="primary",
            width="stretch",
            key="check-eligibility",
        )

    if submitted:
        if not name.strip():
            st.warning("Enter your name to continue.")
        elif not selected_schemes:
            st.warning("Choose at least one scheme to check.")
        else:
            profile = {
                "name": name.strip(),
                "age": int(age),
                "state": state,
                "monthly_income": int(monthly_income),
                "income": int(monthly_income) * 12,
                "gender": gender,
                "employment_status": employment,
                "is_widow": is_widow,
                "disability": has_disability,
                "minority_status": minority_status,
            }
            if _run_analysis(api_base, profile, selected_schemes):
                _set_page("eligibility")
                st.rerun()

    if st.button("Back to welcome", key="back-welcome"):
        _set_page("welcome")
        st.rerun()


def _render_verdicts(
    api_base: str, result: dict[str, Any], schemes: list[dict[str, Any]]
) -> None:
    scheme_names = {scheme["scheme_id"]: scheme["name"] for scheme in schemes}
    verdicts = result.get("verdicts", {})
    eligible_schemes = [
        scheme_id
        for scheme_id, verdict in verdicts.items()
        if verdict.get("verdict") == "eligible"
    ]
    with st.container(key="eligibility-summary"):
        st.badge(
            f"{len(eligible_schemes)} eligible scheme"
            f"{'' if len(eligible_schemes) == 1 else 's'}",
            icon=":material/check_circle:",
            color="green" if eligible_schemes else "gray",
        )
        if eligible_schemes:
            st.markdown("#### Schemes you may be eligible for - ")
            for scheme_id in eligible_schemes:
                st.markdown(
                    f"**{scheme_names.get(scheme_id, scheme_id)}** "
                    f'<span class="scheme-id-pill" title="Scheme Id">{scheme_id}</span>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption(
                "No selected schemes currently match all reviewed eligibility "
                "rules."
            )
    st.subheader("Your eligibility results")
    if not verdicts:
        st.info("No reviewed eligibility rules were available for the selected schemes.")
        return

    for scheme_id, verdict in verdicts.items():
        with st.container(border=True):           
            st.markdown(
                f"### Scheme: {scheme_names.get(scheme_id, scheme_id)}"
                f'<span class="scheme-id-pill" title="Scheme Id">'
                f'{escape(scheme_id)}</span></h3>',
                unsafe_allow_html=True,
            )
            decision = verdict.get("verdict", "cant_tell")
            if decision == "eligible":
                st.success("Eligible", icon=":material/check_circle:")
                if st.button(
                    "Continue with this scheme",
                    key=f"select-{scheme_id}",
                    type="primary",
                ):
                    if (result.get("application") or {}).get("scheme_id") != scheme_id:
                        if not _run_analysis(
                            api_base,
                            st.session_state["citizen"],
                            [scheme_id],
                        ):
                            return
                    st.session_state["selected_scheme"] = scheme_id
                    _set_page("documents")
                    st.rerun()
            elif decision == "not_eligible":
                st.warning("Not eligible", icon=":material/info:")
            else:
                st.info("More information is needed", icon=":material/help:")
            st.write(verdict.get("reason", "No explanation was returned."))

            conditions = verdict.get("conditions", [])
            if conditions:
                st.dataframe(
                    [
                        {
                            "Profile fact": condition.get("field"),
                            "Rule": condition.get("op"),
                            "Result": condition.get("outcome"),
                            "Source clause": condition.get("clause_id"),
                        }
                        for condition in conditions
                    ],
                    hide_index=True,
                    width="stretch",
                )
            missing = verdict.get("missing_fields", [])
            unresolved = verdict.get("unresolved_fields", [])
            if missing or unresolved:
                st.caption(
                    "Information needed: "
                    + ", ".join(dict.fromkeys([*missing, *unresolved]))
                )
            citations = verdict.get("citations", [])
            if citations:
                with st.expander("View source clauses"):
                    for citation in citations:
                        st.markdown(
                            f"- **{citation.get('clause_id', 'Source')}:** "
                            f"{citation.get('text', '')}"
                        )


def _render_eligibility(
    api_base: str, schemes: list[dict[str, Any]]
) -> None:
    _render_verdicts(api_base, st.session_state["result"] or {}, schemes)
    if st.button("Back to details", key="eligibility-back"):
        _set_page("intake")
        st.rerun()


def _render_documents(api_base: str, schemes: list[dict[str, Any]]) -> None:
    result = st.session_state["result"] or {}
    scheme_id = st.session_state["selected_scheme"]
    scheme = next(
        (item for item in schemes if item["scheme_id"] == scheme_id), None
    )
    scheme_name = scheme["name"] if scheme else scheme_id
    required_documents = result.get("documents", {}).get(scheme_id, [])
    uploaded = st.session_state["uploads"].setdefault(scheme_id, {})

    st.markdown(
        f'<h3>Documents for Scheme: {escape(scheme_name)} '
        f'<span class="scheme-id-pill" title="Scheme Id">'
        f'{escape(scheme_id)}</span></h3>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Files are validated and tracked for this local demo; file contents are "
        "discarded after validation. Redact personal ID numbers before uploading."
    )
    if not required_documents:
        st.info("No documents are listed for this scheme.")

    for index, document_type in enumerate(required_documents):
        with st.container(border=True):
            st.markdown(f"**{document_type}**")
            existing = uploaded.get(document_type)
            if existing:
                st.success(f"Uploaded: {existing['filename']}")
                continue
            file_key = f"upload-{result['thread_id']}-{scheme_id}-{index}"
            uploaded_file = st.file_uploader(
                f"Choose {document_type}",
                type=["pdf", "png", "jpg", "jpeg"],
                max_upload_size=10,
                key=file_key,
            )
            if uploaded_file and st.button(
                f"Upload {document_type}",
                key=f"upload-button-{result['thread_id']}-{index}",
                disabled=uploaded_file.size > MAX_UPLOAD_BYTES,
            ):
                try:
                    response = _upload_file(
                        api_base,
                        result["thread_id"],
                        scheme_id,
                        document_type,
                        uploaded_file,
                    )
                except (RuntimeError, ValueError) as error:
                    st.error(str(error), title="Upload failed")
                else:
                    uploaded[document_type] = response
                    st.success(f"{document_type} uploaded.")
                    st.rerun()

    missing_documents = [
        document for document in required_documents if document not in uploaded
    ]
    if missing_documents:
        st.info(
            f"Upload the remaining required documents: {', '.join(missing_documents)}"
        )
    left, right = st.columns(2)
    if left.button("Back to eligibility", key="documents-back"):
        _set_page("eligibility")
        st.rerun()
    if right.button(
        "Continue to review",
        type="primary",
        # disabled=bool(missing_documents),
        disabled = False,
        key="documents-continue",
    ):
        _set_page("review")
        st.rerun()


def _render_review(api_base: str, schemes: list[dict[str, Any]]) -> None:
    result = st.session_state["result"] or {}
    citizen = st.session_state["citizen"]
    scheme_id = st.session_state["selected_scheme"]
    scheme = next(
        (item for item in schemes if item["scheme_id"] == scheme_id), None
    )
    scheme_name = scheme["name"] if scheme else scheme_id
    verdict = result.get("verdicts", {}).get(scheme_id, {})
    required_documents = result.get("documents", {}).get(scheme_id, [])
    uploaded = st.session_state["uploads"].get(scheme_id, {})

    st.subheader("Review your application")
    with st.container(border=True):
        st.markdown("#### Personal details")
        first, second = st.columns(2)
        first.write(f"**Name:** {citizen.get('name', 'Not provided')}")
        first.write(f"**Age:** {citizen.get('age', 'Not provided')}")
        first.write(f"**State:** {citizen.get('state', 'Not provided')}")
        second.write(
            f"**Monthly household income:** INR "
            f"{citizen.get('monthly_income', 0):,}"
        )
        second.write(
            f"**Annual income used for rules:** INR {citizen.get('income', 0):,}"
        )
        second.write(f"**Employment:** {citizen.get('employment_status', 'Not provided')}")

    with st.container(border=True):        
        st.markdown(
        f"#### Scheme: {scheme_name}"
        f'<span class="scheme-id-pill" title="Scheme Id">'
        f'{escape(scheme_id)}</span></h3>',
        unsafe_allow_html=True,
    )
        if verdict.get("verdict") == "eligible":
            st.success("Eligible", icon=":material/check_circle:")
        else:
            st.warning("Eligibility changed; please recheck before submitting.")
        st.write(verdict.get("reason", ""))
        st.markdown("#### Required documents")
        if required_documents:
            for document in required_documents:
                file_record = uploaded.get(document)
                st.write(
                    f"{'Uploaded' if file_record else 'Missing'}: {document}"
                    + (f" — {file_record['filename']}" if file_record else "")
                )
        else:
            st.write("No documents listed.")

    confirmed = st.checkbox(
        "I confirm these details are correct and want to submit this demo application.",
        key="review-confirm",
    )
    back, submit = st.columns(2)
    if back.button("Back to documents", key="review-back"):
        _set_page("documents")
        st.rerun()
    if submit.button(
        "Submit application",
        type="primary",
        disabled=not confirmed,
        key="review-submit",
    ):
        approval = result.get("approval") or {}
        with st.status("Submitting your approved draft...", expanded=True) as status:
            try:
                submitted_result = _post_stream(
                    api_base,
                    f"/api/threads/{result['thread_id']}/decision",
                    {
                        "action": "approve",
                        "payload_hash": approval.get("payload_hash"),
                    },
                    status,
                )
            except (RuntimeError, ValueError, json.JSONDecodeError) as error:
                status.update(label="Application submission failed", state="error")
                st.error(str(error), title="Request failed")
            else:
                if not submitted_result.get("submission"):
                    status.update(label="The application was not submitted", state="error")
                    if submitted_result.get("needs_human"):
                        detail = "The draft needs human review. Nothing was submitted."
                    else:
                        detail = (
                            "The approval did not match the current draft. "
                            "Nothing was submitted."
                        )
                    st.error(detail, title="Submission not completed")
                    return
                st.session_state["result"] = submitted_result
                st.session_state["submitted_at"] = time.strftime("%Y-%m-%d %H:%M")
                status.update(label="Application submitted", state="complete")
                _set_page("success")
                st.rerun()


def _reset_search() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith(("intake_", "upload-", "upload-button-")):
            del st.session_state[key]
    st.session_state["page"] = "welcome"
    st.session_state["citizen"] = {}
    st.session_state["selected_schemes"] = []
    st.session_state["selected_scheme"] = None
    st.session_state["result"] = None
    st.session_state["uploads"] = {}
    st.session_state["submitted_at"] = None


def _render_success(schemes: list[dict[str, Any]]) -> None:
    result = st.session_state["result"] or {}
    submission = result.get("submission") or {}
    scheme_id = st.session_state["selected_scheme"]
    scheme = next(
        (item for item in schemes if item["scheme_id"] == scheme_id), None
    )

    st.success("Your demo application has been submitted.")
    st.subheader("Application confirmation")
    st.code(submission.get("application_id", "No reference number returned."))
    st.write(f"**Scheme:** {scheme['name'] if scheme else scheme_id}")
    st.write(f"**Status:** {submission.get('status', 'submitted (mock)')}")
    st.write(f"**Submitted:** {st.session_state.get('submitted_at') or 'Just now'}")
    st.info(
        "This is a mock submission for demonstration. It is not a government "
        "application and does not guarantee a benefit or follow-up."
    )
    st.markdown("**Next steps**")
    st.markdown(
        "1. Keep the reference number for this demo.  \n"
        "2. Contact the relevant scheme office to confirm its real process.  \n"
        "3. Do not share unredacted identity documents in a demo."
    )
    summary = {
        "reference_number": submission.get("application_id"),
        "status": submission.get("status"),
        "scheme_id": scheme_id,
        "scheme_name": scheme["name"] if scheme else scheme_id,
        "citizen": st.session_state["citizen"],
    }
    left, right = st.columns(2)
    left.download_button(
        "Download application summary",
        data=json.dumps(summary, indent=2, ensure_ascii=False),
        file_name="scheme-saathi-application.json",
        mime="application/json",
        width="stretch",
    )
    if right.button("Start a new search", type="primary", width="stretch"):
        _reset_search()
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Scheme Saathi",
        page_icon=":material/account_balance:",
        layout="wide",
    )
    st.html(CSS_PATH)
    _initialize_state()
    _render_header()

    try:
        api_base = _api_base_url()
        health = _api_request(f"{api_base}/health")
        if health.get("status") != "ok":
            raise RuntimeError("FastAPI returned an unexpected health response.")
        schemes = _load_schemes(api_base)
    except (RuntimeError, ValueError, OSError) as error:
        st.error(str(error), title="FastAPI is unavailable")
        st.stop()

    if not schemes:
        st.warning("No schemes with reviewed rules are available.")
        st.stop()

    page = st.session_state["page"]
    if page == "welcome":
        _render_welcome()
    elif page == "intake":
        _render_intake(api_base, schemes)
    elif page == "eligibility":
        _render_eligibility(api_base, schemes)
    elif page == "documents":
        _render_documents(api_base, schemes)
    elif page == "review":
        _render_review(api_base, schemes)
    elif page == "success":
        _render_success(schemes)
    else:
        st.error("The current workflow step is invalid.")
        _reset_search()


if __name__ == "__main__":
    main()