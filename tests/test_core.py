"""Login, permissions, products, barcode, serials, purchases, inventory."""
from base import Base
from shoppos.services import auth, barcode, catalog, inventory, parties, purchasing
from shoppos.util import POSError


class TestAuth(Base):
    def test_login_success_and_failure(self):
        self.assertEqual(self.owner["role"], "Owner")
        with self.assertRaises(POSError):
            auth.login(self.db, "admin", "wrong")
        with self.assertRaises(POSError):
            auth.login(self.db, "nobody", "x")

    def test_password_is_hashed_not_plain(self):
        row = self.db.one("SELECT password_hash,salt FROM users WHERE username='admin'")
        self.assertNotIn("admin123", row["password_hash"])
        self.assertEqual(len(row["password_hash"]), 64)

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            with self.assertRaises(POSError):
                auth.login(self.db, "admin", "bad")
        with self.assertRaises(POSError) as cm:
            auth.login(self.db, "admin", "admin123")
        self.assertIn("locked", str(cm.exception).lower())

    def test_change_password(self):
        auth.change_password(self.db, self.owner, "admin123", "newpass1")
        auth.login(self.db, "admin", "newpass1")
        with self.assertRaises(POSError):
            auth.change_password(self.db, self.owner, "wrong", "another1")

    def test_disabled_user_cannot_login(self):
        u = self.user("Cashier")
        auth.update_user(self.db, self.owner, u["id"], "X", "Cashier", False)
        with self.assertRaises(POSError):
            auth.login(self.db, u["username"], "secret1")

    def test_cashier_permissions(self):
        cashier = self.user("Cashier")
        pid = self.product(stock=5)
        with self.assertRaises(POSError):
            catalog.save_product(self.db, cashier, {"sku": "X", "name": "X", "retail_price": 5})
        with self.assertRaises(POSError):
            auth.list_users(self.db, cashier)
        with self.assertRaises(POSError):
            inventory.adjust_stock(self.db, cashier, pid, 1, "x")
        from shoppos.services import reports, sales
        with self.assertRaises(POSError):
            reports.profit_summary(self.db, cashier)
        with self.assertRaises(POSError):
            sales.cancel_sale(self.db, cashier, 1, "x")

    def test_permissions_are_configurable(self):
        role_perm = auth.permissions_for(self.db, "Cashier")
        self.assertNotIn("pos.discount", role_perm)
        auth.set_role_permissions(self.db, self.owner, "Cashier", list(role_perm | {"pos.discount"}))
        c = self.user("Cashier")
        self.assertIn("pos.discount", c["permissions"])

    def test_owner_permissions_locked(self):
        with self.assertRaises(POSError):
            auth.set_role_permissions(self.db, self.owner, "Owner", [])

    def test_cashier_cannot_see_cost(self):
        pid = self.product(cost=777)
        cashier = self.user("Cashier")
        rows, _ = catalog.search_products(self.db, cashier)
        self.assertTrue(all(r["purchase_price"] is None for r in rows))
        rows, _ = catalog.search_products(self.db, self.owner)
        self.assertEqual(rows[0]["purchase_price"], 777)


class TestProducts(Base):
    def test_create_and_unique_sku_barcode(self):
        self.product(sku="ABC")
        with self.assertRaises(POSError) as cm:
            catalog.save_product(self.db, self.owner, {"sku": "abc", "name": "dup", "retail_price": 5})
        self.assertIn("SKU already exists", str(cm.exception))
        p = self.product()
        bc = catalog.get_product(self.db, p)["barcode"]
        with self.assertRaises(POSError) as cm:
            catalog.save_product(self.db, self.owner, {"sku": "NEW1", "name": "n", "retail_price": 5, "barcode": bc})
        self.assertIn("Barcode already exists", str(cm.exception))

    def test_blank_barcodes_allowed_multiple(self):
        for i in range(3):
            catalog.save_product(self.db, self.owner, {"sku": f"NB{i}", "name": "n", "retail_price": 5, "barcode": ""})

    def test_validation(self):
        with self.assertRaises(POSError):
            catalog.save_product(self.db, self.owner, {"sku": "", "name": "n", "retail_price": 5})
        with self.assertRaises(POSError):
            catalog.save_product(self.db, self.owner, {"sku": "Z", "name": "n", "retail_price": 0})
        with self.assertRaises(POSError):
            catalog.save_product(self.db, self.owner, {"sku": "Z", "name": "n", "retail_price": 10, "min_price": 20})
        with self.assertRaises(POSError):
            catalog.save_product(self.db, self.owner, {"sku": "Z", "name": "n", "retail_price": "abc"})

    def test_price_change_is_audited(self):
        pid = self.product(retail=100)
        d = dict(catalog.get_product(self.db, pid))
        d["retail_price"] = 120
        catalog.save_product(self.db, self.owner, d, pid)
        log = self.db.one("SELECT * FROM audit_logs WHERE action='Price changed'")
        self.assertIn("100", log["old_value"])
        self.assertIn("120", log["new_value"])

    def test_delete_used_product_deactivates(self):
        pid = self.product(stock=5)
        self.sell(pid, 1)
        self.assertEqual(catalog.delete_product(self.db, self.owner, pid), "deactivated")
        clean = self.product()
        self.assertEqual(catalog.delete_product(self.db, self.owner, clean), "deleted")

    def test_barcode_scanning_lookup(self):
        pid = self.product(sku="SCAN1")
        bc = catalog.get_product(self.db, pid)["barcode"]
        self.assertEqual(catalog.find_by_code(self.db, bc)["product"]["id"], pid)
        self.assertEqual(catalog.find_by_code(self.db, "scan1")["product"]["id"], pid)
        self.assertIsNone(catalog.find_by_code(self.db, "nothing"))

    def test_scanning_a_serial_finds_product_and_serial(self):
        pid = self.product(serialized=True, stock=2)
        s = catalog.available_serials(self.db, pid)[0]
        hit = catalog.find_by_code(self.db, s["serial"])
        self.assertEqual(hit["product"]["id"], pid)
        self.assertEqual(hit["serial"]["id"], s["id"])

    def test_code39_barcode_patterns_are_valid(self):
        seen = set()
        for ch, pat in barcode._C39.items():
            self.assertEqual(len(pat), 9, ch)
            self.assertEqual(pat.count("w"), 3, ch)
            seen.add(pat)
        self.assertEqual(len(seen), len(barcode._C39))
        bars, width = barcode.bars("ABC123")
        self.assertTrue(bars and width > 0)
        with self.assertRaises(POSError):
            barcode.normalize("bad*char")

    def test_subcategory_must_belong_to_category(self):
        a = catalog.add_category(self.db, self.owner, "A")
        b = catalog.add_category(self.db, self.owner, "B")
        sub = catalog.add_category(self.db, self.owner, "SubA", a)
        with self.assertRaises(POSError):
            catalog.save_product(self.db, self.owner, {"sku": "Q", "name": "n", "retail_price": 5,
                                                      "category_id": b, "subcategory_id": sub})


class TestSerials(Base):
    def test_duplicate_serial_rejected(self):
        a = self.product(serialized=True)
        b = self.product(serialized=True)
        catalog.add_opening_serials(self.db, self.owner, a, "DL5440ABC123", 100)
        with self.assertRaises(POSError) as cm:
            catalog.add_opening_serials(self.db, self.owner, b, "dl5440abc123", 100)
        self.assertIn("already exists", str(cm.exception))
        with self.assertRaises(POSError):
            catalog.add_opening_serials(self.db, self.owner, a, "X1\nX1", 100)
        self.assertConsistent()

    def test_partial_serial_failure_rolls_back(self):
        a = self.product(serialized=True)
        catalog.add_opening_serials(self.db, self.owner, a, "EXISTS1", 100)
        with self.assertRaises(POSError):
            catalog.add_opening_serials(self.db, self.owner, a, "NEW1\nEXISTS1", 100)
        self.assertIsNone(self.db.one("SELECT * FROM serials WHERE serial='NEW1'"))
        self.assertConsistent()

    def test_serial_history(self):
        pid = self.product(serialized=True, stock=1, warranty=12)
        sid = catalog.available_serials(self.db, pid)[0]["serial"]
        self.sell(pid, 1)
        h = catalog.serial_history(self.db, self.owner, sid)
        self.assertEqual(h["status"], "Sold")
        self.assertEqual(len(h["sales"]), 1)
        self.assertEqual(len(h["warranties"]), 1)


class TestPurchasing(Base):
    def _supplier(self):
        return parties.save_supplier(self.db, self.owner, {"name": "ABC Computers"})

    def test_workflow_po_receive_payable_payment(self):
        sup = self._supplier()
        pid = self.product(serialized=True, cost=1)
        pu = purchasing.create_purchase(self.db, self.owner, sup, [{"product_id": pid, "qty": 2, "unit_cost": 145000}])
        po = purchasing.get_purchase(self.db, pu)
        self.assertEqual(po["status"], "Ordered")
        self.assertEqual(po["total"], 290000)
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 0)  # nothing yet
        with self.assertRaises(POSError):  # wrong serial count
            purchasing.receive_purchase(self.db, self.owner, pu, [{"item_id": po["items"][0]["id"], "qty": 2, "serials": "A1"}])
        status = purchasing.receive_purchase(self.db, self.owner, pu,
                                             [{"item_id": po["items"][0]["id"], "qty": 2, "serials": "A1,A2"}])
        self.assertEqual(status, "Received")
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 2)
        self.assertEqual(parties.get_customer.__name__, "get_customer")
        self.assertEqual(self.db.scalar("SELECT balance FROM suppliers WHERE id=?", (sup,)), 290000)
        purchasing.pay_supplier(self.db, self.owner, sup, 100000, "Bank Transfer", pu)
        self.assertEqual(self.db.scalar("SELECT balance FROM suppliers WHERE id=?", (sup,)), 190000)
        with self.assertRaises(POSError):
            purchasing.pay_supplier(self.db, self.owner, sup, 999999, "Cash")
        self.assertConsistent()

    def test_partial_receiving_and_cost_average(self):
        sup = self._supplier()
        pid = self.product(cost=100, stock=10)
        pu = purchasing.create_purchase(self.db, self.owner, sup, [{"product_id": pid, "qty": 10, "unit_cost": 200}])
        item = purchasing.get_purchase(self.db, pu)["items"][0]
        self.assertEqual(purchasing.receive_purchase(self.db, self.owner, pu, [{"item_id": item["id"], "qty": 5}]),
                         "Partially Received")
        with self.assertRaises(POSError):
            purchasing.receive_purchase(self.db, self.owner, pu, [{"item_id": item["id"], "qty": 6}])
        purchasing.receive_purchase(self.db, self.owner, pu, [{"item_id": item["id"], "qty": 5}])
        p = catalog.get_product(self.db, pid)
        self.assertEqual(p["stock"], 20)
        self.assertAlmostEqual(p["purchase_price"], 150.0, 2)  # (10*100 + 5*200 + 5*200)/20 = 150
        self.assertConsistent()

    def test_purchase_return_and_cancel(self):
        sup = self._supplier()
        pid = self.product(stock=10, cost=50)
        purchasing.purchase_return(self.db, self.owner, sup, [{"product_id": pid, "qty": 3, "unit_cost": 50}], "faulty")
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 7)
        self.assertEqual(self.db.scalar("SELECT balance FROM suppliers WHERE id=?", (sup,)), -150)
        with self.assertRaises(POSError):
            purchasing.purchase_return(self.db, self.owner, sup, [{"product_id": pid, "qty": 99, "unit_cost": 50}])
        pu = purchasing.create_purchase(self.db, self.owner, sup, [{"product_id": pid, "qty": 1, "unit_cost": 5}])
        purchasing.cancel_purchase(self.db, self.owner, pu)
        self.assertConsistent()

    def test_supplier_cash_payment_hits_register(self):
        sup = self._supplier()
        pid = self.product(cost=100)
        pu = purchasing.create_purchase(self.db, self.owner, sup, [{"product_id": pid, "qty": 1, "unit_cost": 100}])
        purchasing.receive_purchase(self.db, self.owner, pu, [{"item_id": purchasing.get_purchase(self.db, pu)["items"][0]["id"], "qty": 1}])
        purchasing.pay_supplier(self.db, self.owner, sup, 40, "Cash")
        from shoppos.services import finance
        reg = finance.register_summary(self.db, finance.open_register(self.db)["id"])
        self.assertEqual(reg["expected"], 10000 - 40)


class TestInventory(Base):
    def test_adjustment_requires_reason_and_logs(self):
        pid = self.product(stock=5)
        with self.assertRaises(POSError):
            inventory.adjust_stock(self.db, self.owner, pid, 9, "")
        inventory.adjust_stock(self.db, self.owner, pid, 9, "stock take")
        self.assertEqual(catalog.get_product(self.db, pid)["stock"], 9)
        t = self.db.one("SELECT * FROM inventory_transactions WHERE type='Adjustment' ORDER BY id DESC")
        self.assertEqual(t["qty_change"], 4)
        self.assertEqual(t["reason"], "stock take")
        self.assertConsistent()

    def test_no_silent_stock_changes_every_change_logged(self):
        pid = self.product(stock=10)
        self.sell(pid, 3)
        s = self.db.scalar("SELECT SUM(qty_change) FROM inventory_transactions WHERE product_id=?", (pid,))
        self.assertEqual(s, 7)

    def test_damaged_stock(self):
        pid = self.product(stock=5)
        inventory.mark_damaged(self.db, self.owner, pid, 2, "dropped")
        p = catalog.get_product(self.db, pid)
        self.assertEqual((p["stock"], p["damaged"]), (3, 2))
        self.assertConsistent()

    def test_stock_list_flags(self):
        pid = self.product(stock=2, min_stock=5)
        rows, _ = inventory.stock_list(self.db, self.owner, status="low")
        self.assertEqual(rows[0]["state"], "Low")
        out = self.product()
        rows, _ = inventory.stock_list(self.db, self.owner, status="out")
        self.assertTrue(any(r["id"] == out for r in rows))
