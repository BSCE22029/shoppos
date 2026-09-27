import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shoppos.bootstrap import open_database  # noqa: E402
from shoppos.services import auth, catalog, finance, inventory, parties, purchasing  # noqa: E402


auth.ITER = 1000  # fast hashing for tests only; production uses 200,000


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SHOPPOS_DATA"] = self.tmp.name
        self.db = open_database(os.path.join(self.tmp.name, "test.db"))
        self.owner = auth.login(self.db, "admin", "admin123")
        finance.open_new_register(self.db, self.owner, 10000)
        self.n = 0

    def tearDown(self):
        self.db.close()
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    # --- helpers
    def user(self, role):
        self.n += 1
        uid = auth.create_user(self.db, self.owner, f"u{self.n}_{role[:3]}", "Test User", "secret1", role)
        return auth.login(self.db, f"u{self.n}_{role[:3]}", "secret1")

    def product(self, sku=None, serialized=False, cost=100.0, retail=150.0, tax=0, warranty=0, min_price=0,
                stock=0, name=None, min_stock=0):
        self.n += 1
        sku = sku or f"SKU{self.n}"
        pid = catalog.save_product(self.db, self.owner, {
            "sku": sku, "name": name or f"Product {sku}", "barcode": f"BC{self.n:06d}", "purchase_price": cost,
            "retail_price": retail, "tax_percent": tax, "warranty_months": warranty, "serialized": serialized,
            "min_price": min_price, "min_stock": min_stock})
        if stock:
            self.stock(pid, stock, cost)
        return pid

    def stock(self, pid, qty, cost=None):
        p = catalog.get_product(self.db, pid)
        cost = cost if cost is not None else p["purchase_price"]
        if p["serialized"]:
            catalog.add_opening_serials(self.db, self.owner, pid, [f"{p['sku']}-S{i}-{self.n}" for i in range(qty)], cost)
        else:
            inventory.adjust_stock(self.db, self.owner, pid, p["stock"] + qty, "test stock")

    def customer(self, name="Cust", limit=0, opening=0):
        return parties.save_customer(self.db, self.owner, {"name": name, "credit_limit": limit, "opening_balance": opening,
                                                           "phone": "0300"})

    def cart(self, items, payments=None, **kw):
        c = {"items": items, "payments": payments or [], **kw}
        return c

    def sell(self, pid, qty=1, method="Cash", price=None, user=None, **kw):
        from shoppos.services import sales
        p = catalog.get_product(self.db, pid)
        it = {"product_id": pid, "qty": qty}
        if price is not None:
            it["unit_price"] = price
        if p["serialized"]:
            it["serial_ids"] = [s["id"] for s in catalog.available_serials(self.db, pid)[:qty]]
        cart = {"items": [it], **kw}
        total = sales.preview_totals(self.db, cart)["total"]
        cart["payments"] = kw.pop("payments", None) or [{"method": method, "amount": total}]
        cart.update({k: v for k, v in kw.items() if k != "payments"})
        return sales.complete_sale(self.db, user or self.owner, cart)

    def assertConsistent(self):
        self.assertEqual(inventory.verify_consistency(self.db), [])
        self.assertEqual(parties.verify_balances(self.db), [])
