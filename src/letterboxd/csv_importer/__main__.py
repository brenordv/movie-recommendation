"""Import a Letterboxd ``watched.csv`` export: ``python -m src.letterboxd.csv_importer [path]``.

Exits 0 when every row is stored or was already recorded, and 1 otherwise.
"""

from dotenv import load_dotenv

load_dotenv()

import sys
from pathlib import Path

from raccoontools_db import close_pool, create_pool

from src.core.db_config import build_conninfo, build_pool_config
from src.core.migrations import apply_migrations
from src.core.movie_reco_db import MovieRecoDb
from src.core.requesters import MediaIdentifierUnavailableError, build_media_identifier_client
from src.letterboxd.csv_importer.importer import CsvImporter, ImportSummary
from src.secret_store import get_secret_store
from src.utils import flush_all_otel_loggers, get_otel_log_handler

DEFAULT_CSV_PATH = Path("data/historical_data/letterboxd/watched.csv")

_logger = get_otel_log_handler("Letterboxd.CsvImport")


def main(argv: list[str]) -> int:
    """Run the import and report how it ended.

    Args:
        argv: Command-line arguments: an optional path to the CSV file.

    Returns:
        The exit code: 0 when every row is stored or was already recorded, 1 otherwise.
    """
    csv_path = Path(argv[0]) if argv else DEFAULT_CSV_PATH
    try:
        summary = _run(csv_path)
    except MediaIdentifierUnavailableError as e:
        _logger.warning(f"Stopping the import: {e} Rows imported so far are kept; run it again later.")
        return 1
    except Exception:
        _logger.exception("The CSV import failed")
        return 1
    finally:
        flush_all_otel_loggers()

    _logger.info(
        f"Import finished: {summary.imported} imported, {summary.already_existed} already recorded, "
        f"{summary.not_identified} not identified, {len(summary.failed_rows)} failed"
        + (f" (rows {', '.join(map(str, summary.failed_rows))})" if summary.failed_rows else "")
    )
    flush_all_otel_loggers()
    return 0 if summary.is_complete else 1


def _run(csv_path: Path) -> ImportSummary:
    _logger.info(f"Reading the settings from {get_secret_store().source}")
    conninfo = build_conninfo()
    pool_config = build_pool_config(conninfo)
    client = build_media_identifier_client()

    apply_migrations(conninfo, _logger)
    create_pool(pool_config)
    try:
        return CsvImporter(csv_path, MovieRecoDb(), client).run()
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
