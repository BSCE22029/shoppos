"""Load test: 10,000 products, 100,000 sales, 500,000+ inventory transactions.
Run:  python tests/perf_check.py      (takes about a minute; uses a temp database)"""
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shoppos.services import auth
auth.ITER = 1000
from shoppos.bootstrap import open_database  # noqa: E402
from shoppos.services import catalog, inventory, reports, sales, parties  # noqa: E402

N_PROD, N_SALES = 10_000, 100_000
REUSE = os.environ.get("PERF_DB")            # set PERF_DB=path to skip regenerating the data
tmp = tempfile.mkdtemp()
db = open_database(REUSE or os.path.join(tmp, "perf.db"))
owner = auth.login(db, "admin", "admin123")
rnd = random.Random(1)


def timed(label, fn, limit=0.5):
    t = time.perf_counter()
    r = fn()
    dt = time.perf_counter() - t
    flag = "OK " if dt <= limit else "SLOW"
    print(f"  [{flag}] {label:<42}{dt * 1000:8.1f} ms")
    return dt <= limit


print("Generating data...")
t0 = time.time()
def generate():
    with db.tx():
        db.many("INSERT INTO products(sku,barcode,name,purchase_price,retail_price,stock,min_stock,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                [(f"SKU{i:06d}", f"{8900000000000 + i}", f"Product {i} {rnd.choice(['Dell', 'HP', 'Lenovo', 'Kingston'])} item",
                  100 + i % 500, 150 + i % 700, rnd.randint(0, 50), 5) for i in range(N_PROD)])
        db.many("INSERT INTO customers(name,phone,created_at) VALUES(?,?,datetime('now'))",
                [(f"Customer {i}", f"03{i:09d}") for i in range(5000)])
        uid = owner["id"]
        day = [f"2025-{1 + (i * 12 // N_SALES):02d}-{1 + i % 28:02d} 10:{i % 60:02d}:00" for i in range(N_SALES)]
        db.many("INSERT INTO sales(invoice_no,date,customer_id,user_id,subtotal,total,paid,cost_total) VALUES(?,?,?,?,?,?,?,?)",
                [(f"INV-{i + 1:06d}", day[i], rnd.randint(1, 5000), uid, 1000, 1000, 1000, 700) for i in range(N_SALES)])
        db.many("INSERT INTO sale_items(sale_id,product_id,qty,unit_price,net,total,cost_total) VALUES(?,?,?,?,?,?,?)",
                [(i % N_SALES + 1, rnd.randint(1, N_PROD), 1, 500, 500, 500, 350) for i in range(N_SALES * 2)])
        db.many("INSERT INTO sale_payments(sale_id,method,amount,date) VALUES(?,?,?,?)",
                [(i + 1, rnd.choice(["Cash", "Card", "Bank Transfer"]), 1000, day[i]) for i in range(N_SALES)])
        db.many("INSERT INTO inventory_transactions(product_id,date,type,qty_change,stock_after,reason) VALUES(?,?,?,?,?,?)",
                [(rnd.randint(1, N_PROD), day[i % N_SALES], "Sale", -1, 10, "perf") for i in range(520_000)])
    db.execute("ANALYZE")


if not REUSE:
    generate()
print(f"  {db.scalar('SELECT COUNT(*) FROM products'):,} products, {db.scalar('SELECT COUNT(*) FROM sales'):,} sales, "
      f"{db.scalar('SELECT COUNT(*) FROM inventory_transactions'):,} inventory transactions "
      f"({time.time() - t0:.1f}s, DB {os.path.getsize(db.path) / 1e6:.0f} MB)")

print("Timing typical screens:")
ok = True
ok &= timed("POS search by name (LIKE)", lambda: catalog.pos_search(db, "Kingston item"))
ok &= timed("POS barcode scan (exact)", lambda: catalog.find_by_code(db, "8900000005000"))
ok &= timed("POS SKU scan (exact)", lambda: catalog.find_by_code(db, "SKU009000"))
ok &= timed("Products page 1 (100 rows)", lambda: catalog.search_products(db, owner, "", limit=100))
ok &= timed("Products page 50 (offset 4900)", lambda: catalog.search_products(db, owner, "", limit=100, offset=4900))
ok &= timed("Product text search", lambda: catalog.search_products(db, owner, "Lenovo"), 1.0)
ok &= timed("Sales list page 1", lambda: sales.list_sales(db, owner, limit=100))
ok &= timed("Sales list by invoice search", lambda: sales.list_sales(db, owner, text="INV-05000"))
ok &= timed("Sales list date range", lambda: sales.list_sales(db, owner, date_from="2025-06-01", date_to="2025-06-30"))
ok &= timed("Sale detail", lambda: sales.get_sale(db, 50000))
ok &= timed("Customer search (name)", lambda: parties.list_customers(db, owner, "Customer 42"), 1.0)
ok &= timed("Inventory grid page 1", lambda: inventory.stock_list(db, owner, limit=100), 1.5)
ok &= timed("Inventory transactions for a product", lambda: inventory.transactions(db, owner, product_id=777))
ok &= timed("Report: monthly sales", lambda: reports.sales_report(db, owner, "month"), 3.0)
ok &= timed("Report: sales by product (year)", lambda: reports.sales_report(db, owner, "product"), 4.0)
ok &= timed("Report: profit summary", lambda: reports.profit_summary(db, owner), 3.0)
ok &= timed("Report: payment methods", lambda: reports.payment_method_report(db, owner), 2.0)
ok &= timed("Dashboard", lambda: reports.dashboard(db, owner), 3.0)
ok &= timed("Report: dead stock", lambda: reports.dead_stock(db, owner), 4.0)
print("ALL WITHIN TARGETS" if ok else "SOME QUERIES ARE SLOW")
db.close()
