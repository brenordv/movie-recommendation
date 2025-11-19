from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

from simple_log_factory.log_factory import log_factory

from src.api.app import app
from src.letterboxd.csv_importer.importer import CsvImporter


_data_folder = Path(__file__).parent.joinpath("data")
_historical_data = _data_folder.joinpath("historical_data").joinpath("letterboxd")
_logger = log_factory("Main", unique_handler_types=True)


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
