import pytest

from src.utils import get_otel_log_handler


def test_get_otel_log_handler_without_an_endpoint_raises_naming_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    with pytest.raises(ValueError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        get_otel_log_handler("Test")
