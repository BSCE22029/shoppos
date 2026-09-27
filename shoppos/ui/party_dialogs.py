"""Ledger and payment dialogs shared by the Customers and Suppliers screens."""
from tkinter import ttk

from ..config import PAYMENT_METHODS
from ..services import finance, parties, purchasing
from ..util import money
from . import widgets
from .widgets import DataTable, Dialog, FormDialog


def payment_form(parent, app, kind, party, purchase_id=None):
    """kind 'customer' (receive) or 'supplier' (pay). Returns True when a payment was recorded."""
    owed = max(party["balance"], 0)

    def save(v):
        amount = v["amount"]
        if kind == "customer":
            finance.receive_customer_payment(app.db, app.user, party["id"], amount, v["method"], v["ref"], v["note"])
        else:
            purchasing.pay_supplier(app.db, app.user, party["id"], amount, v["method"], purchase_id, v["ref"], v["note"])
        return v
    title = "Receive payment" if kind == "customer" else "Pay supplier"
    r = FormDialog(parent, title, [
        {"key": "l", "type": "label", "label": f"{party['name']}\n{'Owes us' if kind == 'customer' else 'We owe'}: {money(owed)}"},
        {"key": "amount", "label": "Amount", "type": "money", "required": True, "default": f"{owed:.2f}".rstrip("0").rstrip(".")},
        {"key": "method", "label": "Method", "type": "choice", "choices": [(m, m) for m in PAYMENT_METHODS], "default": "Cash", "required": True},
        {"key": "ref", "label": "Reference (optional)"}, {"key": "note", "label": "Note (optional)"}],
        on_save=save, save_text="Record payment").show()
    if r:
        app.toast("Payment recorded")
        return True
    return False


class LedgerDialog(Dialog):
    def __init__(self, parent, app, kind, party_id):
        super().__init__(parent, "Ledger", 860, 560, resizable=True)
        self.app, self.kind, self.pid = app, kind, party_id
        self.head = ttk.Label(self, text="", style="H2.TLabel")
        self.head.pack(anchor="w", padx=16, pady=(14, 0))
        self.sub = ttk.Label(self, text="", style="Muted.TLabel")
        self.sub.pack(anchor="w", padx=16, pady=(0, 8))
        cols = [("date", "Date", 140, "w", widgets.fmt_date), ("kind", "Entry", 150), ("ref", "Reference", 130), ("note", "Note", 200),
                ("amount", "Amount", 100, "e", lambda v, r: f"{v:+,.0f}"), ("balance", "Balance", 110, "e", widgets.fmt_money)]
        self.table = DataTable(self, cols, lambda lim, off: (self.rows[off:off + lim], len(self.rows)), page_size=200, height=13,
                               tag_fn=lambda r: "danger" if r["amount"] > 0 else "ok")
        self.table.pack(fill="both", expand=True, padx=16)
        bar = ttk.Frame(self, padding=16)
        bar.pack(fill="x")
        perm = "customers.payments" if kind == "customer" else "suppliers.manage"
        if perm in app.user["permissions"]:
            ttk.Button(bar, text="Receive payment" if kind == "customer" else "Pay supplier", style="Primary.TButton",
                       command=self.pay).pack(side="left")
        ttk.Button(bar, text="Close", style="Secondary.TButton", command=self.destroy).pack(side="right")
        self.reload()

    def reload(self):
        db = self.app.db
        tbl = "customers" if self.kind == "customer" else "suppliers"
        self.party = db.one(f"SELECT * FROM {tbl} WHERE id=?", (self.pid,))
        self.rows = list(reversed(parties.ledger(db, self.kind, self.pid)))
        self.head.configure(text=f"{self.party['name']} - ledger")
        who = "owes us" if self.kind == "customer" else "we owe"
        extra = f"   |   store credit {money(self.party['store_credit'])}" if self.kind == "customer" and self.party["store_credit"] else ""
        self.sub.configure(text=f"Balance: {who} {money(self.party['balance'])}{extra}")
        self.table.reload()

    def pay(self):
        with self.app.guard():
            if payment_form(self, self.app, self.kind, self.party):
                self.reload()
