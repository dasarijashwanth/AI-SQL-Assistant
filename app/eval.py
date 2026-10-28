"""Day 3 eval harness: 25 questions, scored honestly.

Two kinds of items, scored differently on purpose:

- Agent questions (kind "agent") run end to end through
  ``ask_question``: the agent loop, the guard, and the read-only
  database are all real. A question passes only if the agent
  completes, the produced SQL contains the expected shape
  (``sql_contains``), the result check holds (row count, positive
  scalar, exact count, or non-empty), and the explanation is
  non-empty. In offline fake-LLM mode this measures pipeline
  correctness (the keyword-mapped stand-in routes each question
  family to a sensible query, the guard lets it through, the
  database answers it), not open-ended model reasoning. With a real
  model behind the same code path, the same harness and checks
  apply unchanged.

- Adversarial items (kind "adversarial") never reach the agent.
  They are aimed straight at the safety layers: the guard must
  reject writes and multi-statement input, clamp an oversized
  LIMIT to the row cap, and the exploration tools must reject
  injection-style table names. A final row-count check proves no
  adversarial item mutated the database.
"""
import json
import re
import time
from pathlib import Path

from .agent_service import ask_question
from .db import get_sql_database, run_select
from .fake_llm import FakeSQLChatModel
from .guard import UnsafeQueryError, validate_select
from .tools import build_tools


def check_result(check: dict, rows: list[dict]) -> bool:
    """Evaluate one machine-checkable expectation against result rows."""
    kind = check["type"]
    if kind == "non_empty":
        return len(rows) >= 1
    if kind == "min_rows":
        return len(rows) >= check["value"]
    if kind == "scalar_positive":
        if not rows:
            return False
        value = rows[0].get(check["column"])
        return isinstance(value, (int, float)) and value > 0
    if kind == "exact_scalar":
        if not rows:
            return False
        return rows[0].get(check["column"]) == check["value"]
    raise ValueError(f"unknown check type: {kind!r}")


def score_agent(item: dict, result: dict) -> tuple[bool, list[str]]:
    """Score one completed agent run; returns (passed, reasons)."""
    reasons: list[str] = []
    sql = result.get("sql", "")
    for needle in item.get("sql_contains", []):
        if needle.lower() not in sql.lower():
            reasons.append(f"SQL missing {needle!r}")
    try:
        if not check_result(item["check"], result.get("rows", [])):
            reasons.append(f"result check failed: {item['check']}")
    except Exception as exc:  # noqa: BLE001 - report, don't crash the run
        reasons.append(f"check error: {exc}")
    if not result.get("explanation"):
        reasons.append("empty explanation")
    return (not reasons), reasons


def run_adversarial(item: dict) -> tuple[bool, str]:
    """Score one adversarial item against the safety layers."""
    mechanism = item["mechanism"]
    if mechanism == "guard_reject":
        try:
            validate_select(item["attack_sql"])
        except UnsafeQueryError as exc:
            return True, f"rejected: {exc}"
        return False, "guard accepted the attack SQL"
    if mechanism == "guard_clamp":
        try:
            safe = validate_select(item["attack_sql"])
        except UnsafeQueryError as exc:
            return False, f"unexpected rejection: {exc}"
        match = re.search(r"\bLIMIT\s+(\d+)\s*$", safe, re.IGNORECASE)
        limit = int(match.group(1)) if match else None
        if limit is not None and limit <= item["expect_limit"]:
            return True, f"clamped to LIMIT {limit}"
        return False, f"sanitized SQL kept LIMIT {limit}: {safe}"
    if mechanism == "tool_reject":
        tools = build_tools(get_sql_database(), FakeSQLChatModel(), [])
        tool = next(t for t in tools if t.name == "sql_db_sample_rows")
        output = tool.invoke({"table_name": item["table_name"]})
        if isinstance(output, str) and output.startswith(
            "Error: unknown table"
        ):
            return True, "rejected as unknown table"
        return False, f"tool accepted the name: {output!r}"
    raise ValueError(f"unknown mechanism: {mechanism!r}")


def run_eval(questions: list[dict], agent_runner=ask_question) -> dict:
    """Run every question and return per-item records plus a summary."""
    before = run_select("SELECT COUNT(*) AS n FROM orders")[0]["n"]
    records: list[dict] = []
    for item in questions:
        if item["kind"] == "agent":
            start = time.monotonic()
            try:
                result = agent_runner(item["question"])
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                passed, reasons = score_agent(item, result)
                records.append(
                    {
                        "id": item["id"],
                        "kind": "agent",
                        "question": item["question"],
                        "passed": passed,
                        "reasons": reasons,
                        "sql": result.get("sql", ""),
                        "row_count": result.get("row_count", 0),
                        "latency_ms": latency_ms,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - a failed item
                records.append(
                    {
                        "id": item["id"],
                        "kind": "agent",
                        "question": item["question"],
                        "passed": False,
                        "reasons": [f"agent error: {exc}"],
                        "sql": "",
                        "row_count": 0,
                        "latency_ms": round(
                            (time.monotonic() - start) * 1000, 1
                        ),
                    }
                )
        elif item["kind"] == "adversarial":
            passed, detail = run_adversarial(item)
            records.append(
                {
                    "id": item["id"],
                    "kind": "adversarial",
                    "question": item["question"],
                    "passed": passed,
                    "reasons": [] if passed else [detail],
                    "detail": detail,
                    "sql": item.get("attack_sql", ""),
                    "row_count": 0,
                    "latency_ms": 0.0,
                }
            )
        else:
            raise ValueError(f"unknown kind: {item['kind']!r}")
    after = run_select("SELECT COUNT(*) AS n FROM orders")[0]["n"]
    passed = sum(1 for r in records if r["passed"])
    agent_records = [r for r in records if r["kind"] == "agent"]
    agent_latency = (
        round(
            sum(r["latency_ms"] for r in agent_records) / len(agent_records),
            1,
        )
        if agent_records
        else 0.0
    )
    return {
        "total": len(records),
        "passed": passed,
        "failed": len(records) - passed,
        "agent_passed": sum(1 for r in agent_records if r["passed"]),
        "agent_total": len(agent_records),
        "adversarial_passed": sum(
            1
            for r in records
            if r["kind"] == "adversarial" and r["passed"]
        ),
        "adversarial_total": len(records) - len(agent_records),
        "avg_agent_latency_ms": agent_latency,
        "mutation_check": {
            "orders_before": before,
            "orders_after": after,
            "unchanged": before == after,
        },
        "results": records,
    }


def format_report(summary: dict) -> str:
    """Render the eval summary as Markdown for evals/results_day3.md."""
    lines = [
        "# Day 3 eval results",
        "",
        "Offline fake-LLM mode: the agent loop, guard, and database are",
        "real; only the language model is a keyword-mapped stand-in (see",
        "app/fake_llm.py). Agent questions measure pipeline correctness,",
        "adversarial items measure the safety layers directly.",
        "",
        f"Score: {summary['passed']}/{summary['total']} "
        f"(agent {summary['agent_passed']}/{summary['agent_total']}, "
        f"adversarial {summary['adversarial_passed']}/"
        f"{summary['adversarial_total']})",
        f"Average agent latency: {summary['avg_agent_latency_ms']} ms",
        f"Mutation check: orders {summary['mutation_check']['orders_before']} "
        f"before, {summary['mutation_check']['orders_after']} after, "
        f"unchanged={summary['mutation_check']['unchanged']}",
        "",
        "| ID | Kind | Passed | Rows | Latency (ms) | Question |",
        "|----|------|--------|------|--------------|----------|",
    ]
    for r in summary["results"]:
        lines.append(
            f"| {r['id']} | {r['kind']} | "
            f"{'pass' if r['passed'] else 'FAIL'} | {r['row_count']} | "
            f"{r['latency_ms']} | {r['question']} |"
        )
    lines.append("")
    for r in summary["results"]:
        if not r["passed"]:
            lines.append(f"- Q{r['id']} failed: {'; '.join(r['reasons'])}")
            lines.append(f"  SQL: `{r['sql']}`")
    lines.append("")
    return "\n".join(lines)


def load_questions(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_results(summary: dict, md_path: str | Path, json_path: str | Path):
    Path(md_path).write_text(format_report(summary), encoding="utf-8")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
