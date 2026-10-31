"""LangGraph-based orchestrator for Scheme Saathi workflow.

This is the main supervisor/planner that coordinates:
- State management with typed WorkflowState
- Agent routing (Intake -> Eligibility -> Documents -> Application)
- Memory authorization and consent
- Resumption from checkpoints
"""

from typing import Optional
from datetime import datetime
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import StateGraph, START, END

from agents.contracts import IntakeResult, SupervisorPlan
from agents.intake import IntakeAgent
from agents.eligibility import EligibilityAgent
from agents.document_checker import DocumentCheckerAgent
from agents.application import ApplicationAgent
from agents.supervisor import SupervisorAgent
from agents.memory import MemoryService
from agents.persona_validator import PersonaValidator, MemoryAccessValidator
from graph.state import WorkflowState, HouseholdScope


class SchemeStathiOrchestrator:
    """Main orchestrator for the Scheme Saathi workflow.
    
    Responsibilities:
    - Coordinate specialist agents (Intake, Eligibility, Documents, Application)
    - Manage typed workflow state
    - Enforce memory access control
    - Handle resumption from checkpoints
    - Apply output guardrails
    """

    def __init__(
        self,
        supervisor_model: BaseChatModel,
        specialist_model: BaseChatModel,
        memory_service: MemoryService,
    ):
        """Initialize orchestrator with models and memory service.
        
        Args:
            supervisor_model: GPT model for routing decisions
            specialist_model: GPT model for specialist agents
            memory_service: Memory service enforcing consent/allowlist
        """
        self.supervisor_model = supervisor_model
        self.specialist_model = specialist_model
        self.memory_service = memory_service

        # Initialize agents
        self.supervisor = SupervisorAgent(supervisor_model)
        self.intake = IntakeAgent(specialist_model)
        self.eligibility = EligibilityAgent(specialist_model)
        self.document_checker = DocumentCheckerAgent(specialist_model)
        self.application = ApplicationAgent(specialist_model)

        # Build the LangGraph workflow
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine.
        
        Structure:
        START -> intake -> route -> eligibility -> documents -> application -> respond -> END
        """
        graph = StateGraph(WorkflowState)

        # Nodes
        graph.add_node("intake", self._intake_node)
        graph.add_node("route", self._route_node)
        graph.add_node("eligibility", self._eligibility_node)
        graph.add_node("documents", self._documents_node)
        graph.add_node("application", self._application_node)
        graph.add_node("respond", self._respond_node)

        # Edges
        graph.add_edge(START, "intake")
        graph.add_edge("intake", "route")

        # Conditional routing from supervisor
        graph.add_conditional_edges(
            "route",
            self._route_decision,
            {
                "eligibility": "eligibility",
                "documents": "documents",
                "application": "application",
                "respond": "respond",
                "error": "respond",
            },
        )

        # Linear progression when agents return
        graph.add_edge("eligibility", "route")
        graph.add_edge("documents", "route")
        graph.add_edge("application", "route")
        graph.add_edge("respond", END)

        return graph

    def _intake_node(self, state: WorkflowState) -> dict:
        """Intake phase: gather minimum information needed."""
        # Validate scope is authorized
        scope = state.get("household_scope", {})
        MemoryAccessValidator.validate_scope_isolation(
            scope.get("actor_id", ""),
            scope.get("household_id", ""),
        )

        try:
            # Invoke intake agent
            intake_input = {
                "request": state["user_request"],
                "known_facts": self.memory_service.read_facts(
                    scope, []  # Fetch all allowed facts initially
                ),
            }

            result: IntakeResult = self.intake.invoke(intake_input)

            # Validate intake response
            PersonaValidator.validate_intake_facts(result.candidate_facts)

            # Update state
            return {
                "language": result.language,
                "intent": result.intent,
                "candidate_facts": result.candidate_facts,
                "pending_clarifications": result.clarifying_questions,
                "current_step": "intake",
                "next_action": "route",
            }

        except Exception as e:
            return {
                "error_message": f"Intake error: {str(e)}",
                "next_action": "error",
                "current_step": "intake",
            }

    def _route_node(self, state: WorkflowState) -> dict:
        """Route to next appropriate agent."""
        # Build supervisor input
        supervisor_input = {
            "request": state["user_request"],
            "intake": {
                "language": state.get("language", "unknown"),
                "intent": state.get("intent", "other"),
                "candidate_facts": state.get("candidate_facts", []),
                "clarifying_questions": state.get("pending_clarifications", []),
            },
            "selected_scheme_id": state.get("selected_scheme_id"),
        }

        try:
            # Get supervisor routing decision
            plan: SupervisorPlan = self.supervisor.invoke(supervisor_input)

            # Validate supervisor doesn't make decisions
            PersonaValidator.validate_supervisor_response(plan)

            return {
                "next_action": plan.next_agent,
                "current_step": "route",
            }

        except Exception as e:
            return {
                "error_message": f"Routing error: {str(e)}",
                "next_action": "error",
            }

    def _route_decision(self, state: WorkflowState) -> str:
        """Determine next node based on supervisor decision."""
        return state.get("next_action", "respond")

    def _eligibility_node(self, state: WorkflowState) -> dict:
        """Eligibility phase: evaluate against scheme rules."""
        try:
            # TODO: Fetch scheme from knowledge base
            # TODO: Evaluate against rule engine
            # TODO: Return verdict with citations

            # Placeholder for eligibility logic
            return {
                "eligibility_verdict": "cannot_tell",
                "missing_fields_for_verdict": state.get("pending_clarifications", []),
                "current_step": "eligibility",
                "next_action": "route",
            }

        except Exception as e:
            return {
                "error_message": f"Eligibility error: {str(e)}",
                "next_action": "error",
                "current_step": "eligibility",
            }

    def _documents_node(self, state: WorkflowState) -> dict:
        """Document phase: check completeness against requirements."""
        try:
            # TODO: Fetch document requirements from scheme
            # TODO: Process uploaded documents
            # TODO: Compare and identify gaps

            # Placeholder
            return {
                "document_check_result": {},
                "current_step": "documents",
                "next_action": "route",
            }

        except Exception as e:
            return {
                "error_message": f"Document check error: {str(e)}",
                "next_action": "error",
                "current_step": "documents",
            }

    def _application_node(self, state: WorkflowState) -> dict:
        """Application phase: prepare and submit application."""
        try:
            # TODO: Map facts to form fields
            # TODO: Identify missing required fields
            # TODO: Prepare draft for user approval
            # TODO: Require explicit approval before submission

            # Placeholder
            return {
                "application_draft": None,
                "current_step": "application",
                "next_action": "respond",
            }

        except Exception as e:
            return {
                "error_message": f"Application error: {str(e)}",
                "next_action": "error",
                "current_step": "application",
            }

    def _respond_node(self, state: WorkflowState) -> dict:
        """Final response to user."""
        # Prepare response based on current step and any errors
        error = state.get("error_message")
        if error:
            return {
                "next_action": "end",
                "current_step": "complete",
            }

        # TODO: Format appropriate response based on workflow state
        return {
            "next_action": "end",
            "current_step": "complete",
        }

    def run(
        self,
        user_request: str,
        household_scope: HouseholdScope,
        thread_id: Optional[str] = None,
    ) -> dict:
        """Execute workflow for a user request.
        
        Args:
            user_request: User's input message
            household_scope: Authorization context (actor_id, household_id, role)
            thread_id: Optional resumable thread ID
            
        Returns:
            Final workflow result
        """
        # TODO: Load checkpoint if resuming
        if thread_id:
            # Load from checkpointer
            pass

        # Initialize state
        initial_state: WorkflowState = {
            "user_request": user_request,
            "household_scope": household_scope,
            "conversation_history": [(household_scope.get("actor_role", "user"), user_request)],
            "current_step": "intake",
            "language": "unknown",
            "intent": "other",
            "candidate_facts": [],
            "confirmed_facts": {},
            "pending_clarifications": [],
            "next_action": "continue",
            "checkpoint_id": thread_id or str(uuid4()),
            "last_checkpoint_at": datetime.now(),
        }

        # Compile and execute graph
        compiled_graph = self.graph.compile()
        result = compiled_graph.invoke(initial_state)

        # TODO: Save checkpoint
        # TODO: Apply output guardrails

        return result


# Example usage
if __name__ == "__main__":
    from agents.model_factory import create_chat_model

    # Create models
    supervisor_model = create_chat_model("supervisor")
    specialist_model = create_chat_model("specialist")

    # Create memory service
    from agents.memory_service import InMemoryMemoryService, HouseholdAllowlist

    allowlist = HouseholdAllowlist(
        allowed_fields={
            "state_code": {
                "type": "string",
                "purpose": "Filter schemes by state",
            },
            "district_code": {"type": "string", "purpose": "District filtering"},
            "household_size": {"type": "integer", "purpose": "Household size rules"},
        }
    )
    memory_service = InMemoryMemoryService(allowlist)

    # Create orchestrator
    orchestrator = SchemeStathiOrchestrator(
        supervisor_model, specialist_model, memory_service
    )

    # Run workflow
    scope = HouseholdScope(
        actor_id="user123",
        household_id="hh456",
        actor_role="citizen",
        authenticated_at=datetime.now(),
        expires_at=datetime.now().replace(hour=datetime.now().hour + 1),
    )

    result = orchestrator.run(
        user_request="Can I apply for a scholarship?",
        household_scope=scope,
    )

    print("Workflow result:", result)
