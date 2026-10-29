"""Agent tools.

Built from LangChain's SQLDatabaseToolkit, with deliberate swaps
that make the safety story real:

- sql_db_query_checker is replaced by our own guard: it validates the
  SQL with app.guard.validate_select and returns the sanitized query
  (writes rejected, row LIMIT enforced). The LLM's opinion of the query
  is never the line of defense.
- sql_db_query is wrapped so every executed statement is validated by
  the guard again (defense in depth), captured (which is how the API
  can show the exact SQL that ran), and executed through
  app.db.run_select, so the query timeout applies here too. Day 4
  adds a bounded repair budget: if execution raises a SQLite error,
  the error is fed back to the agent for exactly ONE repair attempt;
  a second failure is reported honestly with no further retry.
- Two extra read-only exploration tools: sql_db_sample_rows peeks at a
  few rows of a table, and sql_db_distinct_values lists the real
  values of a column, so the agent filters on values that actually
  exist instead of guessing literals. Both validate table and column
  names against the live schema, so no name can smuggle in SQL.
"""
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_core.tools import StructuredTool

import sqlalchemy

from .db import QueryTimeoutError, get_schema, run_select
from .guard import UnsafeQueryError, validate_select

SAMPLE_ROWS_DEFAULT = 5
SAMPLE_ROWS_MAX = 20
DISTINCT_VALUES_DEFAULT = 50
DISTINCT_VALUES_MAX = 100

# Day 4: the agent gets exactly one repair attempt per question when a
# query fails at execution. The budget is tracked on the shared
# ``attempts`` list (one entry per executed query).
MAX_REPAIR_ATTEMPTS = 1


def _guard_hint(exc: UnsafeQueryError) -> str:
    """One concrete fix for a guard rejection, for the agent to act on."""
    message = str(exc)
    if "Only SELECT" in message:
        return "Rewrite it as a single SELECT statement."
    if "Write keyword" in message:
        return "Remove the write operation; this assistant can only read."
    if "Multiple statements" in message:
        return "Send one statement at a time."
    return "Use a single read-only SELECT statement."


def _guard_error(exc: UnsafeQueryError) -> str:
    return (
        f"Error: blocked by the read-only policy: {exc} "
        f"{_guard_hint(exc)}"
    )


def _schema_map() -> dict[str, list[str]]:
    return {
        table["name"]: [c["name"] for c in table["columns"]]
        for table in get_schema()["tables"]
    }


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _format_rows(rows: list[dict]) -> str:
    if not rows:
        return "No rows returned."
    header = ", ".join(rows[0].keys())
    lines = [header] + [
        ", ".join("" if v is None else str(v) for v in row.values())
        for row in rows
    ]
    return "\n".join(lines)


def build_tools(db, llm, captured_sql: list[str], attempts: list[dict] | None = None):
    """Build the agent's tool set.

    ``captured_sql`` collects every guard-validated query in order.
    ``attempts`` (Day 4) collects one record per executed query:
    {"sql", "error" (str or None), "row_count" (int or None)}. It is
    the repair budget ledger and the source of the /ask response's
    visible retry trace. Callers that don't need it (eval
    adversarial probes) may omit it.
    """
    if attempts is None:
        attempts = []
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = []
    for tool in toolkit.get_tools():
        if tool.name == "sql_db_query":
            tools.append(_guarded_query_tool(captured_sql, attempts))
        elif tool.name == "sql_db_query_checker":
            tools.append(_guard_checker_tool())
        else:
            tools.append(tool)
    tools.append(_sample_rows_tool())
    tools.append(_distinct_values_tool())
    return tools


def _guard_checker_tool() -> StructuredTool:
    def check(query: str) -> str:
        """Validate a SQL query against the read-only policy."""
        try:
            return validate_select(query)
        except UnsafeQueryError as exc:
            return _guard_error(exc)

    return StructuredTool.from_function(
        func=check,
        name="sql_db_query_checker",
        description=(
            "Use this tool to double check a SQL query before executing it. "
            "It enforces the read-only policy (SELECT only, single statement, "
            "row limit) and returns the sanitized query to pass to sql_db_query."
        ),
    )


def _guarded_query_tool(captured_sql: list[str], attempts: list[dict]) -> StructuredTool:
    def run(query: str) -> str:
        """Execute a validated read-only SELECT and return result rows.

        Day 4 repair contract: a SQLite execution error is returned as
        a tool error AND recorded in ``attempts``, so the agent can use
        its one repair attempt. A second failure is reported with an
        explicit do-not-retry instruction, and any further execution
        is refused, so the agent cannot loop. Guard rejections are
        policy feedback, not execution failures: they never execute
        and never touch the repair budget.
        """
        try:
            safe_sql = validate_select(query)
        except UnsafeQueryError as exc:
            return _guard_error(exc)
        prior_failures = sum(1 for a in attempts if a["error"] is not None)
        if prior_failures > MAX_REPAIR_ATTEMPTS:
            return (
                "Error: the repair budget is exhausted: one repair "
                "attempt was already used and it also failed. Do not "
                "retry; report the failure to the user honestly."
            )
        captured_sql.append(safe_sql)
        try:
            rows = run_select(safe_sql)
        except QueryTimeoutError as exc:
            attempts.append(
                {"sql": safe_sql, "error": str(exc), "row_count": None}
            )
            return f"Error: {exc}"
        except sqlalchemy.exc.SQLAlchemyError as exc:
            attempts.append(
                {
                    "sql": safe_sql,
                    "error": f"SQLite execution error: {exc}",
                    "row_count": None,
                }
            )
            if prior_failures >= MAX_REPAIR_ATTEMPTS:
                return (
                    f"Error: the repaired query also failed: {exc} "
                    "Do not retry; report the failure to the user "
                    "honestly."
                )
            return (
                f"Error: the query failed to execute: {exc} "
                "Fix the specific problem (for example a misspelled "
                "column or table name) and try exactly once more. Do "
                "not repeat the failed query unchanged."
            )
        attempts.append(
            {"sql": safe_sql, "error": None, "row_count": len(rows)}
        )
        return _format_rows(rows)

    return StructuredTool.from_function(
        func=run,
        name="sql_db_query",
        description=(
            "Execute a SQL SELECT query against the database and return the "
            "result rows. Input must be a single read-only SELECT statement, "
            "already checked with sql_db_query_checker."
        ),
    )


def _sample_rows_tool() -> StructuredTool:
    def sample_rows(table_name: str, n: int = SAMPLE_ROWS_DEFAULT) -> str:
        """Return up to n sample rows from a table."""
        schema = _schema_map()
        if table_name not in schema:
            return (
                f"Error: unknown table '{table_name}'. "
                f"Available tables: {', '.join(sorted(schema))}."
            )
        n = max(1, min(int(n), SAMPLE_ROWS_MAX))
        try:
            rows = run_select(
                f"SELECT * FROM {_quote(table_name)} LIMIT {n}"
            )
        except QueryTimeoutError as exc:
            return f"Error: {exc}"
        return _format_rows(rows)

    return StructuredTool.from_function(
        func=sample_rows,
        name="sql_db_sample_rows",
        description=(
            "Peek at a few sample rows from a table to see its actual data "
            "shape and values before writing a query. Input is the exact "
            "table name and, optionally, how many rows (default 5, max 20). "
            "Use this before guessing what values a column holds."
        ),
    )


def _distinct_values_tool() -> StructuredTool:
    def distinct_values(
        table_name: str,
        column_name: str,
        limit: int = DISTINCT_VALUES_DEFAULT,
    ) -> str:
        """List the distinct values of a column."""
        schema = _schema_map()
        if table_name not in schema:
            return (
                f"Error: unknown table '{table_name}'. "
                f"Available tables: {', '.join(sorted(schema))}."
            )
        if column_name not in schema[table_name]:
            return (
                f"Error: unknown column '{column_name}' in table "
                f"'{table_name}'. Available columns: "
                f"{', '.join(schema[table_name])}."
            )
        limit = max(1, min(int(limit), DISTINCT_VALUES_MAX))
        try:
            rows = run_select(
                f"SELECT DISTINCT {_quote(column_name)} "
                f"FROM {_quote(table_name)} "
                f"ORDER BY 1 LIMIT {limit}"
            )
        except QueryTimeoutError as exc:
            return f"Error: {exc}"
        if not rows:
            return f"No values found for {table_name}.{column_name}."
        return "\n".join(
            "" if v is None else str(v)
            for row in rows
            for v in row.values()
        )

    return StructuredTool.from_function(
        func=distinct_values,
        name="sql_db_distinct_values",
        description=(
            "List the distinct values of a column, so a WHERE filter uses a "
            "value that actually exists in the data instead of a guessed "
            "literal. Input is the exact table name and column name. "
            "Always use this before filtering on a status, category, or "
            "other coded value."
        ),
    )
