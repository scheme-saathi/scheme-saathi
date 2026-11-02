from graph.diagram import DOC_PATH, render


def test_committed_diagram_matches_the_compiled_graph():
    assert DOC_PATH.read_text(encoding="utf-8") == render(), "run: python -m graph.diagram --write"


def test_diagram_shows_the_correction_loop_and_edit_path():
    text = render()
    assert "validate -.-> draft;" in text and "validate -.-> escalate;" in text
    assert "approval -.-> eligibility;" in text
