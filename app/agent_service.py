"""Ask-a-question service: wires the LLM, tools, and agent together.

The agent is built with LangChain v1's create_agent and the
SQLDatabaseToolkit tools. When OPENAI_API_KEY is set, the model is a
real OpenAI chat model (name from SQL_ASSISTANT_MODEL). When it is not
set, a deterministic fake chat model is used instead, so the whole
pipeline runs offline (see app/fake_llm.py).
"""
import os

from langchain.agents import create_agent
from langchain_core.messages import AIMessage

from .config import get_model_name
from .db import get_sql_database, run_select
from .fake_llm import FakeSQLChatModel
from .tools import build_tools

SYSTEM_PROMPT = (
    "You are a careful data assistant that answers questions by querying a "
    "SQLite database of e-commerce orders. These rules are not negotiable:\n"
    "1. Read-only, always. Only SELECT statements are allowed. Never "
    "INSERT, UPDATE, DELETE, DROP, or any other write, and never try to "
    "work around the guard.\n"
    "2. Work in this order: list the tables, read their schemas, peek at "
    "sample rows with sql_db_sample_rows for any table you will filter, "
    "then run sql_db_query_checker, then sql_db_query. Never run a query "
    "you have not checked.\n"
    "3. Never guess literal values. Before filtering on a status, "
    "category, or any other coded value, look up its real values with "
    "sql_db_distinct_values and use exactly one of them.\n"
    "4. Keep result sets small: prefer aggregates and explicit LIMITs "
    "over dumping whole tables.\n"
    "5. If the checker or the query tool returns an error, read the "
    "reason, fix that specific problem, and try once more at most. "
    "You get exactly one repair attempt per question: if the retry "
    "also fails, stop and report the failure honestly. Never "
    "repeat a rejected query unchanged, and never invent rows to cover "
    "a failed query.\n"
    "6. When you have the result, answer with one short plain-English "
    "sentence. If the query returned no rows, say so plainly instead of "
    "guessing an answer."
)


def get_llm():
    if os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=get_model_name(), temperature=0)
    return FakeSQLChatModel()


def ask_question(question: str) -> dict:
    """Run the agent for one question, with a bounded repair budget.

    The response always includes an ``attempts`` trace: one entry per
    executed query with its SQL and any execution error, so the retry
    is visible. ``repaired`` is True when at least one attempt failed
    before the final outcome. If the last attempt failed (the repair
    budget is spent), the response carries the error visibly with
    empty rows instead of raising: the failure is the answer.
    """
    db = get_sql_database()
    llm = get_llm()
    captured_sql: list[str] = []
    attempts: list[dict] = []
    tools = build_tools(db, llm, captured_sql, attempts)
    agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    if not attempts:
        raise RuntimeError(
            "The agent did not run any query. The last tool result may "
            "have been an error (for example, a query the read-only "
            "guard rejected or one that timed out); check the agent "
            "trace and rephrase the question."
        )
    explanation = ""
    for message in reversed(result["messages"]):
        if (
            isinstance(message, AIMessage)
            and isinstance(message.content, str)
            and message.content.strip()
        ):
            explanation = message.content.strip().splitlines()[0]
            break
    last = attempts[-1]
    repaired = any(a["error"] is not None for a in attempts)
    if last["error"] is None:
        # One final execution of the winning query, exactly as before
        # Day 4: the timeout still surfaces here as an HTTP 504.
        rows = run_select(last["sql"])
        return {
            "question": question,
            "sql": last["sql"],
            "rows": rows,
            "row_count": len(rows),
            "explanation": explanation,
            "attempts": attempts,
            "repaired": repaired,
            "error": None,
        }
    return {
        "question": question,
        "sql": last["sql"],
        "rows": [],
        "row_count": 0,
        "explanation": explanation
        or "The query failed and the one repair attempt also failed.",
        "attempts": attempts,
        "repaired": repaired,
        "error": last["error"],
    }
