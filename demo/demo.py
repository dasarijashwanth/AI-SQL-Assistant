#!/usr/bin/env python3
"""Day 6 demo walkthrough for the AI SQL Assistant.

Runs the full demo end to end with no API key and no network: the
offline fake LLM answers the happy-path question, and the real
read-only guard rejects a write attempt live.

Run it from the project root with the project venv:

    ~/.venv-week4/bin/python demo/demo.py
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force the deterministic fake-LLM path: the demo must work offline.
os.environ.pop("OPENAI_API_KEY", None)

from app.agent_service import ask_question
from app.db import get_sql_database, run_select
from app.fake_llm import FakeSQLChatModel
from app.guard import UnsafeQueryError, validate_select
from app.tools import build_tools


def divider(title: str) -> None:
    print()
    print("=" * 64)
    print(title)
    print("=" * 64)


def part1_happy_path() -> None:
    divider("PART 1: happy path (ask a question, see the answer, SQL, trace)")
    question = "What is the total revenue?"
    print(f"\nQuestion: {question}\n")
    result = ask_question(question)
    print(f"Answer: {result['explanation']}")
    print(f"State: {'repaired' if result['repaired'] else 'grounded'}")
    print(f"\nGenerated SQL:\n  {result['sql']}")
    print("\nAttempts trace:")
    for i, attempt in enumerate(result["attempts"], start=1):
        status = "ok" if attempt["error"] is None else "ERROR"
        print(f"  attempt {i} [{status}]: {attempt['sql']}")
        if attempt["error"]:
            print(f"    error: {attempt['error']}")
    rows = result["rows"]
    print(f"\nRows returned: {result['row_count']}")
    for row in rows:
        print(f"  {dict(row)}")


def part2_guard_rejection() -> None:
    divider("PART 2: the guard rejects a write attempt, live")
    hostile = "DELETE FROM orders"

    print(f"\nAttempt: {hostile}\n")

    # Layer 1: the guard itself, the same validate_select() the API and
    # the agent tools call.
    try:
        validate_select(hostile)
        print("UNEXPECTED: the guard let the DELETE through.")
    except UnsafeQueryError as exc:
        print(f"Guard: blocked. Reason: {exc}")

    # Layer 2: the exact tool the agent uses to check queries
    # (sql_db_query_checker), so this is what the agent would see.
    db = get_sql_database()
    tools = build_tools(db, FakeSQLChatModel(), [])
    checker = next(t for t in tools if t.name == "sql_db_query_checker")
    print(f"\nAgent's query checker says:\n  {checker.invoke(hostile)}")

    # Proof nothing was touched.
    count = run_select("SELECT COUNT(*) AS n FROM orders")[0]["n"]
    print(f"\nOrders table row count after the attempt: {count} (unchanged)")


def main() -> None:
    print("AI SQL Assistant: demo walkthrough (offline fake-LLM mode)")
    part1_happy_path()
    part2_guard_rejection()
    divider("DEMO COMPLETE")


if __name__ == "__main__":
    main()
