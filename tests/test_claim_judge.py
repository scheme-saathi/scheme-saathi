import json

import pytest
from pydantic import ValidationError

from tests.evaluation import calibrate_judge, claim_judge, prepare_claim_review


def labelled_items(count=20):
    return [
        {"id": f"example-{index}", "text": f"Synthetic message {index}", "has_claim": index % 2 == 0}
        for index in range(count)
    ]


def test_calibration_set_requires_twenty_unique_synthetic_labels():
    with pytest.raises(ValidationError):
        claim_judge.CalibrationSet.model_validate({"synthetic_only": True, "items": labelled_items(19)})
    with pytest.raises(ValidationError):
        claim_judge.CalibrationSet.model_validate({"synthetic_only": False, "items": labelled_items()})
    items = labelled_items()
    items[1]["id"] = items[0]["id"]
    with pytest.raises(ValidationError):
        claim_judge.CalibrationSet.model_validate({"synthetic_only": True, "items": items})
    items = labelled_items()
    items[0]["has_claim"] = "true"
    with pytest.raises(ValidationError):
        claim_judge.CalibrationSet.model_validate({"synthetic_only": True, "items": items})


def test_judge_requires_an_explicit_different_provider_for_each_agent():
    claim_judge.validate_models("anthropic/example", ["openai/one", "google/two"])
    for judge, agents in [
        ("openai/other", ["openai/one"]),
        ("example", ["openai/one"]),
        ("anthropic/example", ["one"]),
        ("anthropic/example", []),
    ]:
        with pytest.raises(ValueError):
            claim_judge.validate_models(judge, agents)


def test_cohens_kappa_and_degenerate_case():
    result = claim_judge.agreement([(True, True), (True, False), (False, True), (False, False)])
    assert result["count"] == 4
    assert result["observed_agreement"] == 0.5
    assert result["cohens_kappa"] == 0
    assert claim_judge.agreement([(True, True)] * 20)["cohens_kappa"] is None
    assert claim_judge.agreement([])["observed_agreement"] is None


def test_calibration_reports_failed_calls_without_exposing_text_or_error_message():
    items = claim_judge.CalibrationSet.model_validate(
        {"synthetic_only": True, "items": labelled_items()}
    ).items
    seen = []

    def decide(text):
        seen.append(text)
        if text.endswith("3"):
            raise RuntimeError("provider message with sensitive details")
        return claim_judge.ClaimDecision(has_claim=True, reason="synthetic")

    result = claim_judge.calibrate(items, decide)
    assert seen == [item.text for item in items]
    assert result["complete"] is False
    assert result["errors"] == 2
    assert result["agreement"]["count"] == 18
    assert "sensitive details" not in json.dumps(result)
    assert "Synthetic message" not in json.dumps(result)


def test_judge_receives_only_message_not_human_label(monkeypatch):
    received = []

    class FakeAgent:
        def __init__(self, _model, _input, _output, instructions):
            assert "untrusted" in instructions
            assert "Do not decide eligibility" in instructions

        def invoke(self, value):
            received.append(value.model_dump())
            return claim_judge.ClaimDecision(has_claim=False, reason="A question.")

    monkeypatch.setattr(claim_judge, "StructuredGPTAgent", FakeAgent)
    assert claim_judge.ClaimJudge(object()).judge("Can I apply?").has_claim is False
    assert received == [{"text": "Can I apply?"}]


def test_cli_saves_complete_report_without_raw_messages(tmp_path, monkeypatch):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"synthetic_only": True, "items": labelled_items()}))
    output = tmp_path / "reports" / "report.json"
    monkeypatch.setenv("JUDGE_MODEL", "anthropic/example")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.setattr(calibrate_judge, "ChatOpenAI", lambda **kwargs: object())

    class FakeJudge:
        def __init__(self, _model):
            pass

        def judge(self, text):
            return claim_judge.ClaimDecision(has_claim=int(text.split()[-1]) % 2 == 0, reason="ok")

    monkeypatch.setattr(calibrate_judge, "ClaimJudge", FakeJudge)
    args = ["--labels", str(labels), "--agent-model", "openai/example", "--output", str(output)]
    assert calibrate_judge.main(args) == 0
    result = json.loads(output.read_text())
    assert result["complete"]
    assert result["agreement"]["count"] == 20
    assert result["agreement"]["cohens_kappa"] == 1
    assert result["estimated_cost_usd"] is None
    assert len(result["labels_sha256"]) == 64
    assert len(result["prompt_sha256"]) == 64
    assert "Synthetic message" not in output.read_text()
    with pytest.raises(FileExistsError):
        calibrate_judge.main(args)


def test_prepare_review_uses_development_agent_messages_and_leaves_labels_empty(tmp_path):
    def make_run(name, split, texts):
        run = tmp_path / name
        run.mkdir()
        (run / "summary.json").write_text(json.dumps({"split": split}))
        row = {"case_id": "F01", "error": None, "result": {"transcript": [
            {"role": "citizen", "text": "Question"},
            *[{"role": "agent", "text": text} for text in texts],
        ]}}
        (run / "cases.jsonl").write_text(json.dumps(row) + "\n")
        return run

    one = make_run("one", "development", [f"first {i}" for i in range(12)])
    two = make_run("two", "development", [f"second {i}" for i in range(12)])
    result = prepare_claim_review.prepare([one, two], 20)
    assert len(result["items"]) == 20
    assert result["items"][0]["text"] == "first 0"
    assert result["items"][1]["text"] == "second 0"
    assert all(item["has_claim"] is None for item in result["items"])
    assert len({item["id"] for item in result["items"]}) == 20
    heldout = make_run("heldout", "held_out", ["text"] * 20)
    with pytest.raises(ValueError, match="only development"):
        prepare_claim_review.prepare([heldout], 20)
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_claim_review.prepare([one, one], 20)


def test_classification_preserves_errors_without_text():
    items = [
        claim_judge.ReviewItem(id="one", text="Yes"),
        claim_judge.ReviewItem(id="two", text="Private example"),
    ]

    def decide(text):
        if text == "Private example":
            raise RuntimeError("details")
        return claim_judge.ClaimDecision(has_claim=True, reason="assertion")

    result = claim_judge.judge_messages(items, decide)
    assert result["messages"] == 2
    assert result["claims_detected"] == 1
    assert result["errors"] == 1
    assert result["items"][1] == {"id": "two", "error_type": "RuntimeError"}
    assert "Private example" not in json.dumps(result)


def test_classification_cli_requires_explicit_review_and_accepts_unlabelled_items(tmp_path, monkeypatch):
    labels = tmp_path / "input.json"
    labels.write_text(json.dumps({"synthetic_only": True, "items": [
        {"id": "one", "text": "I cannot tell", "has_claim": None},
    ]}))
    output = tmp_path / "result.json"
    monkeypatch.setenv("JUDGE_MODEL", "anthropic/example")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.setattr(calibrate_judge, "ChatOpenAI", lambda **kwargs: object())

    class FakeJudge:
        def __init__(self, _model):
            pass

        def judge(self, text):
            return claim_judge.ClaimDecision(has_claim=False, reason="unknown")

    monkeypatch.setattr(calibrate_judge, "ClaimJudge", FakeJudge)
    args = ["--classify", str(labels), "--agent-model", "openai/example", "--output", str(output)]
    with pytest.raises(SystemExit):
        calibrate_judge.main(args)
    assert calibrate_judge.main(args + ["--confirm-synthetic"]) == 0
    result = json.loads(output.read_text())
    assert result["mode"] == "classification"
    assert result["items"] == [{"id": "one", "has_claim": False}]
    assert "I cannot tell" not in output.read_text()
