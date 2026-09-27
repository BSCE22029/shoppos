"""Sales, payments, returns, warranty, repairs, expenses, cash, profit, backup, exports."""
import os
import zipfile

from base import Base
from shoppos.services import (audit, auth, backup, catalog, export, finance, inventory, parties, printing, reports,
                              repairs, returns, sales, settings, warranty)
from shoppos.util import POSError


class TestSales(Base):
    def test_basic_sale_updates_everything(self):
        pid = self.product(cost=100, retail=150, stock=10)
        res = self.sell(pid, 2)
        self.assertEqual(res["total"], 300)
        self.assertTrue(res["invoice_no"].startswith("INV-"))
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 8)
        s = sales.get_sale(self.db, res["sale_id"])
        self.assertEqual(s["cost_total"], 200)
        self.assertEqual(s["payments"][0]["method"], "Cash")
        reg = finance.register_summary(self.db, finance.open_register(self.db)["id"])
        self.assertEqual(reg["expected"], 10000 + 300)
        self.assertConsistent()

    def test_invoice_numbers_unique_and_sequential(self):
        pid = self.product(stock=10)
        a, b = self.sell(pid), self.sell(pid)
        self.assertNotEqual(a["invoice_no"], b["invoice_no"])
        self.assertEqual(int(b["invoice_no"][4:]), int(a["invoice_no"][4:]) + 1)

    def test_insufficient_stock(self):
        pid = self.product(stock=2)
        with self.assertRaises(POSError) as cm:
            self.sell(pid, 3)
        self.assertIn("Insufficient stock", str(cm.exception))
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 2)

    def test_serialized_needs_serial_and_marks_sold(self):
        pid = self.product(serialized=True, stock=3, warranty=12)
        with self.assertRaises(POSError) as cm:
            sales.complete_sale(self.db, self.owner, {"items": [{"product_id": pid, "qty": 1}],
                                                      "payments": [{"method": "Cash", "amount": 150}]})
        self.assertIn("serial", str(cm.exception).lower())
        res = self.sell(pid, 1)
        sold = self.db.q("SELECT * FROM serials WHERE status='Sold'")
        self.assertEqual(len(sold), 1)
        self.assertEqual(sold[0]["sale_id"], res["sale_id"])
        self.assertIsNotNone(sold[0]["warranty_expiry"])
        self.assertConsistent()

    def test_same_serial_cannot_be_sold_twice(self):
        pid = self.product(serialized=True, stock=2)
        sid = catalog.available_serials(self.db, pid)[0]["id"]
        cart = {"items": [{"product_id": pid, "qty": 1, "serial_ids": [sid]}], "payments": [{"method": "Cash", "amount": 150}]}
        sales.complete_sale(self.db, self.owner, cart)
        with self.assertRaises(POSError):
            sales.complete_sale(self.db, self.owner, cart)
        # duplicate within cart
        two = {"items": [{"product_id": pid, "qty": 2, "serial_ids": [sid, sid]}], "payments": [{"method": "Cash", "amount": 300}]}
        with self.assertRaises(POSError):
            sales.complete_sale(self.db, self.owner, two)

    def test_serial_of_other_product_rejected(self):
        a = self.product(serialized=True, stock=1)
        b = self.product(serialized=True, stock=1)
        wrong = catalog.available_serials(self.db, b)[0]["id"]
        with self.assertRaises(POSError):
            sales.complete_sale(self.db, self.owner, {"items": [{"product_id": a, "qty": 1, "serial_ids": [wrong]}],
                                                      "payments": [{"method": "Cash", "amount": 150}]})

    def test_split_payment_example(self):
        """Invoice 200,000 = cash 100,000 + bank 50,000 + credit 50,000."""
        pid = self.product(cost=150000, retail=200000, stock=2)
        cust = self.customer("Muhammad Ali", limit=100000)
        res = self.sell(pid, 1, customer_id=cust, payments=[
            {"method": "Cash", "amount": 100000}, {"method": "Bank Transfer", "amount": 50000},
            {"method": "Credit", "amount": 50000}])
        s = sales.get_sale(self.db, res["sale_id"])
        self.assertEqual([(p["method"], p["amount"]) for p in s["payments"]],
                         [("Cash", 100000), ("Bank Transfer", 50000), ("Credit", 50000)])
        self.assertEqual(s["credit"], 50000)
        self.assertEqual(s["paid"], 150000)
        self.assertEqual(parties.get_customer(self.db, cust)["balance"], 50000)
        reg = finance.register_summary(self.db, finance.open_register(self.db)["id"])
        self.assertEqual(reg["expected"], 10000 + 100000)  # only the cash part
        self.assertConsistent()

    def test_wrong_payment_total_rejected(self):
        pid = self.product(stock=2, retail=100)
        with self.assertRaises(POSError) as cm:
            self.sell(pid, 1, payments=[{"method": "Cash", "amount": 90}])
        self.assertIn("Payment amount is incorrect", str(cm.exception))
        with self.assertRaises(POSError):
            self.sell(pid, 1, payments=[{"method": "Cash", "amount": 150}])

    def test_credit_limit_and_customer_required(self):
        pid = self.product(stock=5, retail=1000)
        with self.assertRaises(POSError):
            self.sell(pid, 1, payments=[{"method": "Credit", "amount": 1000}])
        cust = self.customer(limit=500)
        with self.assertRaises(POSError) as cm:
            self.sell(pid, 1, customer_id=cust, payments=[{"method": "Credit", "amount": 1000}])
        self.assertIn("credit limit exceeded", str(cm.exception))
        self.assertEqual(parties.get_customer(self.db, cust)["balance"], 0)

    def test_discount_math_and_permission(self):
        pid = self.product(cost=100, retail=1000, tax=10, stock=5)
        cart = {"items": [{"product_id": pid, "qty": 2, "discount": 100}], "overall_discount": 200}
        t = sales.preview_totals(self.db, cart)
        # base 2000-100=1900; overall 200 -> net 1700; tax 170; total 1870
        self.assertEqual((t["subtotal"], t["line_discount"], t["overall_discount"], t["tax"], t["total"]),
                         (2000, 100, 200, 170, 1870))
        cart["payments"] = [{"method": "Cash", "amount": 1870}]
        cashier = self.user("Cashier")
        with self.assertRaises(POSError):
            sales.complete_sale(self.db, cashier, cart)
        res = sales.complete_sale(self.db, self.owner, cart)
        self.assertEqual(res["total"], 1870)

    def test_overall_discount_allocation_sums_exactly(self):
        a = self.product(retail=333.33, tax=5, stock=10)
        b = self.product(retail=199.99, tax=17, stock=10)
        cart = {"items": [{"product_id": a, "qty": 3}, {"product_id": b, "qty": 7}], "overall_discount": 123.45}
        t = sales.preview_totals(self.db, cart)
        cart["payments"] = [{"method": "Card", "amount": t["total"]}]
        res = sales.complete_sale(self.db, self.owner, cart)
        s = sales.get_sale(self.db, res["sale_id"])
        self.assertAlmostEqual(sum(i["overall_alloc"] for i in s["items"]), 123.45, 2)
        self.assertAlmostEqual(sum(i["total"] for i in s["items"]), s["total"], 2)

    def test_price_override_and_minimum_price(self):
        pid = self.product(retail=1000, min_price=900, stock=5)
        cashier = self.user("Cashier")
        with self.assertRaises(POSError):
            sales.complete_sale(self.db, cashier, {"items": [{"product_id": pid, "qty": 1, "unit_price": 950}],
                                                   "payments": [{"method": "Cash", "amount": 950}]})
        self.sell(pid, 1, price=800)  # the Owner holds pos.below_min, so this is allowed
        auth.set_role_permissions(self.db, self.owner, "Sales Staff",
                                  list(auth.permissions_for(self.db, "Sales Staff") | {"pos.price_override"}))
        staff = self.user("Sales Staff")
        with self.assertRaises(POSError) as cm2:
            self.sell(pid, 1, price=800, user=staff)
        self.assertIn("below the minimum", str(cm2.exception))

    def test_sale_is_atomic_on_failure(self):
        """A bad second line must leave no trace of the first."""
        good = self.product(stock=5)
        bad = self.product(stock=0)
        before = self.db.scalar("SELECT COUNT(*) FROM inventory_transactions")
        with self.assertRaises(POSError):
            sales.complete_sale(self.db, self.owner, {
                "items": [{"product_id": good, "qty": 1}, {"product_id": bad, "qty": 1}],
                "payments": [{"method": "Cash", "amount": 300}]})
        self.assertEqual(catalog.get_product(self.db, good)["stock"], 5)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM sales"), 0)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM inventory_transactions"), before)
        self.assertEqual(self.db.scalar("SELECT value FROM sequences WHERE name='invoice'"), None)
        self.assertConsistent()

    def test_atomic_when_cash_register_closed(self):
        finance.close_register(self.db, self.owner, 10000)
        pid = self.product(stock=5)
        with self.assertRaises(POSError) as cm:
            self.sell(pid, 1)
        self.assertIn("register", str(cm.exception).lower())
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 5)
        self.sell(pid, 1, method="Card")  # non-cash still fine

    def test_hold_and_resume(self):
        pid = self.product(stock=5)
        cart = {"items": [{"product_id": pid, "qty": 2}], "customer_id": None}
        hid = sales.hold_cart(self.db, self.owner, cart)
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 5)  # holding does not touch stock
        self.assertEqual(inventory.reserved_map(self.db)[pid], 2)
        back = sales.resume_held(self.db, self.owner, hid)
        back["payments"] = [{"method": "Cash", "amount": 300}]
        sales.complete_sale(self.db, self.owner, back)
        self.assertEqual(sales.list_held(self.db), [])

    def test_cancel_reverses_everything(self):
        pid = self.product(serialized=True, stock=2, cost=100, warranty=12)
        cust = self.customer(limit=1000)
        res = self.sell(pid, 1, customer_id=cust, payments=[{"method": "Cash", "amount": 100}, {"method": "Credit", "amount": 50}])
        cashier = self.user("Cashier")
        with self.assertRaises(POSError):
            sales.cancel_sale(self.db, cashier, res["sale_id"], "x")
        with self.assertRaises(POSError):
            sales.cancel_sale(self.db, self.owner, res["sale_id"], "")
        sales.cancel_sale(self.db, self.owner, res["sale_id"], "customer cancelled")
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 2)
        self.assertEqual(parties.get_customer(self.db, cust)["balance"], 0)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM serials WHERE status='In Stock'"), 2)
        reg = finance.register_summary(self.db, finance.open_register(self.db)["id"])
        self.assertEqual(reg["expected"], 10000)
        with self.assertRaises(POSError):
            sales.cancel_sale(self.db, self.owner, res["sale_id"], "again")
        self.assertConsistent()


class TestReturns(Base):
    def test_full_return_serialized_verifies_serial(self):
        pid = self.product(serialized=True, stock=2, cost=100, retail=150, warranty=12)
        res = self.sell(pid, 1)
        s = sales.get_sale(self.db, res["sale_id"])
        item = s["items"][0]
        sold_serial = item["serial_rows"][0]["serial_id"]
        other = [x for x in catalog.available_serials(self.db, pid)][0]["id"]
        with self.assertRaises(POSError) as cm:  # a serial that was never on this invoice
            returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": item["id"], "qty": 1, "serial_ids": [other]}], "Cash")
        self.assertIn("not sold on this invoice", str(cm.exception))
        with self.assertRaises(POSError):  # serial missing
            returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": item["id"], "qty": 1}], "Cash")
        r = returns.process_return(self.db, self.owner, s["id"],
                                   [{"sale_item_id": item["id"], "qty": 1, "serial_ids": [sold_serial]}], "Cash")
        self.assertEqual(r["refund_amount"], 150)
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 2)
        self.assertEqual(sales.get_sale(self.db, s["id"])["status"], "Returned")
        with self.assertRaises(POSError) as cm:
            returns.process_return(self.db, self.owner, s["id"],
                                   [{"sale_item_id": item["id"], "qty": 1, "serial_ids": [sold_serial]}], "Cash")
        self.assertIn("already been returned", str(cm.exception))
        reg = finance.register_summary(self.db, finance.open_register(self.db)["id"])
        self.assertEqual(reg["expected"], 10000)  # sale + refund net to zero
        self.assertEqual(self.db.one("SELECT status FROM warranties")["status"], "Void")
        self.assertConsistent()

    def test_partial_return_amounts_and_profit(self):
        pid = self.product(cost=100, retail=150, tax=10, stock=10)
        res = self.sell(pid, 4)  # 4*150=600 + 60 tax = 660
        s = sales.get_sale(self.db, res["sale_id"])
        it = s["items"][0]
        r1 = returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": it["id"], "qty": 1}], "Cash")
        self.assertEqual(r1["amount"], 165)
        self.assertEqual(sales.get_sale(self.db, s["id"])["status"], "Partially Returned")
        r2 = returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": it["id"], "qty": 3}], "Cash")
        self.assertEqual(r1["amount"] + r2["amount"], 660)  # nothing lost to rounding
        with self.assertRaises(POSError):
            returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": it["id"], "qty": 1}], "Cash")
        ps = reports.profit_summary(self.db, self.owner)["summary"]
        self.assertEqual(ps["revenue"], 0)
        self.assertEqual(ps["gross_profit"], 0)
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 10)
        self.assertConsistent()

    def test_return_of_credit_sale_reduces_balance_before_refund(self):
        pid = self.product(cost=100, retail=1000, stock=5)
        cust = self.customer(limit=5000)
        res = self.sell(pid, 1, customer_id=cust, payments=[{"method": "Cash", "amount": 400}, {"method": "Credit", "amount": 600}])
        s = sales.get_sale(self.db, res["sale_id"])
        r = returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": s["items"][0]["id"], "qty": 1}], "Cash")
        self.assertEqual((r["credit_offset"], r["refund_amount"]), (600, 400))
        self.assertEqual(parties.get_customer(self.db, cust)["balance"], 0)
        self.assertConsistent()

    def test_store_credit_refund_and_exchange(self):
        pid = self.product(cost=100, retail=500, stock=5)
        other = self.product(cost=100, retail=300, stock=5)
        cust = self.customer()
        res = self.sell(pid, 1, customer_id=cust)
        s = sales.get_sale(self.db, res["sale_id"])
        returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": s["items"][0]["id"], "qty": 1}], "Store Credit")
        self.assertEqual(parties.get_customer(self.db, cust)["store_credit"], 500)
        # exchange: buy something else using the store credit
        self.sell(other, 1, customer_id=cust, payments=[{"method": "Store Credit", "amount": 300}])
        self.assertEqual(parties.get_customer(self.db, cust)["store_credit"], 200)
        with self.assertRaises(POSError):
            self.sell(other, 1, customer_id=cust, payments=[{"method": "Store Credit", "amount": 300}])
        with self.assertRaises(POSError):  # store credit needs a customer
            walk = sales.get_sale(self.db, self.sell(other, 1)["sale_id"])
            returns.process_return(self.db, self.owner, walk["id"], [{"sale_item_id": walk["items"][0]["id"], "qty": 1}], "Store Credit")

    def test_damaged_return_not_restocked(self):
        pid = self.product(cost=100, retail=150, stock=5)
        res = self.sell(pid, 1)
        s = sales.get_sale(self.db, res["sale_id"])
        returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": s["items"][0]["id"], "qty": 1, "condition": "Damaged"}], "Cash")
        p = catalog.get_product(self.db, pid)
        self.assertEqual((p["stock"], p["damaged"]), (4, 1))
        ps = reports.profit_summary(self.db, self.owner)["summary"]
        self.assertEqual(ps["gross_profit"], -100)  # refund of 150 revenue but the damaged unit's cost is lost
        self.assertConsistent()

    def test_cancelled_sale_cannot_be_returned(self):
        pid = self.product(stock=5)
        res = self.sell(pid, 1)
        sales.cancel_sale(self.db, self.owner, res["sale_id"], "oops")
        s = sales.get_sale(self.db, res["sale_id"])
        with self.assertRaises(POSError):
            returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": s["items"][0]["id"], "qty": 1}], "Cash")

    def test_returned_sale_cannot_be_cancelled(self):
        pid = self.product(stock=5)
        res = self.sell(pid, 2)
        s = sales.get_sale(self.db, res["sale_id"])
        returns.process_return(self.db, self.owner, s["id"], [{"sale_item_id": s["items"][0]["id"], "qty": 1}], "Cash")
        with self.assertRaises(POSError):
            sales.cancel_sale(self.db, self.owner, s["id"], "late")


class TestWarranty(Base):
    def test_created_at_sale_and_lookup(self):
        pid = self.product(serialized=True, stock=2, warranty=12)
        cust = self.customer("Warranty Guy")
        serial = catalog.available_serials(self.db, pid)[0]["serial"]
        res = self.sell(pid, 1, customer_id=cust)
        inv = sales.get_sale(self.db, res["sale_id"])["invoice_no"]
        for kw in ({"serial": serial}, {"invoice": inv}, {"phone": "0300"}, {"product": "Product"}):
            rows, _ = warranty.lookup(self.db, self.owner, **kw)
            self.assertEqual(len(rows), 1, kw)
            self.assertEqual(rows[0]["display_status"], "Active")

    def test_status_expiring_and_expired(self):
        pid = self.product(serialized=True, stock=2, warranty=12)
        self.sell(pid, 1)
        self.sell(pid, 1)
        w = self.db.q("SELECT id FROM warranties ORDER BY id")
        self.db.execute("UPDATE warranties SET expiry_date=date('now','localtime','+10 days') WHERE id=?", (w[0]["id"],))
        self.db.execute("UPDATE warranties SET expiry_date=date('now','localtime','-1 days') WHERE id=?", (w[1]["id"],))
        self.assertEqual(warranty.get(self.db, w[0]["id"])["display_status"], "Expiring Soon")
        self.assertEqual(warranty.get(self.db, w[1]["id"])["display_status"], "Expired")
        with self.assertRaises(POSError) as cm:
            warranty.file_claim(self.db, self.owner, w[1]["id"], "broken")
        self.assertIn("expired", str(cm.exception))

    def test_claim_replacement(self):
        pid = self.product(serialized=True, stock=3, warranty=12)
        self.sell(pid, 1)
        w = self.db.one("SELECT * FROM warranties")
        cid = warranty.file_claim(self.db, self.owner, w["id"], "Dead on arrival")
        self.assertEqual(warranty.get(self.db, w["id"])["display_status"], "Claimed")
        with self.assertRaises(POSError):
            warranty.file_claim(self.db, self.owner, w["id"], "again")
        with self.assertRaises(POSError):
            warranty.resolve_claim(self.db, self.owner, cid, "Replaced")  # needs replacement serial
        rep = catalog.available_serials(self.db, pid)[0]["id"]
        warranty.resolve_claim(self.db, self.owner, cid, "Replaced", "swapped", rep)
        self.assertEqual(warranty.get(self.db, w["id"])["display_status"], "Replaced")
        self.assertEqual(self.db.one("SELECT status FROM serials WHERE id=?", (w["serial_id"],))["status"], "Replaced")
        self.assertEqual(self.db.one("SELECT status FROM serials WHERE id=?", (rep,))["status"], "Sold")
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 1)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM warranties WHERE status='Active'"), 1)
        self.assertConsistent()

    def test_repaired_claim_returns_to_active(self):
        pid = self.product(stock=3, warranty=6)
        self.sell(pid, 1)
        w = self.db.one("SELECT * FROM warranties")
        cid = warranty.file_claim(self.db, self.owner, w["id"], "noisy")
        warranty.resolve_claim(self.db, self.owner, cid, "Repaired", "fixed")
        self.assertEqual(warranty.get(self.db, w["id"])["display_status"], "Active")


class TestRepairs(Base):
    def test_ticket_parts_deduct_inventory_and_deliver(self):
        part = self.product(cost=500, retail=900, stock=5)
        tech = self.user("Technician")
        cust = self.customer("Repair Customer")
        rid = repairs.create_repair(self.db, tech, {"customer_id": cust, "device": "Laptop", "brand": "Dell",
                                                    "complaint": "No power", "technician_id": tech["id"], "estimated_cost": 3000})
        r = repairs.get_repair(self.db, rid)
        self.assertEqual(r["status"], "Received")
        repairs.set_status(self.db, tech, rid, "Diagnosing", "checking board")
        repairs.add_part(self.db, tech, rid, part, 2)
        self.assertEqual(catalog.get_product(self.db, part)["stock"], 3)
        t = self.db.one("SELECT * FROM inventory_transactions WHERE type='Repair Usage'")
        self.assertEqual(t["qty_change"], -2)
        repairs.set_labor(self.db, tech, rid, 1500)
        self.assertEqual(repairs.get_repair(self.db, rid)["final_cost"], 1500 + 2 * 900)
        with self.assertRaises(POSError):  # not ready yet
            repairs.deliver_repair(self.db, tech, rid, [{"method": "Cash", "amount": 3300}])
        repairs.set_status(self.db, tech, rid, "Ready")
        with self.assertRaises(POSError):
            repairs.deliver_repair(self.db, tech, rid, [{"method": "Cash", "amount": 100}])
        cashier = self.user("Cashier")
        with self.assertRaises(POSError):  # cashier cannot manage repairs
            repairs.set_status(self.db, cashier, rid, "In Repair")
        repairs.deliver_repair(self.db, self.owner, rid, [{"method": "Cash", "amount": 3300}])
        self.assertEqual(repairs.get_repair(self.db, rid)["status"], "Delivered")
        rp = reports.profit_summary(self.db, self.owner)["summary"]
        self.assertEqual(rp["repair_profit"], 3300 - 2 * 500)
        with self.assertRaises(POSError):
            repairs.add_part(self.db, self.owner, rid, part, 1)
        self.assertConsistent()

    def test_cancel_returns_parts(self):
        part = self.product(cost=10, retail=20, stock=4)
        rid = repairs.create_repair(self.db, self.owner, {"customer_name": "Walk", "device": "PC", "complaint": "x"})
        repairs.add_part(self.db, self.owner, rid, part, 3)
        repairs.set_status(self.db, self.owner, rid, "Cancelled")
        self.assertEqual(catalog.get_product(self.db, part)["stock"], 4)
        self.assertConsistent()

    def test_insufficient_part_stock(self):
        part = self.product(stock=1)
        rid = repairs.create_repair(self.db, self.owner, {"customer_name": "Walk", "device": "PC", "complaint": "x"})
        with self.assertRaises(POSError):
            repairs.add_part(self.db, self.owner, rid, part, 5)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM repair_parts"), 0)


class TestFinance(Base):
    def test_expense_and_cash_register_reconciliation(self):
        pid = self.product(retail=1000, stock=5)
        self.sell(pid, 2)                                   # +2000 cash
        self.sell(pid, 1, method="Card")                    # not cash
        cat = finance.expense_categories(self.db)[0]["id"]
        finance.add_expense(self.db, self.owner, cat, "2025-01-05", 300, "Cash", "tea")
        finance.add_expense(self.db, self.owner, cat, "2025-01-05", 999, "Bank Transfer", "rent")  # not cash
        finance.cash_movement(self.db, self.owner, "Deposit", 500, "float top-up")
        finance.cash_movement(self.db, self.owner, "Withdrawal", 200, "owner draw")
        with self.assertRaises(POSError):
            finance.cash_movement(self.db, self.owner, "Withdrawal", 999999, "too much")
        reg = finance.register_summary(self.db, finance.open_register(self.db)["id"])
        self.assertEqual(reg["expected"], 10000 + 2000 - 300 + 500 - 200)
        closed = finance.close_register(self.db, self.owner, 11950)
        self.assertEqual(closed["expected_cash"], 12000)
        self.assertEqual(closed["variance"], -50)
        self.assertIn("Variance", finance.daily_cash_report(self.db, closed["id"]))
        self.assertIsNone(finance.open_register(self.db))
        with self.assertRaises(POSError):
            finance.close_register(self.db, self.owner, 1)

    def test_only_one_open_register(self):
        with self.assertRaises(POSError):
            finance.open_new_register(self.db, self.owner, 5)

    def test_customer_payment_updates_balance_and_cash(self):
        cust = self.customer(opening=1000)
        finance.receive_customer_payment(self.db, self.owner, cust, 400, "Cash")
        self.assertEqual(parties.get_customer(self.db, cust)["balance"], 600)
        with self.assertRaises(POSError):
            finance.receive_customer_payment(self.db, self.owner, cust, 5000, "Cash")
        reg = finance.register_summary(self.db, finance.open_register(self.db)["id"])
        self.assertEqual(reg["expected"], 10400)
        self.assertConsistent()

    def test_expense_validation(self):
        cat = finance.expense_categories(self.db)[0]["id"]
        with self.assertRaises(POSError):
            finance.add_expense(self.db, self.owner, cat, "05-01-2025", 10, "Cash", "")
        with self.assertRaises(POSError):
            finance.add_expense(self.db, self.owner, cat, "2025-01-01", -5, "Cash", "")


class TestProfit(Base):
    def test_profit_uses_actual_cost_not_revenue(self):
        a = self.product(cost=100, retail=150, stock=10)
        b = self.product(serialized=True, cost=1000, retail=1300, stock=2)
        self.sell(a, 4)                                  # revenue 600, cogs 400
        self.sell(b, 1)                                  # revenue 1300, cogs 1000
        cat = finance.expense_categories(self.db)[0]["id"]
        finance.add_expense(self.db, self.owner, cat, "2099-01-01", 50, "Bank Transfer", "future")
        ps = reports.profit_summary(self.db, self.owner)["summary"]
        self.assertEqual(ps["revenue"], 1900)
        self.assertEqual(ps["cogs"], 1400)
        self.assertEqual(ps["gross_profit"], 500)
        self.assertEqual(ps["expenses"], 50)
        self.assertEqual(ps["net_profit"], 450)

    def test_profit_with_discount(self):
        a = self.product(cost=100, retail=200, stock=10)
        self.sell(a, 1, payments=[{"method": "Cash", "amount": 170}], overall_discount=30)
        ps = reports.profit_summary(self.db, self.owner)["summary"]
        self.assertEqual((ps["revenue"], ps["gross_profit"], ps["discounts"]), (170, 70, 30))

    def test_average_cost_flows_into_cogs(self):
        from shoppos.services import purchasing
        sup = parties.save_supplier(self.db, self.owner, {"name": "S"})
        pid = self.product(cost=100, stock=10, retail=200)
        pu = purchasing.create_purchase(self.db, self.owner, sup, [{"product_id": pid, "qty": 10, "unit_cost": 200}])
        purchasing.receive_purchase(self.db, self.owner, pu, [{"item_id": purchasing.get_purchase(self.db, pu)["items"][0]["id"], "qty": 10}])
        self.sell(pid, 1)
        ps = reports.profit_summary(self.db, self.owner)["summary"]
        self.assertEqual(ps["cogs"], 150)   # average of 100 and 200

    def test_reports_shape_and_financial_visibility(self):
        a = self.product(cost=100, retail=150, stock=10)
        self.sell(a, 2)
        for g in ("day", "week", "month", "product", "category", "brand", "cashier", "customer", "payment"):
            rep = reports.sales_report(self.db, self.owner, g)
            self.assertTrue(rep["columns"] and rep["rows"], g)
        cashier = self.user("Cashier")
        auth.set_role_permissions(self.db, self.owner, "Cashier", list(auth.permissions_for(self.db, "Cashier") | {"reports.view"}))
        cashier = auth.refresh_user(self.db, cashier)
        rep = reports.sales_report(self.db, cashier, "product")
        self.assertNotIn("profit", [k for k, _ in rep["columns"]])
        d = reports.dashboard(self.db, cashier)
        self.assertNotIn("today_profit", d)
        self.assertIn("today_profit", reports.dashboard(self.db, self.owner))

    def test_inventory_reports(self):
        a = self.product(cost=100, retail=150, stock=3, min_stock=5)
        self.product()  # out of stock
        for fn in (reports.stock_valuation, reports.low_stock, reports.out_of_stock, reports.dead_stock, reports.fast_moving,
                   reports.stock_movement, reports.receivables, reports.payables):
            self.assertIn("rows", fn(self.db, self.owner))
        self.assertEqual(reports.low_stock(self.db, self.owner)["rows"][0]["stock"], 3)
        self.assertEqual(reports.stock_valuation(self.db, self.owner)["summary"]["cost_value"], 300)


class TestSystem(Base):
    def test_backup_and_restore(self):
        pid = self.product(stock=5, name="KeepMe")
        path = backup.create_backup(self.db, self.owner)
        self.assertTrue(os.path.exists(path))
        self.sell(pid, 2)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM sales"), 1)
        cashier = self.user("Cashier")
        with self.assertRaises(POSError):
            backup.restore_backup(self.db, cashier, path)
        backup.restore_backup(self.db, self.owner, path)
        from shoppos.bootstrap import open_database
        db2 = open_database(self.db.path)
        try:
            self.assertEqual(db2.scalar("SELECT COUNT(*) FROM sales"), 0)
            self.assertEqual(db2.scalar("SELECT stock FROM products WHERE name='KeepMe'"), 5)
        finally:
            db2.close()
        db3 = open_database(self.db.path)
        try:
            self.assertTrue(any("pre-restore" in b["name"] for b in backup.list_backups(db3)))
        finally:
            db3.close()

    def test_backup_never_overwrites(self):
        import datetime as dt
        d = os.path.join(self.tmp.name, "b")
        p1 = backup.create_backup(self.db, self.owner, dest_dir=d)
        with open(p1, "rb") as f:
            original = f.read()
        stamp = dt.datetime.strptime(os.path.basename(p1)[len("pos-backup-"):len("pos-backup-") + 15], "%Y%m%d-%H%M%S")

        class Fixed(dt.datetime):  # force the same timestamp -> same file name
            @classmethod
            def now(cls, tz=None):
                return stamp

        real = backup.dt
        backup.dt = type("M", (), {"datetime": Fixed, "timedelta": dt.timedelta})
        try:
            with self.assertRaises(POSError):
                backup.create_backup(self.db, self.owner, dest_dir=d)
        finally:
            backup.dt = real
        with open(p1, "rb") as f:
            self.assertEqual(f.read(), original)

    def test_restore_rejects_garbage(self):
        bad = os.path.join(self.tmp.name, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"not a database")
        with self.assertRaises(Exception):
            backup.restore_backup(self.db, self.owner, bad)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM users"), 1)  # untouched

    def test_auto_backup_once_per_day(self):
        first = backup.auto_backup_if_due(self.db)
        self.assertTrue(first)
        self.assertIsNone(backup.auto_backup_if_due(self.db))

    def test_audit_log_records_key_events(self):
        pid = self.product(stock=5)
        cust = self.customer()
        self.sell(pid, 1)
        actions = {r["action"] for r in self.db.q("SELECT DISTINCT action FROM audit_logs")}
        for a in ("User login", "Product created", "Sale created", "Customer created", "Stock adjusted"):
            self.assertIn(a, actions)
        rows, total = audit.search(self.db, self.owner, "Sale")
        self.assertTrue(total >= 1)
        with self.assertRaises(POSError):
            audit.search(self.db, self.user("Cashier"))

    def test_settings_permission_and_audit(self):
        with self.assertRaises(POSError):
            settings.save(self.db, self.user("Cashier"), {"shop_name": "X"})
        settings.save(self.db, self.owner, {"shop_name": "New Name"})
        self.assertEqual(settings.get(self.db, "shop_name"), "New Name")
        with self.assertRaises(POSError):
            settings.save(self.db, self.owner, {"nonsense": "1"})

    def test_negative_stock_setting(self):
        pid = self.product(stock=1)
        with self.assertRaises(POSError):
            self.sell(pid, 2)
        settings.save(self.db, self.owner, {"allow_negative_stock": "1"})
        self.sell(pid, 2)
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], -1)

    def test_exports_csv_xlsx_pdf(self):
        pid = self.product(cost=100, retail=150, stock=10)
        self.sell(pid, 2)
        rep = reports.sales_report(self.db, self.owner, "product")
        for ext in ("csv", "xlsx", "pdf"):
            path = os.path.join(self.tmp.name, f"r.{ext}")
            export.export(self.db, rep, path)
            self.assertGreater(os.path.getsize(path), 100)
        with zipfile.ZipFile(os.path.join(self.tmp.name, "r.xlsx")) as z:
            self.assertIn("xl/worksheets/sheet1.xml", z.namelist())
            self.assertIn(b"Product", z.read("xl/worksheets/sheet1.xml"))
        with open(os.path.join(self.tmp.name, "r.pdf"), "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        with open(os.path.join(self.tmp.name, "r.csv"), encoding="utf-8-sig") as f:
            self.assertIn("Product", f.readline())
        with self.assertRaises(POSError):
            export.export(self.db, rep, os.path.join(self.tmp.name, "r.txt"))

    def test_receipt_and_invoice_pdf(self):
        pid = self.product(serialized=True, stock=1, retail=165000, warranty=12, name="Dell Latitude 5440")
        cust = self.customer("Muhammad Ali")
        res = self.sell(pid, 1, customer_id=cust)
        text = printing.receipt_text(self.db, res["sale_id"])
        for needle in ("Dell Latitude 5440", "S/N:", "Warranty: 12", "165,000", res["invoice_no"], "Muhammad Ali"):
            self.assertIn(needle, text)
        self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))
        path = printing.save_invoice_pdf(self.db, res["sale_id"])
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF"))

    def test_logo_png_embeds_in_invoice(self):
        import struct, zlib
        def chunk(t, d):
            c = struct.pack(">I", len(d)) + t + d
            return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        w = h = 4
        raw = b"".join(b"\x00" + bytes([255, 0, 0, 255] * w) for _ in range(h))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + \
              chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
        logo = os.path.join(self.tmp.name, "logo.png")
        with open(logo, "wb") as f:
            f.write(png)
        settings.save(self.db, self.owner, {"logo_path": logo})
        pid = self.product(stock=1)
        res = self.sell(pid, 1)
        path = printing.save_invoice_pdf(self.db, res["sale_id"])
        with open(path, "rb") as f:
            self.assertIn(b"/Subtype /Image", f.read())

    def test_migrations_versioned(self):
        from shoppos.migrations import MIGRATIONS
        self.assertEqual(self.db.version, len(MIGRATIONS))
        tables = {r["name"] for r in self.db.q("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"users", "roles", "role_permissions", "products", "categories", "brands", "serials", "product_variants",
                    "suppliers", "customers", "sales", "sale_items", "sale_payments", "purchases", "purchase_items",
                    "purchase_payments", "inventory_transactions", "warehouses", "stock_transfers", "returns",
                    "return_items", "warranties", "warranty_claims", "repairs", "repair_parts", "expenses",
                    "expense_categories", "cash_registers", "cash_transactions", "settings", "audit_logs"}
        self.assertEqual(required - tables, set())

    def test_foreign_keys_enforced(self):
        with self.assertRaises(Exception):
            self.db.execute("INSERT INTO sale_items(sale_id,product_id,qty,unit_price,net,total) VALUES(999,999,1,1,1,1)")
