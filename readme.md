# Movie Recommendation
This is a work in progress, and it is part of my home lab setup.

The way it works is:
1. I did the first load by exporting the data from Letterboxd.
2. Then I used N8N to watch my RSS feed list.
3. Every time a new movie is added, I run the workflow, and it sends the new movies to the API here.
4. This API imports this movie to the database.

While this is running, I'm going to study about vector databases, and improve this project later to create an actual
(but simple) movie recommendation engine.

# Usage
The application expects a running PostgreSQL instance plus the environment variables listed below.
Create a `.env` file in the project root (loaded by `main.py`) or export the variables in your shell
before starting either the importer or the API.

## CSV Import
1. Export your Letterboxd diary and copy `watched.csv` into `data/historical_data/letterboxd/`.
2. Ensure the database and `MEDIA_IDENTIFIER_ENDPOINT_MEDIA_INFO` service are reachable.
3. Install the Python dependencies with [uv](https://github.com/astral-sh/uv):

   ```bash
   uv sync
   ```

4. Run the importer against the exported CSV (uv will manage the virtual environment automatically):

   ```bash
   uv run python -c "from pathlib import Path; from src.letterboxd.csv_importer.importer import CsvImporter; CsvImporter(Path('data/historical_data/letterboxd/watched.csv')).run()"
   ```

The importer will log each row processed and report any movies that could not be identified or inserted.

## API 
### Local
1. Make sure dependencies are installed:

   ```bash
   uv sync
   ```

2. Start the API server, which also loads `.env` automatically:

   ```bash
   uv run python main.py
   ```

   The service listens on `http://0.0.0.0:10149`. Use `uv run uvicorn main:app --reload --port 10149` if you prefer live reloads.
3. Send POST requests to `/watched` with payloads shaped like:

   ```json
   {
     "title": "Heat",
     "watch_date": "2025-11-19T00:00:00Z",
     "year": 1995,
     "letterboxd_uri": "https://letterboxd.com/film/heat/"
   }
   ```

   A `GET /api/health` endpoint is also available for health checks.

### Docker
1. Build the image:

   ```bash
   docker build -t movie-recommendation .
   ```

2. Run the container while wiring through the expected environment variables (either with `--env` flags or an env file):

   ```bash
   docker run --rm -p 10149:10149 --env-file .env movie-recommendation
   ```

3. Interact with the API the same way as the local run (e.g., `curl -X POST http://localhost:10149/watched ...`).

## Environment variables
- `POSTGRES_HOST` – hostname/IP of the PostgreSQL instance.
- `POSTGRES_PORT` – PostgreSQL port (e.g., `5432`).
- `POSTGRES_USER` – database username with rights to the `watched` table.
- `POSTGRES_PASSWORD` – password for `POSTGRES_USER`.
- `POSTGRES_DB` – database that stores the `watched` table.
- `MEDIA_IDENTIFIER_ENDPOINT_MEDIA_INFO` – HTTP endpoint that accepts `title` and `year` query params and responds with metadata used to enrich imports.

## Notes
- Used [gitignore](https://github.com/brenordv/rusted-toolbox/tree/master/crates/tool-gitignore) and [aiignore](https://github.com/brenordv/rusted-toolbox/tree/master/crates/tool-aiignore) tools to create the *ignore files.