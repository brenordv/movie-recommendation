"""Hand-rolled test doubles shared by the unit tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Self, cast
from uuid import uuid4

from psycopg_pool import ConnectionPool

from src.core.movie_reco_db import MovieRecoDb
from src.core.movie_reco_models import WatchedMovie
from src.core.requesters import IdentifiedMovie, MediaIdentifierClient

MEDIA_IDENTIFIER_URL = "http://media-identifier.test:10147"


class FakeCursor:
    """Records executed statements and the row factories it was opened with; returns queued rows."""

    def __init__(self, rows: list[Any] | None = None, error: Exception | None = None) -> None:
        self.executed: list[tuple[str, Any]] = []
        self.row_factories: list[Any] = []
        self._rows = list(rows or [])
        self._error = error

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((query, params))
        if self._error is not None:
            raise self._error

    def fetchone(self) -> Any:
        return self._rows.pop(0) if self._rows else None


class FakeConnection:
    """Hands out one shared cursor; ``execute`` runs on it too, as psycopg's ``Connection.execute`` does."""

    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self, row_factory: Any = None) -> FakeCursor:
        self._cursor.row_factories.append(row_factory)
        return self._cursor

    def execute(self, query: str, params: Any = None) -> FakeCursor:
        self._cursor.execute(query, params)
        return self._cursor


class FakePool:
    """Stands in for a psycopg ConnectionPool; every connection shares one cursor."""

    def __init__(self, rows: list[Any] | None = None, error: Exception | None = None) -> None:
        self.cursor = FakeCursor(rows, error)

    @contextmanager
    def connection(self) -> Iterator[FakeConnection]:
        yield FakeConnection(self.cursor)

    def as_pool(self) -> ConnectionPool:
        return cast(ConnectionPool, self)


def no_pool() -> ConnectionPool:
    """A pool getter for doubles that must never reach the database."""
    raise AssertionError("This test double must not open a database connection.")


class InMemoryMovieRecoDb(MovieRecoDb):
    """MovieRecoDb backed by a dict keyed by Letterboxd URI.

    Args:
        movies: Rows already recorded.
        add_error: An exception every ``add`` raises.
        record_on_add: A row that appears just before ``add`` runs, as a concurrent import would insert it.
    """

    def __init__(
        self,
        movies: list[WatchedMovie] | None = None,
        add_error: Exception | None = None,
        record_on_add: WatchedMovie | None = None,
    ) -> None:
        super().__init__(pool_getter=no_pool)
        self.movies = {movie.letterboxd_uri: movie for movie in movies or []}
        self._add_error = add_error
        self._record_on_add = record_on_add

    def get_by_letterboxd_uri(self, letterboxd_uri: str) -> WatchedMovie | None:
        return self.movies.get(letterboxd_uri)

    def add(self, movie: WatchedMovie) -> bool:
        if self._add_error is not None:
            raise self._add_error
        if self._record_on_add is not None:
            self.movies[self._record_on_add.letterboxd_uri] = self._record_on_add
        if movie.letterboxd_uri in self.movies:
            return False
        self.movies[movie.letterboxd_uri] = movie
        return True


class StubMediaIdentifier(MediaIdentifierClient):
    """Answers with the given outcomes in order (the last one repeats) and records what it was asked."""

    def __init__(self, *outcomes: IdentifiedMovie | Exception | None) -> None:
        super().__init__(MEDIA_IDENTIFIER_URL, retry_delay=0)
        self._outcomes = list(outcomes) or [None]
        self.lookups: list[tuple[str, int]] = []

    def identify_movie(self, title: str, year: int) -> IdentifiedMovie | None:
        self.lookups.append((title, year))
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def identified(title: str = "Heat", year: int | None = 1995, genres: list[str] | None = None) -> IdentifiedMovie:
    """An identified movie with a fresh cache id."""
    return IdentifiedMovie(cache_id=uuid4(), title=title, genres=genres or ["Crime", "Thriller"], year=year)
