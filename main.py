from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

from src.api.app import app
from src.letterboxd.csv_importer.importer import CsvImporter
from src.utils import get_otel_log_handler, flush_all_otel_loggers


_data_folder = Path(__file__).parent.joinpath("data")
_historical_data = _data_folder.joinpath("historical_data").joinpath("letterboxd")
_logger = get_otel_log_handler("Main")


def _import_csvs():
    _logger.info("Starting CSV import...")
    watched_csv = _historical_data.joinpath("watched.csv")

    if not watched_csv.exists():
        error_message = f"File not found: {watched_csv}"
        _logger.error(error_message)
        raise FileNotFoundError(error_message)

    importer = CsvImporter(watched_csv)
    importer.run()


def _run_api():
    # Flush ALL OTEL log handlers before starting uvicorn.
    # On Windows the BatchLogRecordProcessor's background HTTP export
    # can deadlock with ProactorEventLoop initialisation if both run
    # concurrently.  Every TracedLogger has its own BatchLogRecordProcessor;
    # we must drain them all.
    print("Flushing buffered OTEL log records before starting uvicorn.")
    flush_all_otel_loggers()

    print("Starting uvicorn server.")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10149)


def main():
    run_mode = 1

    if run_mode == 1:
        _run_api()
    elif run_mode == 2:
        _import_csvs()
    else:
        _logger.error("Invalid run mode.")

if __name__ == '__main__':
    main()
