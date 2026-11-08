import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.api import app as app_module
from src.api.app import app, get_db, get_media_identifier
from src.core.migrations import MigrationError
from src.core.movie_reco_db import MovieRecoDbError
from src.core.movie_reco_models import WatchedMovie
from src.core.requesters import IdentifiedMovie, MediaIdentifierError, MediaIdentifierUnavailableError
from src.secret_store import SecretsError
from tests.fakes import InMemoryMovieRecoDb, StubMediaIdentifier, identified

HEAT_URI = "https://letterboxd.com/film/heat/"
HEAT_REQUEST = {"title": "Heat", "watch_date": "2025-11-19T00:00:00Z", "year": 1995, "letterboxd_uri": HEAT_URI}
SECRET_IN_ERROR = "connection failed: password=hunter2 host=db.internal"
CONNINFO = "host=db.test dbname=movie_reco user=movie_reco"


def _client(db: InMemoryMovieRecoDb, *outcomes: IdentifiedMovie | Exception | None) -> TestClient:
    identifier = StubMediaIdentifier(*outcomes)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_media_identifier] = lambda: identifier
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides = {}


def test_app_registers_every_endpoint() -> None:
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert paths == {"/api/watched", "/api/health"}


def test_health_check_reports_healthy() -> None:
    response = TestClient(app).get("/api/health")

    assert (response.status_code, response.json()) == (200, {"message": "healthy"})


def test_watched_identified_movie_is_stored_and_answers_201() -> None:
    db = InMemoryMovieRecoDb()

    response = _client(db, identified(title="Heat", year=1995)).post("/api/watched", json=HEAT_REQUEST)

    assert response.status_code == 201
    assert response.json() == {"result": "success", "data": {"title": "Heat", "year": 1995}}
    assert db.movies[HEAT_URI].watch_date.isoformat() == "2025-11-19"


def test_watched_already_recorded_answers_200() -> None:
    db = InMemoryMovieRecoDb([WatchedMovie(HEAT_URI, datetime.now(UTC).date(), "Heat", 1995, None, None)])

    response = _client(db, identified()).post("/api/watched", json=HEAT_REQUEST)

    assert (response.status_code, response.json()["result"]) == (200, "already_exists")


@pytest.mark.parametrize(
    ("outcome", "status_code", "result"),
    [
        (None, 422, "not_identified"),
        (MediaIdentifierUnavailableError("The media identifier answered HTTP 503."), 503, "unavailable"),
        (MediaIdentifierError("The media identifier answered HTTP 500."), 502, "upstream_error"),
    ],
)
def test_watched_media_identifier_outcome_maps_to_its_status_and_stores_nothing(
    outcome: Exception | None, status_code: int, result: str
) -> None:
    db = InMemoryMovieRecoDb()

    response = _client(db, outcome).post("/api/watched", json=HEAT_REQUEST)

    assert response.status_code == status_code
    assert response.json() == {"result": result, "data": {"title": "Heat", "year": 1995}}
    assert db.movies == {}


def test_watched_unexpected_failure_answers_500_without_error_details() -> None:
    db = InMemoryMovieRecoDb(add_error=MovieRecoDbError(SECRET_IN_ERROR))

    response = _client(db, identified()).post("/api/watched", json=HEAT_REQUEST)

    assert response.status_code == 500
    assert response.json() == {"result": "error", "data": {"title": "Heat", "year": 1995}}
    assert "hunter2" not in response.text


def test_watched_strips_the_title_before_identifying_it() -> None:
    db = InMemoryMovieRecoDb()
    identifier = StubMediaIdentifier(identified())
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_media_identifier] = lambda: identifier

    TestClient(app).post("/api/watched", json={**HEAT_REQUEST, "title": "  Heat \t"})

    assert identifier.lookups == [("Heat", 1995)]


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "   "},
        {"title": "Heat\r\nInjected log line"},
        {"title": "x" * 1025},
        {"year": 1899},
        {"year": datetime.now(UTC).year + 1},
        {"letterboxd_uri": "https://example.com/film/heat/"},
        {"letterboxd_uri": "http://letterboxd.com/film/heat/"},
        {"letterboxd_uri": "https://letterboxd.com.evil.example/film/heat/"},
        {"watch_date": "yesterday"},
    ],
    ids=[
        "blank-title",
        "control-characters",
        "title-too-long",
        "year-too-early",
        "year-in-the-future",
        "not-letterboxd",
        "plain-http",
        "lookalike-host",
        "bad-date",
    ],
)
def test_watched_invalid_request_answers_422_without_calling_anything(changes: dict[str, Any]) -> None:
    db = InMemoryMovieRecoDb()
    identifier = StubMediaIdentifier(identified())
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_media_identifier] = lambda: identifier

    response = TestClient(app).post("/api/watched", json={**HEAT_REQUEST, **changes})

    assert response.status_code == 422
    assert identifier.lookups == []
    assert db.movies == {}


@pytest.mark.parametrize("uri", ["https://boxd.it/abc1", "https://www.letterboxd.com/film/heat/"])
def test_watched_accepts_letterboxd_short_links_and_subdomains(uri: str) -> None:
    response = _client(InMemoryMovieRecoDb(), identified()).post(
        "/api/watched", json={**HEAT_REQUEST, "letterboxd_uri": uri}
    )

    assert response.status_code == 201


class LifespanSeams:
    """Replaces the settings, migration and pool functions the lifespan calls, recording what happened.

    Args:
        monkeypatch: The test's monkeypatch fixture.
        db: The repository requests use.
        migration_error: An exception the migration run raises.
    """

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, db: InMemoryMovieRecoDb, migration_error: Exception | None = None
    ) -> None:
        self.events: list[str] = []
        self.migrated_conninfos: list[str] = []
        self.client = StubMediaIdentifier(identified())
        self._migration_error = migration_error
        monkeypatch.setattr(app_module, "build_conninfo", lambda: CONNINFO)
        monkeypatch.setattr(app_module, "build_pool_config", lambda conninfo: object())
        monkeypatch.setattr(app_module, "build_media_identifier_client", lambda: self.client)
        monkeypatch.setattr(app_module, "apply_migrations", self._migrate)
        monkeypatch.setattr(app_module, "create_pool", lambda config: self.events.append("create"))
        monkeypatch.setattr(app_module, "close_pool", lambda: self.events.append("close"))
        monkeypatch.setattr(app_module, "MovieRecoDb", lambda: db)

    def _migrate(self, conninfo: str, logger: object) -> list[object]:
        self.events.append("migrate")
        self.migrated_conninfos.append(conninfo)
        if self._migration_error is not None:
            raise self._migration_error
        return []


def test_lifespan_migrates_then_prepares_the_pool_and_client_that_requests_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seams = LifespanSeams(monkeypatch, InMemoryMovieRecoDb())

    with TestClient(app) as client:
        response = client.post("/api/watched", json=HEAT_REQUEST)

    assert response.status_code == 201
    assert seams.client.lookups == [("Heat", 1995)]
    assert seams.migrated_conninfos == [CONNINFO]
    assert seams.events == ["migrate", "create", "close"]


def test_lifespan_missing_settings_stops_startup_before_opening_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(app_module, "create_pool", lambda config: events.append("create"))

    with pytest.raises(SecretsError), TestClient(app):
        pass

    assert events == []


def test_lifespan_migration_failure_stops_startup_before_opening_the_pool(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seams = LifespanSeams(
        monkeypatch, InMemoryMovieRecoDb(), MigrationError("Migration 0001_baseline failed and was rolled back.")
    )

    with caplog.at_level(logging.ERROR), pytest.raises(MigrationError), TestClient(app):
        pass

    assert seams.events == ["migrate"]
    assert any("Applying database migrations failed" in record.getMessage() for record in caplog.records)
