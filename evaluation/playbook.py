"""The rule extractor's playbook: reviewed lessons, kept in the LangGraph store.

A lesson is proposed by the reflection step and enters the extractor's instructions only after a
person approves it. Any lesson can be withdrawn. Before the held-out run the playbook is frozen:
its approved lessons get a version hash, and the final run refuses a playbook that isn't frozen
or has changed since.

The JSON file is the copy the team reviews in Git; at run time it is loaded into a LangGraph
store (namespace PLAYBOOK_NAMESPACE), and the extractor's lessons are read from the store.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_FILE = ROOT / "data" / "playbook" / "rule_extractor.json"
PLAYBOOK_NAMESPACE = ("playbook", "rule_extractor")
TOP_K = 5

Status = Literal["proposed", "approved", "rejected", "withdrawn"]


class Lesson(BaseModel):
    lesson_id: str
    text: str = Field(description="One or two sentences: when it applies, what to do.")
    applies_when: str
    keywords: list[str] = Field(default_factory=list, description="Words in a scheme's text that signal it applies; empty means always.")
    error_type: str
    examples: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list, description="Checks by code for the reviewer.")
    status: Status = "proposed"
    proposed_on: str = ""
    proposed_by_run: str = ""
    reviewed_by: str | None = None
    reviewed_on: str | None = None
    review_note: str | None = None


class Playbook(BaseModel):
    lessons: list[Lesson] = Field(default_factory=list)
    frozen: bool = False
    frozen_on: str | None = None
    frozen_hash: str | None = None

    # ------------------------------------------------------------ file
    @classmethod
    def load(cls, path: Path = PLAYBOOK_FILE) -> "Playbook":
        return cls.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else cls()

    def save(self, path: Path = PLAYBOOK_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------ review
    def approved(self) -> list[Lesson]:
        return [lesson for lesson in self.lessons if lesson.status == "approved"]

    def get(self, lesson_id: str) -> Lesson:
        return next(lesson for lesson in self.lessons if lesson.lesson_id == lesson_id)

    def add_proposals(self, proposals: list[Lesson]) -> None:
        self._unfrozen()
        known = {lesson.lesson_id for lesson in self.lessons}
        for proposal in proposals:
            if proposal.lesson_id in known:
                raise ValueError(f"lesson {proposal.lesson_id} already exists")
            self.lessons.append(proposal.model_copy(update={"status": "proposed"}))

    def review(self, lesson_id: str, decision: Literal["approved", "rejected"], reviewer: str,
               text: str | None = None, note: str | None = None, on: str | None = None,
               keywords: list[str] | None = None) -> Lesson:
        """A person's decision. An edit replaces the text (and keywords) before approval."""
        self._unfrozen()
        if not reviewer.strip():
            raise ValueError("a lesson needs a named reviewer")
        lesson = self.get(lesson_id)
        if lesson.status not in ("proposed", "approved", "rejected"):
            raise ValueError(f"lesson {lesson_id} is {lesson.status}")
        lesson.status, lesson.reviewed_by = decision, reviewer.strip()
        lesson.reviewed_on, lesson.review_note = on or date.today().isoformat(), note
        if text:
            lesson.text = text
        if keywords is not None:
            lesson.keywords = [k.strip().lower() for k in keywords if k.strip()]
        return lesson

    def discard_proposed(self) -> list[str]:
        """Drop proposals no one has reviewed yet (before reflecting again on the same errors)."""
        self._unfrozen()
        dropped = [lesson.lesson_id for lesson in self.lessons if lesson.status == "proposed"]
        self.lessons = [lesson for lesson in self.lessons if lesson.status != "proposed"]
        return dropped

    def withdraw(self, lesson_id: str, reviewer: str, note: str) -> Lesson:
        self._unfrozen()
        lesson = self.get(lesson_id)
        lesson.status, lesson.reviewed_by, lesson.review_note = "withdrawn", reviewer, note
        lesson.reviewed_on = date.today().isoformat()
        return lesson

    # ------------------------------------------------------------ freeze
    def version_hash(self) -> str:
        payload = json.dumps([lesson.model_dump(include={"lesson_id", "text", "keywords"})
                              for lesson in sorted(self.approved(), key=lambda x: x.lesson_id)], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def freeze(self, on: str | None = None) -> str:
        if any(lesson.status == "proposed" for lesson in self.lessons):
            raise ValueError("review every proposed lesson before freezing")
        self.frozen, self.frozen_on, self.frozen_hash = True, on or date.today().isoformat(), self.version_hash()
        return self.frozen_hash

    def check_frozen(self) -> None:
        """For the held-out run: the playbook must be frozen and unchanged since."""
        if not self.frozen or self.frozen_hash != self.version_hash():
            raise ValueError("the playbook is not frozen, or changed after it was frozen")

    def _unfrozen(self) -> None:
        if self.frozen:
            raise ValueError("the playbook is frozen; it can't change before the held-out run")


# ---------------------------------------------------------------- store and retrieval

def to_store(playbook: Playbook, store: BaseStore | None = None) -> BaseStore:
    """Put the approved lessons into a LangGraph store, where the extractor reads them."""
    store = store or InMemoryStore()
    for lesson in playbook.approved():
        store.put(PLAYBOOK_NAMESPACE, lesson.lesson_id, lesson.model_dump())
    return store


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def relevant_lessons(store: BaseStore, scheme_text: str, top_k: int = TOP_K) -> list[dict[str, Any]]:
    """Only lessons relevant to this scheme: a lesson matches when one of its keywords (a word or
    phrase) is in the scheme's text; a lesson without keywords always applies. Ranked by how many
    keywords match, then by id."""
    text = scheme_text.lower()
    scored = []
    for item in store.search(PLAYBOOK_NAMESPACE, limit=1000):
        lesson = item.value
        keywords = [k.lower().strip() for k in lesson.get("keywords", []) if k.strip()]
        hits = sum(1 for k in keywords if (k in text if " " in k else k in _words(text)))
        if not keywords or hits:
            scored.append((-(hits if keywords else 0.5), lesson["lesson_id"], lesson))
    return [lesson for *_, lesson in sorted(scored)[:top_k]]
