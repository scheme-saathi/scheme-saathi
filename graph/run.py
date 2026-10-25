from langgraph.types import Command

from graph.workflow import build_graph

CITIZEN = {"age": 62, "is_widow": True, "income": 250000}


def main() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "demo-1"}}
    state = graph.invoke({"simulated_citizen": CITIZEN}, config)
    print("paused for approval:", state["__interrupt__"][0].value)
    final = graph.invoke(Command(resume={"approved": True}), config)
    print("submission:", final["submission"])


if __name__ == "__main__":
    main()
