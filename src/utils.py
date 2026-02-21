import os

from simple_log_factory_ext_otel import TracedLogger, otel_log_factory

_all_loggers: dict[int, TracedLogger] = {}


def get_otel_log_handler(log_name: str, fastapi_app=None) -> TracedLogger:
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    if not otel_endpoint:
        raise ValueError(
            "OTEL_EXPORTER_OTLP_ENDPOINT environment variable must be set."
        )

    service_name = "movie-reco-api"

    traced = otel_log_factory(
        service_name=service_name,
        log_name=log_name,
        otel_exporter_endpoint=otel_endpoint,
        instrument_db={"psycopg2": {"enable_commenter": True}},
        instrument_requests=True,
        instrument_fastapi={"app": fastapi_app} if fastapi_app is not None else None,
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
