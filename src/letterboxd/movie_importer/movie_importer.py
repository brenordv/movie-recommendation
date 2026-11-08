"""Record one watched movie: skip it when already recorded, otherwise identify it and store it."""

from datetime import date
from enum import StrEnum

from opentelemetry import trace

from src.core.movie_reco_db import MovieRecoDb
from src.core.movie_reco_models import WatchedMovie
from src.core.requesters import MediaIdentifierClient
from src.utils import get_otel_log_handler

_logger = get_otel_log_handler("MovieImporter")


class ImportResult(StrEnum):
    """How an import ended."""

    SUCCESS = "success"
    ALREADY_EXISTS = "already_exists"
    NOT_IDENTIFIED = "not_identified"


@_logger.trace("import_movie")
def import_movie(
    db: MovieRecoDb,
    client: MediaIdentifierClient,
    letterboxd_uri: str,
    watch_date: date,
    title: str,
    year: int,
) -> ImportResult:
    """Record a watched movie unless its Letterboxd URI is already recorded.

    The stored title, genres and year come from the media identifier; the given year is kept when it has none.

    Args:
        db: The ``watched`` table.
        client: The media identifier client.
        letterboxd_uri: The Letterboxd page of the movie.
        watch_date: The day it was watched.
        title: The title to identify.
        year: The release year to identify.

    Returns:
        ``SUCCESS`` when stored, ``ALREADY_EXISTS`` when the URI was recorded before (including by a concurrent
        import), ``NOT_IDENTIFIED`` when the media identifier could not identify it.

    Raises:
        MediaIdentifierUnavailableError: If the media identifier is unavailable.
        MediaIdentifierError: If the media identifier answers with an error.
        MovieRecoDbError: If the database fails.
    """
    span = trace.get_current_span()
    span.set_attributes({"media.title": title, "media.year": year, "media.letterboxd_uri": letterboxd_uri})

    result = _import(db, client, letterboxd_uri, watch_date, title, year)

    span.set_attribute("import.result", result.value)
    return result


def _import(
    db: MovieRecoDb,
    client: MediaIdentifierClient,
    letterboxd_uri: str,
    watch_date: date,
    title: str,
    year: int,
) -> ImportResult:
    if db.get_by_letterboxd_uri(letterboxd_uri) is not None:
        return ImportResult.ALREADY_EXISTS

    movie = client.identify_movie(title=title, year=year)
    if movie is None:
        return ImportResult.NOT_IDENTIFIED

    inserted = db.add(
        WatchedMovie(
            letterboxd_uri=letterboxd_uri,
            watch_date=watch_date,
            title=movie.title,
            release_year=movie.year if movie.year is not None else year,
            genres=movie.genres,
            cache_id=movie.cache_id,
        )
    )
    return ImportResult.SUCCESS if inserted else ImportResult.ALREADY_EXISTS
