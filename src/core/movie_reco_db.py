import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from simple_log_factory.log_factory import log_factory

from src.core.movie_reco_models import WatchedMovie


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise ValueError(f"Environment variable '{name}' must be set to connect to the database.")
    return value


host = _require_env("POSTGRES_HOST")
port = int(_require_env("POSTGRES_PORT"))
user = _require_env("POSTGRES_USER")
password = _require_env("POSTGRES_PASSWORD")
dbname = _require_env("POSTGRES_DB")

_db_pool: SimpleConnectionPool = SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    host=host,
    port=port,
    user=user,
    password=password,
    dbname=dbname,
)


class MovieRecoDb:
    def __init__(self):
        self._logger = log_factory("MovieRecoDb", unique_handler_types=True)
        self._ensure_table_exists()

    @contextmanager
    def _get_connection(self):
        conn = _db_pool.getconn()
        try:
            yield conn
        finally:
            _db_pool.putconn(conn)

    def _ensure_table_exists(self) -> None:
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    self._logger.debug("Enabling uuid-ossp extension")
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

                    self._logger.debug("Creating the movie recommendation table (watched)")
                    cursor.execute("""
CREATE TABLE IF NOT EXISTS watched (
    letterboxd_uri   TEXT      NOT NULL,
    watch_date       DATE      NOT NULL,
    title            TEXT      NOT NULL,
    release_year     SMALLINT  NOT NULL
        CHECK (release_year BETWEEN 1878 AND 2100),
    cache_id         UUID      NULL,
    genres           TEXT[]    NULL,

    CONSTRAINT letterboxd_watchlist_pk
        PRIMARY KEY (letterboxd_uri)
);""")
                    conn.commit()
        except psycopg2.Error as e:
            error_message = f"Error creating the movie recommendation table: {e}"
            self._logger.error(error_message)
            raise RuntimeError(error_message) from e

    def add(self, letterboxd_uri: str, watch_date: datetime, title: str,
            release_year: int, genres: List[str], cache_id: uuid.UUID) -> WatchedMovie:
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    self._logger.debug(f"Inserting new entry for {letterboxd_uri}")
                    cursor.execute("""
    INSERT INTO watched (letterboxd_uri, watch_date, title, release_year, genres, cache_id)
    VALUES (%s, %s, %s, %s, %s, %s);
    """, (letterboxd_uri, watch_date, title, release_year, genres, cache_id))
                    conn.commit()

                    self._logger.debug(f"Successfully inserted entry for {letterboxd_uri}")

                    return WatchedMovie(
                        letterboxd_uri=letterboxd_uri,
                        watch_date=watch_date,
                        title=title,
                        release_year=release_year,
                        genres=genres,
                        cache_id=cache_id
                    )

        except psycopg2.Error as e:
            error_message = f"Error inserting new entry for {letterboxd_uri}: {e}"
            self._logger.error(error_message)
            raise RuntimeError(error_message) from e

    def get(self, value, search_prop: str = "cache_id") -> Optional[WatchedMovie]:
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    self._logger.debug(f"Searching for {value} in {search_prop}")
                    cursor.execute(f"""SELECT * FROM watched WHERE {search_prop} = %s;""", (value,))
                    result = cursor.fetchone()
                    if result:
                        return WatchedMovie(**dict(zip([desc[0] for desc in cursor.description], result)))
                    else:
                        return None
        except psycopg2.Error as e:
            error_message = f"Error searching for {value} in {search_prop}: {e}"
            self._logger.error(error_message)
            raise RuntimeError(error_message) from e
