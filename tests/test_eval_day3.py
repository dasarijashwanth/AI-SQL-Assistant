"""Tests for the Day 3 eval harness (app/eval.py)."""
import json

from app.eval import (
    check_result,
    load_questions,
    run_adversarial,
    run_eval,
    score_agent,
)
from app.fake_llm import sql_for_question


def test_check_result_variants():
    rows = [{"n": 5}, {"n": 6}]
    assert check_result({"type": "non_empty"}, rows)
    assert not check_result({"type": "non_empty"}, [])
    assert check_result({"type": "min_rows", "value": 2}, rows)
    assert not check_result({"type": "min_rows", "value": 3}, rows)
    assert check_result(
        {"type": "scalar_positive", "column": "n"}, [{"n": 1.5}]
    )
    assert not check_result(
        {"type": "scalar_positive", "column": "n"}, [{"n": 0}]
    )
    assert not check_result(
        {"type": "scalar_positive", "column": "n"}, []
    )
    assert check_result(
        {"type": "exact_scalar", "column": "n", "value": 40}, [{"n": 40}]
    )
    assert not check_result(
        {"type": "exact_scalar", "column": "n", "value": 40}, [{"n": 41}]
    )


def test_score_agent_requires_sql_shape():
    item = {
        "check": {"type": "min_rows", "value": 5},
        "sql_contains": ["GROUP BY p.category"],
    }
    good = {
        "sql": "SELECT p.category FROM x GROUP BY p.category",
        "rows": [{}, {}, {}, {}, {}],
        "explanation": "Done.",
    }
    passed, reasons = score_agent(item, good)
    assert passed and reasons == []
    wrong_sql = dict(good, sql="SELECT * FROM orders")
    passed, reasons = score_agent(item, wrong_sql)
    assert not passed
    assert any("GROUP BY p.category" in r for r in reasons)


def test_fake_map_routes_day3_families():
    assert "GROUP BY p.category" in sql_for_question(
        "Which product categories generate the most revenue?"
    )
    assert "substr(order_date, 1, 7)" in sql_for_question(
        "What is the monthly revenue trend?"
    )
    assert "AVG(rating)" in sql_for_question(
        "What is the average product rating?"
    )
    assert "p.category = 'Electronics'" in sql_for_question(
        "Which customers spent the most on Electronics products?"
    )
    # The three Day 1 wired questions keep their original mapping.
    assert "SUM(total_amount)" in sql_for_question("What is the total revenue?")
    assert "units_sold" in sql_for_question(
        "What are the top 5 products by units sold?"
    )
    assert "substr(order_date, 1, 7)" in sql_for_question(
        "How many orders were placed per month?"
    )


def test_adversarial_guard_rejects_writes():
    for attack in (
        "DELETE FROM orders WHERE status = 'cancelled'",
        "UPDATE products SET price = 0",
        "SELECT * FROM orders; DROP TABLE customers",
    ):
        passed, detail = run_adversarial(
            {"mechanism": "guard_reject", "attack_sql": attack}
        )
        assert passed, detail


def test_adversarial_limit_clamped():
    passed, detail = run_adversarial(
        {
            "mechanism": "guard_clamp",
            "attack_sql": "SELECT * FROM orders LIMIT 100000",
            "expect_limit": 200,
        }
    )
    assert passed, detail


def test_adversarial_tool_rejects_injection_name():
    passed, detail = run_adversarial(
        {
            "mechanism": "tool_reject",
            "table_name": "orders; DROP TABLE customers",
        }
    )
    assert passed, detail


def test_harness_runs_subset_end_to_end(tmp_path):
    questions = load_questions("evals/questions_day3.json")
    subset = [questions[0], questions[1], questions[20]]
    summary = run_eval(subset)
    assert summary["total"] == 3
    assert summary["passed"] + summary["failed"] == 3
    assert summary["agent_total"] == 2
    assert summary["adversarial_total"] == 1
    assert summary["mutation_check"]["unchanged"] is True
    assert summary["mutation_check"]["orders_before"] == 120
    for record in summary["results"]:
        assert record["question"]
        assert isinstance(record["passed"], bool)
    assert all(r["passed"] for r in summary["results"])


def test_harness_questions_file_has_25():
    questions = load_questions("evals/questions_day3.json")
    assert len(questions) == 25
    kinds = [q["kind"] for q in questions]
    assert kinds.count("agent") == 20
    assert kinds.count("adversarial") == 5
    assert [q["id"] for q in questions] == list(range(1, 26))
