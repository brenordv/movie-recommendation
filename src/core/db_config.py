"""PostgreSQL connection settings read from Infisical."""

import psycopg
from psycopg.conninfo import conninfo_to_dict
from raccoontools_db import PoolConfig

from src.secret_store import get_secret

CONNECTION_STRING_SECRET = "MOVIE_RECO_POSTGRES_CONNECTION_STRING"
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 10


def build_conninfo() -> str:
    """Return the libpq connection string held in the ``MOVIE_RECO_POSTGRES_CONNECTION_STRING`` Infisical secret.

    The string is a URI (``postgresql://user:password@host:5432/dbname``) or ``key=value`` pairs, and must name the
    database.

    Returns:
        The connection string, without surrounding whitespace.

    Raises:
        SecretsError: If the secret is not set, or Infisical cannot be read.
        ValueError: If the secret is not a valid connection string with a database name.
    """
    conninfo = get_secret(CONNECTION_STRING_SECRET).strip()
    try:
        params = conninfo_to_dict(conninfo)
    except psycopg.ProgrammingError:
        params = None

    # libpq's parse errors quote the malformed part of the string, and a URI password holding an unencoded @ or /
    # still parses but spills into other parameters (host, port, database name, query options), which connect errors
    # quote; either can be the password. A spilled password always leaves the @ that should have ended it outside the
    # user name and password. The error is raised outside the except block so none of libpq's text travels with it.
    if (
        params is None
        or not params.get("dbname")
        or any("@" in str(value) for key, value in params.items() if key not in ("user", "password"))
    ):
        raise ValueError(
            f"Infisical secret '{CONNECTION_STRING_SECRET}' is not a valid PostgreSQL connection string with a "
            "database name; percent-encode special characters in a URI user name and password, or use quoted "
            "key=value pairs."
        )
    return conninfo


def build_pool_config(conninfo: str) -> PoolConfig:
    """Build the connection pool configuration.

    Args:
        conninfo: The connection string, as ``build_conninfo`` returns it.

    Returns:
        The pool configuration.
    """
    return PoolConfig(conn_info=conninfo, min_size=POOL_MIN_SIZE, max_size=POOL_MAX_SIZE)
