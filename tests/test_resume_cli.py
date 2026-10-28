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
