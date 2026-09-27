import tkinter as tk
from tkinter import ttk

from ...services import parties
from .. import widgets
from ..base import Screen
from ..party_dialogs import LedgerDialog, payment_form
from ..widgets import DataTable, FormDialog


class SuppliersScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Suppliers", "Who you buy from, and what you owe them")
        ttk.Button(act, text="+ New supplier", style="Primary.TButton", command=self.new).pack()
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=34)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search name, company or phone...")
        e.bind("<KeyRelease>", lambda ev: self.table.reload())
        cols = [("name", "Supplier", 200), ("company", "Company", 200), ("phone", "Phone", 110), ("payment_terms", "Terms", 90),
                ("total_purchases", "Total purchases", 120, "e", widgets.fmt_money), ("total_payments", "Total payments", 120, "e", widgets.fmt_money),
                ("balance", "We owe", 110, "e", widgets.fmt_money)]
        self.table = DataTable(self, cols, lambda l, o: parties.list_suppliers(self.db, self.user, self.q.get().strip(), l, o),
                               empty_text="No suppliers found.",
                               on_open=lambda r: self.ledger(), tag_fn=lambda r: "danger" if r["balance"] > 0.005 else None)
        self.table.pack(fill="both", expand=True)
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(10, 0))
        for t, c, s in (("Edit", self.edit, "Secondary"), ("Ledger / statement", self.ledger, "Secondary"), ("Pay supplier", self.pay, "Primary")):
            ttk.Button(b, text=t, style=f"{s}.TButton", command=c).pack(side="left", padx=(0, 8))

    def on_show(self):
        self.table.reload(keep_page=True)

    def _form(self, s=None):
        fields = [{"key": "name", "label": "Supplier name", "required": True}, {"key": "company", "label": "Company"},
                  {"key": "phone", "label": "Phone"}, {"key": "email", "label": "Email"},
                  {"key": "address", "label": "Address", "full": True, "width": 44},
                  {"key": "payment_terms", "label": "Payment terms", "help": "e.g. 30 days, cash on delivery"}]
        if not s:
            fields.append({"key": "opening_balance", "label": "Opening balance (we owe)", "type": "money", "default": "0"})
        fields.append({"key": "notes", "label": "Notes", "type": "multiline", "full": True, "width": 44})

        def save(v):
            return {"id": parties.save_supplier(self.db, self.user, v, s["id"] if s else None)}
        return FormDialog(self, "Edit supplier" if s else "New supplier", fields, s, on_save=save, columns=2, width=720).show()

    def new(self):
        r = self._form()
        if r:
            self.toast("Supplier saved")
            self.table.reload(select_id=r["id"])

    def edit(self):
        s = self.table.selected()
        if s:
            r = self._form(s)
            if r:
                self.toast("Supplier saved")
                self.table.reload(keep_page=True)

    def ledger(self):
        s = self.table.selected()
        if s:
            LedgerDialog(self, self.app, "supplier", s["id"]).show()
            self.table.reload(keep_page=True)

    def pay(self):
        s = self.table.selected()
        if s:
            with self.guard():
                if payment_form(self, self.app, "supplier", s):
                    self.table.reload(keep_page=True)
