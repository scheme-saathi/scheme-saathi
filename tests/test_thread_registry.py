from datetime import timedelta

import pytest

from app import checkpoints
from app.thread_registry import ThreadRegistry, TouchResult

USABLE, EXPIRED, NOT_OWNER = TouchResult.USABLE, TouchResult.EXPIRED, TouchResult.NOT_OWNER


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
    assert registry.touch("t1", "h1") is USABLE
    assert registry.owner_of("t1") == "h1"
    assert registry.touch("t1", "h1") is USABLE


def test_another_household_cannot_take_over_a_thread(registry):
    registry.touch("t1", "h1")

    assert registry.touch("t1", "h2") is NOT_OWNER
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
        assert registry.touch("t1", "h1") is USABLE
    assert registry.expired() == []

    clock.advance(hours=23)
    assert registry.touch("t1", "h1") is EXPIRED  # 7 days old: in use, but past the absolute limit
    assert registry.expired() == ["t1"]


# An expired thread is never brought back, even before cleanup has deleted it


def test_an_idle_thread_is_not_revived_by_its_owner_before_cleanup(registry, clock):
    registry.touch("t1", "h1")
    clock.advance(hours=25)
    assert registry.expired() == ["t1"]

    assert registry.touch("t1", "h1") is EXPIRED

    assert registry.expired() == ["t1"]  # still expired: the touch did not refresh it
    assert registry.is_expired("t1") is True
    assert registry.owner_of("t1") is None


def test_the_idle_limit_is_exact(registry, clock):
    registry.touch("t1", "h1")
    clock.advance(hours=24)
    assert registry.touch("t1", "h1") is USABLE  # exactly at the limit is still in date

    clock.advance(hours=24, seconds=1)
    assert registry.touch("t1", "h1") is EXPIRED


def test_the_absolute_limit_is_exact(registry, clock):
    start = clock.now
    registry.touch("t1", "h1")
    for day in range(1, 7):
        clock.now = start + timedelta(days=day).total_seconds() - 3600  # used every day
        assert registry.touch("t1", "h1") is USABLE
    clock.now = start + timedelta(days=6.5).total_seconds()
    assert registry.touch("t1", "h1") is USABLE  # used within 12 hours of the limit

    clock.now = start + timedelta(days=7).total_seconds()
    assert registry.touch("t1", "h1") is USABLE  # exactly 7 days old, and idle for only 12 hours

    clock.advance(seconds=1)
    assert registry.touch("t1", "h1") is EXPIRED  # past 7 days, though used a moment ago


def test_another_household_touching_an_expired_thread_is_told_it_expired_not_whose_it_is(registry, clock):
    registry.touch("t1", "h1")
    clock.advance(hours=25)
    assert registry.touch("t1", "h2") is EXPIRED
    assert registry.owner_of("t1") is None


def test_an_expired_threads_owner_can_still_be_found_so_forgetting_reaches_it(registry, clock):
    registry.touch("t1", "h1")
    clock.advance(hours=25)
    assert registry.threads_of("h1") == {"t1"}


def test_an_expired_thread_stays_expired_after_a_restart(tmp_path, clock):
    path = tmp_path / "workflow.sqlite"
    first = ThreadRegistry("agent", path, clock=clock)
    first.touch("t1", "h1")
    clock.advance(hours=25)
    assert first.touch("t1", "h1") is EXPIRED
    first.close()

    second = ThreadRegistry("agent", path, clock=clock)
    assert second.touch("t1", "h1") is EXPIRED
    assert second.owner_of("t1") is None
    second.close()


def test_two_registries_on_one_file_cannot_both_revive_an_expired_thread(tmp_path, clock):
    path = tmp_path / "workflow.sqlite"
    one = ThreadRegistry("agent", path, clock=clock)
    two = ThreadRegistry("agent", path, clock=clock)
    one.touch("t1", "h1")
    clock.advance(hours=25)

    assert one.touch("t1", "h1") is EXPIRED
    assert two.touch("t1", "h1") is EXPIRED
    assert one.expired() == ["t1"]
    one.close()
    two.close()


def test_an_in_date_thread_is_found_by_owner_of(registry, clock):
    registry.touch("t1", "h1")
    clock.advance(hours=23)
    assert registry.owner_of("t1") == "h1"
    assert registry.is_expired("t1") is False
    assert registry.is_expired("unknown") is False


# Whose application a thread is for is kept with the thread


def test_a_thread_keeps_whose_application_it_is_for(registry):
    registry.touch("t1", "h1")
    registry.touch("t2", "h1")
    registry.set_subject("t1", "h1", "other", "mother")
    registry.set_subject("t2", "h1", "self", None)

    assert registry.subject_of("t1") == ("other", "mother")
    assert registry.subject_of("t2") == ("self", None)


def test_a_thread_with_no_subject_kept_and_an_unknown_thread_have_none(registry):
    registry.touch("t1", "h1")
    assert registry.subject_of("t1") is None
    assert registry.subject_of("unknown") is None


def test_only_the_owner_can_set_the_subject(registry):
    registry.touch("t1", "h1")
    registry.set_subject("t1", "h2", "other", "son")
    assert registry.subject_of("t1") is None
    registry.set_subject("t1", "h1", "other", "mother")
    registry.set_subject("t1", "h2", "self", None)
    assert registry.subject_of("t1") == ("other", "mother")


def test_the_subject_survives_a_restart_and_goes_with_the_thread(tmp_path, clock):
    path = tmp_path / "workflow.sqlite"
    first = ThreadRegistry("application", path, clock=clock)
    first.touch("t1", "h1")
    first.set_subject("t1", "h1", "other", "mother")
    first.close()

    second = ThreadRegistry("application", path, clock=clock)
    assert second.subject_of("t1") == ("other", "mother")
    second.forget(["t1"])
    assert second.subject_of("t1") is None
    second.close()


def test_the_subject_of_a_thread_is_per_kind(tmp_path, clock):
    path = tmp_path / "workflow.sqlite"
    agent = ThreadRegistry("agent", path, clock=clock)
    application = ThreadRegistry("application", path, clock=clock)
    application.touch("t1", "h1")
    application.set_subject("t1", "h1", "other", "mother")
    assert agent.subject_of("t1") is None
    agent.close()
    application.close()


def test_a_file_made_before_the_subject_was_kept_is_upgraded_without_losing_owners(tmp_path, clock):
    import sqlite3

    path = tmp_path / "workflow.sqlite"
    old = sqlite3.connect(str(path))
    old.execute(
        "CREATE TABLE workflow_threads (kind TEXT NOT NULL, thread_id TEXT NOT NULL, household_id TEXT NOT NULL, "
        "created_at REAL NOT NULL, last_active REAL NOT NULL, PRIMARY KEY (kind, thread_id))"
    )
    old.execute("INSERT INTO workflow_threads VALUES ('application', 'old-thread', 'h1', ?, ?)", (clock(), clock()))
    old.commit()
    old.close()

    registry = ThreadRegistry("application", path, clock=clock)

    assert registry.owner_of("old-thread") == "h1"
    assert registry.subject_of("old-thread") is None  # nothing was kept for it
    registry.set_subject("old-thread", "h1", "other", "father")
    assert registry.subject_of("old-thread") == ("other", "father")
    registry.close()


def test_forgotten_threads_are_gone(registry):
    registry.touch("t1", "h1")
    registry.touch("t2", "h1")

    registry.forget(["t1"])

    assert registry.owner_of("t1") is None
    assert registry.threads_of("h1") == {"t2"}


def test_a_forgotten_thread_id_can_be_claimed_again(registry):
    registry.touch("t1", "h1")
    registry.forget(["t1"])
    assert registry.touch("t1", "h2") is USABLE


def test_a_thread_deleted_after_it_expired_can_be_claimed_again(registry, clock):
    registry.touch("t1", "h1")
    clock.advance(hours=25)
    registry.forget(registry.expired())
    assert registry.touch("t1", "h2") is USABLE
    assert registry.owner_of("t1") == "h2"


def test_owners_survive_a_restart_when_a_file_is_used(tmp_path, clock):
    path = tmp_path / "state" / "workflow.sqlite"
    first = ThreadRegistry("agent", path, clock=clock)
    first.touch("t1", "h1")
    first.close()

    second = ThreadRegistry("agent", path, clock=clock)

    assert second.owner_of("t1") == "h1"
    assert second.touch("t1", "h2") is NOT_OWNER
    second.close()


def test_kinds_sharing_a_file_do_not_see_each_other(tmp_path, clock):
    path = tmp_path / "workflow.sqlite"
    agent = ThreadRegistry("agent", path, clock=clock)
    application = ThreadRegistry("application", path, clock=clock)

    agent.touch("t1", "h1")

    assert application.owner_of("t1") is None
    assert application.touch("t1", "h2") is USABLE
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
