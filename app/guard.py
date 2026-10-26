"""Read-only SQL guard.

This is the safety core of the project. Every SQL string that reaches
the database, whether it came from the LLM agent or from the /query
endpoint, passes through validate_select() first:

- only a single SELECT (or WITH ... SELECT) statement is allowed
- write keywords (INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, ...)
  are rejected anywhere in the statement
- multiple statements separated by ";" are rejected
- a LIMIT no larger than the configured row cap is enforced

String literals and quoted identifiers are stripped before keyword
scanning so a product named "Delete" in a WHERE clause does not cause
a false rejection.
"""
import re

from .config import get_row_limit

WRITE_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "PRAGMA", "CREATE",
    "REPLACE", "TRUNCATE", "VACUUM", "ATTACH", "DETACH", "REINDEX",
    "GRANT", "REVOKE",
}


class UnsafeQueryError(ValueError):
    """Raised when a query violates the read-only policy."""


def _strip_literals(sql: str) -> str:
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    sql = re.sub(r"`[^`]*`", "``", sql)
    return sql


def validate_select(sql: str, row_limit: int | None = None) -> str:
    """Return a sanitized single read-only SELECT, or raise UnsafeQueryError."""
    if row_limit is None:
        row_limit = get_row_limit()
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")
    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if ";" in cleaned:
        raise UnsafeQueryError("Multiple statements are not allowed.")
    scan = _strip_literals(cleaned)
    first = re.match(r"[A-Za-z]+", scan)
    if not first:
        raise UnsafeQueryError("Could not parse a SQL statement.")
    first_word = first.group(0).upper()
    if first_word not in {"SELECT", "WITH"}:
        raise UnsafeQueryError(
            f"Only SELECT statements are allowed (got {first_word})."
        )
    tokens = set(re.findall(r"[A-Za-z]+", scan.upper()))
    bad = tokens & WRITE_KEYWORDS
    if bad:
        raise UnsafeQueryError(
            "Write keyword(s) not allowed in a read-only query: "
            + ", ".join(sorted(bad))
            + "."
        )
    return _enforce_limit(cleaned, row_limit)


def _enforce_limit(sql: str, row_limit: int) -> str:
    match = re.search(
        r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?\s*$", sql, re.IGNORECASE
    )
    if not match:
        return f"{sql} LIMIT {row_limit}"
    if match.group(2):  # LIMIT offset, count
        count = int(match.group(2))
        if count > row_limit:
            return sql[: match.start(2)] + str(row_limit)
        return sql
    value = int(match.group(1))
    if value > row_limit:
        return sql[: match.start(1)] + str(row_limit) + sql[match.end(1):]
    return sql
