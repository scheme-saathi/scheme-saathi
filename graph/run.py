from langgraph.types import Command

from graph.workflow import build_graph

CITIZEN = {"age": 62, "is_widow": True, "income": 250000}


def main() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "demo-1"}}
    state = graph.invoke({"simulated_citizen": CITIZEN}, config)
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

    print("\nApplication approval:")
    print(state["__interrupt__"][0].value)
    final = graph.invoke(Command(resume={"approved": True}), config)
    print("\nMock submission:")
    print(f"  Status: {final['submission']['status']}")
    print(f"  Scheme: {final['submission']['scheme_id']}")


if __name__ == "__main__":
    main()
