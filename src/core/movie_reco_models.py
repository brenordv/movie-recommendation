"""The watched-movie record stored in the ``watched`` table."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID


@dataclass(frozen=True)
class WatchedMovie:
    """A movie watched on a given day.

    Attributes:
        letterboxd_uri: The Letterboxd page of the movie; the record's key.
        watch_date: The day it was watched.
        title: The title as identified by the media identifier.
        release_year: The release year.
        genres: Genre names, or None when unknown.
        cache_id: The media identifier's cache record id, or None when unknown.
    """

    letterboxd_uri: str
    watch_date: date
    title: str
    release_year: int
    genres: list[str] | None
    cache_id: UUID | None
