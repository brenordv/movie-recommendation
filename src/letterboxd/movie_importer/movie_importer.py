from datetime import datetime
from enum import Enum

from opentelemetry import trace

from src.core.movie_reco_db import MovieRecoDb
from src.core.requesters import identify_movie
from src.utils import get_otel_log_handler

_logger = get_otel_log_handler("MovieImporter")
_db = MovieRecoDb()

class ImportResult(Enum):
    SUCCESS = "SUCCESS"
    ALREADY_EXISTS = "ALREADY_ADDED"
    FAILED = "FAILED"


@_logger.trace("import_movie")
def import_movie(
        letterboxd_uri: str,
        watch_date: datetime,
        title: str,
        year: int) -> ImportResult:
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attributes({
            "media.title": title,
            "media.year": year,
            "media.letterboxd_uri": letterboxd_uri,
        })

    _logger.info(f"Processing {title} ({year} / {letterboxd_uri})...")

    watched = _db.get(letterboxd_uri, search_prop="letterboxd_uri")

    if watched is not None:
        _logger.debug(f"Entry already exists in database: {watched}")
        return ImportResult.ALREADY_EXISTS

    media_info = identify_movie(title=title, year=year)
    if media_info is None:
        _logger.warning(f"Could not identify movie: {title} ({year}). Need to try again later...")
        return ImportResult.FAILED

    title = media_info['title']
    genres = media_info['genres']
    year = media_info['year']
    cache_id = media_info['id']

    _logger.debug(f"Movie identified! Cache id: {media_info['id']}")
    _logger.debug(f"Adding entry to database...")

    _db.add(
        letterboxd_uri=letterboxd_uri,
        watch_date=watch_date,
        title=title,
        release_year=year,
        genres=genres,
        cache_id=cache_id,
    )

    _logger.info(f"Successfully inserted entry for {letterboxd_uri}")
    return ImportResult.SUCCESS
