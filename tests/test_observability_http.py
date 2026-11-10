"""Stage 1: request metrics and the protected /metrics endpoint."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app import api
from observability import Metrics, get_metrics, install_observability, set_metrics, settings
from observability.metrics import ALLOWED_LABELS

TOKEN = "test-metrics-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("METRICS_BEARER_TOKEN", TOKEN)


@pytest.fixture
def metrics():
    return Metrics()


def sample_app():
    app = FastAPI()

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"id": item_id}

    @app.post("/items")
    def create():
        return {"ok": True}

    @app.get("/forbidden")
    def forbidden():
        raise HTTPException(status_code=403)

    @app.get("/boom")
    def boom():
        raise RuntimeError("household hh-12345 has age 62")

    @app.get("/stream")
    def stream():
        return StreamingResponse(iter([b"event: a\n\n", b"event: b\n\n"]), media_type="text/event-stream")

    return app


@pytest.fixture
def client(enabled, metrics):
    app = sample_app()
    assert install_observability(app, metrics) is True
    return TestClient(app, raise_server_exceptions=False)


def scrape(client):
    response = client.get("/metrics", headers=AUTH)
    assert response.status_code == 200
    return response.text


def value(metrics, name, **labels):
    return metrics.registry.get_sample_value(name, labels)


# Switching it on and off


@pytest.mark.parametrize("flag", ["", "false", "0", "no", "off", "maybe"])
def test_it_does_nothing_unless_it_is_switched_on(monkeypatch, metrics, flag):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", flag)
    monkeypatch.setenv("METRICS_BEARER_TOKEN", TOKEN)
    app = sample_app()

    assert install_observability(app, metrics) is False

    client = TestClient(app)
    assert client.get("/items/1").status_code == 200
    assert client.get("/metrics", headers=AUTH).status_code == 404
    assert value(metrics, "scheme_saathi_http_requests_total", method="GET", route="/items/{item_id}", status_class="2xx") is None


@pytest.mark.parametrize("flag", ["true", "TRUE", "1", "yes", "on", " true "])
def test_the_on_values(monkeypatch, flag):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", flag)
    assert settings().enabled is True


def test_the_real_api_has_no_metrics_endpoint_by_default():
    client = TestClient(api.create_api(service=object()))
    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 404


def test_the_real_api_counts_its_requests_when_switched_on(enabled):
    client = TestClient(api.create_api(service=object()))
    client.get("/health")
    client.get("/health")

    body = client.get("/metrics", headers=AUTH).text

    assert 'scheme_saathi_http_requests_total{method="GET",route="/health",status_class="2xx"} 2.0' in body
    assert 'route="/metrics"' not in body


# The bearer token


def test_without_a_token_configured_it_refuses_everyone(monkeypatch, metrics):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "")
    app = sample_app()
    install_observability(app, metrics)
    client = TestClient(app)

    assert client.get("/metrics").status_code == 503
    assert client.get("/metrics", headers=AUTH).status_code == 503


def test_a_missing_or_wrong_token_is_refused(client):
    missing = client.get("/metrics")
    assert missing.status_code == 401 and missing.headers["www-authenticate"] == "Bearer"
    for header in ({"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": "Basic " + TOKEN}):
        assert client.get("/metrics", headers=header).status_code == 401


def test_the_right_token_returns_prometheus_text(client):
    response = client.get("/metrics", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE scheme_saathi_http_requests_total counter" in response.text


def test_the_metrics_endpoint_is_not_in_the_api_documentation(client):
    assert "/metrics" not in client.get("/openapi.json").text


def test_the_token_is_never_in_the_output(client):
    client.get("/items/1")
    assert TOKEN not in scrape(client)


# What is counted


def test_requests_are_counted_by_route_template_method_and_status_class(client, metrics):
    client.get("/items/1")
    client.get("/items/2")
    client.post("/items")
    client.get("/forbidden")

    assert value(metrics, "scheme_saathi_http_requests_total", method="GET", route="/items/{item_id}", status_class="2xx") == 2
    assert value(metrics, "scheme_saathi_http_requests_total", method="POST", route="/items", status_class="2xx") == 1
    assert value(metrics, "scheme_saathi_http_requests_total", method="GET", route="/forbidden", status_class="4xx") == 1


def test_durations_are_recorded_per_route(client, metrics):
    client.get("/items/1")
    assert value(metrics, "scheme_saathi_http_request_duration_seconds_count", method="GET", route="/items/{item_id}") == 1
    assert value(metrics, "scheme_saathi_http_request_duration_seconds_sum", method="GET", route="/items/{item_id}") > 0


def test_a_request_that_matches_no_route_is_one_series_however_many_paths_are_tried(client, metrics):
    for path in ("/wp-admin", "/.env", "/a/b/c"):
        client.get(path)
    assert value(metrics, "scheme_saathi_http_requests_total", method="GET", route="unmatched", status_class="4xx") == 3
    assert "wp-admin" not in scrape(client)


def test_an_unhandled_error_is_a_5xx_and_records_only_the_exception_type(client, metrics):
    response = client.get("/boom")

    assert response.status_code == 500
    assert value(metrics, "scheme_saathi_http_requests_total", method="GET", route="/boom", status_class="5xx") == 1
    assert value(metrics, "scheme_saathi_http_exceptions_total", route="/boom", error_type="RuntimeError") == 1
    body = scrape(client)
    assert "hh-12345" not in body and "age 62" not in body  # the message is never kept


def test_a_streamed_response_is_counted_once_it_has_finished(client, metrics):
    assert client.get("/stream").text == "event: a\n\nevent: b\n\n"
    assert value(metrics, "scheme_saathi_http_requests_total", method="GET", route="/stream", status_class="2xx") == 1
    assert value(metrics, "scheme_saathi_http_request_duration_seconds_count", method="GET", route="/stream") == 1


def test_requests_in_progress_returns_to_zero(client, metrics):
    client.get("/items/1")
    client.get("/boom")
    assert value(metrics, "scheme_saathi_http_requests_in_progress") == 0


def test_an_unusual_method_is_one_label_value(client, metrics):
    client.request("PROPFIND", "/items/1")
    assert value(metrics, "scheme_saathi_http_requests_total", method="OTHER", route="/items/{item_id}", status_class="4xx") == 1


def test_reading_the_metrics_does_not_count_as_a_request(client):
    scrape(client)
    assert 'route="/metrics"' not in scrape(client)


# Nothing personal reaches a label


def test_identifiers_in_the_url_path_or_query_never_appear(client):
    client.get("/items/hh-12345?household_id=hh1&email=a@example.test")
    body = scrape(client)
    for private in ("hh-12345", "hh1", "a@example.test", "household_id", "email"):
        assert private not in body


def test_every_label_on_the_apps_own_metrics_is_on_the_allowlist(metrics):
    ours = [family for family in metrics.registry.collect() if family.name.startswith("scheme_saathi_")]
    assert ours
    labels = {label for family in ours for sample in family.samples for label in sample.labels}
    assert labels - {"le"} <= ALLOWED_LABELS


@pytest.mark.parametrize(
    "label", ["household_id", "thread_id", "application_id", "user_id", "actor_id", "session_id", "email", "name"]
)
def test_a_metric_cannot_be_declared_with_a_personal_label(metrics, label):
    with pytest.raises(ValueError):
        metrics._counter("anything_total", "x", [label])


def test_build_info_says_which_version_and_tracing_backend(metrics):
    samples = [s for f in metrics.registry.collect() for s in f.samples if s.name == "scheme_saathi_build_info"]
    assert len(samples) == 1 and samples[0].value == 1
    assert samples[0].labels["tracing_backend"] == "none" and samples[0].labels["version"]


def test_the_shared_metrics_can_be_replaced_for_a_test():
    first = get_metrics()
    assert get_metrics() is first
    fresh = Metrics()
    set_metrics(fresh)
    assert get_metrics() is fresh
