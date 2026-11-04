import pytest


@pytest.fixture(autouse=True)
def mock_portal_test_secret(monkeypatch):
    monkeypatch.setenv("MOCK_PORTAL_AUTH_SECRET", "test-only-mock-portal-secret")
