"""Stage 3: model calls, with their latency, tokens, cost and errors, by role and model and per run."""

import json
from unittest.mock import Mock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from prometheus_client import generate_latest

from agents import model_factory
from agents.supervisor import UnifiedRouter
from observability import Metrics, RunRecorder, activate, record_llm_call, set_metrics
from observability.langchain_callbacks import ModelCallRecorder
from observability.llm import model_label, role_label
from observability.pricing import Price, load_prices, number, price_for

PREFIX = "scheme_saathi_"
MODEL = "vendor/model-one"
PROMPT = "Aadhaar 1234 5678 9012 private prompt text"


@pytest.fixture
def metrics():
    recording = Metrics()
    set_metrics(recording)
    activate()
    return recording


@pytest.fixture
def prices(tmp_path, monkeypatch):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"models": {MODEL: {"input": 1.0, "output": 2.0}}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PRICES_FILE", str(path))
    return path


def value(metrics, name, **labels):
    return metrics.registry.get_sample_value(PREFIX + name, labels) or 0


class FakeModel(BaseChatModel):
    input_tokens: int | None = 1000
    output_tokens: int | None = 500
    response_metadata_extra: dict = {}
    fails: bool = False

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.fails:
            raise RuntimeError(f"provider said no about {PROMPT}")
        usage = None
        if self.input_tokens is not None:
            usage = {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
            }
        message = AIMessage(
            content="a private reply", usage_metadata=usage, response_metadata=self.response_metadata_extra
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def model(role="specialist", name=MODEL, **fields):
    return FakeModel(callbacks=[ModelCallRecorder(role, name)], **fields)


def test_a_call_records_latency_tokens_and_a_table_cost(metrics, prices):
    model().invoke(PROMPT)

    labels = {"role": "specialist", "model": MODEL}
    assert value(metrics, "llm_calls_total", outcome="success", **labels) == 1
    assert value(metrics, "llm_call_duration_seconds_count", **labels) == 1
    assert value(metrics, "llm_tokens_total", direction="input", **labels) == 1000
    assert value(metrics, "llm_tokens_total", direction="output", **labels) == 500
    assert value(metrics, "llm_cost_usd_total", cost_source="table", **labels) == pytest.approx(0.002)
    assert value(metrics, "llm_unpriced_calls_total", **labels) == 0


def test_a_provider_reported_cost_wins_over_the_price_table(metrics, prices):
    model(response_metadata_extra={"token_usage": {"cost": 0.5}}).invoke(PROMPT)

    labels = {"role": "specialist", "model": MODEL}
    assert value(metrics, "llm_cost_usd_total", cost_source="provider", **labels) == pytest.approx(0.5)
    assert value(metrics, "llm_cost_usd_total", cost_source="table", **labels) == 0


def test_a_model_with_no_price_is_unpriced_not_free(metrics):
    model().invoke(PROMPT)

    labels = {"role": "specialist", "model": MODEL}
    assert value(metrics, "llm_unpriced_calls_total", **labels) == 1
    assert value(metrics, "llm_tokens_total", direction="input", **labels) == 1000
    assert value(metrics, "llm_cost_usd_total", cost_source="table", **labels) == 0
    assert value(metrics, "llm_cost_usd_total", cost_source="provider", **labels) == 0


def test_a_call_without_token_counts_is_unpriced(metrics, prices):
    model(input_tokens=None, output_tokens=None).invoke(PROMPT)

    assert value(metrics, "llm_unpriced_calls_total", role="specialist", model=MODEL) == 1


def test_a_failed_call_is_an_error_by_class_name_without_the_message(metrics, prices):
    with pytest.raises(RuntimeError):
        model(fails=True).invoke(PROMPT)

    labels = {"role": "specialist", "model": MODEL}
    assert value(metrics, "llm_calls_total", outcome="error", **labels) == 1
    assert value(metrics, "llm_errors_total", error_type="RuntimeError", **labels) == 1
    assert value(metrics, "llm_unpriced_calls_total", **labels) == 0
    assert value(metrics, "llm_call_duration_seconds_count", **labels) == 1


def test_a_run_adds_up_its_model_calls_cost_and_tokens(metrics, prices):
    with RunRecorder("chat_turn"):
        model().invoke(PROMPT)
        model(role="supervisor").invoke(PROMPT)

    assert value(metrics, "run_llm_calls_sum", kind="chat_turn") == 2
    assert value(metrics, "run_cost_usd_sum", kind="chat_turn") == pytest.approx(0.004)
    assert value(metrics, "run_tokens_total", kind="chat_turn", direction="input") == 2000
    assert value(metrics, "run_tokens_total", kind="chat_turn", direction="output") == 1000
    assert value(metrics, "runs_with_unpriced_calls_total", kind="chat_turn") == 0


def test_a_run_with_an_unpriced_call_is_flagged(metrics):
    with RunRecorder("chat_turn"):
        model().invoke(PROMPT)

    assert value(metrics, "runs_with_unpriced_calls_total", kind="chat_turn") == 1
    assert value(metrics, "run_cost_usd_sum", kind="chat_turn") == 0


def test_a_run_with_no_model_call_records_zero_calls_and_no_cost(metrics):
    with RunRecorder("chat_turn"):
        pass

    assert value(metrics, "run_llm_calls_count", kind="chat_turn") == 1
    assert value(metrics, "run_llm_calls_sum", kind="chat_turn") == 0
    assert value(metrics, "run_cost_usd_count", kind="chat_turn") == 0


def test_a_failed_call_counts_in_the_run_but_adds_no_cost(metrics, prices):
    with pytest.raises(RuntimeError):
        with RunRecorder("chat_turn"):
            model(fails=True).invoke(PROMPT)

    assert value(metrics, "run_llm_calls_sum", kind="chat_turn") == 1
    assert value(metrics, "run_cost_usd_sum", kind="chat_turn") == 0
    assert value(metrics, "runs_with_unpriced_calls_total", kind="chat_turn") == 0


def test_nothing_from_the_prompt_or_reply_reaches_the_metrics(metrics, prices):
    with pytest.raises(RuntimeError):
        model(fails=True).invoke(PROMPT)
    model().invoke(PROMPT)

    exposed = generate_latest(metrics.registry).decode()
    for text in ("1234 5678", "private", "provider said no"):
        assert text not in exposed


def test_recording_does_nothing_while_observability_is_off():
    model().invoke(PROMPT)
    with pytest.raises(RuntimeError):
        model(fails=True).invoke(PROMPT)
    record_llm_call("specialist", MODEL, 1.0, 1, 1, 1.0)


def test_a_recording_failure_never_breaks_the_model_call(metrics, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("recorder is broken")

    monkeypatch.setattr("observability.langchain_callbacks.record_llm_call", broken)

    assert model().invoke(PROMPT).content == "a private reply"
    with pytest.raises(RuntimeError, match="provider said no"):
        model(fails=True).invoke(PROMPT)


def test_untrusted_token_and_cost_values_are_ignored(metrics, prices):
    record_llm_call("specialist", MODEL, 0.1, input_tokens=-5, output_tokens="lots", provider_cost=float("nan"))
    record_llm_call("specialist", MODEL, 0.1, input_tokens=True, output_tokens=None, provider_cost=-1)

    labels = {"role": "specialist", "model": MODEL}
    assert value(metrics, "llm_tokens_total", direction="input", **labels) == 0
    assert value(metrics, "llm_unpriced_calls_total", **labels) == 2


def test_labels_are_restricted_to_plain_values():
    assert model_label("vendor/model:free@2025+x") == "vendor/model:free@2025+x"
    assert model_label('bad "model"\n{x=1}') == "badmodelx1"
    assert model_label("m" * 200) == "m" * 80
    assert model_label(None) == "unknown"
    assert model_label("") == "unknown"
    assert role_label("router") == "router"
    assert role_label("household-42") == "other"


def test_the_shipped_price_file_is_valid_and_an_unlisted_model_has_no_price():
    shipped = load_prices()

    assert shipped and all(isinstance(price, Price) for price in shipped.values())
    assert price_for("vendor/model-one") is None


def test_the_price_table_ignores_bad_entries_and_follows_file_changes(prices):
    assert price_for(MODEL) == Price(1.0, 2.0)
    assert price_for(MODEL).cost(1_000_000, 1_000_000) == pytest.approx(3.0)

    prices.write_text(
        json.dumps(
            {
                "models": {
                    "good": {"input": 3, "output": 4},
                    "negative": {"input": -1, "output": 1},
                    "text": {"input": "1", "output": 1},
                    "flag": {"input": True, "output": 1},
                    "missing": {"input": 1},
                    "not-a-dict": 7,
                }
            }
        ),
        encoding="utf-8",
    )
    # The file's modified time can match at coarse resolution, so force a change.
    import os

    stat = prices.stat()
    os.utime(prices, (stat.st_atime, stat.st_mtime + 5))

    assert load_prices() == {"good": Price(3.0, 4.0)}


@pytest.mark.parametrize("content", ["not json", "[]", '{"models": []}', '{"models": null}'])
def test_an_unreadable_price_file_means_an_empty_table(tmp_path, monkeypatch, content):
    path = tmp_path / "prices.json"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MODEL_PRICES_FILE", str(path))

    assert load_prices() == {}


def test_a_missing_price_file_means_an_empty_table(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_PRICES_FILE", str(tmp_path / "absent.json"))

    assert load_prices() == {}


def test_number_accepts_only_finite_non_negative_numbers():
    assert number(0) == 0.0
    assert number(2.5) == 2.5
    for bad in (True, False, "1", None, -1, float("nan"), float("inf")):
        assert number(bad) is None


@pytest.fixture
def factory_env(monkeypatch):
    monkeypatch.setattr(model_factory, "load_dotenv", lambda: None)
    captured = {}
    monkeypatch.setattr(model_factory, "ChatOpenAI", lambda **kwargs: captured.update(kwargs) or kwargs)
    for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SPECIALIST_MODEL", MODEL)
    monkeypatch.setenv("SUPERVISOR_MODEL", "vendor/model-two")
    return captured


def test_the_model_factory_attaches_the_recorder_with_the_role_and_model(factory_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    model_factory.create_chat_model("specialist")
    recorder = factory_env["callbacks"][0]

    assert isinstance(recorder, ModelCallRecorder)
    assert (recorder.role, recorder.model) == ("specialist", MODEL)
    assert "extra_body" not in factory_env


def test_openrouter_is_asked_for_the_call_cost_only_while_observability_is_on(factory_env, metrics, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    model_factory.create_chat_model("supervisor")

    assert factory_env["extra_body"] == {"usage": {"include": True}}
    assert factory_env["callbacks"][0].model == "vendor/model-two"


def test_openrouter_is_not_asked_for_cost_when_observability_is_off(factory_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    model_factory.create_chat_model("supervisor")

    assert "extra_body" not in factory_env


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_MODEL", MODEL)
    monkeypatch.setenv("SUPERVISOR_MODEL", "vendor/model-two")
    return UnifiedRouter()


def router_response(status=200, usage=None):
    response = Mock(status_code=status, text="denied")
    body = {"choices": [{"message": {"content": json.dumps({"intent": "documents", "language": "en"})}}]}
    if usage is not None:
        body["usage"] = usage
    response.json.return_value = body
    return response


def test_the_router_call_is_recorded_with_the_provider_reported_cost(router, metrics, monkeypatch):
    post = Mock(return_value=router_response(usage={"prompt_tokens": 40, "completion_tokens": 6, "cost": 0.0002}))
    monkeypatch.setattr("agents.supervisor.requests.post", post)

    assert router.classify("What documents do I need?")["intent"] == "documents"

    labels = {"role": "router", "model": MODEL}
    assert post.call_args.kwargs["json"]["usage"] == {"include": True}
    assert value(metrics, "llm_calls_total", outcome="success", **labels) == 1
    assert value(metrics, "llm_tokens_total", direction="input", **labels) == 40
    assert value(metrics, "llm_cost_usd_total", cost_source="provider", **labels) == pytest.approx(0.0002)


def test_the_router_request_is_unchanged_while_observability_is_off(router, monkeypatch):
    post = Mock(return_value=router_response())
    monkeypatch.setattr("agents.supervisor.requests.post", post)

    router.classify("What documents do I need?")

    assert "usage" not in post.call_args.kwargs["json"]


def test_a_router_failure_is_recorded_and_still_falls_back(router, metrics, monkeypatch):
    import requests

    monkeypatch.setattr("agents.supervisor.requests.post", Mock(side_effect=requests.exceptions.Timeout("slow")))
    assert router.classify("What documents do I need?")["intent"] == "documents"

    monkeypatch.setattr("agents.supervisor.requests.post", Mock(return_value=router_response(status=429)))
    assert router.classify("What documents do I need?")["intent"] == "documents"

    labels = {"role": "router", "model": MODEL}
    assert value(metrics, "llm_calls_total", outcome="error", **labels) == 2
    assert value(metrics, "llm_errors_total", error_type="Timeout", **labels) == 1
    assert value(metrics, "llm_errors_total", error_type="RouterHTTPError", **labels) == 1
