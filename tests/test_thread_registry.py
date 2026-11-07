from datetime import timedelta

import pytest

from app import checkpoints
from app.thread_registry import ThreadRegistry


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta).total_seconds()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def registry(clock):
    return ThreadRegistry("agent", clock=clock)


def test_a_thread_belongs_to_the_household_that_first_used_it(registry):
    assert registry.touch("t1", "h1") is True
    assert registry.owner_of("t1") == "h1"
    assert registry.touch("t1", "h1") is True


def test_another_household_cannot_take_over_a_thread(registry):
    registry.touch("t1", "h1")

    assert registry.touch("t1", "h2") is False
    assert registry.owner_of("t1") == "h1"
    assert registry.threads_of("h2") == set()


def test_an_unknown_thread_has_no_owner(registry):
    assert registry.owner_of("missing") is None


def test_threads_are_listed_by_household(registry):
    registry.touch("t1", "h1")
    registry.touch("t2", "h1")
    registry.touch("t3", "h2")

    assert registry.threads_of("h1") == {"t1", "t2"}
    assert registry.threads_of("h2") == {"t3"}


def test_an_idle_thread_expires_after_the_idle_limit(registry, clock):
    registry.touch("t1", "h1")
    clock.advance(hours=23)
    assert registry.expired() == []

    clock.advance(hours=2)
    assert registry.expired() == ["t1"]


def test_using_a_thread_keeps_it_alive_until_the_absolute_limit(registry, clock):
    registry.touch("t1", "h1")
    for _ in range(7):
        clock.advance(hours=23)
        registry.touch("t1", "h1")
    assert registry.expired() == []

    clock.advance(hours=23)
    registry.touch("t1", "h1")
    assert registry.expired() == ["t1"]


def test_forgotten_threads_are_gone(registry):
    registry.touch("t1", "h1")
    registry.touch("t2", "h1")

    registry.forget(["t1"])

    assert registry.owner_of("t1") is None
    assert registry.threads_of("h1") == {"t2"}


def test_a_forgotten_thread_id_can_be_claimed_again(registry):
    registry.touch("t1", "h1")
    registry.forget(["t1"])
    assert registry.touch("t1", "h2") is True


def test_owners_survive_a_restart_when_a_file_is_used(tmp_path, clock):
    path = tmp_path / "state" / "workflow.sqlite"
    first = ThreadRegistry("agent", path, clock=clock)
    first.touch("t1", "h1")
    first.close()

    second = ThreadRegistry("agent", path, clock=clock)

    assert second.owner_of("t1") == "h1"
    assert second.touch("t1", "h2") is False
    second.close()


def test_kinds_sharing_a_file_do_not_see_each_other(tmp_path, clock):
    path = tmp_path / "workflow.sqlite"
    agent = ThreadRegistry("agent", path, clock=clock)
    application = ThreadRegistry("application", path, clock=clock)

    agent.touch("t1", "h1")

    assert application.owner_of("t1") is None
    assert application.touch("t1", "h2") is True
    agent.forget(["t1"])
    assert application.owner_of("t1") == "h2"
    agent.close()
    application.close()


def test_the_checkpointer_is_off_unless_a_database_is_configured(monkeypatch):
    monkeypatch.setenv("SCHEME_SAATHI_CHECKPOINT_DB", "")
    checkpoints.get_checkpointer.cache_clear()

    assert checkpoints.get_checkpointer() is None
    assert checkpoints.thread_registry("agent").owner_of("t1") is None


def test_the_checkpointer_and_registry_share_the_configured_file(tmp_path, monkeypatch):
    path = tmp_path / "state" / "workflow.sqlite"
    monkeypatch.setenv("SCHEME_SAATHI_CHECKPOINT_DB", str(path))
    checkpoints.get_checkpointer.cache_clear()
    try:
        saver = checkpoints.get_checkpointer()
        registry = checkpoints.thread_registry("agent")
        registry.touch("t1", "h1")

        assert type(saver).__name__ == "SqliteSaver"
        assert checkpoints.get_checkpointer() is saver
        assert path.exists()
        registry.close()
        reopened = checkpoints.thread_registry("agent")
        assert reopened.owner_of("t1") == "h1"
        reopened.close()
    finally:
        saver.conn.close()
        checkpoints.get_checkpointer.cache_clear()
