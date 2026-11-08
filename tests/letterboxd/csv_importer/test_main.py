from pathlib import Path

import pytest

from src.core.migrations import MigrationError
from src.core.requesters import IdentifiedMovie, MediaIdentifierUnavailableError
from src.letterboxd.csv_importer import __main__ as cli
from tests.fakes import InMemoryMovieRecoDb, StubMediaIdentifier, identified

HEAT_CSV = "Date,Name,Year,Letterboxd URI\n2025-11-19,Heat,1995,https://boxd.it/heat\n"


class PoolRecorder:
    """Records migration runs, pool creation and closing in place of the migration runner and raccoontools_db."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.migration_error: Exception | None = None

    def migrate(self, conninfo: str, logger: object) -> list[object]:
        self.events.append("migrate")
        if self.migration_error is not None:
            raise self.migration_error
        return []

    def create(self, config: object) -> None:
        self.events.append("create")

    def close(self) -> None:
        self.events.append("close")


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> PoolRecorder:
    recorder = PoolRecorder()
    monkeypatch.setattr(cli, "apply_migrations", recorder.migrate)
    monkeypatch.setattr(cli, "create_pool", recorder.create)
    monkeypatch.setattr(cli, "close_pool", recorder.close)
    return recorder


@pytest.fixture
def db() -> InMemoryMovieRecoDb:
    return InMemoryMovieRecoDb()


def _wire(
    monkeypatch: pytest.MonkeyPatch, db: InMemoryMovieRecoDb, *outcomes: IdentifiedMovie | Exception | None
) -> None:
    monkeypatch.setattr(cli, "build_conninfo", lambda: "host=db.test dbname=movie_reco")
    monkeypatch.setattr(cli, "build_pool_config", lambda conninfo: object())
    monkeypatch.setattr(cli, "build_media_identifier_client", lambda: StubMediaIdentifier(*outcomes))
    monkeypatch.setattr(cli, "MovieRecoDb", lambda: db)


def _csv(tmp_path: Path) -> str:
    path = tmp_path / "watched.csv"
    path.write_text(HEAT_CSV, encoding="utf-8")
    return str(path)


def test_main_complete_import_migrates_exits_zero_and_closes_the_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pool: PoolRecorder, db: InMemoryMovieRecoDb
) -> None:
    _wire(monkeypatch, db, identified(title="Heat"))

    exit_code = cli.main([_csv(tmp_path)])

    assert exit_code == 0
    assert list(db.movies) == ["https://boxd.it/heat"]
    assert pool.events == ["migrate", "create", "close"]


def test_main_migration_failure_exits_one_before_opening_the_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pool: PoolRecorder, db: InMemoryMovieRecoDb
) -> None:
    _wire(monkeypatch, db, identified(title="Heat"))
    pool.migration_error = MigrationError("Migration 0001_baseline failed and was rolled back.")

    exit_code = cli.main([_csv(tmp_path)])

    assert exit_code == 1
    assert pool.events == ["migrate"]
    assert db.movies == {}


def test_main_row_not_identified_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pool: PoolRecorder, db: InMemoryMovieRecoDb
) -> None:
    _wire(monkeypatch, db, None)

    assert cli.main([_csv(tmp_path)]) == 1


def test_main_media_identifier_unavailable_exits_one_and_closes_the_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pool: PoolRecorder, db: InMemoryMovieRecoDb
) -> None:
    _wire(monkeypatch, db, MediaIdentifierUnavailableError("down"))

    exit_code = cli.main([_csv(tmp_path)])

    assert exit_code == 1
    assert pool.events == ["migrate", "create", "close"]


def test_main_missing_csv_exits_one_and_closes_the_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pool: PoolRecorder, db: InMemoryMovieRecoDb
) -> None:
    _wire(monkeypatch, db)

    exit_code = cli.main([str(tmp_path / "missing.csv")])

    assert exit_code == 1
    assert pool.events == ["migrate", "create", "close"]


def test_main_without_settings_exits_one_before_opening_the_pool(tmp_path: Path, pool: PoolRecorder) -> None:
    exit_code = cli.main([_csv(tmp_path)])

    assert exit_code == 1
    assert pool.events == []


def test_main_without_a_path_reads_the_default_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pool: PoolRecorder, db: InMemoryMovieRecoDb
) -> None:
    default_csv = tmp_path / cli.DEFAULT_CSV_PATH
    default_csv.parent.mkdir(parents=True)
    default_csv.write_text(HEAT_CSV, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _wire(monkeypatch, db, identified(title="Heat"))

    assert cli.main([]) == 0
