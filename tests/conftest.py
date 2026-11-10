import json
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# Settings a developer's .env holds. Tests run as in CI, without them: a test that needs one
# sets it itself. With them, the supervisor's router called the live model (and spent credit)
# and Auth0's "missing configuration" test read the real settings back from .env.
DOTENV_SETTINGS = (
    "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "SUPERVISOR_MODEL", "SPECIALIST_MODEL", "CITIZEN_MODEL", "ROUTER_MODEL",
    "AUTH0_DOMAIN", "AUTH0_AUDIENCE", "AUTH0_CLIENT_ID", "AUTH0_HOUSEHOLD_CLAIM",
    "AUTH0_ROLE_CLAIM", "AUTH0_REDIRECT_URI",
)


@pytest.fixture(autouse=True)
def ignore_local_dotenv(monkeypatch):
    """Keep a local .env out of the tests: no module reloads it, and its settings are cleared."""
    import dotenv

    real = dotenv.load_dotenv
    for module in list(sys.modules.values()):
        if getattr(module, "load_dotenv", None) is real:
            monkeypatch.setattr(module, "load_dotenv", lambda *args, **kwargs: False)
    for name in DOTENV_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def close_chroma_clients():
    """Stop every ChromaDB client a test opened.

    ChromaDB keeps each PersistentClient's database open in a process-wide cache until it is
    stopped, about 15-20 open files per memory-store test. On macOS (256 open files by default)
    the suite then failed with "Too many open files" after about 60 such tests.
    """
    yield
    if "chromadb" not in sys.modules:
        return
    from chromadb.api.shared_system_client import SharedSystemClient

    for system in list(SharedSystemClient._identifier_to_system.values()):
        try:
            system.stop()
        except Exception:  # a system already stopped by its test
            pass
    SharedSystemClient.clear_system_cache()


@pytest.fixture(autouse=True)
def mock_portal_test_secret(monkeypatch):
    monkeypatch.setenv("MOCK_PORTAL_AUTH_SECRET", "test-only-mock-portal-secret")
    monkeypatch.setenv("MOCK_PORTAL_NONCE_DB", "")


@pytest.fixture(autouse=True)
def isolated_memory_store(monkeypatch, tmp_path):
    """Point the API's memory store at a temporary folder, so no test writes to the real one."""
    from app import checkpoints, memory_runtime

    monkeypatch.setenv(memory_runtime.DIRECTORY_ENV, str(tmp_path / "memory"))
    monkeypatch.setenv(checkpoints.DATABASE_ENV, "")  # workflow state stays in memory unless a test opts in
    memory_runtime.get_memory_service.cache_clear()
    checkpoints.get_checkpointer.cache_clear()
    yield
    getattr(memory_runtime.get_memory_service, "cache_clear", lambda: None)()
    checkpoints.get_checkpointer.cache_clear()


@pytest.fixture(autouse=True)
def observability_off_and_isolated(monkeypatch):
    """Keep the suite independent of the developer's .env, and each test's metrics separate.

    Empty (not removed) values stop load_dotenv from filling them back in from a local .env.
    """
    from observability import set_metrics, set_tracer

    monkeypatch.setenv("OBSERVABILITY_ENABLED", "")
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "")
    monkeypatch.setenv("MODEL_PRICES_FILE", "")
    for name in (
        "TRACING_BACKEND",
        "TRACING_SAMPLE_RATE",
        "TRACING_HASH_SALT",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
    ):
        monkeypatch.setenv(name, "")
    set_metrics(None)
    set_tracer(None)
    yield
    set_metrics(None)
    set_tracer(None)


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
    from graph import tools
    tools.scheme_is_closed.cache_clear()  # a test that swaps scheme records must not see another's cache
