"""GPT agent orchestration skeleton, separate from the deterministic demo graph."""

from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.application import ApplicationAgent
from agents.contracts import (
    ApplicationInput,
    DocumentCheckInput,
    EligibilityInput,
    FactMap,
    IntakeAskInput,
    IntakeExtractInput,
    Language,
    SupervisorInput,
)
from agents.document_checker import DocumentCheckerAgent
from agents.eligibility import EligibilityAgent
from agents.intake import IntakeAgent, income_period
from agents.model_factory import create_chat_model
from agents.supervisor import SupervisorAgent
from graph import tools
from graph.tools import evaluate_scheme
from graph.workflow import application_hash
from servers.rule_engine.rules import Evaluation


MAX_QUESTIONS = 8  # per intake, so a long tail of open schemes can't turn into an interview
MAX_ATTEMPTS_PER_FIELD = 2  # a field asked twice without a usable answer counts as "don't know"
PROFILE_GOALS = {"intake", "eligibility", "application"}


def merge_facts(old: FactMap | None, new: FactMap | None) -> FactMap:
    """Each turn adds to the facts from earlier turns; a newer value for a field wins."""
    return {**(old or {}), **(new or {})}


class AgentWorkflowState(TypedDict, total=False):
    request: str
    actor_id: str
    intent: str
    validation_errors: list[str]
    known_facts: Annotated[FactMap, merge_facts]
    confirmed_facts: Annotated[FactMap, merge_facts]
    selected_scheme_id: str
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
    intake_stopped: str | None  # "dont_know", "no_answer" or "question_cap"
    reply_unanswered: bool  # the reply to a question held no facts at all
    confirm_status: str  # "confirmed", "edit_rejected", "rejected" or "invalid"
    rejected_edits: list[str]  # edited fields that were unknown or the wrong type
    explanations: dict[str, str]  # candidate scheme -> cited explanation, once facts are confirmed
    verdicts: dict[str, dict[str, Any]]  # candidate scheme -> rule-engine evaluation
    eligibility: dict[str, Any]
    document_check: dict[str, Any]
    application_draft: dict[str, Any]
    approval_status: str
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
    update["plan"] = plan.model_dump(mode="json")
    if plan.language != "unknown":
        update["language"] = plan.language
    elif validation is not None:
        update["language"] = validation.language
    if validation is not None:
        update["intent"] = validation.intent
    return update


def _guard_output(
    agents: AgentSet, state: AgentWorkflowState, update: dict[str, str], agent_name: str
) -> dict[str, str]:
    """Supervisor output check: nothing leaves the graph unless it passes."""
    language = state.get("language", "unknown")
    result = agents.supervisor.validate_output(update["response"], agent_name, language)
    if result.passed:
        return update
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
    """The selected scheme, or every scheme whose rules are fully reviewed."""
    scheme_id = state.get("selected_scheme_id")
    return [scheme_id] if scheme_id else tools.search_schemes({})


def _facts_so_far(state: AgentWorkflowState) -> FactMap:
    """Confirmed facts, overridden by anything said since: known_facts holds the latest values."""
    return {**state.get("confirmed_facts", {}), **state.get("known_facts", {})}


def _unconfirmed(state: AgentWorkflowState) -> FactMap:
    confirmed = state.get("confirmed_facts", {})
    return {f: v for f, v in state.get("known_facts", {}).items() if f not in confirmed or confirmed[f] != v}


def _intake_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, Any]:
    """Read typed facts from the message into known_facts. They stay unconfirmed."""
    specs = tools.field_specs(_candidate_schemes(state))
    if not specs:  # no reviewed rule fields, so nothing the profile could hold
        return {"pending_field": None}
    pending = state.get("pending_field")
    result = agents.intake.extract(
        IntakeExtractInput(
            request=state["request"],
            pending_field=pending,
            pending_question=state.get("pending_question") if pending else None,
        ),
        specs,
    )
    update: dict[str, Any] = {
        "known_facts": result.facts,
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
    if result.dont_know:
        update["declined_fields"] = [*state.get("declined_fields", []), pending]
        update["intake_stopped"] = "dont_know"
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


def _stop_intake(state: AgentWorkflowState, reason: str, declined: list[str]) -> dict[str, Any]:
    open_fields = _open_fields(state)
    return {
        "intake_stopped": reason,
        "declined_fields": declined,
        "status": "intake_stopped",
        "response": "I can't finish the eligibility check without these details: "
        + ", ".join(f.replace("_", " ") for f in open_fields)
        + ". Tell me if you find out, and I'll check again.",
    }


def _intake_question_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, Any]:
    """Ask for the one field that settles the most open verdicts, then wait for the reply.

    Stops instead when that field has had its attempts or the question cap is reached.
    """
    declined = state.get("declined_fields", [])
    if state.get("intake_stopped"):
        return _stop_intake(state, state["intake_stopped"], declined)
    field = tools.next_question(state["verdicts"], declined)
    attempts = state.get("question_attempts", {})
    if attempts.get(field, 0) >= MAX_ATTEMPTS_PER_FIELD:
        return _stop_intake(state, "no_answer", [*declined, field])
    if state.get("questions_asked", 0) >= MAX_QUESTIONS:
        return _stop_intake(state, "question_cap", declined)
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

    try:
        return evaluate_scheme(facts, scheme_id)
    except Exception:
        return {
            "verdict": "cant_tell",
            "reason": "The deterministic rule engine could not evaluate this scheme with the current facts.",
            "missing_fields": [],
            "unresolved_fields": [],
            "conditions": [],
            "citations": [],
        }


def _eligibility_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    """Evaluate every candidate scheme on the facts so far, then explain the selected one.

    While some facts are unconfirmed the verdicts only steer intake's questions; once all are
    confirmed they are final and, without a selected scheme, each gets a cited explanation.
    """
    verdicts = {s: evaluate_scheme(_facts_so_far(state), s) for s in _candidate_schemes(state)}
    explanations = {}
    if not state.get("selected_scheme_id") and not _unconfirmed(state):
        explanations = {
            s: agents.eligibility.invoke(EligibilityInput(scheme_id=s, evaluation=v)).explanation
            for s, v in verdicts.items()
        }
    return {"verdicts": verdicts, "explanations": explanations, **_selected_scheme_eligibility(agents, state)}


def _selected_scheme_eligibility(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    scheme_id = state.get("selected_scheme_id")
    raw_evaluation = state.get("deterministic_evaluation")
    facts = state.get("confirmed_facts") or {}

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
            "explanation": narrative.explanation,
            "clarifying_questions": narrative.clarifying_questions,
        },
    }


def _route_after_eligibility(state: AgentWorkflowState) -> str:
    # Still open: ask the next question, or, once intake has stopped, say what is missing.
    if _open_fields(state) and (
        state.get("intake_stopped") or tools.next_question(state["verdicts"], state.get("declined_fields", []))
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
    # Confirmed or edited facts are evaluated again: an edit can reopen a verdict.
    return "eligibility" if state["confirm_status"] in {"confirmed", "edit_rejected"} else END


def _document_checker_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    result = agents.document_checker.invoke(
        DocumentCheckInput(
            scheme_id=state["selected_scheme_id"],
            required_documents=state.get("required_documents", []),
            available_documents=state.get("available_documents", []),
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
            portal_draft = tools.create_portal_draft(form)
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
            "options": ["approve", "edit", "reject"],
        }
    )
    action = decision.get("action") if isinstance(decision, dict) else None
    if action == "approve":
        if decision.get("payload_hash") == current:
            return {"approval_status": "approved", "approved_hash": current}
        return {"approval_status": "invalid", "approved_hash": ""}
    if action == "edit" and isinstance(decision.get("changes"), dict):
        facts = {**state.get("confirmed_facts", {}), **decision["changes"]}
        return {
            "confirmed_facts": facts,
            "approval_status": "edited",
            "approved_hash": "",
            "status": "draft_edited",
            "response": "Facts were edited. Prepare a new draft to review again.",
        }
    return {
        "approval_status": "rejected" if action == "reject" else "invalid",
        "approved_hash": "",
    }


def _route_after_approval(state: AgentWorkflowState) -> str:
    return "submit" if state["approval_status"] == "approved" else "approval_end"


def _approval_end_node(state: AgentWorkflowState) -> dict[str, str]:
    status = state["approval_status"]
    if status == "edited":
        return {}
    messages = {
        "rejected": "The draft was rejected. Nothing was submitted.",
        "invalid": "The approval did not match this exact form. Nothing was submitted.",
    }
    return {"status": f"approval_{status}", "response": messages[status]}


def _submit_node(state: AgentWorkflowState) -> dict[str, Any]:
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
        submission = tools.submit_application(form, application_id=portal_draft["application_id"])
    return {
        "submission": submission,
        "status": "submitted",
        "response": f"Application submitted (mock). Reference: {submission['application_id']}",
    }


def _respond_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, str]:
    if state.get("validation_errors"):
        return {"status": "validation_error", "response": " ".join(state["validation_errors"])}
    return _guard_output(
        agents, state, {"status": "responded", "response": state["plan"]["reason"]}, "supervisor"
    )


def _finish_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, str]:
    update = _finish_update(state)
    if state.get("application_draft") is not None:
        agent_name = "application"
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
        missing = state["document_check"]["missing_documents"]
        response = (
            "Missing documents: " + ", ".join(missing)
            if missing
            else "Document checklist complete; authenticity is not verified."
        )
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
    """
    runtime = agents or AgentSet.from_environment()
    builder = StateGraph(AgentWorkflowState)
    
    # Add all nodes
    builder.add_node("supervisor", lambda state: _supervisor_node(runtime, state))
    builder.add_node("intake", lambda state: _intake_node(runtime, state))
    builder.add_node("intake_question", lambda state: _intake_question_node(runtime, state))
    builder.add_node("reroute", lambda state: _supervisor_node(runtime, state, validate=False))
    builder.add_node("confirm", _confirm_node)
    builder.add_node("eligibility", lambda state: _eligibility_node(runtime, state))
    builder.add_node(
        "document_checker", lambda state: _document_checker_node(runtime, state)
    )
    builder.add_node("application", lambda state: _application_node(runtime, state))
    builder.add_node("approval", _approval_node)
    builder.add_node("approval_end", _approval_end_node)
    builder.add_node("submit", _submit_node)
    builder.add_node("finish", lambda state: _finish_node(runtime, state))
    builder.add_node("respond", lambda state: _respond_node(runtime, state))
    
    # Entry point: Supervisor ALWAYS first
    builder.add_edge(START, "supervisor")
    
    # After Supervisor routes to: intake, eligibility, document_checker, application, or finish
    builder.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "intake": "intake",
            "eligibility": "intake",  # facts in the message come first
            "document_checker": "document_checker",
            "application": "intake",
            "respond": "respond",  # direct response without specialist
        },
    )

    builder.add_conditional_edges(
        "intake", _route_after_intake, {"eligibility": "eligibility", "reroute": "reroute"}
    )
    builder.add_conditional_edges(
        "reroute",
        _route_after_reroute,
        {"eligibility": "eligibility", "document_checker": "document_checker", "respond": "respond"},
    )

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
    builder.add_conditional_edges("confirm", _route_after_confirm, {"eligibility": "eligibility", END: END})
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
        {"submit": "submit", "approval_end": "approval_end"},
    )
    builder.add_edge("approval_end", END)
    builder.add_edge("submit", END)
    
    # Respond → END (respond node handles its own final output)
    builder.add_edge("respond", END)
    
    # Finish → END
    builder.add_edge("finish", END)
    
    return builder.compile(checkpointer=checkpointer)
