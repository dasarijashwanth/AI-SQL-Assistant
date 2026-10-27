"""Database access.

The application engine connects to SQLite in read-only mode
(URI mode=ro) and sets PRAGMA query_only = ON on every connection, so
writes are impossible at the connection level even if a query somehow
slipped past app/guard.py. Defense in depth, on purpose.

Every executed statement also runs under a query timeout
(SQL_ASSISTANT_QUERY_TIMEOUT, default 10 seconds): a SQLite progress
handler aborts the statement once the deadline passes, so a runaway
query (a cartesian join, a huge recursive CTE) cannot hang the API.
"""
import sqlite3
import time
from decimal import Decimal

import sqlalchemy
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from .config import get_db_path, get_query_timeout
from .guard import validate_select

_engine: Engine | None = None


class QueryTimeoutError(RuntimeError):
    """Raised when a database query runs past the configured timeout."""


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        path = get_db_path()

        def _creator():
            conn = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, check_same_thread=False
            )
            conn.execute("PRAGMA query_only = ON")
            return conn

        _engine = create_engine("sqlite://", creator=_creator)
    return _engine


def get_sql_database():
    """LangChain SQLDatabase wrapper over the read-only engine."""
    from langchain_community.utilities import SQLDatabase

    return SQLDatabase(get_engine())


def _convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def run_select(sql: str) -> list[dict]:
    """Validate and execute a read-only SELECT, returning rows as dicts.

    Raises QueryTimeoutError if the statement runs longer than
    SQL_ASSISTANT_QUERY_TIMEOUT seconds.
    """
    safe_sql = validate_select(sql)
    timeout = get_query_timeout()
    with get_engine().connect() as conn:
        raw = conn.connection.driver_connection
        deadline = time.monotonic() + timeout
        raw.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, 1000
        )
        try:
            result = conn.execute(text(safe_sql))
            return [
                {k: _convert(v) for k, v in row.items()}
                for row in result.mappings()
            ]
        except sqlalchemy.exc.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise QueryTimeoutError(
                    f"Query timed out after {timeout:g} seconds. "
                    "Narrow the query with filters or a smaller LIMIT "
                    "and try again."
                ) from exc
            raise
        finally:
            raw.set_progress_handler(None, 0)


def get_schema() -> dict:
    inspector = inspect(get_engine())
    tables = []
    for name in inspector.get_table_names():
        columns = [
            {"name": c["name"], "type": str(c["type"])}
            for c in inspector.get_columns(name)
        ]
        tables.append({"name": name, "columns": columns})
    return {"tables": tables}
