from collections.abc import Callable
from datetime import date
from uuid import uuid4

import psycopg
import pytest

from src.core.movie_reco_db import MovieRecoDb, MovieRecoDbError
from src.core.movie_reco_models import WatchedMovie
from tests.fakes import FakePool

HEAT = WatchedMovie(
    letterboxd_uri="https://letterboxd.com/film/heat/",
    watch_date=date(2025, 11, 19),
    title="Heat",
    release_year=1995,
    genres=["Crime", "Thriller"],
    cache_id=uuid4(),
)


def _db(pool: FakePool) -> MovieRecoDb:
    return MovieRecoDb(pool_getter=pool.as_pool)


def test_get_by_letterboxd_uri_returns_the_row_queried_by_uri() -> None:
    pool = FakePool(rows=[HEAT])

    movie = _db(pool).get_by_letterboxd_uri(HEAT.letterboxd_uri)

    assert movie == HEAT
    assert pool.cursor.executed[0][1] == (HEAT.letterboxd_uri,)


def test_get_by_letterboxd_uri_unknown_uri_returns_none() -> None:
    assert _db(FakePool()).get_by_letterboxd_uri("https://letterboxd.com/film/unknown/") is None


def test_add_new_movie_inserts_every_field_and_returns_true() -> None:
    pool = FakePool(rows=[(HEAT.letterboxd_uri,)])

    inserted = _db(pool).add(HEAT)

    assert inserted is True
    [(statement, params)] = pool.cursor.executed
    assert "ON CONFLICT (letterboxd_uri) DO NOTHING" in statement
    assert params == (HEAT.letterboxd_uri, HEAT.watch_date, HEAT.title, HEAT.release_year, HEAT.genres, HEAT.cache_id)


def test_add_already_recorded_uri_returns_false() -> None:
    assert _db(FakePool(rows=[])).add(HEAT) is False


@pytest.mark.parametrize(
    "operation",
    [
        lambda db: db.get_by_letterboxd_uri(HEAT.letterboxd_uri),
        lambda db: db.add(HEAT),
    ],
    ids=["get_by_letterboxd_uri", "add"],
)
def test_database_error_is_wrapped_with_the_psycopg_error_as_cause(operation: Callable[[MovieRecoDb], object]) -> None:
    error = psycopg.OperationalError("connection lost")
    db = _db(FakePool(error=error))

    with pytest.raises(MovieRecoDbError) as raised:
        operation(db)

    assert raised.value.__cause__ is error
