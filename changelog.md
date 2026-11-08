# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-11-07

### Breaking changes

- Settings come from [Infisical](https://infisical.com/). The environment (or `.env`) holds only the Infisical
  bootstrap (`INFISICAL_HOST`, `INFISICAL_MOVIE_RECO_CLIENT_ID`, `INFISICAL_MOVIE_RECO_CLIENT_SECRET`,
  `INFISICAL_MOVIE_RECO_PROJECT_ID`, and `INFISICAL_ENV`, which defaults to `dev`) and `OTEL_EXPORTER_OTLP_ENDPOINT`.
  Two Infisical secrets replace the rest, read once at startup by the API and by the CSV importer:
  - `MOVIE_RECO_POSTGRES_CONNECTION_STRING`: one connection string replaces `POSTGRES_HOST`, `POSTGRES_PORT`,
    `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`.
  - `MOVIE_RECO_MEDIA_IDENTIFIER_URL`: the media identifier's base URL (for example
    `http://media-identifier:10147`) replaces `MEDIA_IDENTIFIER_ENDPOINT_MEDIA_INFO`, which held the full
    `/api/media-info` URL.
- The API no longer starts when a setting is missing or invalid; it used to start and fail later.
- Requires media identifier API 2.0.0.
- `POST /api/watched` answers:
  - `422` with `"result": "not_identified"` when the media identifier cannot identify the movie (was `500`). Don't
    retry these.
  - `503` with `"result": "unavailable"` when the media identifier is down or overloaded (was `500`). Retry later.
  - `502` with `"result": "upstream_error"` when the media identifier answers with an error (was `500`).
  - `422` with FastAPI's validation detail for an invalid request (was `400`). `title` is trimmed and up to 1024
    characters without control characters, `year` runs from 1900 to the current year, and `letterboxd_uri` must be an
    https URL on letterboxd.com or boxd.it.
  - `500` bodies no longer carry the exception text.
- The CSV import runs with `uv run python -m src.letterboxd.csv_importer [path]` instead of editing `run_mode` in
  `main.py`. It exits 1 when any row was not stored.
- The Docker image runs `uvicorn --workers $WORKERS` instead of gunicorn with the deprecated `uvicorn.workers` worker,
  and contains no `.env`. Pass the Infisical bootstrap and `OTEL_EXPORTER_OTLP_ENDPOINT` when the container starts
  (see `.env.example`).
- The database role no longer needs to create extensions: the unused `uuid-ossp` extension is not created.
- The database role needs CREATE on the `public` schema, because startup applies migrations, and should own the
  `watched` table so later migrations can alter it. The readme has the SQL for a dedicated role, and for upgrading a 1.0.0 database.

### Added

- Infisical secret store with the [Infisical SDK](https://pypi.org/project/infisicalsdk/) 1.0.18, the same design as
  media identifier API 2.0.0.
- Versioned SQL migrations in `migrations/`, applied at startup by the API and the CSV importer and recorded in a
  `schema_migrations` table. An advisory lock makes processes that start together apply each migration once.
- Readme instructions for a dedicated PostgreSQL role and database.
- Hermetic unit test suite (no Infisical, database, media identifier or telemetry collector needed).
- ruff, ruff format and mypy configuration.
- GitHub workflow `QA` that runs lint, format check, type check and tests on pull requests to `master`.
- `.env.example`, `.python-version` and an allowlist `.dockerignore`.

### Changed

- Dependencies updated: fastapi 0.162.2, uvicorn 0.54.0, requests 2.34.2, raccoontools 3.7.0,
  simple-log-factory-ext-otel 2.0.0. psycopg2 is replaced by raccoontools-db 1.1.0 (psycopg 3 connection pool), and
  the `dotenv` shim by python-dotenv 1.2.4.
- `/api/watched` runs in FastAPI's threadpool, so a slow database or media identifier call no longer blocks other
  requests or the health check.
- The connection pool is opened during application startup instead of at import time, after the migrations, and is
  closed on shutdown.
- Calls to the media identifier retry only `500`, `502`, `503` and `504` (three attempts, 1 s and 2 s apart), have
  a 30 s timeout and don't follow redirects. Other answers, such as `400` or `422`, are no longer retried.
- When the media identifier returns a movie without a release year, the year from the request is stored.
- The Docker image is a two-stage build on `python:3.14-slim` that runs as a non-root user, without compilers or
  `libpq-dev`.
- Requests to `/api/health` are no longer traced.
- Each failure is logged once, at the endpoint or the CSV importer. Logs no longer carry the full request or the
  client address.

### Fixed

- The Docker image could not be built: its base image ran Python 3.11 while the project required 3.14.
- Two identical requests at the same time no longer fail on the primary key; the second one answers "already
  exists".
- The movie lookup no longer builds its SQL with an interpolated column name.
- Requests without client address information no longer fail.
- The readme documented `POST /watched`; the route is `POST /api/watched`.

### Removed

- gunicorn, psycopg2, and the `run_mode` switch in `main.py`.

### Security

- `.dockerignore` is an allowlist, so `.env`, `data/` and local settings never reach the image.
- The database password lives in Infisical instead of `.env`, read with a machine identity whose credentials are the
  only secret left in the environment. Connection-string and URL errors name the setting, never its value.
- Error responses no longer expose exception text.

## [1.0.0]

Initial Release.
