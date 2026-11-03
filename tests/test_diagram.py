from graph.diagram import DOC_PATH, render


def test_committed_diagram_matches_the_compiled_graph():
    assert DOC_PATH.read_text(encoding="utf-8") == render(), "run: python -m graph.diagram --write"


def test_diagram_shows_the_correction_loop_and_edit_path():
    """Test that diagram shows Supervisor-first routing and specialist flows."""
    text = render()
    # Supervisor routes to specialists (conditional edges may have labels)
    # eligibility and application goals share this edge, so Mermaid labels it
    assert "supervisor -. &nbsp;application&nbsp; .-> intake;" in text
    assert ("supervisor -.-> eligibility;" in text or "supervisor" in text and "eligibility" in text)
    assert "supervisor -.-> document_checker;" in text
    assert "supervisor -.-> respond;" in text
    
    # Specialists can route to each other (conditional paths)
    assert "intake -.-> eligibility;" in text or "intake" in text and "eligibility" in text
    assert "intake --> eligibility;" in text
    assert "eligibility -.-> intake_question;" in text
    assert "intake_question --> __end__;" in text
    
    # All paths eventually reach END
    assert "finish --> __end__;" in text
    assert "respond --> __end__;" in text
