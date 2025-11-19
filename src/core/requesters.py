import os


import raccoontools.shared.requests_with_retry as requests
from simple_log_factory.log_factory import log_factory

_logger = log_factory("Requesters", unique_handler_types=True)

#@retry_request(delay_is_exponential=True, log_level=logging.DEBUG)
def identify_movie(title: str, year: int, media_type: str = "movie"):
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

    response = requests.get(url, params={"title": title, "year": year, "media_type": "movie"})

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
