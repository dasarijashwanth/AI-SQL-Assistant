# Demo script: AI SQL Assistant (Day 6)

A scripted walkthrough you can run live or narrate over. Everything
runs fully offline with the deterministic fake LLM (no API key), and
the whole thing takes about two minutes.

Run it from the project root:

```bash
~/.venv-week4/bin/python demo/demo.py
```

Or step through it by hand in the Streamlit UI:

```bash
streamlit run app/ui.py
```

## Part 1: happy path

1. Ask: **"What is the total revenue?"**
2. Point out the three things in the answer:
   - the one-line plain-English answer,
   - the generated SQL in the expander (`SELECT ROUND(SUM(total_amount),
     2) AS total_revenue FROM orders WHERE status IN ('completed',
     'shipped')`),
   - the attempts trace (one attempt, succeeded) and the result rows.
3. Note the state badge: **grounded** means the answer came from the
   database.

## Part 2: the guard rejects a write, live

1. Try the hostile input: **"DELETE FROM orders"** (or run part 2 of
   `demo/demo.py`).
2. Show the rejection: the guard raises "Only SELECT statements are
   allowed" / "Write keyword(s) not allowed", and the agent's
   `sql_db_query_checker` tool returns the same block as policy
   feedback with a concrete fix hint.
3. Prove nothing was touched: `SELECT COUNT(*) FROM orders` still
   returns **120 rows**.

## Talking points

- Read-only is enforced in three independent layers: the query guard
  (`app/guard.py`), the checker-tool swap (`app/tools.py`), and the
  SQLite read-only connection (`app/db.py`).
- Every executed query is captured and shown; failures get exactly one
  bounded repair attempt, then an honest failure, never a retry loop.
- The demo database is synthetic and regenerable
  (`scripts/build_demo_db.py`).
