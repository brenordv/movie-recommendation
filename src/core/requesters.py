import os

import raccoontools.shared.requests_with_retry as requests
from opentelemetry import trace

from src.utils import get_otel_log_handler

_logger = get_otel_log_handler("Requesters")


@_logger.trace("identify_movie")
def identify_movie(title: str, year: int, media_type: str = "movie"):
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attributes({
            "media.title": title,
            "media.year": year,
            "media.type": media_type,
        })

    url = os.environ.get("MEDIA_IDENTIFIER_ENDPOINT_MEDIA_INFO")

    if url is None:
        error_message = "MEDIA_IDENTIFIER_ENDPOINT_MEDIA_INFO is not set"
        _logger.error(error_message)
        raise ValueError(error_message)

    if title is None or title.strip() == "":
        error_message = "title is not set"
        _logger.error(error_message)
        raise ValueError(error_message)

    if year is None or year < 1900:
        error_message = "year is not set"
        _logger.error(error_message)
        raise ValueError(error_message)

    if media_type is None or media_type.strip() == "":
        error_message = "media_type is not set"
        _logger.error(error_message)
        raise ValueError(error_message)

    if span.is_recording():
        span.set_attribute("http.url", url)

    response = requests.get(url, params={"title": title, "year": year, "media_type": "movie"})

    if span.is_recording():
        span.set_attribute("http.status_code", response.status_code)

    if not response.ok:
        _logger.error(f"Error fetching media info for {title} ({year}): {response.status_code} - {response.text}")
        return None

    if response.status_code == 204:
        _logger.warning(f"Media not found: {title} ({year})")
        return None

    try:
        return response.json()
    except Exception as e:
        _logger.error(f"Error parsing media info for {title} ({year}): {e}")
        return None
