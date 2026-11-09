"""GPT agent orchestration skeleton, separate from the deterministic demo graph."""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.application import ApplicationAgent
from agents.contracts import (
    ApplicationInput,
    DocumentCheckInput,
    DocumentCheckResult,
    EligibilityInput,
    EvidencePassage,
    FactMap,
    IntakeAnswerInput,
    IntakeAskInput,
    IntakeExtractInput,
    Language,
    SchemeChoiceInput,
    SchemeOption,
    SupervisorInput,
)
from agents.document_checker import DocumentCheckerAgent
from agents.eligibility import EligibilityAgent
from agents.intake import IntakeAgent, income_period
from agents.family import family_relation, relation_in_text
from agents.memory import MemoryService, clean_relation
from agents.model_factory import create_chat_model
from agents.supervisor import SupervisorAgent, asks_about_own_eligibility
from graph import tools
from graph.memory_nodes import (
    load_remembered,
    memory_context,
    save_application_reference,
    save_confirmed,
)
from graph.workflow import application_hash
from observability.hooks import record_memory_operation
from servers.rule_engine.rules import Evaluation

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SHORTLIST_SIZE = 5  # schemes one intake asks about, so questions stay relevant to the person
MAX_QUESTIONS = 12  # per intake, so a long tail of open schemes can't turn into an interview
MAX_ATTEMPTS_PER_FIELD = 2  # a field asked twice without a usable answer is skipped, like "don't know"
PROFILE_GOALS = {"intake", "eligibility", "application"}
RESET_FACTS = "__reset__"  # in a facts update: drop what is held and start from the rest


def merge_facts(old: FactMap | None, new: FactMap | None) -> FactMap:
    """Each turn adds to the facts from earlier turns; a newer value for a field wins.

    An update that carries RESET_FACTS replaces them instead: the person is now talking about
    someone else, and one person's facts must never mix with another's.
    """
    if new and RESET_FACTS in new:
        return {field: value for field, value in new.items() if field != RESET_FACTS}
    return {**(old or {}), **(new or {})}


class AgentWorkflowState(TypedDict, total=False):
    request: str
    actor_id: str
    intent: str
    validation_errors: list[str]
    known_facts: Annotated[FactMap, merge_facts]
    confirmed_facts: Annotated[FactMap, merge_facts]
    subject: str  # "self" or "other": whose facts these are
    relation: str | None  # for "other": a word such as "mother"
    memory_loaded: bool  # remembered facts were read for this thread
    remembered_facts: FactMap  # what memory holds for this person, as last read or saved
    remembered_fields: list[str]  # fields prefilled from memory, so the person sees where they came from
    memory_saved: list[str]  # fields remembered or reconfirmed at the last confirmation
    reference_saved: bool  # the submitted application was remembered for status checks
    selected_scheme_id: str
    shortlist: list[str]  # reviewed schemes this intake is about, found by retrieval on the request
    deterministic_evaluation: dict[str, Any]
    required_documents: list[str]
    available_documents: list[str]
    application_required_fields: list[str]
    application_field_mapping: dict[str, str]
    plan: dict[str, str]
    language: Language
    pending_field: str | None  # the field intake's last question asked for
    pending_question: str | None  # that question's wording
    intake_request: str  # the message that started intake; later turns are short answers
    declined_fields: list[str]  # fields the user said they don't know
    question_attempts: dict[str, int]  # field -> times asked in this intake
    questions_asked: int
    intake_stopped: str | None  # "question_cap" when intake has asked its maximum
    reply_unanswered: bool  # the reply to a question held no facts at all
    confirm_status: str  # "confirmed", "edit_rejected", "rejected" or "invalid"
    rejected_edits: list[str]  # edited fields that were unknown or the wrong type
    explanations: dict[str, str]  # candidate scheme -> cited explanation, once facts are confirmed
    verdicts: dict[str, dict[str, Any]]  # candidate scheme -> rule-engine evaluation
    eligibility: dict[str, Any]
    document_check: dict[str, Any]
    application_draft: dict[str, Any]
    approval_status: str
    citizen_agreed: bool  # an operator's per-application tick: the person helped agrees to be on their list
    portal_draft: dict[str, Any]
    approved_hash: str
    submission: dict[str, Any]
    status: str
    response: str


@dataclass
class AgentSet:
    intake: IntakeAgent
    supervisor: SupervisorAgent
    eligibility: EligibilityAgent
    document_checker: DocumentCheckerAgent
    application: ApplicationAgent

    @classmethod
    def from_environment(cls) -> "AgentSet":
        supervisor_model = create_chat_model("supervisor")
        specialist_model = create_chat_model("specialist")
        return cls(
            intake=IntakeAgent(specialist_model),
            supervisor=SupervisorAgent(supervisor_model),
            eligibility=EligibilityAgent(specialist_model),
            document_checker=DocumentCheckerAgent(specialist_model),
            application=ApplicationAgent(specialist_model),
        )


def _supervisor_node(
    agents: AgentSet, state: AgentWorkflowState, validate: bool = True
) -> dict[str, Any]:
    """Entry point: validate input, detect language and intent, route.

    `validate=False` is for the reroute pass, where the same message was already validated this turn.
    """
    update: dict[str, Any] = {}
    validation = None
    is_reply = bool(state.get("pending_field"))
    if validate:
        validation = agents.supervisor.validate_input(
            state["request"], state.get("actor_id"), is_reply=is_reply
        )
        if not validation.passed:
            return {
                "language": validation.language,
                "intent": validation.intent,
                "validation_errors": validation.errors,
                "plan": {"next_agent": "respond", "reason": "The request did not pass input validation."},
            }
        update = {"validation_errors": []}
    if is_reply:
        # A reply to intake's question ("yes", "1 lakh") means nothing without that question,
        # so the plan from the earlier turn stands and the model is not asked to re-route it.
        return update
    plan = agents.supervisor.invoke(
        SupervisorInput(
            request=state["request"],
            selected_scheme_id=state.get("selected_scheme_id"),
        )
    )
    if plan.next_agent == "respond" and asks_about_own_eligibility(state["request"]):
        # Code, not the model, keeps personal eligibility questions on the rule-engine path.
        logger.info("Rerouted a personal eligibility question from respond to intake.")
        plan = plan.model_copy(update={
            "next_agent": "intake",
            "scheme_question": False,
            "reason": f"{plan.reason} (Rerouted: the user asks about their own eligibility.)",
        })
    update["plan"] = plan.model_dump(mode="json")
    if plan.language != "unknown":
        update["language"] = plan.language
    elif validation is not None:
        update["language"] = validation.language
    if validation is not None:
        update["intent"] = validation.intent
    return update


def _guard_output(
    agents: AgentSet,
    state: AgentWorkflowState,
    update: dict[str, str],
    agent_name: str,
    blocked_message: dict[str, str] | None = None,
) -> dict[str, str]:
    """Supervisor output check: nothing leaves the graph unless it passes.

    `blocked_message`, by language, replaces the generic error when a block has a known,
    safe next step to offer the person.
    """
    language = state.get("language", "unknown")
    result = agents.supervisor.validate_output(update["response"], agent_name, language)
    if result.passed:
        return update
    logger.warning("Output from %s blocked: %s", agent_name, "; ".join(result.errors))
    if blocked_message:
        return {"status": "output_blocked", "response": blocked_message.get(language, blocked_message["en"])}
    blocked = agents.supervisor.handle_validation_error(result, language)
    return {"status": "output_blocked", "response": blocked["user_message"]}


def _route_after_supervisor(state: AgentWorkflowState) -> str:
    """The Supervisor's next step. Any goal that needs a profile starts with intake."""
    if state.get("validation_errors"):
        return "respond"
    if state.get("pending_field"):
        return "intake"
    return state["plan"]["next_agent"]


def _candidate_schemes(state: AgentWorkflowState) -> list[str]:
    """The selected scheme, else this intake's shortlist, else every scheme whose rules are reviewed."""
    scheme_id = state.get("selected_scheme_id")
    if scheme_id:
        return [scheme_id]
    return state.get("shortlist") or tools.search_schemes({})


@lru_cache(maxsize=1)
def _scheme_catalogue() -> tuple[tuple[str, str, str], ...]:
    """(scheme_id, name, short description) for every scheme whose rules are reviewed."""
    reviewed = set(tools.search_schemes({}))
    found: dict[str, tuple[str, str, str]] = {}
    for path in sorted((PROJECT_ROOT / "data" / "schemes").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        scheme_id = record.get("scheme_id")
        if scheme_id not in reviewed:
            continue
        items = ((record.get("sections") or {}).get("details") or {}).get("items") or []
        found[scheme_id] = (scheme_id, record.get("name", scheme_id), str((items[:1] or [{}])[0].get("text", ""))[:200])
    return tuple(found.values())


def _shortlist_schemes(agents: AgentSet, request: str, facts: FactMap | None = None) -> list[str]:
    """Reviewed schemes the model judges relevant to the request and facts; empty means check them all."""
    options = [SchemeOption(scheme_id=i, name=n, description=d) for i, n, d in _scheme_catalogue()]
    if not options:
        return []
    try:
        choice = SchemeChoiceInput(request=request, known_facts=facts or {}, schemes=options)
        return agents.intake.choose_schemes(choice)[:SHORTLIST_SIZE]
    except Exception:
        logger.warning("Scheme shortlisting failed; every reviewed scheme will be checked.")
        return []


def _facts_so_far(state: AgentWorkflowState) -> FactMap:
    """Confirmed facts, overridden by anything said since: known_facts holds the latest values."""
    return {**state.get("confirmed_facts", {}), **state.get("known_facts", {})}


def _unconfirmed(state: AgentWorkflowState) -> FactMap:
    confirmed = state.get("confirmed_facts", {})
    return {f: v for f, v in state.get("known_facts", {}).items() if f not in confirmed or confirmed[f] != v}


def _subject(state: AgentWorkflowState) -> str:
    """Whose facts these are; the signed-in person unless a message said otherwise."""
    return state.get("subject") or "self"


def _fresh_assessment(request: str) -> dict[str, Any]:
    """Everything one person's check built up, cleared for a different person."""
    return {
        "known_facts": {RESET_FACTS: True},
        "confirmed_facts": {RESET_FACTS: True},
        "remembered_facts": {},
        "remembered_fields": [],
        "memory_loaded": False,
        "memory_saved": [],
        "verdicts": {},
        "explanations": {},
        "eligibility": None,
        "document_check": None,
        "application_draft": None,
        "portal_draft": None,
        "approved_hash": "",
        "approval_status": "",
        "confirm_status": "",
        "rejected_edits": [],
        "intake_request": request,
        "declined_fields": [],
        "question_attempts": {},
        "questions_asked": 0,
        "intake_stopped": None,
    }


def _subject_update(
    agents: AgentSet, state: AgentWorkflowState, result: Any, replying: bool
) -> dict[str, Any]:
    """Whose facts a message is about; a switch of person starts a clean assessment.

    A new request with no facts and no named relation says nothing about whose it is, so the
    subject stays as it was. A short reply to a question counts only when it names a different
    relation and brings facts: "yes" must never move the check to someone else.
    """
    relation = clean_relation(result.relation) if result.subject == "other" else None
    if replying:
        if not (relation and result.facts and relation != state.get("relation")):
            return {}
    elif not (result.subject == "other" or result.facts):
        return {}
    subject = result.subject
    update: dict[str, Any] = {"subject": subject, "relation": relation}
    known_person = state.get("subject") or state.get("remembered_fields")
    if known_person and (_subject(state), state.get("relation")) != (subject, relation):
        update |= _fresh_assessment(state["request"])
        update["known_facts"] = {RESET_FACTS: True, **result.facts}
        if not state.get("selected_scheme_id"):
            update["shortlist"] = _shortlist_schemes(agents, state["request"], result.facts)
    return update


def _intake_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, Any]:
    """Read typed facts from the message into known_facts. They stay unconfirmed."""
    pending = state.get("pending_field")
    if pending is None and not state.get("selected_scheme_id"):
        state = {**state, "shortlist": _shortlist_schemes(agents, state["request"], _facts_so_far(state))}
    with tools.acting_as("intake"):
        specs = tools.field_specs(_candidate_schemes(state))
    if not specs:  # no reviewed rule fields, so nothing the profile could hold
        return {"pending_field": None}
    result = agents.intake.extract(
        IntakeExtractInput(
            request=state["request"],
            pending_field=pending,
            pending_question=state.get("pending_question") if pending else None,
        ),
        specs,
    )
    shortlist = state.get("shortlist") or []
    if pending is not None and result.facts and not state.get("selected_scheme_id"):
        # An answer is new information, so re-pick; keep the old list if the re-pick fails or is empty.
        facts = {**_facts_so_far(state), **result.facts}
        shortlist = _shortlist_schemes(agents, state.get("intake_request", state["request"]), facts) or shortlist
    update: dict[str, Any] = {
        "known_facts": result.facts,
        "shortlist": shortlist,
        "pending_field": None,
        "pending_question": None,
        "reply_unanswered": pending is not None and not result.facts and not result.dont_know,
    }
    if pending is None:  # a fresh intake: earlier "don't know"s and counts no longer apply
        update |= {
            "intake_request": state["request"],
            "declined_fields": [],
            "question_attempts": {},
            "questions_asked": 0,
            "intake_stopped": None,
        }
    update |= _subject_update(agents, state, result, replying=pending is not None)
    if result.dont_know:
        # Skip only this fact: intake goes on with the questions that can still change a verdict.
        update["declined_fields"] = [*state.get("declined_fields", []), pending]
    return update


def _route_after_intake(state: AgentWorkflowState) -> str:
    # A reply with nothing in it may be a new request ("what documents do I need?"),
    # so the Supervisor routes it instead of intake repeating its question.
    return "reroute" if state.get("reply_unanswered") else "eligibility"


def _route_after_reroute(state: AgentWorkflowState) -> str:
    """The message was already read by intake, so a profile goal goes straight to eligibility."""
    goal = state["plan"]["next_agent"]
    return "eligibility" if goal in PROFILE_GOALS else goal


def _open_fields(state: AgentWorkflowState) -> list[str]:
    """Fields an answer could still settle a verdict with, including declined ones."""
    return sorted(
        {f for v in state["verdicts"].values() if v["verdict"] == "cant_tell" for f in v["unresolved_fields"]}
    )


def _skipped_fields(state: AgentWorkflowState) -> list[str]:
    """Fields not to ask again: declined ("don't know"), or asked twice without a usable answer."""
    tired = [f for f, n in state.get("question_attempts", {}).items() if n >= MAX_ATTEMPTS_PER_FIELD]
    return list(dict.fromkeys([*state.get("declined_fields", []), *tired]))


def _stop_intake(state: AgentWorkflowState, reason: str, declined: list[str]) -> dict[str, Any]:
    if reason == "question_cap":
        response = (
            "You have reached your limit of questions. The eligible and other relevant schemes "
            "are available in the list below."
        )
    else:
        response = (
            "I can't finish the eligibility check without these details: "
            + ", ".join(f.replace("_", " ") for f in _open_fields(state))
            + ". Tell me if you find out, and I'll check again."
        )
    return {
        "intake_stopped": reason,
        "declined_fields": declined,
        "status": "intake_stopped",
        "response": response,
    }


def _intake_question_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, Any]:
    """Ask for the one field that settles the most open verdicts, then wait for the reply.

    Facts the person doesn't know, or couldn't answer twice, are skipped rather than ending
    intake. Intake stops only at the question cap.
    """
    declined = state.get("declined_fields", [])
    if state.get("intake_stopped"):
        return _stop_intake(state, state["intake_stopped"], declined)
    if state.get("questions_asked", 0) >= MAX_QUESTIONS:
        return _stop_intake(state, "question_cap", declined)
    field = tools.next_question(state["verdicts"], _skipped_fields(state))
    attempts = state.get("question_attempts", {})
    spec = tools.field_specs(_candidate_schemes(state))[field]
    question = agents.intake.ask(
        IntakeAskInput(
            field=field,
            field_type=spec["type"],
            known_values=spec["known_values"],
            period=income_period(field),
            language=state.get("language", "unknown"),
            request=state.get("intake_request", state["request"]),
        )
    )
    guarded = _guard_output(
        agents, state, {"status": "needs_information", "response": question.question}, "intake"
    )
    if guarded["status"] == "output_blocked":
        return guarded
    return {
        "pending_field": field,
        "pending_question": question.question,
        "question_attempts": {**attempts, field: attempts.get(field, 0) + 1},
        "questions_asked": state.get("questions_asked", 0) + 1,
        **guarded,
    }


def _resolve_deterministic_evaluation(state: AgentWorkflowState) -> dict[str, Any] | None:
    """Use the project rule engine as the source of truth when a scheme and facts are known."""
    scheme_id = state.get("selected_scheme_id")
    if not scheme_id:
        return None

    facts = state.get("confirmed_facts") or {}  # a verdict only ever rests on confirmed facts
    if not isinstance(facts, dict) or not facts:
        return None

    return tools.evaluate_scheme(facts, scheme_id)


def _eligibility_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    """Evaluate every candidate scheme on the facts so far, then explain the selected one.

    While some facts are unconfirmed the verdicts only steer intake's questions; once all are
    confirmed they are final and, without a selected scheme, each gets a cited explanation.
    """
    verdicts = {
        scheme_id: tools.evaluate_scheme(_facts_so_far(state), scheme_id)
        for scheme_id in _candidate_schemes(state)
    }
    explanations = {}
    if not state.get("selected_scheme_id") and not _unconfirmed(state):
        explanations = {
            s: tools.with_closed_note(
                s, agents.eligibility.invoke(EligibilityInput(scheme_id=s, evaluation=v)).explanation)
            for s, v in verdicts.items()
        }
    return {"verdicts": verdicts, "explanations": explanations, **_selected_scheme_eligibility(agents, state)}


def _selected_scheme_eligibility(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    scheme_id = state.get("selected_scheme_id")
    raw_evaluation = state.get("deterministic_evaluation")
    facts = state.get("confirmed_facts") or {}

    if not scheme_id:
        return {
            "eligibility": {
                "verdict": "cant_tell",
                "reason": "A scheme was not selected for eligibility evaluation.",
                "missing_fields": [],
                "unresolved_fields": [],
                "conditions": [],
                "citations": [],
            }
        }

    if raw_evaluation is None:
        raw_evaluation = _resolve_deterministic_evaluation(state)

    if raw_evaluation is None:
        failed = {
            "verdict": "cant_tell",
            "reason": "A deterministic rule evaluation was not provided.",
            "missing_fields": [],
            "unresolved_fields": [],
            "conditions": [],
            "citations": [],
        }
        if not scheme_id:
            failed["reason"] = "A scheme was not selected for eligibility evaluation."
        elif not facts:
            failed["reason"] = "No facts have been confirmed yet."
        return {"eligibility": failed}

    evaluation = Evaluation.model_validate(raw_evaluation)
    evaluation_data = evaluation.model_dump(mode="json")
    narrative = agents.eligibility.invoke(
        EligibilityInput(scheme_id=scheme_id, evaluation=evaluation_data)
    )
    # Not written back to state: a later turn with new facts must be evaluated afresh.
    return {
        "eligibility": {
            **evaluation_data,
            "explanation": tools.with_closed_note(scheme_id, narrative.explanation),
            "clarifying_questions": narrative.clarifying_questions,
        },
    }


def _at_question_cap(state: AgentWorkflowState) -> bool:
    """This intake has asked its maximum (an older thread may carry the stop flag instead)."""
    return state.get("intake_stopped") == "question_cap" or state.get("questions_asked", 0) >= MAX_QUESTIONS


def _route_after_eligibility(state: AgentWorkflowState) -> str:
    # Still open: ask the next question. At the question cap, or once nothing left to ask can
    # change a verdict, the person confirms the facts given so far and gets every verdict:
    # the decided ones, and the open ones as a final "can't tell" naming what is missing.
    # (Stopping at the cap without that left 11 of 21 C2 development cases with no answer.)
    if (
        _open_fields(state)
        and not _at_question_cap(state)
        and tools.next_question(state["verdicts"], _skipped_fields(state))
    ):
        return "intake_question"
    if _unconfirmed(state):
        return "confirm"
    is_application = state["plan"]["next_agent"] == "application"
    eligible = state["eligibility"]["verdict"] == "eligible"
    return "document_checker" if is_application and eligible else "finish"


def _fits(kind: str, value: Any) -> bool:
    """The rule engine's types: it never coerces, so neither may an edit."""
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


def _confirm_node(state: AgentWorkflowState) -> dict[str, Any]:
    """Pause until the person confirms the exact facts the final verdicts will rest on."""
    facts = _facts_so_far(state)
    shown = application_hash(facts)
    decision = interrupt(
        {
            "kind": "confirm_facts",
            "facts": facts,
            "payload_hash": shown,
            "subject": _subject(state),
            "relation": state.get("relation"),
            "remembered_fields": [f for f in state.get("remembered_fields", []) if f in facts],
            "rejected_edits": state.get("rejected_edits", []),
            "options": ["approve", "edit", "reject"],
        }
    )
    action = decision.get("action") if isinstance(decision, dict) else None
    if action == "approve":
        if decision.get("payload_hash") == shown:
            return {"confirmed_facts": facts, "confirm_status": "confirmed", "rejected_edits": []}
        return {
            "confirm_status": "invalid",
            "status": "confirmation_invalid",
            "response": "The confirmation did not match the facts shown. Nothing was confirmed.",
        }
    if action == "edit" and isinstance(decision.get("changes"), dict):
        specs = tools.field_specs(_candidate_schemes(state))
        changes = decision["changes"]
        valid = {f: v for f, v in changes.items() if f in specs and _fits(specs[f]["type"], v)}
        rejected = sorted(set(changes) - set(valid))
        if rejected:  # show the facts again, with what could not be used
            return {"known_facts": valid, "rejected_edits": rejected, "confirm_status": "edit_rejected"}
        # Editing the facts shown, and sending them back, confirms them.
        return {
            "known_facts": valid,
            "confirmed_facts": {**facts, **valid},
            "confirm_status": "confirmed",
            "rejected_edits": [],
        }
    return {
        "confirm_status": "rejected",
        "status": "facts_rejected",
        "response": "Nothing was confirmed. Tell me what to correct and I'll check again.",
    }


def _route_after_confirm(state: AgentWorkflowState) -> str:
    # Confirmed facts are offered to memory first; an edit that was not usable is shown again,
    # and either way the verdicts are evaluated again: an edit can reopen a verdict.
    if state["confirm_status"] == "confirmed":
        return "memory_save"
    return "eligibility" if state["confirm_status"] == "edit_rejected" else END


def _memory_load_node(
    memory: MemoryService | None, state: AgentWorkflowState, config: dict[str, Any]
) -> dict[str, Any]:
    """Prefill facts the signed-in person asked to be remembered, once per thread.

    They go in as unconfirmed facts, so the confirm step shows them and no verdict is final
    until the person has seen them. Only the fields the candidate schemes need are read.
    """
    ctx = memory_context(memory, config)
    if ctx is None or ctx.scope.actor_role != "citizen" or state.get("memory_loaded"):
        return {}
    if _subject(state) != "self":
        return {}
    try:
        specs = tools.field_specs(_candidate_schemes(state))
        remembered = load_remembered(ctx, specs, _facts_so_far(state))
    except Exception:
        logger.warning("Memory could not be read; continuing without it.")
        record_memory_operation("load", "error")
        return {}
    record_memory_operation("load", "hit" if remembered else "miss")
    return {
        "memory_loaded": True,
        "subject": "self",
        "relation": None,
        "known_facts": remembered,
        "remembered_facts": remembered,
        "remembered_fields": sorted(remembered),
    }


def _memory_save_node(
    memory: MemoryService | None, state: AgentWorkflowState, config: dict[str, Any]
) -> dict[str, Any]:
    """Remember the confirmed facts the policy allows. Facts about someone else are never saved."""
    ctx = memory_context(memory, config)
    if ctx is None or ctx.scope.actor_role != "citizen" or _subject(state) != "self":
        return {}
    try:
        saved, held = save_confirmed(
            ctx, state.get("confirmed_facts") or {}, state.get("remembered_facts") or {}
        )
    except Exception:
        logger.warning("Memory could not be updated; continuing without it.")
        record_memory_operation("save", "error")
        return {}
    record_memory_operation("save", "saved" if saved else "skipped")
    return {"memory_saved": saved, "remembered_facts": held}


def _document_checker_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    result = agents.document_checker.invoke(
        DocumentCheckInput(
            scheme_id=state["selected_scheme_id"],
            required_documents=state.get("required_documents", []),
            available_documents=state.get("available_documents", []),
            household_persona=state.get("confirmed_facts", {}),
        )
    )
    return {"document_check": result.model_dump(mode="json")}


def _route_after_documents(state: AgentWorkflowState) -> str:
    if state["plan"]["next_agent"] == "application":
        return "application"
    return "finish"


def _application_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    if state["eligibility"]["verdict"] != "eligible":
        raise ValueError("Application drafting requires an eligible rule-engine result.")
    if not state.get("selected_scheme_id"):
        raise ValueError("Application drafting requires a selected scheme.")
    scheme_id = state["selected_scheme_id"]
    required = state.get("application_required_fields")
    mapping = state.get("application_field_mapping")
    if not required:
        required, derived_mapping = tools.application_form_spec(scheme_id)
        mapping = mapping or derived_mapping
    draft = agents.application.invoke(
        ApplicationInput(
            scheme_id=scheme_id,
            confirmed_facts=state.get("confirmed_facts", {}),
            required_fields=required,
            field_mapping=mapping or {field: field for field in required},
        )
    )
    update: dict[str, Any] = {
        "application_draft": draft.model_dump(mode="json"),
        "application_required_fields": required,
        "application_field_mapping": mapping or {field: field for field in required},
    }
    if not draft.missing_fields:
        form = {"scheme_id": draft.scheme_id, "applicant": draft.fields}
        with tools.acting_as("application"):
            portal_draft = tools.create_portal_draft(
                form, household_id=state.get("actor_id")
            )
        update["portal_draft"] = {**portal_draft, "form_hash": application_hash(form)}
    return update


def _application_form(state: AgentWorkflowState) -> dict[str, Any]:
    """The exact form a person approves and the portal receives."""
    draft = state["application_draft"]
    return {"scheme_id": draft["scheme_id"], "applicant": draft["fields"]}


def _route_after_application(state: AgentWorkflowState) -> str:
    # An incomplete draft goes back to the person for more facts, not to approval.
    return "finish" if state["application_draft"]["missing_fields"] else "approval"


def _approval_node(state: AgentWorkflowState) -> dict[str, Any]:
    """Pause for a person. Approval counts only if it names the hash of this exact form."""
    form = _application_form(state)
    current = application_hash(form)
    decision = interrupt(
        {
            "form": form,
            "portal_draft_id": (state.get("portal_draft") or {}).get("application_id"),
            "payload_hash": current,
            "subject": _subject(state),
            "relation": state.get("relation"),
            "options": ["approve", "edit", "reject"],
        }
    )
    action = decision.get("action") if isinstance(decision, dict) else None
    authenticated = bool(state.get("actor_id"))
    if action == "approve":
        if decision.get("payload_hash") == current:
            portal_draft_id = (state.get("portal_draft") or {}).get("application_id")
            if not portal_draft_id:
                tools.audit_approval_event("approve", "invalid", authenticated)
                return {"approval_status": "invalid", "approved_hash": ""}
            tools.audit_approval_event("approve", "accepted", authenticated)
            return {
                "approval_status": "approved",
                "approved_hash": current,
                "citizen_agreed": decision.get("citizen_agreed") is True,
            }
        tools.audit_approval_event("approve", "invalid", authenticated)
        return {"approval_status": "invalid", "approved_hash": ""}
    if action == "edit" and isinstance(decision.get("changes"), dict):
        tools.audit_approval_event("edit", "accepted", authenticated)
        facts = {**state.get("confirmed_facts", {}), **decision["changes"]}
        return {
            "confirmed_facts": facts,
            "approval_status": "edited",
            "approved_hash": "",
            "status": "draft_edited",
            "response": "Facts were edited. Prepare a new draft to review again.",
        }
    tools.audit_approval_event(
        "reject" if action == "reject" else "invalid",
        "rejected" if action == "reject" else "invalid",
        authenticated,
    )
    return {
        "approval_status": "rejected" if action == "reject" else "invalid",
        "approved_hash": "",
    }


def _route_after_approval(state: AgentWorkflowState) -> str:
    if state["approval_status"] == "approved":
        return "submit"
    return "memory_save_edit" if state["approval_status"] == "edited" else "approval_end"


def _approval_end_node(state: AgentWorkflowState) -> dict[str, str]:
    status = state["approval_status"]
    if status == "edited":
        return {}
    messages = {
        "rejected": "The draft was rejected. Nothing was submitted.",
        "invalid": "The approval did not match this exact form. Nothing was submitted.",
    }
    return {"status": f"approval_{status}", "response": messages[status]}


MAX_TRACKED = 10  # applications one status reply looks up
TRACK_TEXT = {
    "en": {
        "head": "Your saved applications, with the status the portal shows now:",
        "none": (
            "I have no saved applications for you. An application is remembered only if "
            "you allowed it before submitting."
        ),
        "none_for": "I have no saved applications for your {relation}.",
        "off": "Remembering applications is not available right now.",
        "other": "for your {relation}",
        "someone": "for someone else",
        "gone": "not found at the portal",
        "unknown": "status unavailable right now",
        "reference": "reference",
    },
    "hi": {
        "head": "आपके सहेजे गए आवेदन और पोर्टल पर अभी दिख रही स्थिति:",
        "none": (
            "आपके लिए कोई आवेदन सहेजा हुआ नहीं है। आवेदन तभी याद रखा जाता है जब आपने "
            "जमा करने से पहले अनुमति दी हो।"
        ),
        "none_for": "आपके {relation} के लिए कोई आवेदन सहेजा हुआ नहीं है।",
        "off": "आवेदन याद रखने की सुविधा अभी उपलब्ध नहीं है।",
        "other": "आपके {relation} के लिए",
        "someone": "किसी और के लिए",
        "gone": "पोर्टल पर नहीं मिला",
        "unknown": "स्थिति अभी उपलब्ध नहीं है",
        "reference": "संदर्भ",
    },
    "mr": {
        "head": "तुमचे जतन केलेले अर्ज आणि पोर्टलवर आत्ता दिसणारी स्थिती:",
        "none": (
            "तुमच्यासाठी कोणताही अर्ज जतन केलेला नाही. सादर करण्यापूर्वी तुम्ही परवानगी दिली "
            "असेल तरच अर्ज लक्षात ठेवला जातो."
        ),
        "none_for": "तुमच्या {relation} साठी कोणताही अर्ज जतन केलेला नाही.",
        "off": "अर्ज लक्षात ठेवण्याची सुविधा सध्या उपलब्ध नाही.",
        "other": "तुमच्या {relation} साठी",
        "someone": "इतर कोणासाठी",
        "gone": "पोर्टलवर सापडला नाही",
        "unknown": "स्थिती सध्या उपलब्ध नाही",
        "reference": "संदर्भ",
    },
}


def _track_node(
    agents: AgentSet, memory: MemoryService | None, state: AgentWorkflowState, config: dict[str, Any]
) -> dict[str, str]:
    """Answer "where is my application?" from the person's own saved list, with live portal status.

    The applications come from the signed-in person's memory, never from an ID in the message,
    so asking about a stranger's application finds nothing.
    """
    text = TRACK_TEXT.get(state.get("language", "unknown"), TRACK_TEXT["en"])
    ctx = memory_context(memory, config)
    if ctx is None:
        return _guard_output(agents, state, {"status": "responded", "response": text["off"]}, "supervisor")
    try:
        references = ctx.service.read_application_references(ctx.scope)
    except Exception:
        logger.warning("Saved applications could not be read.")
        return _guard_output(agents, state, {"status": "responded", "response": text["off"]}, "supervisor")
    if not references:
        return _guard_output(agents, state, {"status": "no_applications", "response": text["none"]}, "supervisor")

    asked = relation_in_text(state.get("request", ""))
    if asked:
        references = [
            r for r in references if r.subject == "other" and family_relation(r.relation) == asked
        ]
        if not references:
            reply = {"status": "no_applications", "response": text["none_for"].format(relation=asked)}
            return _guard_output(agents, state, reply, "supervisor")

    lines = []
    for reference in references[:MAX_TRACKED]:
        try:
            status = tools.application_status(reference.application_id, ctx.scope.household_id)["status"]
        except tools.ToolCallError as error:
            status = text["gone"] if error.code == "application_not_found" else text["unknown"]
        except Exception:
            status = text["unknown"]
        for_whom = ""
        if reference.subject == "other":
            relation = reference.relation
            if relation and reference.nickname:
                relation = f"{relation} ({reference.nickname})"
            for_whom = " " + (text["other"].format(relation=relation) if relation else text["someone"])
        lines.append(
            f"- {reference.scheme_id}: {status}{for_whom} ({text['reference']} {reference.application_id[:8]})"
        )
    update = {"status": "applications_listed", "response": text["head"] + "\n" + "\n".join(lines)}
    return _guard_output(agents, state, update, "supervisor")


def _remember_application(
    memory: MemoryService | None,
    state: AgentWorkflowState,
    config: dict[str, Any],
    form: dict[str, Any],
    submission: dict[str, Any],
) -> dict[str, Any]:
    """Remember the submitted application for status checks, if consent allows. Never fails the run."""
    ctx = memory_context(memory, config)
    if ctx is None:
        return {}
    try:
        saved = save_application_reference(
            ctx,
            form["scheme_id"],
            submission["application_id"],
            _subject(state),
            state.get("relation"),
            citizen_agreed=state.get("citizen_agreed") is True,
        )
    except Exception:
        logger.warning("The submitted application could not be remembered.")
        record_memory_operation("reference", "error")
        return {"reference_saved": False}
    record_memory_operation("reference", "saved" if saved else "skipped")
    return {"reference_saved": saved}


def _submit_node(
    memory: MemoryService | None, state: AgentWorkflowState, config: dict[str, Any]
) -> dict[str, Any]:
    """The only write. Refuses unless the approved hash still matches the form."""
    form = _application_form(state)
    if application_hash(form) != state.get("approved_hash"):
        return {
            "approval_status": "invalid",
            "status": "approval_invalid",
            "response": "The form changed after approval. Nothing was submitted.",
        }
    portal_draft = state.get("portal_draft") or {}
    if portal_draft.get("form_hash") != state.get("approved_hash") or not portal_draft.get("application_id"):
        return {
            "approval_status": "invalid",
            "status": "approval_invalid",
            "response": "There is no portal draft for the approved form. Nothing was submitted.",
        }
    with tools.acting_as("application"):
        submission = tools.submit_application(
            form,
            application_id=portal_draft["application_id"],
            write_capability=tools.issue_submission_capability(
                form,
                state["approved_hash"],
                application_id=portal_draft["application_id"],
                household_id=state.get("actor_id"),
            ),
            household_id=state.get("actor_id"),
        )
    return {
        "submission": submission,
        "status": "submitted",
        "response": f"Application submitted (mock). Reference: {submission['application_id']}",
        **_remember_application(memory, state, config, form, submission),
    }


# A scheme answer that decided the person's own eligibility is replaced by an offer to check
# it properly: only the rule engine, on confirmed facts, may say who qualifies.
CHECK_ELIGIBILITY_INSTEAD = {
    "hi": "मैं योजना दस्तावेज़ों से यह तय नहीं कर सकता कि आप या आपके परिजन पात्र हैं या नहीं। "
          "अगर आप मुझे उस व्यक्ति के बारे में बताएँ, जैसे उम्र और परिवार के पास बीपीएल कार्ड है या नहीं, "
          "तो मैं नियमों से जाँच कर दूँगा।",
    "mr": "योजनेच्या कागदपत्रांवरून तुम्ही किंवा तुमचे नातेवाईक पात्र आहात की नाही हे मी ठरवू शकत नाही. "
          "त्या व्यक्तीबद्दल सांगा, जसे वय आणि कुटुंबाकडे बीपीएल कार्ड आहे का, म्हणजे मी नियमांनुसार तपासतो.",
    "en": "I can't decide from the scheme documents whether you or your family member qualify. "
          "If you tell me about the person, such as their age and whether the family has a BPL card, "
          "I'll check the scheme rules for you.",
}

NOT_FOUND = {
    "hi": "मुझे यह जानकारी समीक्षित योजना दस्तावेज़ों में नहीं मिली।",
    "mr": "मला ही माहिती तपासलेल्या योजना कागदपत्रांमध्ये सापडली नाही.",
    "en": "I couldn't find this in the reviewed scheme documents.",
}


def _scheme_answer(agents: AgentSet, state: AgentWorkflowState) -> dict[str, str]:
    """Intake drafts a cited answer from schemes-kb evidence; nothing relevant gives NOT_FOUND."""
    language = state.get("language", "unknown")
    not_found = {"status": "answer_not_found", "response": NOT_FOUND.get(language, NOT_FOUND["en"])}
    try:
        with tools.acting_as("intake"):
            passages = tools.search_evidence(state["request"], state.get("selected_scheme_id"))
        if not passages:
            return not_found
        result = agents.intake.answer(
            IntakeAnswerInput(
                question=state["request"],
                language=language,
                passages=[EvidencePassage(id=p["id"], scheme_id=p["scheme_id"], text=p["text"]) for p in passages],
            )
        )
    except Exception:
        logger.exception("A scheme question could not be answered from evidence.")
        return not_found
    if not result.found:
        return not_found
    sources = sorted({
        f"{p['scheme_id']}: {c['source_url']}" + (f" (page {c['page']})" if c.get("page") else "")
        for p in passages if p["id"] in result.cited_passage_ids for c in p["citations"]
    })
    return {"status": "answered", "response": result.answer + "\n\nSources:\n" + "\n".join(f"- {s}" for s in sources)}


def _respond_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, str]:
    if state.get("validation_errors"):
        return {"status": "validation_error", "response": " ".join(state["validation_errors"])}
    if state["plan"].get("scheme_question"):
        return _guard_output(
            agents, state, _scheme_answer(agents, state), "scheme_info", CHECK_ELIGIBILITY_INSTEAD
        )
    return _guard_output(
        agents, state, {"status": "responded", "response": state["plan"]["reason"]}, "supervisor"
    )


def _finish_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, str]:
    if state.get("document_check") is not None and state.get("application_draft") is None:
        review = agents.supervisor.invoke(
            SupervisorInput(
                request=state["request"],
                selected_scheme_id=state.get("selected_scheme_id"),
                document_check=state["document_check"],
            )
        )
        update = {"status": "documents_checked", "response": review.reason}
    else:
        update = _finish_update(state)
    if state.get("application_draft") is not None:
        agent_name = "application"
    elif state.get("document_check") is not None and state.get("application_draft") is None:
        agent_name = "supervisor"
    elif state.get("document_check") is not None:
        agent_name = "document_checker"
    elif state.get("eligibility") is not None:
        agent_name = "eligibility"
    else:
        agent_name = "supervisor"
    return _guard_output(agents, state, update, agent_name)


def _finish_update(state: AgentWorkflowState) -> dict[str, str]:
    if state.get("application_draft") is not None:
        incomplete = bool(state["application_draft"]["missing_fields"])
        return {
            "status": "draft_needs_information" if incomplete else "draft_ready_for_review",
            "response": state["application_draft"]["review_summary"],
        }
    if state.get("document_check") is not None:
        check = DocumentCheckResult.model_validate(state["document_check"])
        missing = check.missing_documents
        response_parts = (
            ["Missing documents: " + ", ".join(missing)]
            if missing
            else ["Document checklist complete; authenticity is not verified."]
        )
        response_parts.extend(check.possible_inconsistencies)
        response_parts.extend(check.clarifying_questions)
        response = " ".join(response_parts)
        return {"status": "documents_checked", "response": response}
    if state.get("explanations") and not state.get("selected_scheme_id"):
        return {
            "status": "eligibility_checked",
            "response": "\n".join(f"{s}: {text}" for s, text in state["explanations"].items()),
        }
    if state.get("eligibility") is not None:
        return {
            "status": "eligibility_checked",
            "response": state["eligibility"].get(
                "explanation", state["eligibility"]["reason"]
            ),
        }
    return {"status": "responded", "response": state["plan"]["reason"]}


def build_agent_graph(
    agents: AgentSet | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    memory: MemoryService | None = None,
):
    """Build agent workflow with Supervisor as entry point.
    
    Graph Flow:
    START → Supervisor (detect language/intent and route; a pending question skips the model)
            ├→ intake (message → typed known_facts) → eligibility (verdicts for candidate schemes)
            │       ├→ intake_question (one question that settles the most open verdicts) → END
            │       └→ document_checker → application → approval → submit, or finish
            ├→ document_checker
            └→ respond (direct response without specialist)
    → finish (format response)
    → END

    With `memory`, remembered facts are prefilled after intake (memory_load) and confirmed facts
    are remembered after the confirm step and after an edit at approval (memory_save); submit
    remembers the application reference. The person comes from the run config (graph.memory_nodes.
    memory_config); without it, or without consent, nothing is read or written.
    """
    runtime = agents or AgentSet.from_environment()
    builder = StateGraph(AgentWorkflowState)
    
    # Add all nodes
    builder.add_node("supervisor", lambda state: _supervisor_node(runtime, state))
    builder.add_node(
        "intake",
        lambda state: tools.run_as("intake", _intake_node, runtime, state),
    )
    builder.add_node(
        "intake_question",
        lambda state: tools.run_as("intake", _intake_question_node, runtime, state),
    )
    builder.add_node("reroute", lambda state: _supervisor_node(runtime, state, validate=False))
    builder.add_node(
        "confirm", lambda state: tools.run_as("intake", _confirm_node, state)
    )
    builder.add_node(
        "eligibility",
        lambda state: tools.run_as("eligibility", _eligibility_node, runtime, state),
    )
    builder.add_node(
        "document_checker",
        lambda state: tools.run_as(
            "document_checker", _document_checker_node, runtime, state
        ),
    )
    builder.add_node(
        "application",
        lambda state: tools.run_as("application", _application_node, runtime, state),
    )
    builder.add_node("approval", _approval_node)
    builder.add_node("approval_end", _approval_end_node)
    builder.add_node("submit", lambda state, config: _submit_node(memory, state, config))
    builder.add_node("finish", lambda state: _finish_node(runtime, state))
    builder.add_node("respond", lambda state: _respond_node(runtime, state))
    if memory is not None:
        builder.add_node(
            "memory_load",
            lambda state, config: tools.run_as("intake", _memory_load_node, memory, state, config),
        )
        builder.add_node("memory_save", lambda state, config: _memory_save_node(memory, state, config))
        builder.add_node("memory_save_edit", lambda state, config: _memory_save_node(memory, state, config))
        builder.add_node("track", lambda state, config: _track_node(runtime, memory, state, config))
        builder.add_edge("track", END)
    # Where a profile goal goes once intake has read the message, and where a confirmation goes next
    facts_ready = "memory_load" if memory is not None else "eligibility"
    after_confirmed = "memory_save" if memory is not None else "eligibility"
    after_edited = "memory_save_edit" if memory is not None else "approval_end"

    def route_after_supervisor(state: AgentWorkflowState) -> str:
        # A follow-up about an application is answered from the person's own saved list.
        if (
            memory is not None
            and state.get("intent") == "follow_up"
            and not state.get("validation_errors")
            and not state.get("pending_field")
        ):
            return "track"
        return _route_after_supervisor(state)
    
    # Entry point: Supervisor ALWAYS first
    builder.add_edge(START, "supervisor")
    
    # After Supervisor routes to: intake, eligibility, document_checker, application, or finish
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "intake": "intake",
            "eligibility": "intake",  # facts in the message come first
            "document_checker": "document_checker",
            "application": "intake",
            "respond": "respond",  # direct response without specialist
            "track": "track" if memory is not None else "respond",
        },
    )

    builder.add_conditional_edges(
        "intake", _route_after_intake, {"eligibility": facts_ready, "reroute": "reroute"}
    )
    builder.add_conditional_edges(
        "reroute",
        _route_after_reroute,
        {"eligibility": facts_ready, "document_checker": "document_checker", "respond": "respond"},
    )
    if memory is not None:
        builder.add_edge("memory_load", "eligibility")
        builder.add_edge("memory_save", "eligibility")
        builder.add_edge("memory_save_edit", "approval_end")

    # Eligibility → one intake question while a verdict is open, else Document Checker → Finish
    builder.add_conditional_edges(
        "eligibility",
        _route_after_eligibility,
        {
            "intake_question": "intake_question",
            "confirm": "confirm",
            "document_checker": "document_checker",
            "finish": "finish",
        },
    )
    builder.add_conditional_edges(
        "confirm",
        _route_after_confirm,
        {"memory_save": after_confirmed, "eligibility": "eligibility", END: END},
    )
    builder.add_edge("intake_question", END)
    
    # Document Checker → Application (if needed) → Finish
    builder.add_conditional_edges(
        "document_checker",
        _route_after_documents,
        {"application": "application", "finish": "finish"},
    )
    
    # Application → human approval of the exact form → submit (the only write)
    builder.add_conditional_edges(
        "application",
        _route_after_application,
        {"approval": "approval", "finish": "finish"},
    )
    builder.add_conditional_edges(
        "approval",
        _route_after_approval,
        {"submit": "submit", "memory_save_edit": after_edited, "approval_end": "approval_end"},
    )
    builder.add_edge("approval_end", END)
    builder.add_edge("submit", END)
    
    # Respond → END (respond node handles its own final output)
    builder.add_edge("respond", END)
    
    # Finish → END
    builder.add_edge("finish", END)
    
    return tools.budget_graph(builder.compile(checkpointer=checkpointer))
