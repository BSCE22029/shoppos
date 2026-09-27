"""Small pick-a-record dialogs shared by several screens."""
import tkinter as tk
from tkinter import ttk

from ..services import catalog
from . import widgets
from .widgets import DataTable, Dialog


class ProductPicker(Dialog):
    def __init__(self, parent, app, title="Choose product", only_serialized=None, in_stock_only=False, show_cost=False):
        super().__init__(parent, title, 720, 480, resizable=True)
        self.app, self.in_stock_only, self.only_serialized = app, in_stock_only, only_serialized
        ttk.Label(self, text="Search by name, SKU, barcode or model", style="Muted.TLabel").pack(anchor="w", padx=16, pady=(14, 4))
        self.q = tk.StringVar()
        e = ttk.Entry(self, textvariable=self.q)
        e.pack(fill="x", padx=16)
        e.bind("<KeyRelease>", lambda ev: self.reload())
        e.bind("<Return>", lambda ev: self.pick())
        e.bind("<Down>", lambda ev: self.table.tree.focus_set())
        cols = [("sku", "SKU", 110), ("name", "Product", 300), ("retail_price", "Price", 90, "e", widgets.fmt_money),
                ("stock", "Stock", 60, "e")]
        if show_cost:
            cols.insert(3, ("purchase_price", "Cost", 90, "e", widgets.fmt_money))
        self.table = DataTable(self, cols, self._load, page_size=40, height=11, on_open=lambda r: self.pick())
        self.table.pack(fill="both", expand=True, padx=16, pady=10)
        bar = ttk.Frame(self, padding=(16, 0, 16, 14))
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Select", style="Primary.TButton", command=self.pick).pack(side="right")
        self.reload()
        self.after(80, e.focus_set)

    def _load(self, limit, offset):
        rows = catalog.pos_search(self.app.db, self.q.get().strip(), 200)
        if self.in_stock_only:
            rows = [r for r in rows if r["stock"] > 0]
        if self.only_serialized is not None:
            rows = [r for r in rows if bool(r["serialized"]) == self.only_serialized]
        return rows[offset:offset + limit], len(rows)

    def reload(self):
        self.table.reload()
        self.table.focus_first()

    def pick(self):
        r = self.table.selected()
        if not r:
            widgets.show_warn(self, "Select a product.")
            return
        self.result = r
        self.destroy()
