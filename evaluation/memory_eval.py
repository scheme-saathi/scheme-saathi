"""Does remembering cut the questions a returning citizen is asked, without changing what the rules decide?

Each case is a synthetic person who has used the assistant before. The harness runs the real
agent graph, rule engine and memory policy twice for them on the same scheme:

1. a first visit, where they answer every question and confirm, so memory saves what the policy allows;
2. a return visit, once with memory on and once with memory off (the control).

Only the language model is replaced: the "persona" answers from its own recorded facts and says
it does not know anything it has no fact for. Three things are checked on every case:

- the verdict is the same with memory on and off (memory must never change a decision);
- memory never makes the return visit ask more questions than the control;
- the control asks exactly what the first visit asked (the persona is consistent).

The cases here are a development set drawn from the repository's own synthetic households. They are
not held-out cases. Held-out cases must be written by someone who did not write the memory code and
supplied with --cases, so the people tuning the agent never see them.

    python -m evaluation.memory_eval [--personas N] [--schemes N] [--cases FILE] [--out DIR] [--no-report] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents.contracts import (
    ApplicationDraft,
    DocumentCheckResult,
    IntakeExtraction,
    IntakeQuestion,
    SupervisorPlan,
)
from agents.eligibility import EligibilityAgent
from agents.memory import MemoryConsent, MemoryScope, MemoryService, utc_now
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService
from agents.supervisor import InputValidator, OutputValidator, UnifiedRouter
from graph import tools
from graph.agent_workflow import AgentSet, build_agent_graph
from graph.memory_nodes import memory_config
from graph.persona import HOUSEHOLD_TEST_CASES, ROOT

OPENING = "Can my household get help from this scheme?"
MAX_TURNS = 40
HOUSEHOLD = "eval-household"
SCOPE = MemoryScope(actor_id="eval-person", household_id=HOUSEHOLD, actor_role="citizen")
DEFAULT_SCHEMES = 3
DEFAULT_OUT = ROOT / "data" / "evaluation-runs"


@dataclass(frozen=True)
class Case:
    case_id: str
    facts: dict[str, Any]


@dataclass(frozen=True)
class Outcome:
    questions: list[str]
    confirmations: int
    prefilled: list[str]
    saved: list[str]
    verdict: str


@dataclass
class CaseResult:
    case_id: str
    scheme_id: str
    first_visit: Outcome
    return_with_memory: Outcome | None = None
    return_without_memory: Outcome | None = None
    failures: list[str] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        """The first visit reached the confirm step, the only point where anything is remembered."""
        return self.first_visit.confirmations > 0


def persona_facts(case: Mapping[str, Any]) -> dict[str, Any]:
    """The rule-field facts a household test case states. Anything it does not state stays unknown.

    Household income stands in for the family income the rules use, and the persona is an Indian
    citizen by construction. Maharashtra residence follows the persona's state.
    """
    recorded = case.get("profile_facts") or {}
    facts: dict[str, Any] = {"is_indian_citizen": True}
    if isinstance(recorded.get("respondent_age"), (int, float)):
        facts["age"] = recorded["respondent_age"]
    income = recorded.get("approx_annual_household_income_inr", recorded.get("annual_household_income_inr"))
    if isinstance(income, (int, float)):
        facts["annual_family_income"] = income
    if isinstance(case.get("state"), str):
        facts["is_maharashtra_resident"] = case["state"].strip().lower() == "maharashtra"
    return facts


def household_cases(limit: int | None = None) -> list[Case]:
    """Development cases from the repository's synthetic household test cases."""
    cases = []
    for path in HOUSEHOLD_TEST_CASES:
        for raw in json.loads(path.read_text(encoding="utf-8")):
            facts = persona_facts(raw)
            if "age" in facts or "annual_family_income" in facts:
                cases.append(Case(str(raw.get("test_case_id") or raw.get("source_persona_id")), facts))
    return cases[:limit] if limit else cases


def external_cases(path: Path) -> list[Case]:
    """Cases supplied from outside, a JSON list of {"case_id": "...", "facts": {...}}."""
    cases = [Case(str(item["case_id"]), dict(item["facts"])) for item in json.loads(path.read_text(encoding="utf-8"))]
    if not cases:
        raise ValueError("The cases file holds no cases.")
    return cases


def schemes_that_use_memory(allowlist: HouseholdAllowlist, limit: int | None = None) -> list[str]:
    """Reviewed schemes whose rules ask for at least one field the policy lets memory keep."""
    names = sorted({path.stem for path in (ROOT / "data" / "rules").glob("*") if path.stem})
    chosen = []
    with tools.acting_as("intake"):
        for scheme_id in names:
            try:
                specs = tools.field_specs([scheme_id])
            except Exception:
                continue  # a scheme with no reviewed rules has nothing to evaluate
            if any(allowlist.is_field_allowed(name) for name in specs):
                chosen.append(scheme_id)
            if len(chosen) == limit:
                break
    return chosen


class PersonaIntake:
    """Stands in for the intake model: answers a question from the persona's own facts."""

    def __init__(self, facts: Mapping[str, Any]) -> None:
        self.facts = dict(facts)
        self.questions: list[str] = []

    def extract(self, value: Any, specs: Mapping[str, Any]) -> IntakeExtraction:
        pending = value.pending_field
        if pending is None:
            return IntakeExtraction()
        if pending in self.facts:
            return IntakeExtraction(facts={pending: self.facts[pending]})
        return IntakeExtraction(dont_know=True)

    def ask(self, value: Any) -> IntakeQuestion:
        self.questions.append(value.field)
        return IntakeQuestion(field=value.field, question=f"What is your {value.field.replace('_', ' ')}?")

    def reply(self, field_name: str) -> str:
        return str(self.facts[field_name]) if field_name in self.facts else "I don't know"


class _Supervisor:
    """Always routes to the eligibility check, with the real input and output guardrails."""

    def __init__(self) -> None:
        router = UnifiedRouter()
        router.api_available = False
        self._input = InputValidator(router=router)
        self._output = OutputValidator()
        self._plan = SupervisorPlan(next_agent="eligibility", reason="Check.", language="en")

    def validate_input(self, request: str, actor_id: str | None = None, is_reply: bool = False) -> Any:
        return self._input.validate_request(request, actor_id, is_reply)

    def validate_output(self, response: Any, agent_name: str, language: str) -> Any:
        return self._output.validate_specialist_output(response, agent_name, language)

    def handle_validation_error(self, result: Any, language: str) -> dict[str, str]:
        return {"user_message": self._output.get_user_friendly_error(result, language)}

    def invoke(self, value: Any) -> SupervisorPlan:
        return self._plan


class _Stub:
    def __init__(self, result: Any) -> None:
        self._result = result

    def invoke(self, value: Any) -> Any:
        return self._result


def _pending(result: Mapping[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__")
    return interrupts[0].value if interrupts else None


def run_session(
    facts: Mapping[str, Any],
    scheme_id: str,
    memory: MemoryService | None,
    thread_id: str,
) -> Outcome:
    """One visit: ask, answer and confirm until the check is finished."""
    intake = PersonaIntake(facts)
    agents = AgentSet(
        intake=intake,
        supervisor=_Supervisor(),
        eligibility=EligibilityAgent(model=None),
        document_checker=_Stub(DocumentCheckResult()),
        application=_Stub(ApplicationDraft(scheme_id=scheme_id, fields={}, missing_fields=[], review_summary="-")),
    )
    graph = build_agent_graph(agents, checkpointer=MemorySaver(), memory=memory)
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if memory is not None:
        configurable.update(memory_config(SCOPE))
    config = {"configurable": configurable}

    confirmations = 0
    result = graph.invoke({"request": OPENING, "selected_scheme_id": scheme_id}, config)
    for _ in range(MAX_TURNS):
        pending = _pending(result)
        if pending is not None and pending.get("kind") == "confirm_facts":
            confirmations += 1
            decision = {"action": "approve", "payload_hash": pending["payload_hash"]}
            result = graph.invoke(Command(resume=decision), config)
        elif result.get("pending_field"):
            reply = intake.reply(result["pending_field"])
            result = graph.invoke({"request": reply, "selected_scheme_id": scheme_id}, config)
        else:
            break
    state = graph.get_state(config).values
    verdict = (state.get("verdicts") or {}).get(scheme_id, {}).get("verdict", "none")
    return Outcome(
        questions=intake.questions,
        confirmations=confirmations,
        prefilled=list(state.get("remembered_fields") or []),
        saved=list(result.get("memory_saved") or state.get("memory_saved") or []),
        verdict=verdict,
    )


def _memory(allowlist: HouseholdAllowlist) -> InMemoryMemoryService:
    service = InMemoryMemoryService(allowlist)
    now = utc_now()
    service.record_consent(
        SCOPE,
        MemoryConsent(
            purpose="profile_facts",
            granted=True,
            notice_version="eval",
            decided_at=now,
            expires_at=now + timedelta(days=30),
            consent_reference="eval-consent",
        ),
    )
    return service


def evaluate_case(case: Case, scheme_id: str, allowlist: HouseholdAllowlist) -> CaseResult:
    """A first visit; when it reaches the confirm step, a return visit with and without memory."""
    memory = _memory(allowlist)
    first = run_session(case.facts, scheme_id, memory, f"{case.case_id}-{scheme_id}-first")
    result = CaseResult(case.case_id, scheme_id, first)
    if not result.completed:
        return result
    result.return_with_memory = run_session(case.facts, scheme_id, memory, f"{case.case_id}-{scheme_id}-on")
    result.return_without_memory = run_session(case.facts, scheme_id, None, f"{case.case_id}-{scheme_id}-off")

    with_memory, without = result.return_with_memory, result.return_without_memory
    if with_memory.verdict != without.verdict:
        result.failures.append(f"verdict changed with memory: {without.verdict} -> {with_memory.verdict}")
    if len(with_memory.questions) > len(without.questions):
        result.failures.append("memory made the return visit ask more questions")
    if first.questions != without.questions:
        result.failures.append("the control did not repeat the first visit's questions")
    return result


def evaluate(
    cases: list[Case],
    pool: list[str],
    per_case: int = DEFAULT_SCHEMES,
    progress: Callable[[int, int, str, int, int], None] | None = None,
) -> list[CaseResult]:
    """Per case, scan the pool until `per_case` first visits have completed. Early stops are kept too.

    `progress(done, total, case_id, completed, stopped)` is called after each case.
    """
    allowlist = HouseholdAllowlist.from_policy_file()
    results = []
    for index, case in enumerate(cases, start=1):
        completed = stopped = 0
        for scheme_id in pool:
            result = evaluate_case(case, scheme_id, allowlist)
            results.append(result)
            completed += result.completed
            stopped += not result.completed
            if completed == per_case:
                break
        if progress:
            progress(index, len(cases), case.case_id, completed, stopped)
    return results


def summarise(results: list[CaseResult]) -> dict[str, Any]:
    done = [r for r in results if r.completed]
    runs = len(done)
    first = sum(len(r.first_visit.questions) for r in done)
    on = sum(len(r.return_with_memory.questions) for r in done)
    off = sum(len(r.return_without_memory.questions) for r in done)
    prefilled: dict[str, int] = {}
    for result in done:
        for name in result.return_with_memory.prefilled:
            prefilled[name] = prefilled.get(name, 0) + 1
    return {
        "first_visits": len(results),
        "first_visits_stopped_early": len(results) - runs,
        "runs": runs,
        "cases": len({r.case_id for r in results}),
        "cases_with_a_completed_visit": len({r.case_id for r in done}),
        "schemes": sorted({r.scheme_id for r in done}),
        "questions_first_visit": first,
        "questions_return_without_memory": off,
        "questions_return_with_memory": on,
        "questions_saved": off - on,
        "reduction_percent": round(100 * (off - on) / off, 1) if off else 0.0,
        "runs_with_fewer_questions": sum(
            len(r.return_with_memory.questions) < len(r.return_without_memory.questions) for r in done
        ),
        "mean_questions_with_memory": round(on / runs, 2) if runs else 0.0,
        "mean_questions_without_memory": round(off / runs, 2) if runs else 0.0,
        "confirmations_per_return_visit": round(sum(r.return_with_memory.confirmations for r in done) / runs, 2) if runs else 0.0,
        "prefilled_fields": dict(sorted(prefilled.items())),
        "failed_runs": sum(bool(r.failures) for r in results),
    }


def write_report(results: list[CaseResult], summary: Mapping[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"memory_eval_{stamp}.json"
    path.write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2), encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--personas", type=int, default=None, help="use only the first N development cases")
    parser.add_argument("--schemes", type=int, default=DEFAULT_SCHEMES, help="completed first visits wanted per case")
    parser.add_argument("--cases", type=Path, default=None, help="JSON file of held-out cases to use instead")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the JSON report")
    parser.add_argument("--no-report", action="store_true", help="print the summary only")
    parser.add_argument("--quiet", action="store_true", help="do not print a progress line per case")
    args = parser.parse_args(argv)

    cases = external_cases(args.cases) if args.cases else household_cases(args.personas)
    schemes = schemes_that_use_memory(HouseholdAllowlist.from_policy_file())
    if not schemes:
        print("No reviewed scheme uses a field memory may keep.", file=sys.stderr)
        return 2
    started = time.monotonic()

    def show(done: int, total: int, case_id: str, completed: int, stopped: int) -> None:
        elapsed = int(time.monotonic() - started)
        left = int(elapsed / done * (total - done))
        print(
            f"[{done}/{total}] {case_id}: {completed} completed, {stopped} stopped early "
            f"({elapsed}s elapsed, about {left}s left)",
            flush=True,
        )

    results = evaluate(cases, schemes, args.schemes, None if args.quiet else show)
    summary = summarise(results)
    print(json.dumps(summary, indent=2))
    for result in results:
        for failure in result.failures:
            print(f"FAIL {result.case_id} {result.scheme_id}: {failure}", file=sys.stderr)
    if not args.no_report:
        print(f"Report: {write_report(results, summary, args.out)}")
    return 1 if summary["failed_runs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
