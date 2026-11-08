"""Client for the media identifier API's ``/api/media-info`` endpoint."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import requests
from raccoontools.decorators.retry import retry_request

from src.secret_store import get_secret

URL_SECRET = "MOVIE_RECO_MEDIA_IDENTIFIER_URL"
MEDIA_INFO_PATH = "/api/media-info"
REQUEST_TIMEOUT_SECONDS = 30
ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0
RETRIED_STATUS_CODES = [500, 502, 503, 504]
UNAVAILABLE_STATUS_CODES = frozenset({502, 503, 504})
_NO_CONTENT = 204
_OK = 200


class MediaIdentifierError(Exception):
    """The media identifier answered with an error or an unusable body; retrying the same request will not help.

    Messages carry the HTTP status at most, never the URL or the response body.
    """


class MediaIdentifierUnavailableError(MediaIdentifierError):
    """The media identifier could not be reached or reported itself unavailable; the request can be retried later."""


@dataclass(frozen=True)
class IdentifiedMovie:
    """A movie as the media identifier knows it.

    Attributes:
        cache_id: The media identifier's cache record id.
        title: The identified title.
        genres: Genre names, or None when unknown.
        year: The release year, or None when the media identifier has none.
    """

    cache_id: UUID
    title: str
    genres: list[str] | None
    year: int | None


def validate_base_url(raw_url: str) -> str:
    """Check and normalize the media identifier's base URL.

    Args:
        raw_url: The base URL, such as ``http://media-identifier:10147``.

    Returns:
        The URL without surrounding whitespace or a trailing slash.

    Raises:
        ValueError: If the URL is not http(s), has no host, or carries credentials, a query or a fragment. The message
            names the setting, never the value.
    """
    base_url = raw_url.strip().rstrip("/")
    parts = urlsplit(base_url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            f"Infisical secret '{URL_SECRET}' must be an http(s) base URL with a host and without credentials, "
            "query or fragment."
        )
    return base_url


class MediaIdentifierClient:
    """Looks movies up by title and year.

    A 500, 502, 503 or 504 answer is retried up to three attempts in total, with an exponential delay; network errors
    are not retried. Redirects are not followed.

    Args:
        base_url: The media identifier's base URL; see :func:`validate_base_url`.
        retry_delay: Seconds before the first retry; each later retry waits twice as long.

    Raises:
        ValueError: If ``base_url`` is invalid.
    """

    def __init__(self, base_url: str, retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS) -> None:
        self._media_info_url = validate_base_url(base_url) + MEDIA_INFO_PATH
        self._get_with_retry = retry_request(
            retries=ATTEMPTS,
            delay=retry_delay,
            delay_is_exponential=True,
            retry_only_on_status_codes=RETRIED_STATUS_CODES,
        )(self._get)

    def _get(self, params: dict[str, str | int]) -> requests.Response:
        return requests.get(self._media_info_url, params=params, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

    def identify_movie(self, title: str, year: int) -> IdentifiedMovie | None:
        """Identify a movie.

        Args:
            title: The movie's title.
            year: The movie's release year.

        Returns:
            The movie, or None when the media identifier answers 204 (nothing identified; final).

        Raises:
            MediaIdentifierUnavailableError: If the media identifier cannot be reached, or answers 502, 503 or 504
                after the retries.
            MediaIdentifierError: If it answers any other status, or a 200 whose body is not a movie record.
        """
        failure: str | None = None
        try:
            response = self._get_with_retry({"media_type": "movie", "title": title, "year": year})
        except requests.RequestException as e:
            failure = type(e).__name__

        # requests' messages quote the request URL; the error is raised outside the except so none of it travels along.
        if failure is not None:
            raise MediaIdentifierUnavailableError(f"The media identifier could not be reached ({failure}).")

        status = response.status_code
        if status == _NO_CONTENT:
            return None
        if status in UNAVAILABLE_STATUS_CODES:
            raise MediaIdentifierUnavailableError(f"The media identifier answered HTTP {status}.")
        if status != _OK:
            raise MediaIdentifierError(f"The media identifier answered HTTP {status}.")

        return _parse_movie(response)


def _parse_movie(response: requests.Response) -> IdentifiedMovie:
    try:
        body: Any = response.json()
    except requests.JSONDecodeError:
        body = None

    if not isinstance(body, dict):
        raise MediaIdentifierError("The media identifier answered HTTP 200 without a JSON object.")

    title = body.get("title")
    cache_id = _parse_uuid(body.get("id"))
    if not isinstance(title, str) or not title.strip() or cache_id is None:
        raise MediaIdentifierError("The media identifier answered HTTP 200 without a valid id and title.")

    genres = body.get("genres")
    year = body.get("year")
    return IdentifiedMovie(
        cache_id=cache_id,
        title=title,
        genres=genres if isinstance(genres, list) and all(isinstance(g, str) for g in genres) else None,
        year=year if isinstance(year, int) and not isinstance(year, bool) else None,
    )


def _parse_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def build_media_identifier_client() -> MediaIdentifierClient:
    """Build the client from the ``MOVIE_RECO_MEDIA_IDENTIFIER_URL`` Infisical secret.

    Returns:
        The client.

    Raises:
        SecretsError: If the secret is not set, or Infisical cannot be read.
        ValueError: If the secret is not a valid base URL.
    """
    return MediaIdentifierClient(get_secret(URL_SECRET))
