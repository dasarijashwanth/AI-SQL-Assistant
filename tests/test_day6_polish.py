"""Day 6 tests: UI polish fixes and the demo script's key steps.

Polish covered here: format_attempt has no em dashes (user-facing
copy rule), successful attempts now carry their row count, and the
helpers stay total on empty/partial inputs. The demo steps are tested
through the service layer: the happy path answers from the database,
and a DELETE is rejected by the guard (both directly and through the
agent's query-checker tool) with the orders table untouched.
"""
import pytest

import app.ui as ui
from app.db import get_sql_database, run_select
from app.fake_llm import FakeSQLChatModel
from app.guard import UnsafeQueryError, validate_select
from app.tools import build_tools


def test_format_attempt_has_no_em_dash():
    bad = ui.format_attempt({"sql": "SELECT nope", "error": "no such column"}, 2)
    assert "\u2014" not in bad
    assert "Attempt 2" in bad
    assert "failed" in bad


def test_format_attempt_success_shows_row_count():
    one = ui.format_attempt({"sql": "SELECT 1", "error": None, "row_count": 1}, 1)
    assert "succeeded" in one
    assert "1 row" in one
    many = ui.format_attempt({"sql": "SELECT 1", "error": None, "row_count": 5}, 1)
    assert "5 rows" in many


def test_format_attempt_missing_row_count_still_renders():
    ok = ui.format_attempt({"sql": "SELECT 1", "error": None}, 1)
    assert "Attempt 1" in ok
    assert "succeeded" in ok


def test_format_attempt_empty_dict_does_not_crash():
    label = ui.format_attempt({}, 3)
    assert "Attempt 3" in label


def test_status_label_missing_keys_defaults_to_grounded():
    assert ui.status_label({}) == "grounded"


def test_status_label_error_wins_over_repaired():
    assert ui.status_label({"error": "x", "repaired": True}) == "failed"


def test_demo_happy_path_answers_from_database(client):
    result = ui.run_question("What is the total revenue?")
    assert ui.status_label(result) == "grounded"
    assert result["error"] is None
    assert result["rows"][0]["total_revenue"] > 0
    assert "SELECT" in result["sql"]
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["error"] is None


def test_demo_guard_rejects_delete_directly():
    with pytest.raises(UnsafeQueryError):
        validate_select("DELETE FROM orders")


def test_demo_agent_checker_tool_rejects_delete(client):
    db = get_sql_database()
    tools = build_tools(db, FakeSQLChatModel(), [])
    checker = next(t for t in tools if t.name == "sql_db_query_checker")
    response = checker.invoke("DELETE FROM orders")
    assert "blocked by the read-only policy" in response
    assert "SELECT" in response  # the fix hint points back to SELECT


def test_demo_orders_table_untouched_after_write_attempt(client):
    with pytest.raises(UnsafeQueryError):
        validate_select("DELETE FROM orders")
    db = get_sql_database()
    tools = build_tools(db, FakeSQLChatModel(), [])
    checker = next(t for t in tools if t.name == "sql_db_query_checker")
    checker.invoke("DROP TABLE orders")
    assert run_select("SELECT COUNT(*) AS n FROM orders")[0]["n"] == 120
