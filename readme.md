# Movie Recommendation
This is a work in progress, and it is part of my home lab setup.

The way it works is:
1. I did the first load by exporting the data from Letterboxd.
2. Then I used N8N to watch my RSS feed list.
3. Every time a new movie is added, I run the workflow, and it sends the new movies to the API here.
4. This API identifies the movie with the media identifier API (2.0.0 or newer) and stores it in PostgreSQL.

While this is running, I'm going to study about vector databases, and improve this project later to create an actual
(but simple) movie recommendation engine.

# Setup
Requires Python 3.14 and [uv](https://docs.astral.sh/uv/), PostgreSQL 15 or newer and a running media identifier API.

## Database
Give the app its own login role and a database that role owns. Run this in `psql` as a superuser:

```sql
CREATE ROLE movie_reco LOGIN;
\password movie_reco
CREATE DATABASE movie_reco OWNER movie_reco;
REVOKE CONNECT ON DATABASE movie_reco FROM PUBLIC;
```

[`\password`](https://www.postgresql.org/docs/current/app-psql.html) prompts for the password and keeps it out of
the shell history and the server log. Owning the database lets the role create its tables in the `public` schema
without superuser rights, which the startup migrations need. It also means the role can drop the database, so keep
its password in Infisical only.

On a cluster upgraded from PostgreSQL 14 or older, `public` keeps its old owner and stays writable by every role
([details](https://www.postgresql.org/docs/current/ddl-schemas.html)). Fix that once, connected to the new database:

```sql
\c movie_reco
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO movie_reco;
```

### Upgrading from 1.0.0
If the `watched` table already exists in a database the role doesn't own, run this once as a superuser, connected to
that database, before the first start of 2.0.0. The role needs CREATE on the schema to add the `schema_migrations`
table and later tables, and has to own `watched` so later migrations can alter it:

```sql
GRANT CONNECT ON DATABASE <database> TO movie_reco;
GRANT CREATE ON SCHEMA public TO movie_reco;
ALTER TABLE watched OWNER TO movie_reco;
```

### Migrations
The API and the CSV importer apply pending migrations from `migrations/` when they start, before they serve or import
anything, and record them in the `schema_migrations` table. A fresh database gets its tables on the first start; an
existing `watched` table is adopted as is (its columns are not checked). When several processes start together, one
applies the migrations and the others wait for it, for up to 60 seconds. New migrations go in
`migrations/NNNN_name.sql` with the next number. Never edit a file that was already applied; startup refuses to run
when one changed.

## Settings
Settings live in [Infisical](https://infisical.com/docs/documentation/platform/identities/universal-auth). Create a
project for this app, and a machine identity with Universal Auth and read-only access to it (one identity per
environment). Add these secrets at the root (`/`) of each environment:

| Secret | Example |
|---|---|
| `MOVIE_RECO_POSTGRES_CONNECTION_STRING` | `postgresql://movie_reco:<password>@db:5432/movie_reco` (percent-encode special characters in the password, for example with `urllib.parse.quote(password, safe="")`) |
| `MOVIE_RECO_MEDIA_IDENTIFIER_URL` | `http://media-identifier:10147` (base URL; `/api/media-info` is added) |

A plain `http://` media identifier URL is accepted for hosts on your own network; use `https://` anywhere else.

The environment holds only the Infisical bootstrap and the telemetry endpoint. Copy `.env.example` to `.env` (loaded
by both entry points) or export the variables:

| Variable | Meaning |
|---|---|
| `INFISICAL_HOST` | Infisical base URL; a bare host gets `https://` |
| `INFISICAL_ENV` | Infisical environment slug, default `dev` |
| `INFISICAL_MOVIE_RECO_CLIENT_ID` / `INFISICAL_MOVIE_RECO_CLIENT_SECRET` | the machine identity |
| `INFISICAL_MOVIE_RECO_PROJECT_ID` | the Infisical project |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector, for example `http://localhost:4318` |

# Usage
```bash
uv sync
```

## CSV import
Export your Letterboxd data and run the importer on `watched.csv` (the default path is
`data/historical_data/letterboxd/watched.csv`):

```bash
uv run python -m src.letterboxd.csv_importer path/to/watched.csv
```

It logs each row that could not be imported and a summary at the end. It exits 0 when every row was stored or was
already recorded, and 1 otherwise. When the media identifier is unavailable it stops; run it again later, since
rows already stored are skipped.

## API
### Local
```bash
uv run python main.py
```

The service listens on `http://0.0.0.0:10149`. Use `uv run uvicorn main:app --reload --port 10149` for live reloads.

Send POST requests to `/api/watched`:

```json
{
  "title": "Heat",
  "watch_date": "2025-11-19T00:00:00Z",
  "year": 1995,
  "letterboxd_uri": "https://letterboxd.com/film/heat/"
}
```

The answer is `{"result": ..., "data": {"title": ..., "year": ...}}`:

| Status | `result` | Meaning | Retry? |
|---|---|---|---|
| 201 | `success` | stored | no |
| 200 | `already_exists` | this `letterboxd_uri` was stored before | no |
| 422 | `not_identified` | the media identifier could not identify the movie | no |
| 422 | (FastAPI `detail`) | invalid request | no, fix the request |
| 503 | `unavailable` | the media identifier is down | yes, later |
| 502 | `upstream_error` | the media identifier answered with an error | a few times at most |
| 500 | `error` | unexpected failure; details are in the logs | a few times at most |

`GET /api/health` answers `{"message": "healthy"}`.

### Docker
```bash
docker build -t movie-recommendation .
docker run --rm -p 10149:10149 --env-file .env movie-recommendation
```

# Development
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

The same checks run on every pull request to `master` (`.github/workflows/qa.yml`). The test suite needs no
Infisical, database or media identifier.

## Notes
- Used [gitignore](https://github.com/brenordv/rusted-toolbox/tree/master/crates/tool-gitignore) and [aiignore](https://github.com/brenordv/rusted-toolbox/tree/master/crates/tool-aiignore) tools to create the *ignore files.
