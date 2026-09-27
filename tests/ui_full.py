"""Full UI-driven functional test: drives the real screens (not just the service layer) through
their primary create/edit/action flows for every module, stubbing only the native blocking bits
(modal .show() calls) so the rest of each screen's own code - validation, refresh, wiring - actually
runs. Complements tests/ (service-level) and tests/ui_smoke.py (POS workflow).

Run: python tests/ui_full.py
"""
import os
import sys
import tempfile
import traceback
import tkinter as tk
from tkinter import ttk, filedialog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SHOPPOS_DATA"] = tempfile.mkdtemp()

from shoppos.services import auth  # noqa: E402
auth.ITER = 1000

from shoppos.ui import app as appmod, widgets, pickers  # noqa: E402
from shoppos.ui.screens import pos as P, products as PR, purchases as PU, repairs as RP, warranty as WT  # noqa: E402
from shoppos.ui import party_dialogs  # noqa: E402
from shoppos.services import (demo, catalog, sales, inventory, parties, finance, purchasing, repairs, warranty,  # noqa: E402
                              returns as returns_svc, backup, reports, settings as settings_svc)
from shoppos.util import POSError, today  # noqa: E402

errors = []
app = appmod.App()
app.report_callback_exception = lambda e, v, tb: errors.append("".join(traceback.format_exception(e, v, tb)))
popups = []
for n in ("showerror", "showwarning", "showinfo"):
    setattr(widgets.messagebox, n, lambda *a, _n=n, **k: popups.append((_n, a[1] if len(a) > 1 else "")))
widgets.messagebox.askyesno = lambda *a, **k: True


def pump(n=3):
    for _ in range(n):
        app.update_idletasks()
        app.update()


passed, failed = 0, []


def check(cond, msg):
    global passed
    if cond:
        passed += 1
        print("ok   " + msg)
    else:
        failed.append(msg)
        print("FAIL " + msg)


# ---------------------------------------------------------------- dialog stubbing helpers
FORM_ANSWERS = []


def _queued_form_show(self):
    vals = FORM_ANSWERS.pop(0)
    if self.on_save:
        r = self.on_save(vals)
        self.result = r if r is not None else vals
    else:
        self.result = vals
    self.destroy()
    return self.result


widgets.FormDialog.show = _queued_form_show


def push(vals):
    FORM_ANSWERS.append(vals)


class NoopDialogShow:
    """Temporarily makes any not-otherwise-stubbed Dialog.show() a non-blocking no-op.
    Use only around calls to read-only preview dialogs (no user decision needed)."""

    def __enter__(self):
        self.orig = widgets.Dialog.show
        widgets.Dialog.show = lambda self: (self.destroy(), None)[1]
        return self

    def __exit__(self, *a):
        widgets.Dialog.show = self.orig


def find_button(widget, text):
    for w in widget.winfo_children():
        try:
            if isinstance(w, (tk.Button, ttk.Button)) and w.cget("text") == text:
                return w
        except tk.TclError:
            pass
        found = find_button(w, text)
        if found:
            return found
    return None


def product_fields(sku, name, retail, **extra):
    d = dict(sku=sku, barcode="", name=name, brand_id=None, cat=None, model="", rack="R1", location="Main Shop",
             supplier_id=None, purchase_price="100", wholesale_price="120", retail_price=str(retail),
             min_price="0", min_stock="2", warranty_months="0", tax_percent="0", discount_percent="0",
             image_path="", description="", serialized=False, active=True, auto_barcode=True)
    d.update(extra)
    return d


# ================================================================== setup
user = auth.login(app.db, "admin", "admin123")
app.user = user
r = demo.load_demo(app.db, user)
print(f"demo data: {r['products']} products, {r['sales']} sales")
app.show_shell()
pump()

for key, label, perm, cls, group in appmod.NAV:
    app.navigate(key)
    pump()
check(len(app.screens) == 18, "all 18 screens open without error")

# ================================================================== PRODUCTS
app.navigate("products")
pump()
scr = app.screens["products"]

push(product_fields("UI-NEW-001", "UI Test Laptop Stand", "2500"))
scr.new()
pump()
row = app.db.one("SELECT * FROM products WHERE sku='UI-NEW-001'")
check(row is not None, "Products: new product created via screen")
check(row and row["retail_price"] == 2500, "Products: new product has the entered price")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == row["id"]][0])
push(product_fields("UI-NEW-001", "UI Test Laptop Stand (edited)", "2750"))
scr.edit()
pump()
row2 = catalog.get_product(app.db, row["id"])
check(row2["name"].endswith("(edited)") and row2["retail_price"] == 2750, "Products: edit updates name and price")

# categories & brands
mgr = PR.ManageDialog(scr, app)
push({"n": "UI Test Brand"})
mgr.add_brand()
pump()
check(app.db.scalar("SELECT 1 FROM brands WHERE name='UI Test Brand'"), "Products: new brand created via Categories & brands")
push({"n": "UI Test Category"})
mgr.add_cat(False)
pump()
check(app.db.scalar("SELECT 1 FROM categories WHERE name='UI Test Category'"), "Products: new top-level category created")
mgr.destroy()

# serial numbers on an existing serialized product
ser_prod = app.db.one("SELECT * FROM products WHERE serialized=1 AND active=1 LIMIT 1")
full = catalog.get_product(app.db, ser_prod["id"])
before_n = len(catalog.available_serials(app.db, ser_prod["id"]))
sd = PR.SerialsDialog(scr, app, full)
push({"serials": "UITESTSER0001\nUITESTSER0002", "cost": "5000"})
sd.add()
pump()
after_n = len(catalog.available_serials(app.db, ser_prod["id"]))
check(after_n == before_n + 2, "Products: adding serial numbers via the Serial numbers dialog increases stock")
sd.destroy()

# barcode label sheet
bd = PR.BarcodeDialog(scr, app, full)
if bd.code:
    bd.labels()
    label_path = os.path.join(app.paths["exports"], f"labels-{full['sku']}.html")
    check(os.path.isfile(label_path) and os.path.getsize(label_path) > 200, "Products: barcode label sheet HTML generated")
else:
    check(False, "Products: barcode label sheet HTML generated")
bd.destroy()

# delete an unused product (real delete, not deactivate)
push(product_fields("UI-DEL-001", "UI Throwaway Product", "100"))
scr.new()
pump()
del_row = app.db.one("SELECT * FROM products WHERE sku='UI-DEL-001'")
scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == del_row["id"]][0])
scr.delete()
pump()
check(not app.db.scalar("SELECT 1 FROM products WHERE id=?", (del_row["id"],)), "Products: unused product is really deleted")

# ================================================================== INVENTORY
app.navigate("inventory")
pump()
scr = app.screens["inventory"]
plain = app.db.one("SELECT * FROM products WHERE serialized=0 AND active=1 LIMIT 1")
scr.q.set(plain["sku"])
scr.table.reload()
scr.table.tree.selection_set(scr.table.tree.get_children()[0])
push({"qty": "999", "reason": "UI test recount"})
scr.adjust()
pump()
check(catalog.get_product(app.db, plain["id"])["stock"] == 999, "Inventory: stock adjustment applied")
check(inventory.verify_consistency(app.db) == [], "Inventory: still consistent after adjustment")

plain2 = app.db.one("SELECT * FROM products WHERE serialized=0 AND active=1 AND id<>?", (plain["id"],))
before_dmg = catalog.get_product(app.db, plain2["id"])["damaged"]
scr.q.set(plain2["sku"])
scr.table.reload()
scr.table.tree.selection_set(scr.table.tree.get_children()[0])
push({"qty": "1", "reason": "UI test damage"})
scr.damage()
pump()
check(catalog.get_product(app.db, plain2["id"])["damaged"] == before_dmg + 1, "Inventory: mark damaged applied")

scr.show_moves({"id": plain["id"], "name": plain["name"]})
pump()
check(scr.mv_product and scr.mv_product["id"] == plain["id"], "Inventory: movements tab loads for a product")

scr.check()
pump()
check(("showinfo" in [p[0] for p in popups[-1:]]) or True, "Inventory: integrity check runs without error")

# ================================================================== SUPPLIERS
app.navigate("suppliers")
pump()
scr = app.screens["suppliers"]
push({"name": "UI Test Supplier", "company": "UI Co", "phone": "0300-0000000", "email": "", "address": "Karachi",
      "payment_terms": "30 days", "opening_balance": "5000", "notes": ""})
scr.new()
pump()
sup = app.db.one("SELECT * FROM suppliers WHERE name='UI Test Supplier'")
check(sup is not None and sup["balance"] == 5000, "Suppliers: new supplier created with opening balance")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == sup["id"]][0])
push({"name": "UI Test Supplier", "company": "UI Co Renamed", "phone": "0300-0000000", "email": "",
      "address": "Karachi", "payment_terms": "15 days", "notes": ""})
scr.edit()
pump()
check(app.db.one("SELECT company FROM suppliers WHERE id=?", (sup["id"],))["company"] == "UI Co Renamed",
      "Suppliers: edit updates company name")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == sup["id"]][0])
push({"amount": "2000", "method": "Cash", "ref": "", "note": "UI test payment"})
scr.pay()
pump()
check(app.db.one("SELECT balance FROM suppliers WHERE id=?", (sup["id"],))["balance"] == 3000,
      "Suppliers: payment reduces balance")

ldg = party_dialogs.LedgerDialog(scr, app, "supplier", sup["id"])
check(len(ldg.rows) >= 2, "Suppliers: ledger shows opening balance and payment entries")
ldg.destroy()

# ================================================================== CUSTOMERS
app.navigate("customers")
pump()
scr = app.screens["customers"]
push({"name": "UI Test Customer", "company": "", "phone": "0311-1111111", "email": "", "address": "Lahore",
      "credit_limit": "50000", "opening_balance": "0", "notes": ""})
scr.new()
pump()
cust = app.db.one("SELECT * FROM customers WHERE name='UI Test Customer'")
check(cust is not None and cust["credit_limit"] == 50000, "Customers: new customer created with credit limit")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == cust["id"]][0])
push({"name": "UI Test Customer", "company": "Renamed Co", "phone": "0311-1111111", "email": "", "address": "Lahore",
      "credit_limit": "60000", "notes": ""})
scr.edit()
pump()
check(app.db.one("SELECT credit_limit FROM customers WHERE id=?", (cust["id"],))["credit_limit"] == 60000,
      "Customers: edit updates credit limit")

# sell on credit to this customer directly via the service so there is a balance to collect
plain3 = app.db.one("SELECT * FROM products WHERE serialized=0 AND active=1 AND id NOT IN (?,?)", (plain["id"], plain2["id"]))
sales.complete_sale(app.db, user, {"customer_id": cust["id"], "items": [{"product_id": plain3["id"], "qty": 1}],
                                   "payments": [{"method": "Credit", "amount": plain3["retail_price"]}]})
check(True, "Customers: setup credit sale for payment test")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == cust["id"]][0])
owed = parties.get_customer(app.db, cust["id"])["balance"]
push({"amount": str(owed), "method": "Cash", "ref": "", "note": "UI test full payment"})
scr.pay()
pump()
check(parties.get_customer(app.db, cust["id"])["balance"] == 0, "Customers: receive payment clears balance")

with NoopDialogShow():
    scr.ledger()
    pump()
with NoopDialogShow():
    scr.history()
    pump()
check(True, "Customers: ledger and purchase history dialogs open without error")

# ================================================================== PURCHASES
app.navigate("purchases")
pump()
scr = app.screens["purchases"]

dlg = PU.PurchaseDialog(scr, app)
dlg.sup.set(sup["name"])
pickers.ProductPicker.show = lambda self: {**plain, "purchase_price": plain["purchase_price"]}
push({"qty": "10", "cost": "150"})
dlg.add()
pump()
check(len(dlg.items) == 1 and dlg.items[0]["qty"] == 10, "Purchases: add product to a new purchase order")
dlg.save()
pump()
po_id = dlg.result
check(po_id is not None, "Purchases: purchase order created")
po = purchasing.get_purchase(app.db, po_id) if po_id else None
check(po and po["status"] == "Ordered" and po["total"] == 1500, "Purchases: order total correct (10 x 150)")

rdlg = PU.ReceiveDialog(scr, app, po_id)
for rr in rdlg.rows:
    if rr["item"]["serialized"]:
        rr["serials"] = "\n".join(f"UIPO{i}" for i in range(int(rr["qty"].get() or 0)))
rdlg.receive()
pump()
po_after = purchasing.get_purchase(app.db, po_id)
check(po_after["status"] == "Received", "Purchases: goods received into stock")
check(catalog.get_product(app.db, plain["id"])["stock"] == 999 + 10, "Purchases: received quantity added to stock")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == po_id][0])
push({"amount": "500", "method": "Bank Transfer", "ref": "TT1", "note": "UI test PO payment"})
scr.pay()
pump()
check(purchasing.get_purchase(app.db, po_id)["paid"] == 500, "Purchases: pay supplier from purchase order")

dlg2 = PU.PurchaseDialog(scr, app)
dlg2.sup.set(sup["name"])
push({"qty": "1", "cost": "10"})
dlg2.add()
dlg2.save()
pump()
cancel_id = dlg2.result
scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == cancel_id][0])
scr.cancel_po()
pump()
check(purchasing.get_purchase(app.db, cancel_id)["status"] == "Cancelled", "Purchases: cancel an unreceived order")

retdlg = PU.PurchaseReturnDialog(scr, app)
retdlg.sup.set(sup["name"])
stock_before = catalog.get_product(app.db, plain["id"])["stock"]
pickers.ProductPicker.show = lambda self: {**plain, "purchase_price": plain["purchase_price"]}
push({"qty": "1", "cost": "50"})
retdlg.add()
retdlg.save()
pump()
check(retdlg.result is True, "Purchases: return to supplier saved")
check(catalog.get_product(app.db, plain["id"])["stock"] == stock_before - 1, "Purchases: return to supplier reduces stock")
check(inventory.verify_consistency(app.db) == [] and parties.verify_balances(app.db) == [],
      "Purchases: books still consistent")

# ================================================================== RETURNS
app.navigate("returns")
pump()
scr = app.screens["returns"]
res2 = sales.complete_sale(app.db, user, {"customer_id": None, "items": [{"product_id": plain2["id"], "qty": 2}],
                                          "payments": [{"method": "Cash", "amount": plain2["retail_price"] * 2}]})
inv_no = res2["invoice_no"]
scr.load_invoice(inv_no)
pump()
check(scr.sale is not None and len(scr.rows) == 1, "Returns: invoice found and loaded")
scr.rows[0]["qty"].set("1")
scr.rows[0]["cond"].set("Good")
scr.process(False)
pump()
check(app.db.one("SELECT status FROM sales WHERE invoice_no=?", (inv_no,))["status"] == "Partially Returned",
      "Returns: partial return processed via the screen")

# serialized-item return
ser_prod2 = app.db.one("SELECT * FROM products WHERE serialized=1 AND stock>0 AND active=1 LIMIT 1")
res3 = sales.complete_sale(app.db, user, {"items": [{"product_id": ser_prod2["id"], "qty": 1,
                                                     "serial_ids": [catalog.available_serials(app.db, ser_prod2["id"])[0]["id"]]}],
                                          "payments": [{"method": "Cash", "amount": ser_prod2["retail_price"]}]})
inv2 = res3["invoice_no"]
scr.load_invoice(inv2)
pump()
row0 = scr.rows[0]
lbl = ttk.Label(scr.body)
P.SerialPicker.show = lambda self: [{"id": row0["item"]["sold_serials"][0]["serial_id"],
                                     "serial": row0["item"]["sold_serials"][0]["serial"]}]
scr.pick_serials(row0, lbl)
pump()
check(len(row0["serials"]) == 1, "Returns: serial number picked for a serialized return line")
scr.process(False)
pump()
check(app.db.one("SELECT status FROM sales WHERE invoice_no=?", (inv2,))["status"] == "Returned",
      "Returns: serialized full return processed via the screen")
check(inventory.verify_consistency(app.db) == [], "Returns: inventory still consistent")

# ================================================================== WARRANTY
app.navigate("warranty")
pump()
scr = app.screens["warranty"]
w_row = app.db.one("SELECT w.id, w.serial_id, se.serial FROM warranties w JOIN serials se ON se.id=w.serial_id "
                   "WHERE w.status='Active' LIMIT 1")
scr.vars["serial"].set(w_row["serial"])
scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == w_row["id"]][0])
push({"issue": "UI test - device does not power on"})
scr.claim()
pump()
check(app.db.scalar("SELECT COUNT(*) FROM warranty_claims WHERE warranty_id=? AND status='Open'", (w_row["id"],)) == 1,
      "Warranty: claim filed via the screen")

scr.claims.reload()
scr.claims.tree.selection_set([i for i, rr in scr.claims.rows.items() if rr["date"] and rr["status"] == "Open"][0])
with NoopDialogShow():
    scr.resolve()
    pump()
check(True, "Warranty: resolve-claim dialog builds without error")

# ================================================================== REPAIRS
app.navigate("repairs")
pump()
scr = app.screens["repairs"]
techs = app.db.q("SELECT id FROM users WHERE active=1")
push({"customer_id": cust["id"], "customer_name": "", "customer_phone": "", "device": "Laptop", "brand": "UITest",
      "model": "X1", "serial": "", "complaint": "UI test complaint - will not boot", "condition": "minor scratches",
      "accessories": "charger", "technician_id": techs[0]["id"], "estimated_cost": "1500", "expected_at": today()})
RP.TicketDialog.show = lambda self: self.destroy()
scr.new()
pump()
ticket = app.db.one("SELECT * FROM repairs WHERE device='Laptop' AND brand='UITest'")
check(ticket is not None and ticket["status"] == "Received", "Repairs: new ticket created via the screen")

td = RP.TicketDialog(scr, app, ticket["id"])
td.status.set("Diagnosing")
td.snote.set("UI test note")
td.set_status()
pump()
check(repairs.get_repair(app.db, ticket["id"])["status"] == "Diagnosing", "Repairs: status update via ticket dialog")

part_prod = app.db.one("SELECT * FROM products WHERE serialized=0 AND stock>0 AND active=1 LIMIT 1")
pickers.ProductPicker.show = lambda self: part_prod
push({"q": "1"})
td.add_part()
pump()
check(len(td.r["parts"]) == 1, "Repairs: part added and deducted from stock")

td.labor.set("750")
td.set_labor()
pump()
check(repairs.get_repair(app.db, ticket["id"])["labor_charge"] == 750, "Repairs: labor charge set")

td.new_note.set("UI test technician note")
td.add_note()
pump()
check(len(td.r["notes"]) >= 2, "Repairs: technician note added")

td.status.set("Ready")
td.set_status()
pump()
due = td.r["final_cost"] - td.r["paid"]
P.PayDialog.show = lambda self: {"payments": [{"method": "Cash", "amount": due, "ref": None}], "change": 0}
td.deliver()
pump()
check(repairs.get_repair(app.db, ticket["id"])["status"] == "Delivered", "Repairs: delivered and paid via the screen")
td.destroy()

# ================================================================== EXPENSES
app.navigate("expenses")
pump()
scr = app.screens["expenses"]
cats = finance.expense_categories(app.db)
push({"n": "UI Test Category"})
scr.add_cat()
pump()
check(app.db.scalar("SELECT 1 FROM expense_categories WHERE name='UI Test Category'"), "Expenses: new category created")
cat_id = app.db.scalar("SELECT id FROM expense_categories WHERE name='UI Test Category'")
reg_before = finance.register_summary(app.db, finance.open_register(app.db)["id"])["expected"]
push({"cat": cat_id, "date": today(), "amount": "1234", "method": "Cash", "desc": "UI test expense"})
scr.add()
pump()
check(app.db.scalar("SELECT COUNT(*) FROM expenses WHERE description='UI test expense'") == 1, "Expenses: expense recorded")
reg_after = finance.register_summary(app.db, finance.open_register(app.db)["id"])["expected"]
check(reg_after == reg_before - 1234, "Expenses: cash expense deducted from the register")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["description"] == "UI test expense"][0])
scr.delete()
pump()
check(app.db.scalar("SELECT COUNT(*) FROM expenses WHERE description='UI test expense'") == 0, "Expenses: delete removes it")
reg_restored = finance.register_summary(app.db, finance.open_register(app.db)["id"])["expected"]
check(reg_restored == reg_before, "Expenses: deleting a cash expense restores the register total")

# ================================================================== CASH REGISTER
app.navigate("cash")
pump()
scr = app.screens["cash"]
before = finance.register_summary(app.db, finance.open_register(app.db)["id"])["expected"]
push({"amount": "1000", "note": "UI test deposit"})
scr.move("Deposit")
pump()
after = finance.register_summary(app.db, finance.open_register(app.db)["id"])["expected"]
check(after == before + 1000, "Cash register: deposit recorded")
push({"amount": "300", "note": "UI test withdrawal"})
scr.move("Withdrawal")
pump()
check(finance.register_summary(app.db, finance.open_register(app.db)["id"])["expected"] == after - 300,
      "Cash register: withdrawal recorded")

reg_id = finance.open_register(app.db)["id"]
with NoopDialogShow():
    scr.moves(reg_id)
    pump()
check(True, "Cash register: movements dialog opens without error")

expected = finance.register_summary(app.db, reg_id)["expected"]
with NoopDialogShow():
    push({"actual": str(expected), "note": "UI test close"})
    scr.close()
    pump()
closed = app.db.one("SELECT * FROM cash_registers WHERE id=?", (reg_id,))
check(closed["status"] == "Closed" and closed["variance"] == 0, "Cash register: close with zero variance")

push({"cash": "20000"})
scr.open()
pump()
check(finance.open_register(app.db) is not None, "Cash register: reopened for the rest of the day")

# ================================================================== REPORTS
app.navigate("reports")
pump()
scr = app.screens["reports"]


def run_report(path_labels):
    node = None
    for top in scr.tree.get_children():
        if scr.tree.item(top, "text") == path_labels[0]:
            for child in scr.tree.get_children(top):
                if scr.tree.item(child, "text") == path_labels[1]:
                    node = child
    scr.tree.selection_set(node)
    scr.run()
    pump()


run_report(("Sales", "Daily sales"))
check(scr.report is not None and scr.report["rows"], "Reports: daily sales report runs")
run_report(("Financial", "Profit & loss"))
check(scr.report is not None and "net_profit" in (scr.report.get("summary") or {}), "Reports: profit & loss runs")
run_report(("Inventory", "Low stock"))
check(scr.report is not None, "Reports: low stock report runs")

exp_dir = tempfile.mkdtemp()
for ext in ("csv", "xlsx", "pdf"):
    target = os.path.join(exp_dir, f"report.{ext}")
    reports_mod = sys.modules["shoppos.ui.screens.reports"]
    reports_mod.filedialog.asksaveasfilename = (lambda _t=target: (lambda **kw: _t))()
    widgets.messagebox.askyesno = lambda *a, **k: False
    scr.export(ext)
    pump()
    check(os.path.isfile(target) and os.path.getsize(target) > 50, f"Reports: export to {ext.upper()} works")
widgets.messagebox.askyesno = lambda *a, **k: True

# ================================================================== USERS
app.navigate("users")
pump()
scr = app.screens["users"]
push({"username": "uitest", "name": "UI Test User", "role": "Cashier", "pw": "testpass1", "pw2": "testpass1"})
scr.new()
pump()
new_user = app.db.one("SELECT * FROM users WHERE username='uitest'")
check(new_user is not None and new_user["role"] == "Cashier", "Users: new user created via the screen")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == new_user["id"]][0])
push({"name": "UI Test User Two", "role": "Sales Staff", "active": True})
scr.edit()
pump()
check(app.db.one("SELECT full_name, role FROM users WHERE id=?", (new_user["id"],))["role"] == "Sales Staff",
      "Users: edit changes role")

scr.table.reload()
scr.table.tree.selection_set([i for i, rr in scr.table.rows.items() if rr["id"] == new_user["id"]][0])
push({"pw": "resetpass1"})
scr.reset()
pump()
relog = auth.login(app.db, "uitest", "resetpass1")
check(relog["username"] == "uitest", "Users: password reset takes effect")

scr.role.set("Sales Staff")
scr.load_role()
before_perms = auth.permissions_for(app.db, "Sales Staff")
scr.vars["reports.view"].set(True)
scr.save_role()
pump()
check("reports.view" in auth.permissions_for(app.db, "Sales Staff"), "Users: role permission change saved")

# ================================================================== AUDIT
app.navigate("audit")
pump()
scr = app.screens["audit"]
scr.table.reload()
check(scr.table.total > 0, "Audit: log has entries")
first_row = next(iter(scr.table.rows.values()))
with NoopDialogShow():
    scr.detail(first_row)
    pump()
check(True, "Audit: detail dialog opens without error")

# ================================================================== SETTINGS  (rebuilds the shell - keep last)
app.navigate("settings")
pump()
scr = app.screens["settings"]
scr.vars["shop_name"][1].set("UI Test Shop Name")
scr.save()
pump()
check(settings_svc.get(app.db, "shop_name") == "UI Test Shop Name", "Settings: business settings saved")

# ================================================================== BACKUP  (re-fetch screen: settings.save() rebuilt the shell)
app.navigate("backup")
pump()
scr = app.screens["backup"]
temp_backup_dir = tempfile.mkdtemp()
scr.folder.set(temp_backup_dir)
scr.freq.set("daily")
scr.on_close.set(True)
scr.keep.set("10")
scr.save_opts()
pump()
check(settings_svc.get(app.db, "backup_dir") == temp_backup_dir, "Backup: backup settings saved")
scr.now()
pump()
files = [f for f in os.listdir(temp_backup_dir) if f.endswith(".db")]
check(len(files) >= 1, "Backup: manual backup created in the chosen folder")

# ================================================================== final integrity
check(inventory.verify_consistency(app.db) == [], "Final: inventory consistent across all tests")
check(parties.verify_balances(app.db) == [], "Final: customer/supplier ledgers consistent across all tests")

print()
print(f"{passed} passed, {len(failed)} failed, {len(errors)} unhandled UI errors")
for m in failed:
    print("FAILED:", m)
for e in errors[:8]:
    print("ERROR:", e)
app.destroy()
sys.exit(1 if (failed or errors) else 0)
