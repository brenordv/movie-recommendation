"""Import a Letterboxd ``watched.csv`` export row by row."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from opentelemetry import trace
from raccoontools.generators.file_ops_generators import read_csv

from src.core.movie_reco_db import MovieRecoDb, MovieRecoDbError
from src.core.requesters import MediaIdentifierClient, MediaIdentifierError, MediaIdentifierUnavailableError
from src.letterboxd.movie_importer.movie_importer import ImportResult, import_movie
from src.utils import get_otel_log_handler

_logger = get_otel_log_handler("Letterboxd.CsvImporter")

WATCH_DATE_FORMAT = "%Y-%m-%d"


@dataclass
class ImportSummary:
    """Counts of how each row of an import ended.

    Attributes:
        imported: Rows stored.
        already_existed: Rows whose Letterboxd URI was recorded before.
        not_identified: Rows the media identifier could not identify.
        failed_rows: Row numbers (1-based, header included) that could not be read or stored.
    """

    imported: int = 0
    already_existed: int = 0
    not_identified: int = 0
    failed_rows: list[int] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True when every row is stored or was already recorded."""
        return self.not_identified == 0 and not self.failed_rows

    def count(self, result: ImportResult) -> None:
        """Count one imported row.

        Args:
            result: How the row's import ended.
        """
        match result:
            case ImportResult.SUCCESS:
                self.imported += 1
            case ImportResult.ALREADY_EXISTS:
                self.already_existed += 1
            case ImportResult.NOT_IDENTIFIED:
                self.not_identified += 1


@dataclass(frozen=True)
class WatchedRow:
    """The fields of one ``watched.csv`` row.

    Attributes:
        letterboxd_uri: The ``Letterboxd URI`` column.
        title: The ``Name`` column.
        year: The ``Year`` column.
        watch_date: The ``Date`` column.
    """

    letterboxd_uri: str
    title: str
    year: int
    watch_date: date


def parse_row(row: Mapping[str, str | None] | list[str]) -> WatchedRow:
    """Read the fields of one ``watched.csv`` row.

    Args:
        row: The row as ``read_csv`` yields it, keyed by the header.

    Returns:
        The row's fields.

    Raises:
        ValueError: If the row has no header, or a field is missing, blank or malformed.
    """
    if not isinstance(row, Mapping):
        raise ValueError("The row has no header.")

    values = {key: (row.get(key) or "").strip() for key in ("Letterboxd URI", "Name", "Year", "Date")}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing column value(s): {', '.join(missing)}.")

    return WatchedRow(
        letterboxd_uri=values["Letterboxd URI"],
        title=values["Name"],
        year=int(values["Year"]),
        watch_date=datetime.strptime(values["Date"], WATCH_DATE_FORMAT).date(),
    )


class CsvImporter:
    """Imports every row of a Letterboxd ``watched.csv`` export.

    Args:
        file_path: The CSV file.
        db: The ``watched`` table.
        client: The media identifier client.

    Raises:
        FileNotFoundError: If the file does not exist.
        IsADirectoryError: If the path is a directory.
        ValueError: If the file is empty.
    """

    def __init__(self, file_path: Path, db: MovieRecoDb, client: MediaIdentifierClient) -> None:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.is_dir():
            raise IsADirectoryError(f"File is a directory: {file_path}")

        if file_path.stat().st_size == 0:
            raise ValueError(f"File is empty: {file_path}")

        if file_path.suffix.lower() != ".csv":
            _logger.warning(f"File doesn't seem to be a CSV file: {file_path}")

        self.file_path = file_path
        self._db = db
        self._client = client

    @_logger.trace("CsvImporter.run")
    def run(self) -> ImportSummary:
        """Import every row; a row that cannot be read or stored is logged and counted, and the import goes on.

        Returns:
            How the rows ended.

        Raises:
            MediaIdentifierUnavailableError: If the media identifier becomes unavailable; the rows before it stay
                imported.
        """
        trace.get_current_span().set_attribute("file.path", str(self.file_path))
        _logger.info(f"Importing file: {self.file_path}")

        summary = ImportSummary()
        for row, metadata in read_csv(self.file_path):
            try:
                watched = parse_row(row)
                result = import_movie(
                    db=self._db,
                    client=self._client,
                    letterboxd_uri=watched.letterboxd_uri,
                    watch_date=watched.watch_date,
                    title=watched.title,
                    year=watched.year,
                )
            except MediaIdentifierUnavailableError:
                raise
            except ValueError, MediaIdentifierError, MovieRecoDbError:
                _logger.exception(f"Row {metadata.index} could not be imported")
                summary.failed_rows.append(metadata.index)
                continue

            summary.count(result)
            if result == ImportResult.NOT_IDENTIFIED:
                _logger.info(f"Row {metadata.index}: {watched.title!r} ({watched.year}) could not be identified")

        return summary
