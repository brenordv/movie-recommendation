from pathlib import Path
from datetime import datetime

from raccoontools.generators.file_ops_generators import read_csv
from simple_log_factory.log_factory import log_factory

from src.core.movie_reco_db import MovieRecoDb
from src.letterboxd.movie_importer.movie_importer import import_movie, ImportResult


class CsvImporter:
    def __init__(self, file_path: Path):
        self._logger = log_factory("Letterboxd.CsvImporter", unique_handler_types=True)
        self._logger.info("Starting...")

        if not file_path.exists():
            error_message = f"File not found: {file_path}"
            self._logger.error(error_message)
            raise FileNotFoundError(error_message)

        if file_path.is_dir():
            error_message = f"File is a directory: {file_path}"
            self._logger.error(error_message)
            raise IsADirectoryError(error_message)

        if not file_path.name.lower().endswith("csv"):
            self._logger.warning(f"File doesn't seem to be a CSV file: {file_path}")

        if file_path.stat().st_size == 0:
            self._logger.warning(f"File is empty: {file_path}")
            raise ValueError("File is empty")

        self._logger.debug(f"File seems workable. Looks like we can use this: {file_path}")

        self._logger.debug("Initializing movie reco db...")
        self._db = MovieRecoDb()

        self.file_path = file_path

    def run(self):
        self._logger.info(f"Importing file: {self.file_path}")

        failed = []

        for row, metadata in read_csv(self.file_path):
            self._logger.debug(f"Processing row data #{metadata.index}...")

            try:
                letterboxed_uri = row["Letterboxd URI"]
                title = row["Name"]
                year = int(row["Year"])
                watch_date = datetime.strptime(row['Date'], "%Y-%m-%d")

                result = import_movie(
                    letterboxd_uri=letterboxed_uri,
                    watch_date=watch_date,
                    title=title,
                    year=year,
                )

                if result == ImportResult.FAILED:
                    failed.append(row)

                self._logger.debug(f"Result: {result}")
            except Exception as e:
                self._logger.error(f"Error processing row data #{metadata.index}: {e}")
                failed.append(row)

        if len(failed) > 0:
            self._logger.warning(f"Failed to import {len(failed)} movies:")
            for row in failed:
                self._logger.warning(f"  {row}")
