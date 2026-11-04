from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from servers.doc_check.server import compare_document_fields
from servers.mock_portal.authorization import (
    CapabilityError,
    application_payload_hash,
    issue_write_capability,
)
from servers.mock_portal.server import (
    APPLICATIONS,
    app,
    create_application,
    get_application_status,
    submit_draft,
)
from servers.rule_engine.server import evaluate_profile
from servers.schemes_kb.server import get_required_documents, get_scheme_details, search_schemes


@pytest.fixture
def sample_profile():
    return {"age": 62, "is_widow": True, "income": 250000}


def test_schemes_kb_read_tools_return_scheme_metadata_and_requirements():
    schemes = search_schemes()
    assert "SYNTH-PENSION-001" in schemes

    details = get_scheme_details("SYNTH-PENSION-001")
    assert details["ok"] is True
    assert details["data"]["scheme_id"] == "SYNTH-PENSION-001"

    required = get_required_documents("SYNTH-PENSION-001")
    assert required["ok"] is True
    assert required["data"]
    assert "Aadhaar card" in required["data"]


def test_rule_engine_tool_evaluates_profile(sample_profile):
    result = evaluate_profile(sample_profile, "SYNTH-PENSION-001")
    assert result["ok"] is True
    assert result["data"]["verdict"] == "eligible"


def test_rule_engine_tool_handles_unknown_scheme():
    result = evaluate_profile({"age": 62}, "UNKNOWN-SCHEME")
    assert result["ok"] is False
    assert result["error"]["code"] == "scheme_not_found"


def test_doc_check_tool_detects_mismatches():
    result = compare_document_fields(
        document_a={"name": "Anita Rao", "dob": "1990-01-01"},
        document_b={"name": "Anita R. Rao", "dob": "1990-01-01"},
    )
    assert result["ok"] is True
    assert result["data"]["name_matches"] is False
    assert result["data"]["date_matches"] is True


def test_mock_portal_http_workflow():
    client = TestClient(app)
    scheme_id = "SYNTH-PENSION-001"
    applicant = {"name": "Anita Rao", "age": 62, "is_widow": True, "income": 250000}
    form_hash = application_payload_hash(scheme_id, applicant)
    draft_capability = issue_write_capability("create_draft", scheme_id, form_hash)

    create_response = client.post(
        "/applications",
        json={
            "scheme_id": scheme_id,
            "applicant": applicant,
        },
    )
    assert create_response.status_code == 401

    create_response = client.post(
        "/applications",
        headers={"Authorization": f"Bearer {draft_capability}"},
        json={"scheme_id": scheme_id, "applicant": applicant},
    )
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["ok"] is True
    application_id = payload["data"]["application_id"]

    status_response = client.get(f"/applications/{application_id}")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "draft"

    status = get_application_status(application_id)
    assert status["ok"] is True
    assert status["data"]["status"] == "draft"

    submit_capability = issue_write_capability(
        "submit_application",
        scheme_id,
        form_hash,
    )
    submitted = create_application(
        scheme_id=scheme_id,
        applicant=applicant,
        submit=True,
        write_capability=submit_capability,
    )
    assert submitted["ok"] is True
    assert submitted["data"]["status"] == "submitted"


def test_mock_portal_write_capability_is_bound_to_form_and_one_use():
    scheme_id = "SYNTH-PENSION-001"
    applicant = {"age": 62}
    no_capability = create_application(
        scheme_id=scheme_id,
        applicant=applicant,
    )
    assert no_capability["ok"] is False
    assert no_capability["error"]["code"] == "forbidden"

    capability = issue_write_capability(
        "create_draft",
        scheme_id,
        application_payload_hash(scheme_id, applicant),
    )

    denied = create_application(
        scheme_id=scheme_id,
        applicant={"age": 63},
        write_capability=capability,
    )
    assert denied["ok"] is False
    assert denied["error"]["code"] == "forbidden"

    changed_documents = create_application(
        scheme_id=scheme_id,
        applicant=applicant,
        documents={"proof": "different"},
        write_capability=capability,
    )
    assert changed_documents["ok"] is False
    assert changed_documents["error"]["code"] == "forbidden"

    created = create_application(
        scheme_id=scheme_id,
        applicant=applicant,
        write_capability=capability,
    )
    assert created["ok"] is True

    replayed = create_application(
        scheme_id=scheme_id,
        applicant=applicant,
        write_capability=capability,
    )
    assert replayed["ok"] is False
    assert replayed["error"]["code"] == "forbidden"


def test_submission_capability_is_bound_to_the_draft_form_and_one_use():
    scheme_id = "SYNTH-PENSION-001"
    applicant = {"age": 62}
    form_hash = application_payload_hash(scheme_id, applicant)
    draft_capability = issue_write_capability("create_draft", scheme_id, form_hash)
    created = create_application(
        scheme_id=scheme_id,
        applicant=applicant,
        write_capability=draft_capability,
    )
    application_id = created["data"]["application_id"]

    wrong_form_capability = issue_write_capability(
        "submit_draft",
        application_id,
        application_payload_hash(scheme_id, {"age": 63}),
    )
    denied = submit_draft(application_id, wrong_form_capability)
    assert denied["ok"] is False
    assert denied["error"]["code"] == "forbidden"

    submit_capability = issue_write_capability(
        "submit_draft",
        application_id,
        form_hash,
    )
    submitted = submit_draft(application_id, submit_capability)
    assert submitted["ok"] is True
    assert submitted["data"]["status"] == "submitted"
    assert submit_draft(application_id, submit_capability)["error"]["code"] == "not_a_draft"


def test_changed_portal_draft_cannot_be_submitted_with_old_approval():
    scheme_id = "SYNTH-PENSION-001"
    applicant = {"age": 62}
    form_hash = application_payload_hash(scheme_id, applicant)
    draft_capability = issue_write_capability("create_draft", scheme_id, form_hash)
    created = create_application(
        scheme_id=scheme_id,
        applicant=applicant,
        write_capability=draft_capability,
    )
    application_id = created["data"]["application_id"]
    submit_capability = issue_write_capability("submit_draft", application_id, form_hash)

    APPLICATIONS[application_id]["applicant"]["age"] = 63
    result = submit_draft(application_id, submit_capability)

    assert result["ok"] is False
    assert result["error"]["code"] == "application_changed"
    assert APPLICATIONS[application_id]["status"] == "draft"


def test_write_capabilities_fail_closed_without_server_secret(monkeypatch):
    monkeypatch.setenv("MOCK_PORTAL_AUTH_SECRET", "")
    with pytest.raises(CapabilityError, match="not configured"):
        issue_write_capability("create_draft", "C01", "hash")
