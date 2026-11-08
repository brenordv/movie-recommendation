from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pytest

from src.core.movie_reco_db import MovieRecoDbError
from src.core.movie_reco_models import WatchedMovie
from src.core.requesters import IdentifiedMovie, MediaIdentifierError, MediaIdentifierUnavailableError
from src.letterboxd.csv_importer.importer import CsvImporter, ImportSummary, WatchedRow, parse_row
from tests.fakes import InMemoryMovieRecoDb, StubMediaIdentifier, identified

HEADER = "Date,Name,Year,Letterboxd URI"
HEAT_ROW = "2025-11-19,Heat,1995,https://boxd.it/heat"
ALIEN_ROW = "2025-11-20,Alien,1979,https://boxd.it/alien"


def _csv(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "watched.csv"
    path.write_text("\n".join((HEADER, *rows)) + "\n", encoding="utf-8")
    return path


Outcome = IdentifiedMovie | Exception | None


def _importer(path: Path, db: InMemoryMovieRecoDb | None = None, *outcomes: Outcome) -> CsvImporter:
    return CsvImporter(path, db or InMemoryMovieRecoDb(), StubMediaIdentifier(*outcomes))


def test_parse_row_reads_every_field() -> None:
    row = {"Date": "2025-11-19", "Name": " Heat ", "Year": "1995", "Letterboxd URI": "https://boxd.it/heat"}

    assert parse_row(row) == WatchedRow("https://boxd.it/heat", "Heat", 1995, date(2025, 11, 19))


@pytest.mark.parametrize(
    "row",
    [
        ["2025-11-19", "Heat", "1995", "https://boxd.it/heat"],
        {"Date": "2025-11-19", "Name": "Heat", "Year": "1995", "Letterboxd URI": None},
        {"Date": "2025-11-19", "Name": "", "Year": "1995", "Letterboxd URI": "https://boxd.it/heat"},
        {"Date": "2025-11-19", "Name": "Heat", "Year": "nineteen", "Letterboxd URI": "https://boxd.it/heat"},
        {"Date": "19/11/2025", "Name": "Heat", "Year": "1995", "Letterboxd URI": "https://boxd.it/heat"},
    ],
    ids=["no-header", "missing-uri", "blank-name", "bad-year", "bad-date"],
)
def test_parse_row_unusable_row_raises_value_error(row: Mapping[str, str | None] | list[str]) -> None:
    with pytest.raises(ValueError):
        parse_row(row)


def test_run_counts_each_outcome(tmp_path: Path) -> None:
    recorded = WatchedMovie("https://boxd.it/alien", date(2025, 11, 20), "Alien", 1979, None, None)
    db = InMemoryMovieRecoDb([recorded])
    path = _csv(tmp_path, HEAT_ROW, ALIEN_ROW, "2025-11-21,Unknown Film,2001,https://boxd.it/unknown")

    summary = _importer(path, db, identified(title="Heat"), None).run()

    assert summary == ImportSummary(imported=1, already_existed=1, not_identified=1, failed_rows=[])
    assert db.movies["https://boxd.it/heat"].title == "Heat"


@pytest.mark.parametrize(
    ("db", "outcome"),
    [
        (InMemoryMovieRecoDb(), MediaIdentifierError("The media identifier answered HTTP 500.")),
        (InMemoryMovieRecoDb(add_error=MovieRecoDbError("insert failed")), identified()),
    ],
    ids=["media-identifier-error", "database-error"],
)
def test_run_row_that_cannot_be_stored_is_counted_as_failed_and_the_import_goes_on(
    tmp_path: Path, db: InMemoryMovieRecoDb, outcome: Outcome
) -> None:
    path = _csv(tmp_path, HEAT_ROW, "not-a-date,Broken,1995,https://boxd.it/broken")

    summary = _importer(path, db, outcome).run()

    assert summary.failed_rows == [2, 3]
    assert summary.imported == 0


def test_run_media_identifier_unavailable_stops_the_import_keeping_earlier_rows(tmp_path: Path) -> None:
    db = InMemoryMovieRecoDb()
    path = _csv(tmp_path, HEAT_ROW, ALIEN_ROW)

    with pytest.raises(MediaIdentifierUnavailableError):
        _importer(path, db, identified(title="Heat"), MediaIdentifierUnavailableError("down")).run()

    assert list(db.movies) == ["https://boxd.it/heat"]


@pytest.mark.parametrize(
    ("summary", "complete"),
    [
        (ImportSummary(imported=2, already_existed=1), True),
        (ImportSummary(imported=2, not_identified=1), False),
        (ImportSummary(imported=2, failed_rows=[3]), False),
    ],
)
def test_summary_is_complete_only_when_every_row_landed(summary: ImportSummary, complete: bool) -> None:
    assert summary.is_complete is complete


def test_importer_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _importer(tmp_path / "missing.csv")


def test_importer_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        _importer(tmp_path)


def test_importer_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "watched.csv"
    path.touch()

    with pytest.raises(ValueError, match="empty"):
        _importer(path)
