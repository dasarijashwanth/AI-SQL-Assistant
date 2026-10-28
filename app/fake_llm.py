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
CATEGORY_REVENUE_SQL = (
    "SELECT p.category AS category, "
    "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
    "FROM order_items oi JOIN products p ON p.id = oi.product_id "
    "GROUP BY p.category ORDER BY revenue DESC"
)
MONTHLY_REVENUE_SQL = (
    "SELECT substr(order_date, 1, 7) AS month, "
    "ROUND(SUM(total_amount), 2) AS revenue "
    "FROM orders WHERE status IN ('completed', 'shipped') "
    "GROUP BY month ORDER BY month"
)
AVG_ORDER_VALUE_SQL = (
    "SELECT ROUND(AVG(total_amount), 2) AS avg_order_value "
    "FROM orders WHERE status != 'cancelled'"
)
AVG_RATING_SQL = "SELECT ROUND(AVG(rating), 2) AS avg_rating FROM reviews"
TOP_RATED_SQL = (
    "SELECT p.name AS product, ROUND(AVG(r.rating), 2) AS avg_rating, "
    "COUNT(*) AS review_count FROM reviews r "
    "JOIN products p ON p.id = r.product_id "
    "GROUP BY p.name HAVING COUNT(*) >= 3 ORDER BY avg_rating DESC"
)
MOST_REVIEWED_SQL = (
    "SELECT p.name AS product, COUNT(*) AS review_count FROM reviews r "
    "JOIN products p ON p.id = r.product_id "
    "GROUP BY p.name ORDER BY review_count DESC LIMIT 1"
)
REVIEW_COUNT_SQL = "SELECT COUNT(*) AS review_count FROM reviews"
TOP_CUSTOMERS_SQL = (
    "SELECT c.name AS customer, ROUND(SUM(o.total_amount), 2) AS total_spend "
    "FROM orders o JOIN customers c ON c.id = o.customer_id "
    "WHERE o.status != 'cancelled' "
    "GROUP BY c.name ORDER BY total_spend DESC LIMIT 5"
)
ELECTRONICS_CUSTOMERS_SQL = (
    "SELECT c.name AS customer, "
    "ROUND(SUM(oi.quantity * oi.unit_price), 2) AS electronics_spend "
    "FROM orders o JOIN customers c ON c.id = o.customer_id "
    "JOIN order_items oi ON oi.order_id = o.id "
    "JOIN products p ON p.id = oi.product_id "
    "WHERE p.category = 'Electronics' "
    "GROUP BY c.name ORDER BY electronics_spend DESC LIMIT 5"
)
CUSTOMER_COUNT_SQL = "SELECT COUNT(*) AS customer_count FROM customers"
PRODUCT_COUNT_SQL = "SELECT COUNT(*) AS product_count FROM products"
ORDER_COUNT_SQL = "SELECT COUNT(*) AS order_count FROM orders"
STATUS_COUNTS_SQL = (
    "SELECT status, COUNT(*) AS order_count FROM orders "
    "GROUP BY status ORDER BY order_count DESC"
)
PAYMENT_METHODS_SQL = (
    "SELECT method, COUNT(*) AS payment_count FROM payments "
    "GROUP BY method ORDER BY payment_count DESC"
)
RECENT_ORDERS_SQL = (
    "SELECT id, customer_id, order_date, total_amount, status FROM orders "
    "ORDER BY order_date DESC LIMIT 10"
)
PENDING_ORDERS_SQL = (
    "SELECT id, customer_id, order_date, total_amount FROM orders "
    "WHERE status = 'pending' ORDER BY order_date"
)
PRODUCTS_BY_PRICE_SQL = (
    "SELECT name, price, category FROM products "
    "ORDER BY price DESC LIMIT 5"
)
LARGEST_ORDERS_SQL = (
    "SELECT id, customer_id, order_date, total_amount FROM orders "
    "ORDER BY total_amount DESC LIMIT 10"
)
DEFAULT_SQL = "SELECT * FROM orders"


def sql_for_question(question: str) -> str:
    """Keyword map from a natural-language question to canned SQL.

    Ordered most specific first. The three Day 1 wired questions keep
    their original mapping: total revenue, top products by units, and
    orders per month. Day 3 adds one branch per new question family so
    the eval harness can check that the pipeline routes each family to
    a sensible query; the map is a stand-in for a real model, not a
    measure of open-ended question understanding.
    """
    q = question.lower()
    if "categor" in q:
        return CATEGORY_REVENUE_SQL
    if "month" in q and "revenue" in q:
        return MONTHLY_REVENUE_SQL
    if "month" in q:
        return ORDERS_PER_MONTH_SQL
    if "average" in q and "rating" in q:
        return AVG_RATING_SQL
    if "rating" in q or "rated" in q:
        return TOP_RATED_SQL
    if "how many reviews" in q or "number of reviews" in q:
        return REVIEW_COUNT_SQL
    if "review" in q:
        return MOST_REVIEWED_SQL
    if "product" in q and (
        "top" in q or "best" in q or "units" in q or "sold" in q
    ):
        return TOP_PRODUCTS_SQL
    if "average" in q and "order" in q:
        return AVG_ORDER_VALUE_SQL
    if "electronic" in q:
        return ELECTRONICS_CUSTOMERS_SQL
    if "customer" in q and ("top" in q or "spen" in q):
        return TOP_CUSTOMERS_SQL
    if "how many customers" in q or "number of customers" in q:
        return CUSTOMER_COUNT_SQL
    if "how many products" in q or "number of products" in q:
        return PRODUCT_COUNT_SQL
    if "status" in q:
        return STATUS_COUNTS_SQL
    if "payment" in q:
        return PAYMENT_METHODS_SQL
    if "recent" in q or "latest" in q:
        return RECENT_ORDERS_SQL
    if "pending" in q:
        return PENDING_ORDERS_SQL
    if "expensive" in q or "cheapest" in q:
        return PRODUCTS_BY_PRICE_SQL
    if "revenue" in q or "sales" in q or "earned" in q:
        return TOTAL_REVENUE_SQL
    if (
        "how many orders" in q
        or "total orders" in q
        or "number of orders" in q
    ):
        return ORDER_COUNT_SQL
    if ("largest" in q or "biggest" in q) and "order" in q:
        return LARGEST_ORDERS_SQL
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
