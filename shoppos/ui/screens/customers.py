import tkinter as tk
from tkinter import ttk

from ...services import parties, sales
from ...util import money
from .. import widgets
from ..base import Screen
from ..party_dialogs import LedgerDialog, payment_form
from ..widgets import DataTable, Dialog, FormDialog


class CustomersScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Customers", "Contacts, credit and purchase history")
        if self.can("customers.manage"):
            ttk.Button(act, text="+ New customer", style="Primary.TButton", command=self.new).pack()
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=34)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search name, company or phone...")
        e.bind("<KeyRelease>", lambda ev: self.table.reload())
        self.owing = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Only customers who owe money", variable=self.owing, command=lambda: self.table.reload()).pack(side="left", padx=12)
        cols = [("name", "Customer", 190), ("company", "Company", 150), ("phone", "Phone", 110), ("credit_limit", "Credit limit", 95, "e", widgets.fmt_money),
                ("total_purchases", "Total purchases", 115, "e", widgets.fmt_money), ("total_paid", "Total paid", 105, "e", widgets.fmt_money),
                ("balance", "Owes", 100, "e", widgets.fmt_money), ("store_credit", "Store credit", 95, "e", widgets.fmt_money)]
        self.table = DataTable(self, cols, lambda l, o: parties.list_customers(self.db, self.user, self.q.get().strip(), l, o, self.owing.get()),
                               empty_text="No customers found.",
                               on_open=lambda r: self.history(), tag_fn=lambda r: "danger" if r["balance"] > 0.005 else None)
        self.table.pack(fill="both", expand=True)
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(10, 0))
        if self.can("customers.manage"):
            ttk.Button(b, text="Edit", style="Secondary.TButton", command=self.edit).pack(side="left", padx=(0, 8))
        ttk.Button(b, text="Purchase history", style="Secondary.TButton", command=self.history).pack(side="left", padx=(0, 8))
        ttk.Button(b, text="Ledger / statement", style="Secondary.TButton", command=self.ledger).pack(side="left", padx=(0, 8))
        if self.can("customers.payments"):
            ttk.Button(b, text="Receive payment", style="Primary.TButton", command=self.pay).pack(side="left")

    def on_show(self):
        self.table.reload(keep_page=True)

    def _form(self, c=None):
        fields = [{"key": "name", "label": "Name", "required": True}, {"key": "company", "label": "Company"},
                  {"key": "phone", "label": "Phone"}, {"key": "email", "label": "Email"},
                  {"key": "address", "label": "Address", "full": True, "width": 44},
                  {"key": "credit_limit", "label": "Credit limit (0 = no credit)", "type": "money", "default": "0"}]
        if not c:
            fields.append({"key": "opening_balance", "label": "Opening balance (owes us)", "type": "money", "default": "0"})
        fields.append({"key": "notes", "label": "Notes", "type": "multiline", "full": True, "width": 44})

        def save(v):
            return {"id": parties.save_customer(self.db, self.user, v, c["id"] if c else None)}
        return FormDialog(self, "Edit customer" if c else "New customer", fields, c, on_save=save, columns=2, width=720).show()

    def new(self):
        r = self._form()
        if r:
            self.toast("Customer saved")
            self.table.reload(select_id=r["id"])

    def edit(self):
        c = self.table.selected()
        if c:
            r = self._form(c)
            if r:
                self.toast("Customer saved")
                self.table.reload(keep_page=True)

    def ledger(self):
        c = self.table.selected()
        if c:
            LedgerDialog(self, self.app, "customer", c["id"]).show()
            self.table.reload(keep_page=True)

    def pay(self):
        c = self.table.selected()
        if c:
            with self.guard():
                if payment_form(self, self.app, "customer", c):
                    self.table.reload(keep_page=True)
                    self.app.update_register_status()

    def history(self):
        c = self.table.selected()
        if not c:
            return
        d = Dialog(self, f"Purchase history - {c['name']}", 780, 520, resizable=True)
        ttk.Label(d, text=c["name"], style="H2.TLabel").pack(anchor="w", padx=16, pady=(14, 8))
        rows = parties.customer_history(self.db, self.user, c["id"])
        t = DataTable(d, [("invoice_no", "Invoice", 110), ("date", "Date", 140, "w", widgets.fmt_date), ("total", "Total", 100, "e", widgets.fmt_money),
                          ("paid", "Paid", 100, "e", widgets.fmt_money), ("credit", "On credit", 100, "e", widgets.fmt_money), ("status", "Status", 120)],
                      lambda l, o: (rows[o:o + l], len(rows)), page_size=100, height=12,
                      tag_fn=lambda r: "muted" if r["status"] == "Cancelled" else None)
        t.pack(fill="both", expand=True, padx=16)
        t.reload()
        ttk.Button(d, text="Close", style="Secondary.TButton", command=d.destroy).pack(pady=12)
        d.show()
