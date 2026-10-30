import argparse
import json
import sys
from pathlib import Path

from langgraph.types import Command

from graph.persona import load_persona_profile
from graph.workflow import build_graph, sqlite_checkpointer

CITIZEN = {"age": 62, "is_widow": True, "income": 250000}
DEFAULT_DB = Path("data/checkpoints.sqlite3")


PREVIEW_BANNER = ("DRAFT PREVIEW: these verdicts use unreviewed draft rules. They are for rule authors only, "
                  "are not eligibility advice, and no application is drafted or submitted.")


def print_verdicts(state) -> None:
    if state.get("include_draft"):
        print(PREVIEW_BANNER + "\n")
    print("Eligibility results:")
    for scheme_id, result in state["verdicts"].items():
        print(f"\n  Scheme: {scheme_id}")
        print(f"  Verdict: {result['verdict'].replace('_', ' ').title()}")
        print(f"  Reason: {result['reason']}")
        if result["missing_fields"]:
            print(f"  Missing facts: {', '.join(result['missing_fields'])}")
        if result["unresolved_fields"]:
            print(f"  Unresolved facts: {', '.join(result['unresolved_fields'])}")
        print("  Conditions:")
        for condition in result["conditions"]:
            status = condition["outcome"].upper()
            print(
                f"    - {condition['field']} {condition['op']} "
                f"(clause {condition['clause_id']}): {status}"
            )
        if result["citations"]:
            print("  Evidence:")
            for citation in result["citations"]:
                print(f"    - [{citation['clause_id']}] {citation['text']}")


def print_approval(state) -> None:
    print("\nApplication approval:")
    print(state["__interrupt__"][0].value)


def print_submission(final) -> None:
    if final.get("needs_human"):
        print("\nNo valid application could be drafted; sent to a person for review.")
        for problem in final.get("critique", []):
            print(f"  - {problem}")
        return
    if final.get("approval_status") == "invalid":
        print("\nThe approval did not match the current application; nothing was submitted.")
        return
    if not final.get("submission"):
        print("\nApplication was not approved; nothing was submitted.")
        return
    print("\nMock submission:")
    print(f"  Status: {final['submission']['status']}")
    print(f"  Scheme: {final['submission']['scheme_id']}")


def pending_hash(graph, config) -> str:
    return graph.get_state(config).tasks[0].interrupts[0].value["payload_hash"]


def decision_payload(graph, config, decision: str, changes: dict | None, payload_hash: str | None) -> dict:
    if decision == "approve":
        return {"action": "approve", "payload_hash": payload_hash or pending_hash(graph, config)}
    if decision == "edit":
        return {"action": "edit", "changes": changes or {}}
    return {"action": "reject"}


def finish(graph, config, result, decision: str) -> None:
    if "__interrupt__" in result:
        print("\nThe edited application needs a new approval:" if decision == "edit" else "\nStill waiting for approval:")
        print_approval(result)
    else:
        print_submission(result)


def initial_input(citizen: dict, scheme_ids: list[str] | None, include_draft: bool = False) -> dict:
    return {"simulated_citizen": citizen, **({"scheme_ids": scheme_ids} if scheme_ids else {}),
            **({"include_draft": True} if include_draft else {})}


def run_demo(citizen: dict, scheme_ids: list[str] | None, include_draft: bool = False) -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "demo-1"}}
    state = graph.invoke(initial_input(citizen, scheme_ids, include_draft), config)
    print_verdicts(state)
    if "__interrupt__" not in state:
        print("\nPreview only; no application drafted." if include_draft else "\nNo application to approve.")
        return
    print_approval(state)
    approval = decision_payload(graph, config, "approve", None, None)
    print_submission(graph.invoke(Command(resume=approval), config))


def run_start(db: Path, thread_id: str, citizen: dict, scheme_ids: list[str] | None, include_draft: bool = False) -> int:
    with sqlite_checkpointer(db) as saver:
        graph = build_graph(saver)
        config = {"configurable": {"thread_id": thread_id}}
        if graph.get_state(config).values:
            print(f"Thread '{thread_id}' already exists in {db}; choose another --thread-id.", file=sys.stderr)
            return 1
        state = graph.invoke(initial_input(citizen, scheme_ids, include_draft), config)
        print_verdicts(state)
        if "__interrupt__" not in state:
            print("\nPreview only; no application drafted." if include_draft else "\nNo application to approve.")
            return 0
        print_approval(state)
        print(f"\nPaused and saved to {db} (thread '{thread_id}'). Resume later with: "
              f"python -m graph.run --phase resume --db {db} --thread-id {thread_id} --decision approve")
    return 0


def run_resume(db: Path, thread_id: str, decision: str, changes: dict | None = None,
               payload_hash: str | None = None) -> int:
    if not db.exists():
        print(f"Checkpoint database not found: {db}", file=sys.stderr)
        return 1
    with sqlite_checkpointer(db) as saver:
        graph = build_graph(saver)
        config = {"configurable": {"thread_id": thread_id}}
        if "approval" not in graph.get_state(config).next:
            print(f"Thread '{thread_id}' is not waiting for approval.", file=sys.stderr)
            return 1
        print(f"Resuming thread '{thread_id}' from {db} with decision: {decision}")
        resume = decision_payload(graph, config, decision, changes, payload_hash)
        finish(graph, config, graph.invoke(Command(resume=resume), config), decision)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scheme Saathi workflow demo.")
    parser.add_argument("--phase", choices=["start", "resume"],
                        help="Persistent mode: 'start' pauses at approval and exits; 'resume' continues in a new process.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--thread-id", default="demo-1")
    parser.add_argument("--scheme-id", action="append", dest="scheme_ids",
                        help="Evaluate this scheme (repeatable). Default: every scheme with fully reviewed rules.")
    # Let the user choose one profile source: custom JSON (--citizen) or a saved example (--persona-id). argparse rejects using both; 
    # using neither keeps the default sample profile (CITIZEN).
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument("--citizen", help="Simulated citizen profile as a JSON object. Default: a sample widow.")
    profile_group.add_argument("--persona-id", help="Load a synthetic persona by ID (for example, SS001).")
    parser.add_argument("--include-draft", action="store_true",
                        help="Preview verdicts using unreviewed draft rules. For rule authors; nothing is drafted or submitted.")
    parser.add_argument("--decision", choices=["approve", "edit", "reject"], default="approve")
    parser.add_argument("--changes", help="With --decision edit: JSON object of profile fields to change.")
    parser.add_argument("--payload-hash", help="With --decision approve: hash of the form being approved "
                        "(default: the form currently waiting).")
    args = parser.parse_args([] if argv is None else argv)
    try:
        citizen = load_persona_profile(args.persona_id) if args.persona_id else (
            json.loads(args.citizen) if args.citizen else CITIZEN
        )
        if not isinstance(citizen, dict):
            raise ValueError("--citizen must be a JSON object")
        changes = json.loads(args.changes) if args.changes else None
        if args.decision == "edit" and not isinstance(changes, dict):
            raise ValueError("--decision edit requires --changes as a JSON object")
        if args.phase != "resume" and args.scheme_ids:
            from graph.mock_tools import search_schemes
            search_schemes({}, args.scheme_ids, args.include_draft)
    except ValueError as error:
        parser.error(str(error))
    if args.phase == "start":
        return run_start(args.db, args.thread_id, citizen, args.scheme_ids, args.include_draft)
    if args.phase == "resume":
        return run_resume(args.db, args.thread_id, args.decision, changes, args.payload_hash)
    run_demo(citizen, args.scheme_ids, args.include_draft)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
