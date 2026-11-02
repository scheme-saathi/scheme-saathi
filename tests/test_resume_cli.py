import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run([sys.executable, "-m", "graph.run", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def test_run_stops_then_resumes_in_a_new_process(tmp_path):
    db = str(tmp_path / "cp.sqlite3")
    started = run("--phase", "start", "--db", db, "--thread-id", "t1")
    assert started.returncode == 0, started.stderr
    assert "Paused and saved" in started.stdout
    assert "Mock submission" not in started.stdout

    resumed = run("--phase", "resume", "--db", db, "--thread-id", "t1", "--decision", "approve")
    assert resumed.returncode == 0, resumed.stderr
    assert "submitted (mock)" in resumed.stdout

    again = run("--phase", "resume", "--db", db, "--thread-id", "t1")
    assert again.returncode == 1
    assert "not waiting for approval" in again.stderr


def test_rejected_resume_submits_nothing_and_duplicate_start_is_refused(tmp_path):
    db = str(tmp_path / "cp.sqlite3")
    run("--phase", "start", "--db", db, "--thread-id", "t2")
    assert "nothing was submitted" in run("--phase", "resume", "--db", db, "--thread-id", "t2",
                                          "--decision", "reject").stdout
    assert run("--phase", "start", "--db", db, "--thread-id", "t2").returncode == 1


def test_unknown_scheme_id_is_rejected():
    result = run("--scheme-id", "NOPE")
    assert result.returncode == 2 and "NOPE" in result.stderr


def test_draft_scheme_reports_cant_tell_without_approval():
    result = run("--scheme-id", "C10")
    assert result.returncode == 0, result.stderr
    assert "Cant Tell" in result.stdout and "No application to approve" in result.stdout


def test_persona_id_loads_profile_facts():
    """Load a saved persona and verify its facts are used by the workflow."""
    result = run("--persona-id", "SS006")
    assert result.returncode == 0, result.stderr
    assert "age gte (clause cl-1): TRUE" in result.stdout


def test_persona_id_and_citizen_cannot_be_combined():
    """Reject CLI input that supplies both supported profile sources."""
    result = run("--persona-id", "SS001", "--citizen", '{"age": 40}')
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


def hash_in(output):
    import re
    return re.search(r"'payload_hash': '([0-9a-f]{64})'", output).group(1)


def test_edit_then_approve_in_separate_processes(tmp_path):
    db = str(tmp_path / "cp.sqlite3")
    started = run("--phase", "start", "--db", db, "--thread-id", "e1")
    old = hash_in(started.stdout)
    edited = run("--phase", "resume", "--db", db, "--thread-id", "e1", "--decision", "edit",
                 "--changes", '{"income": 200000}')
    assert edited.returncode == 0, edited.stderr
    assert "needs a new approval" in edited.stdout and hash_in(edited.stdout) != old
    approved = run("--phase", "resume", "--db", db, "--thread-id", "e1", "--decision", "approve")
    assert "submitted (mock)" in approved.stdout


def test_stale_approval_after_an_edit_is_refused(tmp_path):
    db = str(tmp_path / "cp.sqlite3")
    old = hash_in(run("--phase", "start", "--db", db, "--thread-id", "e2").stdout)
    run("--phase", "resume", "--db", db, "--thread-id", "e2", "--decision", "edit", "--changes", '{"income": 200000}')
    stale = run("--phase", "resume", "--db", db, "--thread-id", "e2", "--decision", "approve", "--payload-hash", old)
    assert "did not match the current application" in stale.stdout
    assert "submitted (mock)" not in stale.stdout


def test_edit_requires_changes():
    assert run("--phase", "resume", "--decision", "edit").returncode == 2
