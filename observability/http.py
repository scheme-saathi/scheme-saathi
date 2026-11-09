"""FastAPI hooks: a middleware that times and counts requests, and the protected /metrics endpoint."""

from __future__ import annotations

import hmac
import logging
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from observability.config import settings
from observability.metrics import HTTP_METHODS, Metrics, get_metrics

logger = logging.getLogger(__name__)

METRICS_PATH = "/metrics"
UNMATCHED = "unmatched"


def _route_template(scope: dict[str, Any]) -> str:
    """The route as declared ("/api/threads/{thread_id}/decision"), never the URL that was requested.

    A request that matched no route is "unmatched", so scanners and typos cannot create new series,
    and an identifier in a URL never reaches a label.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else UNMATCHED


class MetricsMiddleware:
    """Pure ASGI, so streamed (server-sent event) responses are not buffered or delayed."""

    def __init__(self, app: Any, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == METRICS_PATH:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        method = method if method in HTTP_METHODS else "OTHER"
        status = 500  # what a caller sees if the app fails before it starts a response
        started = time.perf_counter()
        self.metrics.http_in_progress.inc()

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as error:
            self.metrics.http_exceptions.labels(route=_route_template(scope), error_type=type(error).__name__).inc()
            raise
        finally:
            route = _route_template(scope)
            self.metrics.http_in_progress.dec()
            self.metrics.http_requests.labels(method=method, route=route, status_class=f"{status // 100}xx").inc()
            self.metrics.http_duration.labels(method=method, route=route).observe(time.perf_counter() - started)


def _authorized(request: Request, token: str) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(supplied.strip().encode(), token.encode())


def install_observability(application: FastAPI, metrics: Metrics | None = None) -> bool:
    """Turn on request metrics and /metrics when OBSERVABILITY_ENABLED is set; otherwise do nothing.

    /metrics needs `Authorization: Bearer <METRICS_BEARER_TOKEN>`. With no token configured it
    refuses every request rather than serving openly.
    """
    config = settings()
    if not config.enabled:
        return False
    metrics = metrics or get_metrics()
    application.add_middleware(MetricsMiddleware, metrics=metrics)

    if config.metrics_token is None:
        logger.warning("Observability is on but METRICS_BEARER_TOKEN is not set, so /metrics will refuse requests.")

    def read_metrics(request: Request) -> Response:
        token = settings().metrics_token
        if token is None:
            return Response("Metrics are not configured.", status_code=503)
        if not _authorized(request, token):
            return Response("A bearer token is required.", status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    application.add_api_route(METRICS_PATH, read_metrics, methods=["GET"], include_in_schema=False)
    return True