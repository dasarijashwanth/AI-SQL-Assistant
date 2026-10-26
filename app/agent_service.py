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
    "SQLite database of e-commerce orders. Work read-only: first list the "
    "tables, then read their schemas, then check your query with "
    "sql_db_query_checker, then run it with sql_db_query. Only SELECT "
    "statements are allowed; a guard rejects writes, multiple statements, "
    "and unbounded result sets. If a query errors, fix it and try once "
    "more. When you have the result, answer with one short plain-English "
    "sentence."
)


def get_llm():
    if os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=get_model_name(), temperature=0)
    return FakeSQLChatModel()


def ask_question(question: str) -> dict:
    db = get_sql_database()
    llm = get_llm()
    captured_sql: list[str] = []
    tools = build_tools(db, llm, captured_sql)
    agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    if not captured_sql:
        raise RuntimeError("The agent did not run any query.")
    sql = captured_sql[-1]
    rows = run_select(sql)
    explanation = ""
    for message in reversed(result["messages"]):
        if (
            isinstance(message, AIMessage)
            and isinstance(message.content, str)
            and message.content.strip()
        ):
            explanation = message.content.strip().splitlines()[0]
            break
    return {
        "question": question,
        "sql": sql,
        "rows": rows,
        "row_count": len(rows),
        "explanation": explanation,
    }
