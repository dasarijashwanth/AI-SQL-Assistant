"""Day 2 tests: sample-rows and distinct-value tools, query timeouts,
stricter prompts, and clearer error messages.

Everything runs offline against the temp demo database built by
conftest.py. No test touches the real repository data directory.
"""
import os

import pytest

from app.agent_service import SYSTEM_PROMPT
from app.db import QueryTimeoutError, get_sql_database, run_select
from app.fake_llm import FakeSQLChatModel
from app.tools import build_tools

# A deliberately runaway query: a 20M-row recursive CTE. Under a short
# timeout the SQLite progress handler must abort it instead of hanging.
RUNAWAY_SQL = (
    "WITH RECURSIVE cnt(x) AS ("
    " SELECT 1 UNION ALL SELECT x + 1 FROM cnt WHERE x < 20000000"
    ") SELECT COUNT(*) AS n FROM cnt"
)


@pytest.fixture()
def tools(demo_db):
    captured: list[str] = []
    built = build_tools(get_sql_database(), FakeSQLChatModel(), captured)
    return {tool.name: tool for tool in built}


def test_toolbox_includes_day2_tools(tools):
    assert "sql_db_sample_rows" in tools
    assert "sql_db_distinct_values" in tools


def test_sample_rows_default_five(tools):
    out = tools["sql_db_sample_rows"].invoke({"table_name": "orders"})
    lines = out.strip().splitlines()
    assert lines[0].startswith("id,")
    assert "customer_id" in lines[0]
    assert len(lines) == 6  # header + 5 rows


def test_sample_rows_caps_at_twenty(tools):
    out = tools["sql_db_sample_rows"].invoke(
        {"table_name": "orders", "n": 100}
    )
    assert len(out.strip().splitlines()) == 21  # header + 20 rows


def test_sample_rows_unknown_table_lists_tables(tools):
    out = tools["sql_db_sample_rows"].invoke({"table_name": "ordrs"})
    assert "unknown table 'ordrs'" in out
    assert "customers" in out and "orders" in out


def test_sample_rows_rejects_injection_as_unknown_table(tools):
    out = tools["sql_db_sample_rows"].invoke(
        {"table_name": "orders; DROP TABLE orders"}
    )
    assert "unknown table" in out
    # And the orders table survived the attempt.
    assert run_select("SELECT COUNT(*) AS n FROM orders")[0]["n"] == 120


def test_distinct_values_lists_real_statuses(tools):
    out = tools["sql_db_distinct_values"].invoke(
        {"table_name": "orders", "column_name": "status"}
    )
    values = set(out.strip().splitlines())
    assert "completed" in values
    assert "shipped" in values


def test_distinct_values_unknown_column_lists_columns(tools):
    out = tools["sql_db_distinct_values"].invoke(
        {"table_name": "orders", "column_name": "statuz"}
    )
    assert "unknown column 'statuz'" in out
    assert "total_amount" in out


def test_distinct_values_unknown_table(tools):
    out = tools["sql_db_distinct_values"].invoke(
        {"table_name": "ordrs", "column_name": "status"}
    )
    assert "unknown table 'ordrs'" in out


def test_distinct_values_rejects_injection_column(tools):
    out = tools["sql_db_distinct_values"].invoke(
        {"table_name": "orders", "column_name": "status; DROP TABLE orders"}
    )
    assert "unknown column" in out
    assert run_select("SELECT COUNT(*) AS n FROM orders")[0]["n"] == 120


def test_guarded_query_tool_rejects_write_with_hint(tools):
    out = tools["sql_db_query"].invoke(
        {"query": "DELETE FROM orders WHERE id = 1"}
    )
    assert "read-only policy" in out
    assert "Rewrite it as a single SELECT statement" in out
    # A write keyword smuggled inside a SELECT gets its own hint.
    out = tools["sql_db_query"].invoke({"query": "SELECT DELETE FROM orders"})
    assert "Remove the write operation" in out


def test_runaway_query_times_out_and_engine_recovers(monkeypatch):
    monkeypatch.setenv("SQL_ASSISTANT_QUERY_TIMEOUT", "0.2")
    with pytest.raises(QueryTimeoutError, match="timed out"):
        run_select(RUNAWAY_SQL)
    # The timeout must not poison later queries on the same engine.
    assert run_select("SELECT COUNT(*) AS n FROM orders")[0]["n"] == 120


def test_query_endpoint_returns_504_on_timeout(client, monkeypatch):
    monkeypatch.setenv("SQL_ASSISTANT_QUERY_TIMEOUT", "0.2")
    resp = client.post("/query", json={"sql": RUNAWAY_SQL})
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"]


def test_system_prompt_requires_exploration_before_guessing():
    assert "sql_db_sample_rows" in SYSTEM_PROMPT
    assert "sql_db_distinct_values" in SYSTEM_PROMPT
    assert "Never guess literal values" in SYSTEM_PROMPT
    assert "Never repeat a rejected query unchanged" in SYSTEM_PROMPT
