"""Text files stay plain UTF-8: no byte-order mark, no double-encoded (mojibake) text.

A file once re-saved on Windows gained a byte-order mark and turned its Hindi and Marathi
wording and some arrows into garbage such as the pairs below. The patterns use escapes so this
file never contains the damage it looks for.
"""

import re
import subprocess
from pathlib import Path

import pytest

from graph import agent_workflow

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = (".py", ".md", ".json", ".toml", ".yml", ".yaml", ".example", ".txt", ".cfg", ".ini")
BOM = b"\xef\xbb\xbf"
# Devanagari read as Windows-1252 starts with these pairs; arrows and box lines start with the others.
MOJIBAKE = re.compile("\u00e0[\u00a4\u00a5]|\u00e2[\u2020\u201d\u20ac]|\ufffd")


def tracked_text_files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8"
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available to list the tracked files")
    return [ROOT / name for name in listed if name.endswith(TEXT_SUFFIXES) and (ROOT / name).is_file()]


def has_devanagari(text: str) -> bool:
    return any("\u0900" <= char <= "\u097f" for char in text)


def test_no_tracked_text_file_has_a_byte_order_mark_or_garbled_text():
    problems = []
    for path in tracked_text_files():
        data = path.read_bytes()
        if data.startswith(BOM):
            problems.append(f"{path.relative_to(ROOT)}: starts with a byte-order mark")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path.relative_to(ROOT)}: is not valid UTF-8")
            continue
        if MOJIBAKE.search(text):
            problems.append(f"{path.relative_to(ROOT)}: contains garbled (double-encoded) text")
    assert not problems, "\n".join(problems)


def test_the_agent_workflow_file_is_plain_utf_8():
    data = (ROOT / "graph" / "agent_workflow.py").read_bytes()
    assert not data.startswith(BOM)
    assert not MOJIBAKE.search(data.decode("utf-8"))


@pytest.mark.parametrize("language", ["hi", "mr"])
def test_the_not_found_reply_reaches_hindi_and_marathi_users_in_devanagari(language):
    assert has_devanagari(agent_workflow.NOT_FOUND[language])


@pytest.mark.parametrize("language", ["hi", "mr"])
def test_the_tracking_replies_are_written_in_devanagari(language):
    for key, text in agent_workflow.TRACK_TEXT[language].items():
        assert has_devanagari(text), (language, key)
