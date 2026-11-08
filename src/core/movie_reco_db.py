"""The ``watched`` table: lookup and insert."""

from collections.abc import Callable

import psycopg
from psycopg.rows import class_row
from psycopg_pool import ConnectionPool
from raccoontools_db import get_pool

from src.core.movie_reco_models import WatchedMovie

_SELECT_BY_URI = """
SELECT letterboxd_uri, watch_date, title, release_year, genres, cache_id
FROM watched
WHERE letterboxd_uri = %s;"""

_INSERT = """
INSERT INTO watched (letterboxd_uri, watch_date, title, release_year, genres, cache_id)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (letterboxd_uri) DO NOTHING
RETURNING letterboxd_uri;"""


class MovieRecoDbError(Exception):
    """A database operation on the ``watched`` table failed; the cause is the psycopg error."""


class MovieRecoDb:
    """Reads and writes the ``watched`` table; every call borrows its own pooled connection.

    Args:
        pool_getter: Returns the connection pool to use.
    """

    def __init__(self, pool_getter: Callable[[], ConnectionPool] = get_pool) -> None:
        self._pool_getter = pool_getter

    def get_by_letterboxd_uri(self, letterboxd_uri: str) -> WatchedMovie | None:
        """Return the watched movie with this Letterboxd URI.

        Args:
            letterboxd_uri: The Letterboxd page of the movie.

        Returns:
            The record, or None when there is none.

        Raises:
            MovieRecoDbError: If the query fails.
        """
        try:
            with self._pool_getter().connection() as conn:
                with conn.cursor(row_factory=class_row(WatchedMovie)) as cursor:
                    cursor.execute(_SELECT_BY_URI, (letterboxd_uri,))
                    return cursor.fetchone()
        except psycopg.Error as e:
            raise MovieRecoDbError("Looking up a watched movie failed.") from e

    def add(self, movie: WatchedMovie) -> bool:
        """Insert a watched movie unless one with the same Letterboxd URI exists.

        Args:
            movie: The record to insert.

        Returns:
            True when the row was inserted, False when the URI was already recorded.

        Raises:
            MovieRecoDbError: If the insert fails.
        """
        params = (
            movie.letterboxd_uri,
            movie.watch_date,
            movie.title,
            movie.release_year,
            movie.genres,
            movie.cache_id,
        )
        try:
            with self._pool_getter().connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(_INSERT, params)
                    return cursor.fetchone() is not None
        except psycopg.Error as e:
            raise MovieRecoDbError("Inserting a watched movie failed.") from e
