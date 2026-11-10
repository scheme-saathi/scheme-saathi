import json
from unittest.mock import Mock

import pytest

from agents.supervisor import UnifiedRouter


@pytest.mark.parametrize(
    ("router_model", "supervisor_model", "expected"),
    [("custom/router", "custom/supervisor", "custom/router"), (" ", "custom/supervisor", "custom/supervisor")],
)
def test_classifier_uses_configured_model(monkeypatch, router_model, supervisor_model, expected):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_MODEL", router_model)
    monkeypatch.setenv("SUPERVISOR_MODEL", supervisor_model)
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": json.dumps({"intent": "documents", "language": "en"})}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr("agents.supervisor.requests.post", post)

    assert UnifiedRouter().classify("What documents do I need?") == {"intent": "documents", "language": "en"}
    assert post.call_args.kwargs["json"]["model"] == expected


@pytest.mark.parametrize(("key", "model"), [("", "custom/model"), ("test-key", "")])
def test_classifier_without_key_or_model_uses_local_fallback(monkeypatch, key, model):
    monkeypatch.setenv("OPENROUTER_API_KEY", key)
    monkeypatch.setenv("ROUTER_MODEL", "")
    monkeypatch.setenv("SUPERVISOR_MODEL", model)
    post = Mock()
    monkeypatch.setattr("agents.supervisor.requests.post", post)

    assert UnifiedRouter().classify("What documents do I need?")["intent"] == "documents"
    post.assert_not_called()
