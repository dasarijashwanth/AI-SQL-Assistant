def test_health_reports_fake_offline_mode(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm"] == "fake"


def test_schema_loads_all_tables(client):
    resp = client.get("/schema")
    assert resp.status_code == 200
    tables = {t["name"]: t for t in resp.json()["tables"]}
    assert set(tables) == {
        "customers", "products", "orders",
        "order_items", "payments", "reviews",
    }
    order_cols = {c["name"] for c in tables["orders"]["columns"]}
    assert "total_amount" in order_cols
    assert "customer_id" in order_cols


def test_ask_total_revenue_offline(client):
    resp = client.post("/ask", json={"question": "What is the total revenue?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sql"].lstrip().upper().startswith("SELECT")
    assert body["row_count"] >= 1
    assert body["rows"][0]["total_revenue"] > 0


def test_ask_top_products_offline(client):
    resp = client.post(
        "/ask", json={"question": "What are the top 5 products by units sold?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == 5
    assert "units_sold" in body["rows"][0]
    units = [r["units_sold"] for r in body["rows"]]
    assert units == sorted(units, reverse=True)


def test_ask_orders_per_month_offline(client):
    resp = client.post(
        "/ask", json={"question": "How many orders were placed per month?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] >= 6
    assert "order_count" in body["rows"][0]
    assert sum(r["order_count"] for r in body["rows"]) == 120


def test_query_valid_select(client):
    resp = client.post("/query", json={"sql": "SELECT COUNT(*) AS n FROM orders"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"][0]["n"] == 120
    assert body["row_count"] == 1


def test_query_rejects_write(client):
    resp = client.post("/query", json={"sql": "DELETE FROM orders WHERE id = 1"})
    assert resp.status_code == 400


def test_query_rejects_drop(client):
    resp = client.post("/query", json={"sql": "DROP TABLE orders"})
    assert resp.status_code == 400
