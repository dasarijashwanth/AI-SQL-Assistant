"""Configuration for the SQL assistant.

Everything is driven by environment variables so the same code runs in
tests, local dev, and demos:

- SQL_ASSISTANT_DB_PATH: path to the SQLite demo database
  (default: <project>/data/demo.db)
- SQL_ASSISTANT_MODEL: model name for the real LLM
  (default: gpt-4o-mini)
- OPENAI_API_KEY: when unset, the app uses a deterministic fake chat
  model so everything works fully offline (see app/fake_llm.py).
- SQL_ASSISTANT_ROW_LIMIT: hard cap on rows any query may return
  (default: 200)
- SQL_ASSISTANT_QUERY_TIMEOUT: max seconds any single database query
  may run before it is interrupted (default: 10)
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_db_path() -> str:
    return os.environ.get(
        "SQL_ASSISTANT_DB_PATH", str(PROJECT_ROOT / "data" / "demo.db")
    )


def get_model_name() -> str:
    return os.environ.get("SQL_ASSISTANT_MODEL", "gpt-4o-mini")


def get_row_limit() -> int:
    return int(os.environ.get("SQL_ASSISTANT_ROW_LIMIT", "200"))


def get_query_timeout() -> float:
    return float(os.environ.get("SQL_ASSISTANT_QUERY_TIMEOUT", "10"))


def llm_mode() -> str:
    return "openai" if os.environ.get("OPENAI_API_KEY") else "fake"
