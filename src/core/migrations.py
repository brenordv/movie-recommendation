"""Versioned SQL migrations: numbered files in ``migrations/``, each applied once and recorded in a ledger table.

Runs take a PostgreSQL advisory lock on a dedicated connection, so several workers starting together apply each file
exactly once. Every file runs in its own transaction together with its ledger row, so a file must not contain
``BEGIN``/``COMMIT`` or statements that cannot run in a transaction block, such as ``CREATE INDEX CONCURRENTLY``.
"""

import hashlib
import re
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from simple_log_factory_ext_otel import TracedLogger

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
MIGRATION_LOCK_ID = zlib.crc32(b"movie-recommendation.migrations")
LOCK_WAIT_SECONDS = 60.0
LOCK_POLL_SECONDS = 0.5
STATEMENT_LOCK_TIMEOUT = "30s"

_FILE_NAME_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

Connect = Callable[[str], Any]
"""Opens an autocommit connection for a connection string."""


class MigrationError(RuntimeError):
    """The migrations cannot be planned or applied."""


@dataclass(frozen=True)
class Migration:
    """One migration file.

    Attributes:
        version: The file's number.
        name: The file name between the number and the extension.
        sql: The file's text.
        checksum: SHA-256 of the text, see ``checksum_of``.
    """

    version: int
    name: str
    sql: str
    checksum: str

    @property
    def label(self) -> str:
        """The file name without the extension, e.g. ``0001_baseline``."""
        return f"{self.version:04d}_{self.name}"


def checksum_of(sql_text: str) -> str:
    """Return the SHA-256 of a migration's text, with CRLF line endings counted as LF.

    Args:
        sql_text: The migration's text.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(sql_text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Load every ``NNNN_name.sql`` file in ``directory``, ordered by version.

    Args:
        directory: Folder holding the migration files.

    Returns:
        The migrations, lowest version first.

    Raises:
        MigrationError: If the folder is missing or empty, a ``.sql`` file is misnamed, or two files share a version.
    """
    if not directory.is_dir():
        raise MigrationError(f"Migrations folder '{directory.name}' not found.")

    migrations: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_NAME_PATTERN.match(path.name)
        if match is None:
            raise MigrationError(f"Invalid migration file name '{path.name}': expected NNNN_lowercase_name.sql.")

        version = int(match["version"])
        if version in migrations:
            raise MigrationError(f"Migration version {version} is used by more than one file.")

        sql_text = path.read_text(encoding="utf-8")
        migrations[version] = Migration(version, match["name"], sql_text, checksum_of(sql_text))

    if not migrations:
        raise MigrationError(f"No migration files found in '{directory.name}'.")

    return [migrations[version] for version in sorted(migrations)]


def plan_migrations(available: list[Migration], applied: dict[int, str]) -> list[Migration]:
    """Return the migrations still to apply, in order.

    Args:
        available: The migration files.
        applied: Checksums of the versions already applied, by version.

    Returns:
        The pending migrations, lowest version first.

    Raises:
        MigrationError: If an applied migration's file changed since it was applied, or a pending migration is
            numbered below one already applied (it would run out of order).
    """
    for migration in available:
        recorded = applied.get(migration.version)
        if recorded is not None and recorded != migration.checksum:
            raise MigrationError(f"Migration {migration.label} changed after it was applied.")

    pending = [migration for migration in available if migration.version not in applied]
    latest_applied = max(applied, default=0)
    for migration in pending:
        if migration.version < latest_applied:
            raise MigrationError(
                f"Migration {migration.label} is pending but version {latest_applied} is already applied; "
                "give it a number after the latest migration."
            )

    return pending


def _connect_autocommit(conninfo: str) -> psycopg.Connection[Any]:
    return psycopg.connect(conninfo, autocommit=True)


def apply_migrations(
    conninfo: str,
    logger: TracedLogger,
    directory: Path = MIGRATIONS_DIR,
    connect: Connect = _connect_autocommit,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
) -> list[Migration]:
    """Apply the pending migrations, in version order, stopping at the first failure.

    Args:
        conninfo: Connection string of the database to migrate.
        logger: Logger for progress messages.
        directory: Folder holding the migration files.
        connect: Opens the autocommit connection the run uses.
        lock_wait_seconds: How long to wait for another run holding the migration lock.

    Returns:
        The migrations applied by this run (empty when the schema was current).

    Raises:
        MigrationError: If the files are inconsistent, the lock is not acquired in time, or a migration fails (its
            changes are rolled back).
        psycopg.Error: If connecting, taking the lock, or reading the ledger fails.
    """
    migrations = discover_migrations(directory)

    with logger.span("apply_migrations"), connect(conninfo) as conn:
        _acquire_lock(conn, logger, lock_wait_seconds)
        conn.execute(f"SET lock_timeout = '{STATEMENT_LOCK_TIMEOUT}'")
        conn.execute(_LEDGER_DDL)
        applied = {row[0]: row[1] for row in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()}

        pending = plan_migrations(migrations, applied)
        if not pending:
            logger.info(f"Database schema at version {max(applied, default=0)}; no migrations pending.")
            return []

        for migration in pending:
            _apply(conn, migration, logger)

    return pending


def _acquire_lock(conn: Any, logger: TracedLogger, lock_wait_seconds: float) -> None:
    deadline = time.monotonic() + lock_wait_seconds
    waiting = False
    while True:
        row = conn.execute("SELECT pg_try_advisory_lock(%s)", (MIGRATION_LOCK_ID,)).fetchone()
        if row is not None and row[0]:
            return
        if time.monotonic() >= deadline:
            raise MigrationError("Timed out waiting for another migration run to release its lock.")
        if not waiting:
            logger.info("Waiting for another migration run to release its lock.")
            waiting = True
        time.sleep(LOCK_POLL_SECONDS)


def _apply(conn: Any, migration: Migration, logger: TracedLogger) -> None:
    started = time.perf_counter()
    try:
        with conn.transaction(), conn.cursor() as cursor:
            cursor.execute(migration.sql)
            statuses = [cursor.statusmessage or ""]
            while cursor.nextset():
                statuses.append(cursor.statusmessage or "")
            cursor.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                (migration.version, migration.name, migration.checksum),
            )
    except psycopg.Error as e:
        raise MigrationError(f"Migration {migration.label} failed and was rolled back: {e}") from e

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    logger.info(f"Applied migration {migration.label} in {elapsed_ms} ms: {', '.join(filter(None, statuses))}")
