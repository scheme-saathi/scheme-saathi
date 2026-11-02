from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from servers.doc_check.server import compare_document_fields
from servers.mock_portal.server import app, create_application, get_application_status
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

    create_response = client.post(
        "/applications",
        json={
            "scheme_id": "SYNTH-PENSION-001",
            "applicant": {"name": "Anita Rao", "age": 62, "is_widow": True, "income": 250000},
            "documents": {"proof_of_identity": "uploaded"},
        },
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

    submitted = create_application(
        scheme_id="SYNTH-PENSION-001",
        applicant={"name": "Anita Rao", "age": 62, "is_widow": True, "income": 250000},
        documents={"proof_of_identity": "uploaded"},
        submit=True,
    )
    assert submitted["ok"] is True
    assert submitted["data"]["status"] == "submitted"
