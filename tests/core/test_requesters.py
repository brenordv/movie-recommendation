import json
import traceback
from typing import Any
from uuid import UUID

import pytest
import requests

from src.core import requesters
from src.core.requesters import (
    URL_SECRET,
    IdentifiedMovie,
    MediaIdentifierClient,
    MediaIdentifierError,
    MediaIdentifierUnavailableError,
    build_media_identifier_client,
    validate_base_url,
)
from src.secret_store import SecretsError
from tests.fakes import MEDIA_IDENTIFIER_URL

CACHE_ID = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
HEAT_RECORD = {
    "id": CACHE_ID,
    "title": "Heat",
    "genres": ["Crime", "Drama"],
    "year": 1995,
    "media_type": "movie",
    "used_nimble": None,
}


def _response(status_code: int, body: object = None, raw: bytes | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
    return response


class FakeGet:
    """Replaces ``requests.get``: answers with queued responses or errors (the last repeats) and records each call."""

    def __init__(self, *outcomes: requests.Response | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"url": url, **kwargs})
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def client() -> MediaIdentifierClient:
    return MediaIdentifierClient(MEDIA_IDENTIFIER_URL, retry_delay=0)


def _answer(monkeypatch: pytest.MonkeyPatch, *outcomes: requests.Response | Exception) -> FakeGet:
    fake = FakeGet(*outcomes)
    monkeypatch.setattr(requesters.requests, "get", fake)
    return fake


def test_identify_movie_queries_media_info_for_a_movie_without_following_redirects(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient
) -> None:
    fake = _answer(monkeypatch, _response(200, HEAT_RECORD))

    client.identify_movie("Heat", 1995)

    assert fake.calls == [
        {
            "url": f"{MEDIA_IDENTIFIER_URL}/api/media-info",
            "params": {"media_type": "movie", "title": "Heat", "year": 1995},
            "timeout": requesters.REQUEST_TIMEOUT_SECONDS,
            "allow_redirects": False,
        }
    ]


def test_identify_movie_ok_returns_the_movie(monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient) -> None:
    _answer(monkeypatch, _response(200, HEAT_RECORD))

    movie = client.identify_movie("Heat", 1995)

    assert movie == IdentifiedMovie(cache_id=UUID(CACHE_ID), title="Heat", genres=["Crime", "Drama"], year=1995)


def test_identify_movie_null_year_and_genres_are_kept_as_none(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient
) -> None:
    _answer(monkeypatch, _response(200, {**HEAT_RECORD, "year": None, "genres": None}))

    movie = client.identify_movie("Heat", 1995)

    assert movie is not None
    assert (movie.year, movie.genres) == (None, None)


@pytest.mark.parametrize(("field", "value"), [("year", "1995"), ("year", True), ("genres", "Crime"), ("genres", [1])])
def test_identify_movie_malformed_optional_field_becomes_none(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient, field: str, value: object
) -> None:
    _answer(monkeypatch, _response(200, {**HEAT_RECORD, field: value}))

    movie = client.identify_movie("Heat", 1995)

    assert getattr(movie, field) is None


def test_identify_movie_no_content_returns_none_without_retrying(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient
) -> None:
    fake = _answer(monkeypatch, _response(204))

    assert client.identify_movie("Some.Rom.File", 2001) is None
    assert len(fake.calls) == 1


def test_identify_movie_retries_a_server_error_and_returns_the_later_answer(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient
) -> None:
    fake = _answer(monkeypatch, _response(503), _response(200, HEAT_RECORD))

    movie = client.identify_movie("Heat", 1995)

    assert movie is not None
    assert len(fake.calls) == 2


@pytest.mark.parametrize("status_code", [502, 503, 504])
def test_identify_movie_unavailable_after_every_attempt_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient, status_code: int
) -> None:
    fake = _answer(monkeypatch, _response(status_code))

    with pytest.raises(MediaIdentifierUnavailableError, match=f"HTTP {status_code}"):
        client.identify_movie("Heat", 1995)

    assert len(fake.calls) == requesters.ATTEMPTS


def test_identify_movie_internal_error_after_every_attempt_raises_a_final_error(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient
) -> None:
    fake = _answer(monkeypatch, _response(500, {"detail": "Internal error while processing the request."}))

    with pytest.raises(MediaIdentifierError, match="HTTP 500") as raised:
        client.identify_movie("Heat", 1995)

    assert not isinstance(raised.value, MediaIdentifierUnavailableError)
    assert len(fake.calls) == requesters.ATTEMPTS


@pytest.mark.parametrize("status_code", [301, 400, 404, 422])
def test_identify_movie_client_error_or_redirect_raises_a_final_error_without_retrying(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient, status_code: int
) -> None:
    fake = _answer(monkeypatch, _response(status_code, {"detail": "secret-ish detail"}))

    with pytest.raises(MediaIdentifierError) as raised:
        client.identify_movie("Heat", 1995)

    assert not isinstance(raised.value, MediaIdentifierUnavailableError)
    assert str(raised.value) == f"The media identifier answered HTTP {status_code}."
    assert len(fake.calls) == 1


@pytest.mark.parametrize("error", [requests.ConnectionError("refused"), requests.Timeout("timed out")])
def test_identify_movie_network_error_raises_unavailable_without_the_url(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient, error: requests.RequestException
) -> None:
    fake = _answer(monkeypatch, type(error)(f"failed for {MEDIA_IDENTIFIER_URL}/api/media-info?title=Heat"))

    with pytest.raises(MediaIdentifierUnavailableError, match=type(error).__name__) as raised:
        client.identify_movie("Heat", 1995)

    assert len(fake.calls) == 1
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "media-identifier.test" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize(
    "response",
    [
        _response(200, raw=b"<html>not json</html>"),
        _response(200, ["Heat"]),
        _response(200, {**HEAT_RECORD, "id": None}),
        _response(200, {**HEAT_RECORD, "id": "not-a-uuid"}),
        _response(200, {**HEAT_RECORD, "title": "  "}),
        _response(200, {key: value for key, value in HEAT_RECORD.items() if key != "title"}),
    ],
    ids=["invalid-json", "not-an-object", "null-id", "malformed-id", "blank-title", "missing-title"],
)
def test_identify_movie_ok_with_an_unusable_body_raises_a_final_error(
    monkeypatch: pytest.MonkeyPatch, client: MediaIdentifierClient, response: requests.Response
) -> None:
    _answer(monkeypatch, response)

    with pytest.raises(MediaIdentifierError, match="HTTP 200") as raised:
        client.identify_movie("Heat", 1995)

    assert not isinstance(raised.value, MediaIdentifierUnavailableError)


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (" http://media-identifier:10147/ \n", "http://media-identifier:10147"),
        ("https://media.example.lan", "https://media.example.lan"),
        ("http://media.example.lan/prefix", "http://media.example.lan/prefix"),
    ],
)
def test_validate_base_url_trims_whitespace_and_the_trailing_slash(raw_url: str, expected: str) -> None:
    assert validate_base_url(raw_url) == expected


@pytest.mark.parametrize(
    "raw_url",
    [
        "media-identifier:10147",
        "ftp://media.example.lan",
        "http://",
        "http://ops:hunter2@media.example.lan",
        "http://media.example.lan?token=hunter2",
        "http://media.example.lan#hunter2",
    ],
)
def test_validate_base_url_invalid_url_raises_naming_the_setting_without_the_value(raw_url: str) -> None:
    with pytest.raises(ValueError) as raised:
        validate_base_url(raw_url)

    assert str(raised.value) == (
        f"Infisical secret '{URL_SECRET}' must be an http(s) base URL with a host and without credentials, "
        "query or fragment."
    )


def test_build_media_identifier_client_reads_the_url_secret(
    monkeypatch: pytest.MonkeyPatch, secret_values: dict[str, str]
) -> None:
    secret_values[URL_SECRET] = "http://media-identifier:10147/"
    fake = _answer(monkeypatch, _response(204))

    build_media_identifier_client().identify_movie("Heat", 1995)

    assert fake.calls[0]["url"] == "http://media-identifier:10147/api/media-info"


def test_build_media_identifier_client_missing_secret_raises_naming_it() -> None:
    with pytest.raises(SecretsError, match=URL_SECRET):
        build_media_identifier_client()
