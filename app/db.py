"""Database access.

The application engine connects to SQLite in read-only mode
(URI mode=ro) and sets PRAGMA query_only = ON on every connection, so
writes are impossible at the connection level even if a query somehow
slipped past app/guard.py. Defense in depth, on purpose.
"""
import sqlite3
from decimal import Decimal

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from .config import get_db_path
from .guard import validate_select

_engine: Engine | None = None


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
    """Validate and execute a read-only SELECT, returning rows as dicts."""
    safe_sql = validate_select(sql)
    with get_engine().connect() as conn:
        result = conn.execute(text(safe_sql))
        return [
            {k: _convert(v) for k, v in row.items()}
            for row in result.mappings()
        ]


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
