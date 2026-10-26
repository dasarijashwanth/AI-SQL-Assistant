"""FastAPI surface for the AI SQL assistant.

Endpoints:
- GET  /health  service status, including which LLM mode is active
- GET  /schema  table and column listing for the demo database
- POST /ask     natural-language question, answered by the agent
- POST /query   guarded direct SELECT execution (transparency/debugging)
"""
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent_service import ask_question
from .config import get_db_path, get_model_name, llm_mode
from .db import get_schema, run_select
from .guard import UnsafeQueryError, validate_select

app = FastAPI(
    title="AI SQL Assistant",
    description=(
        "Read-only natural-language SQL over a demo e-commerce database."
    ),
)


class AskRequest(BaseModel):
    question: str


class QueryRequest(BaseModel):
    sql: str


def _require_db() -> None:
    if not os.path.exists(get_db_path()):
        raise HTTPException(
            status_code=503,
            detail=(
                "Demo database not found. Build it first: "
                "python scripts/build_demo_db.py"
            ),
        )


@app.get("/health")
def health():
    mode = llm_mode()
    return {
        "status": "ok",
        "llm": mode,
        "model": get_model_name() if mode == "openai" else "fake-offline",
    }


@app.get("/schema")
def schema():
    _require_db()
    return get_schema()


@app.post("/ask")
def ask(payload: AskRequest):
    _require_db()
    try:
        return ask_question(payload.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/query")
def query(payload: QueryRequest):
    _require_db()
    try:
        safe_sql = validate_select(payload.sql)
    except UnsafeQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = run_select(safe_sql)
    return {"sql": safe_sql, "rows": rows, "row_count": len(rows)}
