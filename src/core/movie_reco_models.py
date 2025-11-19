from datetime import datetime
import uuid
from typing import List


class WatchedMovie:
    def __init__(self, letterboxd_uri: str, watch_date: datetime, title: str,
                 release_year: int, genres: List[str], cache_id: uuid.UUID):
        self.letterboxd_uri = letterboxd_uri
        self.watch_date = watch_date
        self.title = title
        self.release_year = release_year
        self.genres = genres
        self.cache_id = cache_id

    def __repr__(self):
        return f"WatchedMovie(letterboxd_uri='{self.letterboxd_uri}', watch_date={self.watch_date}, title='{self.title}', release_year={self.release_year}, genres={self.genres}, cache_id={self.cache_id})"
