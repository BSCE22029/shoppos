import tkinter as tk
from tkinter import ttk

from ...config import PAYMENT_METHODS
from ...services import finance, settings
from ...util import money, today
from .. import widgets
from ..base import Screen
from ..widgets import DataTable, FormDialog, date_range_bar


class ExpensesScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Expenses", "Rent, electricity, salaries and every other shop cost")
        ttk.Button(act, text="+ Add expense", style="Primary.TButton", command=self.add).pack(side="right")
        ttk.Button(act, text="New category", style="Secondary.TButton", command=self.add_cat).pack(side="right", padx=8)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.cat = tk.StringVar(value="All categories")
        self.cat_cb = ttk.Combobox(bar, textvariable=self.cat, state="readonly", width=22)
        self.cat_cb.pack(side="left")
        self.cat_cb.bind("<<ComboboxSelected>>", lambda e: self.table.reload())
        f, self.dates = date_range_bar(bar, lambda: self.table.reload(), 30)
        f.pack(side="left", padx=12)
        cols = [("date", "Date", 100), ("category", "Category", 140), ("description", "Description", 300), ("method", "Method", 110),
                ("amount", "Amount", 110, "e", widgets.fmt_money), ("username", "By", 90)]
        self.table = DataTable(self, cols, self._load, page_size=50)
        self.table.pack(fill="both", expand=True)
        self.total = ttk.Label(self, text="", font=("Segoe UI", 12, "bold"))
        self.total.pack(anchor="e", pady=6)
        ttk.Button(self, text="Delete selected expense", style="Danger.TButton", command=self.delete).pack(anchor="w")

    def _cats(self):
        return {c["name"]: c["id"] for c in finance.expense_categories(self.db)}

    def _load(self, limit, offset):
        f, t = self.dates()
        cid = self._cats().get(self.cat.get())
        rows, total, s = finance.list_expenses(self.db, self.user, f, t, cid, limit, offset)
        self.total.configure(text=f"Total for selection: {money(s, settings.get(self.db, 'currency'))}")
        return rows, total

    def on_show(self):
        self.cat_cb["values"] = ["All categories"] + list(self._cats())
        self.table.reload(keep_page=True)

    def add(self):
        cats = self._cats()

        def save(v):
            return {"id": finance.add_expense(self.db, self.user, v["cat"], v["date"], v["amount"], v["method"], v["desc"])}
        r = FormDialog(self, "New expense", [
            {"key": "cat", "label": "Category", "type": "choice", "choices": [(i, n) for n, i in cats.items()], "required": True},
            {"key": "date", "label": "Date (YYYY-MM-DD)", "default": today(), "required": True},
            {"key": "amount", "label": "Amount", "type": "money", "required": True},
            {"key": "method", "label": "Payment method", "type": "choice", "choices": [(m, m) for m in PAYMENT_METHODS], "default": "Cash", "required": True},
            {"key": "desc", "label": "Description", "width": 44, "full": True},
            {"key": "l", "type": "label", "label": "Cash expenses are deducted from the cash register."}], on_save=save).show()
        if r:
            self.toast("Expense recorded")
            self.app.update_register_status()
            self.table.reload()

    def add_cat(self):
        def save(v):
            return {"id": finance.add_expense_category(self.db, self.user, v["n"])}
        if FormDialog(self, "New expense category", [{"key": "n", "label": "Name", "required": True}], on_save=save).show():
            self.on_show()

    def delete(self):
        r = self.table.selected()
        if r and widgets.confirm(self, "Delete this expense? Cash expenses are put back in the register.", danger=True):
            with self.guard():
                finance.delete_expense(self.db, self.user, r["id"])
                self.table.reload(keep_page=True)
