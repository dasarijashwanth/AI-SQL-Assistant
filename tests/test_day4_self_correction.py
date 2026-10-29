"""Day 4 tests: error recovery and self-correction.

The repair contract under test:
- a query that fails at SQLite execution is fed back to the agent for
  exactly ONE repair attempt, and the retry is visible in the /ask
  response (``attempts`` trace, ``repaired`` flag);
- if the repair also fails, the failure is returned visibly with no
  infinite loop (exactly two executed queries);
- the guard stays intact on the repair path: a write attempt during
  repair is rejected and never consumes the repair budget.
"""
from app.agent_service import ask_question
from app.db import get_sql_database
from app.fake_llm import FakeSQLChatModel
from app.tools import build_tools


def _query_tool():
    captured, attempts = [], []
    tools = build_tools(get_sql_database(), FakeSQLChatModel(), captured, attempts)
    tool = next(t for t in tools if t.name == "sql_db_query")
    return tool, captured, attempts


def test_repair_succeeds_after_one_failure(client):
    resp = client.post(
        "/ask",
        json={"question": "What is the total revenue with a broken column?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["repaired"] is True
    assert body["error"] is None
    assert body["row_count"] >= 1
    assert body["rows"][0]["total_revenue"] > 0
    assert len(body["attempts"]) == 2
    first, second = body["attempts"]
    assert "total_revenue_broken" in first["sql"]
    assert first["error"] is not None
    assert "no such column" in first["error"].lower()
    assert second["error"] is None
    assert body["sql"] == second["sql"]
    assert body["explanation"]


def test_repair_failure_returns_error_without_loop(client):
    resp = client.post(
        "/ask",
        json={"question": "What is the total revenue, always broken?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == []
    assert body["row_count"] == 0
    assert body["repaired"] is True
    assert body["error"] is not None
    assert "no such column" in body["error"].lower()
    # exactly one repair attempt: two executed queries, then the agent
    # stopped instead of looping
    assert len(body["attempts"]) == 2
    assert all(a["error"] is not None for a in body["attempts"])
    assert body["explanation"]


def test_repair_asks_directly_via_service():
    result = ask_question("What is the total revenue with a broken column?")
    assert result["repaired"] is True
    assert result["error"] is None
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["error"] is not None
    assert result["attempts"][1]["error"] is None


def test_guard_rejects_write_during_repair():
    tool, captured, attempts = _query_tool()
    out = tool.invoke({"query": "DELETE FROM orders WHERE id = 1"})
    assert "blocked by the read-only policy" in out
    # guard rejections never execute, so the repair budget is untouched
    assert attempts == []
    assert captured == []


def test_repair_budget_blocks_third_execution():
    tool, captured, attempts = _query_tool()
    out1 = tool.invoke({"query": "SELECT nope_col FROM orders"})
    assert "try exactly once more" in out1
    assert len(attempts) == 1
    out2 = tool.invoke({"query": "SELECT nope_col FROM orders"})
    assert "Do not retry" in out2
    assert len(attempts) == 2
    # a third execution is refused outright, even for a valid query
    out3 = tool.invoke({"query": "SELECT COUNT(*) AS n FROM orders"})
    assert "repair budget is exhausted" in out3
    assert len(attempts) == 2


def test_successful_question_records_attempts_trace(client):
    resp = client.post("/ask", json={"question": "What is the total revenue?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["repaired"] is False
    assert body["error"] is None
    assert len(body["attempts"]) == 1
    assert body["attempts"][0]["error"] is None
    assert body["attempts"][0]["sql"] == body["sql"]
