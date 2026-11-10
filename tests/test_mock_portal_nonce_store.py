import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from servers.mock_portal.authorization import CapabilityError, consume_write_capability, issue_write_capability
from servers.mock_portal.nonce_store import NonceStore


@pytest.fixture
def shared_store(monkeypatch, tmp_path):
    path = tmp_path / "nonces.sqlite"
    monkeypatch.setenv("MOCK_PORTAL_NONCE_DB", str(path))
    return path


def test_replay_is_rejected_after_process_restart(shared_store):
    token = issue_write_capability("create_draft", "scheme", "hash", "household")
    consume_write_capability(token, "create_draft", "scheme", "hash", "household")
    code = (
        "import os; from servers.mock_portal.authorization import consume_write_capability, CapabilityError\n"
        "try:\n"
        "    consume_write_capability(os.environ['TEST_TOKEN'], 'create_draft', 'scheme', 'hash', 'household')\n"
        "except CapabilityError as exc:\n"
        "    assert 'already been used' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('replay accepted')\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "TEST_TOKEN": token},
    )
    if os.name == "posix":
        assert shared_store.stat().st_mode & 0o777 == 0o600


def test_concurrent_consumption_is_atomic(shared_store):
    stores = [NonceStore(str(shared_store)), NonceStore(str(shared_store))]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda store: store.consume_nonce("nonce", time.time() + 60), stores))
    assert sorted(results) == [False, True]


def test_concurrent_processes_cannot_consume_same_capability(shared_store):
    token = issue_write_capability("create_draft", "scheme", "hash", "household")
    code = (
        "import os, sys; from servers.mock_portal.authorization import consume_write_capability, CapabilityError\n"
        "try:\n"
        "    consume_write_capability(os.environ['TEST_TOKEN'], 'create_draft', 'scheme', 'hash', 'household')\n"
        "except CapabilityError:\n"
        "    sys.exit(2)\n"
    )
    env = {**os.environ, "TEST_TOKEN": token}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: subprocess.run([sys.executable, "-c", code], env=env).returncode,
            range(2),
        ))
    assert sorted(results) == [0, 2]


@pytest.mark.usefixtures("shared_store")
def test_invalid_binding_does_not_consume_capability():
    token = issue_write_capability("create_draft", "scheme", "hash", "household")
    with pytest.raises(CapabilityError):
        consume_write_capability(token, "create_draft", "scheme", "wrong", "household")
    with pytest.raises(CapabilityError):
        consume_write_capability(token, "create_draft", "scheme", "hash", "other")
    consume_write_capability(token, "create_draft", "scheme", "hash", "household")
    with pytest.raises(CapabilityError, match="already been used"):
        consume_write_capability(token, "create_draft", "scheme", "hash", "household")


def test_expired_nonces_are_purged_on_use(shared_store):
    store = NonceStore(str(shared_store))
    assert store.consume_nonce("expired", time.time() - 1)
    assert store.consume_nonce("current", time.time() + 60)
    with store.connect() as db:
        assert db.execute("SELECT nonce FROM used_nonces").fetchall() == [("current",)]


def test_invalid_store_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_PORTAL_NONCE_DB", str(tmp_path))
    token = issue_write_capability("create_draft", "scheme", "hash", "household")
    with pytest.raises(OSError):
        consume_write_capability(token, "create_draft", "scheme", "hash", "household")
