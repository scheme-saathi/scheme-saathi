import pytest
from fastapi.testclient import TestClient

from app.auth import AuthenticatedHousehold, authenticated_household
from servers.mock_portal import server


@pytest.fixture(autouse=True)
def applications(monkeypatch):
    records = {
        "app-1": {"household_id": "hh1", "status": "submitted"},
        "app-op": {"household_id": "operator:op-1", "status": "draft"},
        "app-legacy": {"status": "submitted"},
    }
    monkeypatch.setattr(server, "APPLICATIONS", records)
    return records


def status(application_id, household_id=None):
    return server.get_application_status(application_id, household_id)


def test_the_owner_sees_the_status():
    result = status("app-1", "hh1")
    assert result["ok"] is True and result["data"]["status"] == "submitted"


def test_another_household_is_told_the_application_does_not_exist():
    result = status("app-1", "hh2")
    missing = status("no-such-application", "hh2")

    assert result["ok"] is False
    assert result["error"]["code"] == "application_not_found"
    assert result["error"]["code"] == missing["error"]["code"]


def test_an_operator_sees_only_applications_made_under_their_own_account():
    assert status("app-op", "operator:op-1")["ok"] is True
    assert status("app-op", "operator:op-2")["ok"] is False
    assert status("app-1", "operator:op-1")["ok"] is False


def test_a_record_with_no_owner_is_not_shown_to_any_household():
    assert status("app-legacy", "hh1")["ok"] is False


def test_a_lookup_without_a_household_keeps_the_earlier_behaviour():
    assert status("app-1")["ok"] is True


@pytest.mark.parametrize(
    ("household_id", "expected"),
    [("hh1", 200), ("hh2", 403), ("operator:op-1", 403)],
)
def test_the_http_route_checks_the_owner(household_id, expected):
    server.app.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        household_id, "sub-1", "operator" if household_id.startswith("operator:") else "citizen"
    )
    try:
        response = TestClient(server.app).get("/applications/app-1")
    finally:
        server.app.dependency_overrides.clear()
    assert response.status_code == expected
