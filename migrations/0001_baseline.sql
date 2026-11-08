-- The watched movies table. IF NOT EXISTS lets a database created by 1.0.0 adopt this baseline as is.
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
);
