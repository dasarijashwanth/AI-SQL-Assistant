import pytest

from app.guard import UnsafeQueryError, validate_select


def test_rejects_delete():
    with pytest.raises(UnsafeQueryError):
        validate_select("DELETE FROM orders WHERE id = 1")


def test_rejects_drop():
    with pytest.raises(UnsafeQueryError):
        validate_select("DROP TABLE orders")


def test_rejects_update():
    with pytest.raises(UnsafeQueryError):
        validate_select("UPDATE orders SET status = 'x' WHERE id = 1")


def test_rejects_insert():
    with pytest.raises(UnsafeQueryError):
        validate_select("INSERT INTO orders VALUES (1, 2, '2026-01-01', 'paid', 10.0)")


def test_rejects_multi_statement():
    with pytest.raises(UnsafeQueryError):
        validate_select("SELECT * FROM orders; DROP TABLE orders")


def test_accepts_select_and_enforces_limit():
    sql = validate_select("SELECT * FROM orders", row_limit=50)
    assert sql.upper().startswith("SELECT")
    assert sql.rstrip().upper().endswith("LIMIT 50")


def test_keeps_smaller_limit():
    sql = validate_select("SELECT * FROM orders LIMIT 5")
    assert sql.rstrip().upper().endswith("LIMIT 5")


def test_clamps_large_limit():
    sql = validate_select("SELECT * FROM orders LIMIT 10000", row_limit=200)
    assert sql.rstrip().upper().endswith("LIMIT 200")


def test_write_keyword_inside_string_literal_is_allowed():
    sql = validate_select("SELECT * FROM products WHERE name = 'Delete Pro'")
    assert sql.upper().startswith("SELECT")
