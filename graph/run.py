import argparse
import json
import sys
from pathlib import Path

from langgraph.types import Command

from graph.workflow import build_graph, sqlite_checkpointer

CITIZEN = {"age": 62, "is_widow": True, "income": 250000}
DEFAULT_DB = Path("data/checkpoints.sqlite3")


def print_verdicts(state) -> None:
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
    if not final.get("submission"):
        print("\nApplication was not approved; nothing was submitted.")
        return
    print("\nMock submission:")
    print(f"  Status: {final['submission']['status']}")
    print(f"  Scheme: {final['submission']['scheme_id']}")


def initial_input(citizen: dict, scheme_ids: list[str] | None) -> dict:
    return {"simulated_citizen": citizen, **({"scheme_ids": scheme_ids} if scheme_ids else {})}


def run_demo(citizen: dict, scheme_ids: list[str] | None) -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "demo-1"}}
    state = graph.invoke(initial_input(citizen, scheme_ids), config)
    print_verdicts(state)
    if "__interrupt__" not in state:
        print("\nNo application to approve.")
        return
    print_approval(state)
    print_submission(graph.invoke(Command(resume={"approved": True}), config))


def run_start(db: Path, thread_id: str, citizen: dict, scheme_ids: list[str] | None) -> int:
    with sqlite_checkpointer(db) as saver:
        graph = build_graph(saver)
        config = {"configurable": {"thread_id": thread_id}}
        if graph.get_state(config).values:
            print(f"Thread '{thread_id}' already exists in {db}; choose another --thread-id.", file=sys.stderr)
            return 1
        state = graph.invoke(initial_input(citizen, scheme_ids), config)
        print_verdicts(state)
        if "__interrupt__" not in state:
            print("\nNo application to approve.")
            return 0
        print_approval(state)
        print(f"\nPaused and saved to {db} (thread '{thread_id}'). Resume later with: "
              f"python -m graph.run --phase resume --db {db} --thread-id {thread_id} --decision approve")
    return 0


def run_resume(db: Path, thread_id: str, decision: str) -> int:
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
        print_submission(graph.invoke(Command(resume={"approved": decision == "approve"}), config))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scheme Saathi workflow demo.")
    parser.add_argument("--phase", choices=["start", "resume"],
                        help="Persistent mode: 'start' pauses at approval and exits; 'resume' continues in a new process.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--thread-id", default="demo-1")
    parser.add_argument("--scheme-id", action="append", dest="scheme_ids",
                        help="Evaluate this scheme (repeatable). Default: every scheme with fully reviewed rules.")
    parser.add_argument("--citizen", help="Simulated citizen profile as a JSON object. Default: a sample widow.")
    parser.add_argument("--decision", choices=["approve", "reject"], default="approve")
    args = parser.parse_args([] if argv is None else argv)
    try:
        citizen = json.loads(args.citizen) if args.citizen else CITIZEN
        if not isinstance(citizen, dict):
            raise ValueError("--citizen must be a JSON object")
        if args.phase != "resume" and args.scheme_ids:
            from graph.mock_tools import search_schemes
            search_schemes({}, args.scheme_ids)
    except ValueError as error:
        parser.error(str(error))
    if args.phase == "start":
        return run_start(args.db, args.thread_id, citizen, args.scheme_ids)
    if args.phase == "resume":
        return run_resume(args.db, args.thread_id, args.decision)
    run_demo(citizen, args.scheme_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
