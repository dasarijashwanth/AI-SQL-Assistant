"""Agent tools.

Built from LangChain's SQLDatabaseToolkit, with two deliberate swaps
that make the safety story real:

- sql_db_query_checker is replaced by our own guard: it validates the
  SQL with app.guard.validate_select and returns the sanitized query
  (writes rejected, row LIMIT enforced). The LLM's opinion of the query
  is never the line of defense.
- sql_db_query is wrapped so every executed statement is validated by
  the guard again (defense in depth) and captured, which is how the
  API can show the exact SQL that ran.
"""
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_core.tools import StructuredTool

from .guard import UnsafeQueryError, validate_select


def build_tools(db, llm, captured_sql: list[str]):
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = []
    for tool in toolkit.get_tools():
        if tool.name == "sql_db_query":
            tools.append(_guarded_query_tool(tool, captured_sql))
        elif tool.name == "sql_db_query_checker":
            tools.append(_guard_checker_tool())
        else:
            tools.append(tool)
    return tools


def _guard_checker_tool() -> StructuredTool:
    def check(query: str) -> str:
        """Validate a SQL query against the read-only policy."""
        try:
            return validate_select(query)
        except UnsafeQueryError as exc:
            return f"Error: query rejected by the read-only guard: {exc}"

    return StructuredTool.from_function(
        func=check,
        name="sql_db_query_checker",
        description=(
            "Use this tool to double check a SQL query before executing it. "
            "It enforces the read-only policy (SELECT only, single statement, "
            "row limit) and returns the sanitized query to pass to sql_db_query."
        ),
    )


def _guarded_query_tool(original, captured_sql: list[str]) -> StructuredTool:
    def run(query: str) -> str:
        """Execute a validated read-only SELECT and return result rows."""
        try:
            safe_sql = validate_select(query)
        except UnsafeQueryError as exc:
            return f"Error: query rejected by the read-only guard: {exc}"
        captured_sql.append(safe_sql)
        return original.invoke({"query": safe_sql})

    return StructuredTool.from_function(
        func=run,
        name="sql_db_query",
        description=(
            "Execute a SQL SELECT query against the database and return the "
            "result rows. Input must be a single read-only SELECT statement, "
            "already checked with sql_db_query_checker."
        ),
    )
