"""Test-session setup: the suite runs without Infisical, PostgreSQL, the media identifier or a telemetry collector."""

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Keep `.env` unloaded, telemetry off and the Infisical bootstrap out of the environment.

    Runs before any test module (and so any ``src`` or ``main`` import) is collected.
    """
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:4318"

    from src.secret_store import REQUIRED_BOOTSTRAP_VARIABLES

    for name in (*REQUIRED_BOOTSTRAP_VARIABLES, "INFISICAL_ENV"):
        os.environ.pop(name, None)


@pytest.fixture(autouse=True)
def secret_values(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Serve the Infisical secrets from a dict that starts empty, so every setting is absent unless a test sets it.

    The store caches what it reads, so a test fills the dict before the code under test reads the secret.
    """
    from src import secret_store

    values: dict[str, str] = {}
    monkeypatch.setattr(secret_store, "_default_store", secret_store.SecretStore(values.get, "test secrets"))
    return values
