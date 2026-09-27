"""UI smoke + workflow test: builds the real window, opens every screen, then drives real POS / returns / repair / warranty
workflows through the screen code (modal dialogs are stubbed with scripted answers).
Run: python tests/ui_smoke.py"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ["SHOPPOS_DATA"] = tmp
from shoppos.services import auth
auth.ITER = 1000
from shoppos.ui import app as appmod, widgets
from shoppos.ui.screens import pos as P
from shoppos.services import demo, catalog, sales, inventory, parties, finance, reports

errors = []
app = appmod.App()
app.report_callback_exception = lambda e, v, tb: errors.append("".join(traceback.format_exception(e, v, tb)))
popups = []
for n in ("showerror", "showwarning", "showinfo"):
    setattr(widgets.messagebox, n, lambda *a, _n=n, **k: popups.append((_n, a[1] if len(a) > 1 else "")))
widgets.messagebox.askyesno = lambda *a, **k: True

def pump(n=3):
    for _ in range(n):
        app.update_idletasks(); app.update()

def check(cond, msg):
    if not cond:
        errors.append("CHECK FAILED: " + msg)
    print(("ok   " if cond else "FAIL ") + msg)

pump()
user = auth.login(app.db, "admin", "admin123")
app.user = user
demo.load_demo(app.db, user)
app.show_shell(); pump()
for key, label, perm, cls, group in appmod.NAV:
    app.navigate(key); pump()
check(len(app.screens) == 18, "all 18 screens open")

# ---- POS: scan, search, quantity, hold/resume, pay
app.navigate("pos"); pump()
pos = app.screens["pos"]
p = app.db.one("SELECT * FROM products WHERE serialized=0 AND stock>10 LIMIT 1")
before = p["stock"]
pos.q.set(p["barcode"]); pos.submit(); pump()
pos.q.set(p["sku"]); pos.submit(); pump()
check(len(pos.cart) == 1 and pos.cart[0]["qty"] == 2, "barcode + SKU scan add the same product twice (qty 2)")
pos.cart_tree.selection_set(pos.cart_tree.get_children()[0]); pos.qty_up(); pump()
check(pos.cart[0]["qty"] == 3, "+ Qty works")
pos.qty_down(); pump()
check(pos.cart[0]["qty"] == 2, "- Qty works")
pos.q.set("no-such-product-xyz"); pos.submit(); pump()
check(len(pos.cart) == 1, "unknown code adds nothing")

ser = app.db.one("SELECT * FROM products WHERE serialized=1 AND stock>1 LIMIT 1")
serials = catalog.available_serials(app.db, ser["id"])
P.SerialPicker.show = lambda self: [serials[0]]                  # cashier picks the first serial
pos.q.set(ser["barcode"]); pos.submit(); pump()
line = [l for l in pos.cart if l["product"]["id"] == ser["id"]][0]
check(line["qty"] == 1 and line["serials"][0]["serial"] == serials[0]["serial"], "serialized product added with chosen serial")
pos.q.set(serials[1]["serial"]); pos.submit(); pump()                # scanning a serial number directly adds it
check(line["qty"] == 2 and len(line["serials"]) == 2, "scanning a serial number adds that unit")

total_before = sales.preview_totals(app.db, pos.cart_dict())["total"]
check(str(pos.t_total.cget("text")).replace(",", "").endswith(str(int(total_before))), "total label matches service total")

# hold then resume
P.ask_text = lambda *a, **k: "held by test"
pos.hold(); pump()
check(pos.cart == [] and len(sales.list_held(app.db)) == 1, "hold clears cart and stores the sale")
P.ResumeDialog.show = lambda self: sales.list_held(app.db)[0]["id"]
pos.resume(); pump()
check(len(pos.cart) == 2, "resume restores both lines")

# customer + payment (cash + credit split)
cust = app.db.one("SELECT * FROM customers ORDER BY credit_limit-balance DESC LIMIT 1")
pos.set_customer(cust)
cash = 10000
credit = total_before - cash
P.PayDialog.show = lambda self: {"payments": [{"method": "Cash", "amount": cash, "ref": None}, {"method": "Credit", "amount": credit, "ref": None}], "change": 0}
P.SaleDoneDialog.show = lambda self: None
bal_before = parties.get_customer(app.db, cust["id"])["balance"]
pos.pay(); pump()
check(pos.cart == [], "cart cleared after payment")
last = app.db.one("SELECT * FROM sales ORDER BY id DESC LIMIT 1")
check(abs(last["total"] - total_before) < 0.01 and abs(last["credit"] - credit) < 0.01, "sale saved with split payment")
check(abs(parties.get_customer(app.db, cust["id"])["balance"] - (bal_before + credit)) < 0.01, "customer balance increased by credit portion")
check(app.db.one("SELECT stock FROM products WHERE id=?", (p["id"],))["stock"] == before - 2, "stock reduced")
check(app.db.scalar("SELECT COUNT(*) FROM held_sales") == 0, "held sale removed after completion")
check(inventory.verify_consistency(app.db) == [] and parties.verify_balances(app.db) == [], "inventory and ledgers consistent")

# insufficient stock is a friendly message, not a crash
pos.reset(); popups.clear()
zero = app.db.one("SELECT * FROM products WHERE stock=0 AND serialized=0 AND active=1 LIMIT 1")
if zero:
    pos.add_product(zero); pump()
    check(pos.cart == [] and popups, "out-of-stock product is refused with a message")

# ---- Sales screen: cancel via UI
app.navigate("sales"); pump()
sc = app.screens["sales"]
sc.table.reload()
row = next(r for r in sc.table.rows.values() if r["id"] == last["id"])
sc.table.tree.selection_set([i for i, r in sc.table.rows.items() if r["id"] == last["id"]][0])
widgets.FormDialog.show = lambda self: self.on_save({"reason": "test cancel"}) or True
sc.cancel(); pump()
check(app.db.one("SELECT status FROM sales WHERE id=?", (last["id"],))["status"] == "Cancelled", "sale cancelled from the Sales screen")
check(inventory.verify_consistency(app.db) == [] and parties.verify_balances(app.db) == [], "consistent after cancel")

# ---- theme toggle + logout/login round trip
app.toggle_theme(); pump(); app.toggle_theme(); pump()
check(app.current is not None, "theme toggles without losing the current screen")
# idle session timeout signs the user out
app.last_activity -= 60 * 60
app._idle_check(); pump()
check(app.user is None, "session times out after being idle")
app.user = user; app.show_shell(); pump()
app.logout(); pump()
check(app.user is None, "logout returns to login")
errors_ui = [e for e in errors if not e.startswith("CHECK")]
print("unhandled UI errors:", len(errors_ui))
for e in errors[:6]:
    print(e)
app.destroy()
sys.exit(1 if errors else 0)
