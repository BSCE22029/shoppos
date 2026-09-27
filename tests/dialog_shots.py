"""Renders key dialogs (without blocking) to PNG for visual review."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screenshots as S   # reuses the app + grab()
S.prepare()
app, grab, pump, out = S.app, S.grab, S.pump, S.out
from shoppos.ui import widgets
from shoppos.ui.screens import pos as P, repairs as R, products as PR, purchases as PU
from shoppos.services import catalog, parties, repairs

def dshot(name, dlg):
    dlg.update_idletasks(); dlg.show = None
    w, h = dlg._size
    from shoppos.ui import theme
    dlg.geometry(f"{theme.px(w) if w else dlg.winfo_reqwidth()}x{theme.px(h) if h else dlg.winfo_reqheight()}+150+40")
    pump(); dlg.lift(); pump()
    S.grab(dlg, os.path.join(out, name + ".png")); print("saved", name, flush=True)
    dlg.destroy(); pump()

app.navigate("pos"); pump()
cust = parties.get_customer(app.db, 2)
d = P.PayDialog(app, 54600, cust, "PKR"); d.payments.append({"method": "Cash", "amount": 30000, "ref": None}); d.refresh(); dshot("d1_pay", d)
prod = app.db.one("SELECT * FROM products WHERE serialized=1 AND stock>3 LIMIT 1")
d = P.SerialPicker(app, prod, catalog.available_serials(app.db, prod["id"])); dshot("d2_serials", d)
d = P.CustomerPicker(app, app); dshot("d3_customer", d)
class Fake: pass
app.navigate("products"); pump(); scr = app.screens["products"]
try:
    d = None
    orig = widgets.FormDialog.show
    captured = {}
    def fake_show(self):
        captured["d"] = self; return None
    widgets.FormDialog.show = fake_show
    PR.ProductDialog(scr, catalog.get_product(app.db, prod["id"])).show()
    widgets.FormDialog.show = orig
    dshot("d4_product", captured["d"])
finally:
    widgets.FormDialog.show = orig
rid = app.db.scalar("SELECT id FROM repairs LIMIT 1")
d = R.TicketDialog(app, app, rid); dshot("d5_ticket", d)
d = PU.PurchaseDialog(app, app); dshot("d6_po", d)
app.destroy()
