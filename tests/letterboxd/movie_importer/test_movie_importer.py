from datetime import date, timedelta

import pytest

from src.core.movie_reco_db import MovieRecoDbError
from src.core.movie_reco_models import WatchedMovie
from src.core.requesters import MediaIdentifierUnavailableError
from src.letterboxd.movie_importer.movie_importer import ImportResult, import_movie
from tests.fakes import InMemoryMovieRecoDb, StubMediaIdentifier, identified

HEAT_URI = "https://letterboxd.com/film/heat/"
WATCH_DATE = date.today() - timedelta(days=1)


def _recorded(uri: str = HEAT_URI) -> WatchedMovie:
    return WatchedMovie(uri, WATCH_DATE, "Heat", 1995, None, None)


def _import(db: InMemoryMovieRecoDb, client: StubMediaIdentifier, year: int = 1995) -> ImportResult:
    return import_movie(db=db, client=client, letterboxd_uri=HEAT_URI, watch_date=WATCH_DATE, title="heat", year=year)


def test_import_movie_stores_the_identified_movie() -> None:
    db = InMemoryMovieRecoDb()
    movie = identified(title="Heat", year=1995, genres=["Crime"])

    result = _import(db, StubMediaIdentifier(movie))

    assert result == ImportResult.SUCCESS
    assert db.movies[HEAT_URI] == WatchedMovie(HEAT_URI, WATCH_DATE, "Heat", 1995, ["Crime"], movie.cache_id)


def test_import_movie_identified_without_a_year_keeps_the_requested_year() -> None:
    db = InMemoryMovieRecoDb()

    _import(db, StubMediaIdentifier(identified(year=None)), year=1996)

    assert db.movies[HEAT_URI].release_year == 1996


def test_import_movie_already_recorded_skips_the_media_identifier() -> None:
    client = StubMediaIdentifier(identified())

    result = _import(InMemoryMovieRecoDb([_recorded()]), client)

    assert result == ImportResult.ALREADY_EXISTS
    assert client.lookups == []


def test_import_movie_recorded_concurrently_reports_already_exists() -> None:
    db = InMemoryMovieRecoDb(record_on_add=_recorded())

    result = _import(db, StubMediaIdentifier(identified(title="Heat (concurrent)")))

    assert result == ImportResult.ALREADY_EXISTS
    assert db.movies[HEAT_URI].title == "Heat"


def test_import_movie_not_identified_stores_nothing() -> None:
    db = InMemoryMovieRecoDb()

    result = _import(db, StubMediaIdentifier(None))

    assert result == ImportResult.NOT_IDENTIFIED
    assert db.movies == {}


@pytest.mark.parametrize(
    ("db", "client", "error"),
    [
        (
            InMemoryMovieRecoDb(),
            StubMediaIdentifier(MediaIdentifierUnavailableError("down")),
            MediaIdentifierUnavailableError,
        ),
        (
            InMemoryMovieRecoDb(add_error=MovieRecoDbError("insert failed")),
            StubMediaIdentifier(identified()),
            MovieRecoDbError,
        ),
    ],
    ids=["media-identifier-unavailable", "database-error"],
)
def test_import_movie_failure_propagates_and_stores_nothing(
    db: InMemoryMovieRecoDb, client: StubMediaIdentifier, error: type[Exception]
) -> None:
    with pytest.raises(error):
        _import(db, client)

    assert db.movies == {}
