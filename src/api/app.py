"""HTTP API that records watched movies."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, Field, StringConstraints, field_validator
from raccoontools_db import close_pool, create_pool

from src.core.db_config import build_conninfo, build_pool_config
from src.core.migrations import apply_migrations
from src.core.movie_reco_db import MovieRecoDb
from src.core.requesters import (
    MediaIdentifierClient,
    MediaIdentifierError,
    MediaIdentifierUnavailableError,
    build_media_identifier_client,
)
from src.letterboxd.movie_importer.movie_importer import ImportResult, import_movie
from src.secret_store import get_secret_store
from src.utils import flush_all_otel_loggers, get_otel_log_handler

MAX_TITLE_LENGTH = 1024
MAX_URI_LENGTH = 2048
FIRST_ACCEPTED_YEAR = 1900
LETTERBOXD_HOSTS = ("letterboxd.com", "boxd.it")
_NO_CONTROL_CHARACTERS = r"^[^\x00-\x1f\x7f]*$"

_STATUS_BY_RESULT = {
    ImportResult.SUCCESS: status.HTTP_201_CREATED,
    ImportResult.ALREADY_EXISTS: status.HTTP_200_OK,
    ImportResult.NOT_IDENTIFIED: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


class WatchedMovieRequest(BaseModel):
    """A movie watched on a given day, as Letterboxd reports it.

    ``title`` and ``letterboxd_uri`` are stripped and may not hold control characters; ``year`` runs from 1900 to the
    current year; ``letterboxd_uri`` is an https page on letterboxd.com or boxd.it.
    """

    title: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_TITLE_LENGTH, pattern=_NO_CONTROL_CHARACTERS
        ),
    ]
    watch_date: datetime
    year: Annotated[int, Field(ge=FIRST_ACCEPTED_YEAR)]
    letterboxd_uri: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_URI_LENGTH, pattern=_NO_CONTROL_CHARACTERS
        ),
    ]

    @field_validator("year")
    @classmethod
    def _year_not_in_the_future(cls, year: int) -> int:
        current_year = datetime.now(UTC).year
        if year > current_year:
            raise ValueError(f"year must not be after the current year ({current_year})")
        return year

    @field_validator("letterboxd_uri")
    @classmethod
    def _letterboxd_page(cls, letterboxd_uri: str) -> str:
        parts = urlsplit(letterboxd_uri)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not any(host == h or host.endswith(f".{h}") for h in LETTERBOXD_HOSTS):
            raise ValueError("letterboxd_uri must be an https URL on letterboxd.com or boxd.it")
        return letterboxd_uri


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Read the settings, apply pending database migrations and open the connection pool; close it on shutdown.

    Every Infisical setting is read here, so requests never contact Infisical.

    Raises:
        SecretsError: If the Infisical bootstrap is incomplete, Infisical cannot be read, or a secret is not set.
        ValueError: If the connection string or the media identifier URL is invalid.
        MigrationError: If the migrations are inconsistent, their lock is not acquired in time, or one fails.
        psycopg.Error: If connecting to the database, taking the migration lock or reading the ledger fails.
    """
    try:
        logger.info(f"Reading the settings from {get_secret_store().source}")
        conninfo = build_conninfo()
        pool_config = build_pool_config(conninfo)
        app.state.media_identifier = build_media_identifier_client()
    except Exception:
        logger.exception("Reading the settings failed; the API will not start")
        flush_all_otel_loggers()
        raise

    try:
        apply_migrations(conninfo, logger)
    except Exception:
        logger.exception("Applying database migrations failed; the API will not start")
        flush_all_otel_loggers()
        raise

    create_pool(pool_config)
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title="Watched Movie API",
    description="API for importing watched movies to the movie recommendation system.",
    version="2.0.0",
    lifespan=lifespan,
)

logger = get_otel_log_handler("API", fastapi_app=app)


def get_db() -> MovieRecoDb:
    """Return the ``watched`` table repository on the application's pool."""
    return MovieRecoDb()


def get_media_identifier(request: Request) -> MediaIdentifierClient:
    """Return the media identifier client built at startup."""
    client: MediaIdentifierClient = request.app.state.media_identifier
    return client


MovieRecoDbDep = Annotated[MovieRecoDb, Depends(get_db)]
MediaIdentifierDep = Annotated[MediaIdentifierClient, Depends(get_media_identifier)]


def _respond(status_code: int, result: str, item: WatchedMovieRequest) -> JSONResponse:
    trace.get_current_span().set_attribute("import.result", result)
    return JSONResponse(
        status_code=status_code, content={"result": result, "data": {"title": item.title, "year": item.year}}
    )


@app.post("/api/watched")
@logger.trace("/api/watched")
def watched(item: WatchedMovieRequest, db: MovieRecoDbDep, client: MediaIdentifierDep) -> JSONResponse:
    """Record a watched movie.

    Returns 201 when stored, 200 when the Letterboxd URI was already recorded, 422 when the request is invalid or
    the media identifier could not identify the movie, 503 when the media identifier is unavailable (retry later),
    502 when it answered with an error, and 500 when anything else failed. The body is
    ``{"result": ..., "data": {"title": ..., "year": ...}}`` and never carries error details.
    """
    movie = f"{item.title!r} ({item.year})"
    try:
        result = import_movie(
            db=db,
            client=client,
            letterboxd_uri=item.letterboxd_uri,
            watch_date=item.watch_date.date(),
            title=item.title,
            year=item.year,
        )
    except MediaIdentifierUnavailableError as e:
        logger.warning(f"Importing {movie} needs the media identifier, which is unavailable: {e}")
        return _respond(status.HTTP_503_SERVICE_UNAVAILABLE, "unavailable", item)
    except MediaIdentifierError as e:
        logger.error(f"Importing {movie} failed in the media identifier: {e}")
        return _respond(status.HTTP_502_BAD_GATEWAY, "upstream_error", item)
    except Exception:
        logger.exception(f"Importing {movie} failed")
        return _respond(status.HTTP_500_INTERNAL_SERVER_ERROR, "error", item)

    logger.info(f"Importing {movie}: {result.value}")
    return _respond(_STATUS_BY_RESULT[result], result.value, item)


@app.get("/api/health")
async def health_check() -> JSONResponse:
    """Report that the API process is up."""
    return JSONResponse(content={"message": "healthy"}, status_code=status.HTTP_200_OK)
