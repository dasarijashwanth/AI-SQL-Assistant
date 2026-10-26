"""Deterministic offline chat model.

When OPENAI_API_KEY is not set, the app uses FakeSQLChatModel instead
of a real LLM. It is a tiny state machine over the agent's tool-call
loop: list tables, read schema, check a query, run it, then summarize.
The SQL it issues comes from a keyword map over the demo questions, so
the full pipeline (agent, tools, guard, database) runs end to end with
no network and no API key. That is what makes the test suite and the
demo reproducible anywhere.
"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ALL_TABLES = "customers, products, orders, order_items, payments, reviews"

TOTAL_REVENUE_SQL = (
    "SELECT ROUND(SUM(total_amount), 2) AS total_revenue "
    "FROM orders WHERE status IN ('completed', 'shipped')"
)
TOP_PRODUCTS_SQL = (
    "SELECT p.name AS product, SUM(oi.quantity) AS units_sold "
    "FROM order_items oi "
    "JOIN products p ON p.id = oi.product_id "
    "JOIN orders o ON o.id = oi.order_id "
    "WHERE o.status != 'cancelled' "
    "GROUP BY p.name ORDER BY units_sold DESC LIMIT 5"
)
ORDERS_PER_MONTH_SQL = (
    "SELECT substr(order_date, 1, 7) AS month, COUNT(*) AS order_count "
    "FROM orders GROUP BY month ORDER BY month"
)
DEFAULT_SQL = "SELECT * FROM orders"


def sql_for_question(question: str) -> str:
    """Keyword map from a natural-language question to canned SQL."""
    q = question.lower()
    if "product" in q and (
        "top" in q or "best" in q or "units" in q or "sold" in q
    ):
        return TOP_PRODUCTS_SQL
    if "month" in q:
        return ORDERS_PER_MONTH_SQL
    if "revenue" in q or "sales" in q or "earned" in q:
        return TOTAL_REVENUE_SQL
    return DEFAULT_SQL


class FakeSQLChatModel(BaseChatModel):
    """A deterministic stand-in chat model for offline runs and tests."""

    @property
    def _llm_type(self) -> str:
        return "fake-sql-chat-model"

    def bind_tools(self, tools, **kwargs):
        # The generic BaseChatModel.bind_tools raises NotImplementedError.
        # Binding the tools as plain call kwargs is enough here: _generate
        # ignores them and decides purely from the conversation state.
        return self.bind(tools=list(tools), **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._decide(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _decide(self, messages) -> AIMessage:
        question = ""
        for m in messages:
            if isinstance(m, HumanMessage) and isinstance(m.content, str):
                question = m.content
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        step = len(tool_msgs)
        if not tool_msgs:
            return self._tool_call("sql_db_list_tables", {}, step)
        last = tool_msgs[-1]
        name = getattr(last, "name", "") or ""
        if name == "sql_db_list_tables":
            return self._tool_call(
                "sql_db_schema", {"table_names": ALL_TABLES}, step
            )
        if name == "sql_db_schema":
            return self._tool_call(
                "sql_db_query_checker",
                {"query": sql_for_question(question)},
                step,
            )
        if name == "sql_db_query_checker":
            return self._tool_call(
                "sql_db_query", {"query": str(last.content).strip()}, step
            )
        if name == "sql_db_query":
            return AIMessage(content=f"Query executed. Result: {last.content}")
        return AIMessage(content="I could not complete that request.")

    @staticmethod
    def _tool_call(name: str, args: dict, step: int) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": f"fake-call-{step}",
                    "type": "tool_call",
                }
            ],
        )
