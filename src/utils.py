"""The OpenTelemetry-backed logger factory and the flush helper for its handlers."""

import os

from fastapi import FastAPI
from simple_log_factory_ext_otel import TracedLogger, otel_log_factory

SERVICE_NAME = "movie-reco-api"
UNTRACED_URLS = "api/health"

_all_loggers: dict[int, TracedLogger] = {}


def get_otel_log_handler(log_name: str, fastapi_app: FastAPI | None = None) -> TracedLogger:
    """Create a logger that exports logs and traces to the OTLP endpoint.

    Every logger also instruments psycopg and requests, so database and HTTP calls show up as spans. When
    ``fastapi_app`` is given, the app is instrumented too, except for the health check.

    Args:
        log_name: Name of the logger.
        fastapi_app: The application to instrument, if any.

    Returns:
        The traced logger.

    Raises:
        ValueError: If ``OTEL_EXPORTER_OTLP_ENDPOINT`` is not set.
    """
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    if not otel_endpoint:
        raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT environment variable must be set.")

    traced = otel_log_factory(
        service_name=SERVICE_NAME,
        log_name=log_name,
        otel_exporter_endpoint=otel_endpoint,
        instrument_db={"psycopg": {"enable_commenter": True}},
        instrument_requests=True,
        instrument_fastapi=({"app": fastapi_app, "excluded_urls": UNTRACED_URLS} if fastapi_app is not None else None),
    )

    _all_loggers[id(traced)] = traced

    return traced


def flush_all_otel_loggers() -> None:
    """Flush every OtelLogHandler created via get_otel_log_handler().

    Must be called before uvicorn.run() on Windows to drain all
    BatchLogRecordProcessor queues and avoid a deadlock between
    the batch-export background threads and ProactorEventLoop init.
    """
    for traced in _all_loggers.values():
        for h in traced.logger.handlers:
            h.flush()
