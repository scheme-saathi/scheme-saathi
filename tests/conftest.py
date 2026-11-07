import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def mock_portal_test_secret(monkeypatch):
    monkeypatch.setenv("MOCK_PORTAL_AUTH_SECRET", "test-only-mock-portal-secret")


@pytest.fixture(autouse=True)
def isolated_memory_store(monkeypatch, tmp_path):
    """Point the API's memory store at a temporary folder, so no test writes to the real one."""
    from app import memory_runtime

    monkeypatch.setenv(memory_runtime.DIRECTORY_ENV, str(tmp_path / "memory"))
    memory_runtime.get_memory_service.cache_clear()
    yield
    getattr(memory_runtime.get_memory_service, "cache_clear", lambda: None)()


@pytest.fixture(autouse=True)
def synthetic_scheme_fixture(monkeypatch):
    """Serve the test-only SYNTH-PENSION-001 record; it is not in data/, so users never see it."""
    from servers.rule_engine import server as rule_server
    from servers.schemes_kb import server as kb_server

    monkeypatch.setattr(rule_server, "RULE_DIRS", [*rule_server.RULE_DIRS, FIXTURES])
    fixtures = {
        record["scheme_id"]: record
        for record in (json.loads(path.read_text(encoding="utf-8")) for path in FIXTURES.glob("*.json"))
    }
    load = kb_server._load_scheme_records
    monkeypatch.setattr(kb_server, "_load_scheme_records", lambda: {**load(), **fixtures})
