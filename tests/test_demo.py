from graph.run import main


def test_demo_pauses_then_submits(capsys):
    main()
    out = capsys.readouterr().out
    assert "Application approval:" in out
    assert "submitted (mock)" in out
