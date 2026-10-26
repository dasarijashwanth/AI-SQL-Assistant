"""Build the deterministic e-commerce demo database.

Usage:
    python scripts/build_demo_db.py [--out PATH]

Default output: data/demo.db (relative to the project root).

The data is synthetic and seeded (random.Random(42)), so the content
is reproducible on any machine: 40 customers, 25 products, 120 orders
spread across Oct 2025 to Sep 2026, with matching order_items,
payments, and reviews. Commit this script, not just the database.
"""
import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SEED = 42
START_DATE = date(2025, 10, 1)
END_DATE = date(2026, 9, 30)

FIRST_NAMES = [
    "Ava", "Liam", "Maya", "Noah", "Zoe", "Eli", "Ivy", "Owen",
    "Ruby", "Leo", "Nora", "Ezra", "Lila", "Amos", "Cleo", "Hugo",
    "Mira", "Silas", "Tara", "Jonas",
]
LAST_NAMES = [
    "Bennett", "Garcia", "Kim", "Novak", "Patel", "Rossi", "Tanaka",
    "Weber", "Ali", "Novikova", "Chen", "Dubois", "Fischer", "Haddad",
    "Ivanov", "Johnson", "Kowalski", "Lopez", "Meier", "Nasser",
]
CITIES = [
    ("Austin", "TX"), ("Denver", "CO"), ("Seattle", "WA"),
    ("Chicago", "IL"), ("Miami", "FL"), ("Boston", "MA"),
    ("Portland", "OR"), ("Atlanta", "GA"), ("Phoenix", "AZ"),
    ("Dallas", "TX"),
]
PRODUCTS = [
    ("Wireless Noise-Canceling Headphones", "Electronics", 199.99),
    ("Mechanical Keyboard", "Electronics", 129.50),
    ("USB-C Docking Station", "Electronics", 89.99),
    ("27-inch 4K Monitor", "Electronics", 329.00),
    ("Portable SSD 1TB", "Electronics", 119.99),
    ("Ceramic Pour-Over Coffee Set", "Home", 64.95),
    ("Smart LED Floor Lamp", "Home", 79.99),
    ("Memory Foam Pillow", "Home", 49.95),
    ("Cast Iron Skillet", "Home", 39.99),
    ("Robot Vacuum", "Home", 249.00),
    ("Adjustable Dumbbell 25lb", "Fitness", 149.00),
    ("Yoga Mat Pro", "Fitness", 59.95),
    ("Resistance Band Set", "Fitness", 29.99),
    ("Trail Running Shoes", "Fitness", 119.95),
    ("Insulated Steel Bottle", "Fitness", 24.95),
    ("The Data Detective", "Books", 18.99),
    ("Python in Practice", "Books", 44.95),
    ("A Brief History of Maps", "Books", 22.50),
    ("The Quiet Garden", "Books", 16.99),
    ("Deep Work Notes", "Books", 21.95),
    ("Merino Wool Hoodie", "Apparel", 98.00),
    ("Canvas Field Jacket", "Apparel", 139.00),
    ("Everyday Sneakers", "Apparel", 84.95),
    ("Linen Button-Down Shirt", "Apparel", 69.50),
    ("Wool Beanie", "Apparel", 28.00),
]
POSITIVE_COMMENTS = [
    "Exactly as described, works great.",
    "Solid quality, would buy again.",
    "Arrived fast and performs well.",
    "Really happy with this purchase.",
]
MID_COMMENTS = [
    "Good overall, minor quirks.",
    "Does the job, nothing fancy.",
]
NEGATIVE_COMMENTS = [
    "Not as durable as expected.",
    "Disappointed with the quality.",
]
ORDER_STATUSES = ["completed", "shipped", "pending", "cancelled", "returned"]
ORDER_STATUS_WEIGHTS = [0.62, 0.18, 0.08, 0.07, 0.05]
RATING_WEIGHTS = [5, 5, 4, 4, 4, 3, 3, 2, 1]

DDL = [
    "DROP TABLE IF EXISTS reviews",
    "DROP TABLE IF EXISTS payments",
    "DROP TABLE IF EXISTS order_items",
    "DROP TABLE IF EXISTS orders",
    "DROP TABLE IF EXISTS products",
    "DROP TABLE IF EXISTS customers",
    """CREATE TABLE customers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        city TEXT,
        state TEXT,
        created_at TEXT
    )""",
    """CREATE TABLE products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        price REAL NOT NULL,
        stock INTEGER NOT NULL
    )""",
    """CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        order_date TEXT NOT NULL,
        status TEXT NOT NULL,
        total_amount REAL NOT NULL
    )""",
    """CREATE TABLE order_items (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL
    )""",
    """CREATE TABLE payments (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        method TEXT NOT NULL,
        amount REAL NOT NULL,
        status TEXT NOT NULL,
        paid_at TEXT
    )""",
    """CREATE TABLE reviews (
        id INTEGER PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id),
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        rating INTEGER NOT NULL,
        comment TEXT,
        created_at TEXT
    )""",
]


def build(db_path: str) -> dict:
    """Generate the demo database at db_path. Returns row counts."""
    rng = random.Random(SEED)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        for stmt in DDL:
            cur.execute(stmt)

        customers = []
        for i in range(40):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            name = f"{first} {last}"
            email = f"{first.lower()}.{last.lower()}{i}@example.com"
            city, state = rng.choice(CITIES)
            created = START_DATE - timedelta(days=rng.randint(30, 400))
            customers.append((i + 1, name, email, city, state, created.isoformat()))
        cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)

        products = []
        for i, (name, category, price) in enumerate(PRODUCTS):
            products.append((i + 1, name, category, price, rng.randint(0, 200)))
        cur.executemany("INSERT INTO products VALUES (?,?,?,?,?)", products)
        price_by_id = {p[0]: p[3] for p in products}

        span_days = (END_DATE - START_DATE).days
        item_id = 0
        items_by_order: dict[int, list[tuple[int, int]]] = {}
        order_rows, item_rows = [], []
        for oid in range(1, 121):
            customer_id = rng.randint(1, 40)
            order_date = START_DATE + timedelta(days=rng.randint(0, span_days))
            status = rng.choices(ORDER_STATUSES, weights=ORDER_STATUS_WEIGHTS)[0]
            k = rng.randint(1, 4)
            product_ids = rng.sample(range(1, 26), k)
            total = 0.0
            items_by_order[oid] = []
            for pid in product_ids:
                item_id += 1
                qty = rng.randint(1, 5)
                unit_price = price_by_id[pid]
                total += qty * unit_price
                item_rows.append((item_id, oid, pid, qty, unit_price))
                items_by_order[oid].append((pid, customer_id))
            order_rows.append(
                (oid, customer_id, order_date.isoformat(), status, round(total, 2))
            )
        cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", order_rows)
        cur.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", item_rows)
        order_by_id = {o[0]: o for o in order_rows}

        payment_rows = []
        for pid_, (oid, customer_id, odate, status, total) in enumerate(
            order_rows, start=1
        ):
            method = rng.choice(["card", "card", "paypal", "apple_pay"])
            if status in ("completed", "shipped"):
                pay_status, paid_at = "paid", None
            elif status == "returned":
                pay_status, paid_at = "refunded", None
            elif status == "pending":
                pay_status, paid_at = "pending", None
            else:
                pay_status, paid_at = "void", None
            if pay_status in ("paid", "refunded"):
                base = date.fromisoformat(odate)
                paid_at = (base + timedelta(days=rng.randint(0, 2))).isoformat()
            payment_rows.append((pid_, oid, method, total, pay_status, paid_at))
        cur.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", payment_rows)

        review_rows = []
        rid = 0
        for oid, customer_id, odate, status, total in order_rows:
            if status != "completed" or rng.random() >= 0.65:
                continue
            rid += 1
            product_id = rng.choice(items_by_order[oid])[0]
            rating = rng.choice(RATING_WEIGHTS)
            if rating >= 4:
                comment = rng.choice(POSITIVE_COMMENTS)
            elif rating == 3:
                comment = rng.choice(MID_COMMENTS)
            else:
                comment = rng.choice(NEGATIVE_COMMENTS)
            created = date.fromisoformat(odate) + timedelta(days=rng.randint(3, 30))
            review_rows.append(
                (rid, product_id, customer_id, rating, comment, created.isoformat())
            )
        cur.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?)", review_rows)

        conn.commit()
        counts = {
            table: cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "customers", "products", "orders",
                "order_items", "payments", "reviews",
            )
        }
        return counts
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the demo database.")
    default_out = Path(__file__).resolve().parent.parent / "data" / "demo.db"
    parser.add_argument("--out", default=str(default_out))
    args = parser.parse_args()
    counts = build(args.out)
    print(f"Wrote {args.out}")
    for table, n in counts.items():
        print(f"  {table}: {n} rows")


if __name__ == "__main__":
    main()
