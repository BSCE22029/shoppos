import tkinter as tk
from tkinter import ttk

from ...services import catalog, inventory, parties
from ...util import POSError, money
from .. import widgets
from ..base import Screen
from ..pickers import ProductPicker
from ..widgets import DataTable, FormDialog, date_range_bar
from .products import SerialsDialog


class InventoryScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Inventory", "Current stock, availability and every stock movement")
        ttk.Button(act, text="Integrity check", style="Secondary.TButton", command=self.check).pack(side="right")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        st = ttk.Frame(nb, padding=12)
        mv = ttk.Frame(nb, padding=12)
        nb.add(st, text="  Stock  ")
        nb.add(mv, text="  Movements  ")
        self.nb = nb
        # stock tab
        bar = ttk.Frame(st)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=32)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search SKU or product name...")
        e.bind("<KeyRelease>", lambda ev: self._deb())
        self.status = tk.StringVar(value="All")
        cb = ttk.Combobox(bar, textvariable=self.status, state="readonly", width=16, values=["All", "Low stock", "Out of stock"])
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda ev: self.table.reload())
        cols = [("sku", "SKU", 110), ("name", "Product", 300), ("stock", "Current", 70, "e"), ("reserved", "Reserved", 70, "e"),
                ("available", "Available", 75, "e"), ("damaged", "Damaged", 70, "e"), ("sold", "Sold (net)", 75, "e"),
                ("min_stock", "Minimum", 70, "e"), ("state", "State", 90)]
        if self.can("products.cost"):
            cols.insert(8, ("value", "Stock value", 100, "e", widgets.fmt_money))
        self.table = DataTable(st, cols, self._load, page_size=60, tag_fn=lambda r: {"Out of stock": "danger", "Low": "warn"}.get(r["state"]),
                               on_open=lambda r: self.show_moves(r))
        self.table.pack(fill="both", expand=True)
        b = ttk.Frame(st)
        b.pack(fill="x", pady=(10, 0))
        if self.can("inventory.adjust"):
            ttk.Button(b, text="Adjust stock", style="Primary.TButton", command=self.adjust).pack(side="left")
            ttk.Button(b, text="Mark damaged", style="Secondary.TButton", command=self.damage).pack(side="left", padx=8)
        ttk.Button(b, text="Serial numbers", style="Secondary.TButton", command=self.serials).pack(side="left")
        ttk.Button(b, text="Movements of selected", style="Secondary.TButton", command=lambda: self.show_moves(self.table.selected())).pack(side="left", padx=8)
        # movements tab
        bar2 = ttk.Frame(mv)
        bar2.pack(fill="x", pady=(0, 10))
        self.mv_product = None
        self.mv_lbl = ttk.Label(bar2, text="All products", style="Muted.TLabel", width=34)
        ttk.Button(bar2, text="Product...", style="Secondary.TButton", command=self.pick_mv).pack(side="left")
        self.mv_lbl.pack(side="left", padx=8)
        self.mv_type = tk.StringVar(value="All")
        cb2 = ttk.Combobox(bar2, textvariable=self.mv_type, state="readonly", width=18, values=["All"] + inventory.TX_TYPES)
        cb2.pack(side="left")
        cb2.bind("<<ComboboxSelected>>", lambda ev: self.mv.reload())
        f, self.mv_dates = date_range_bar(bar2, lambda: self.mv.reload(), 30)
        f.pack(side="left", padx=12)
        self.mv = DataTable(mv, [("date", "Date", 130, "w", widgets.fmt_date), ("sku", "SKU", 100), ("product", "Product", 260),
                                 ("type", "Type", 130), ("qty_change", "Change", 70, "e", lambda v, r: f"{v:+d}" if v else "0"),
                                 ("damaged_change", "Damaged", 70, "e", lambda v, r: f"{v:+d}" if v else ""),
                                 ("stock_after", "Stock after", 80, "e"), ("reason", "Reason", 260), ("username", "User", 80)],
                            self._load_mv, page_size=60, tag_fn=lambda r: "danger" if r["qty_change"] < 0 else "ok")
        self.mv.pack(fill="both", expand=True)
        self._job = None

    def _deb(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(250, self.table.reload)

    def _load(self, limit, offset):
        s = {"Low stock": "low", "Out of stock": "out"}.get(self.status.get())
        return inventory.stock_list(self.db, self.user, self.q.get().strip(), status=s, limit=limit, offset=offset)

    def _load_mv(self, limit, offset):
        f, t = self.mv_dates()
        ty = None if self.mv_type.get() == "All" else self.mv_type.get()
        return inventory.transactions(self.db, self.user, self.mv_product["id"] if self.mv_product else None, ty, f, t, limit, offset)

    def on_show(self):
        self.table.reload(keep_page=True)
        self.mv.reload(keep_page=True)

    def _need(self):
        r = self.table.selected()
        if not r:
            widgets.show_warn(self, "Select a product first.")
        return r

    def adjust(self):
        r = self._need()
        if not r:
            return
        if r["serialized"]:
            widgets.show_info(self, "Serial-numbered products change stock by adding, selling or marking individual serial numbers.\n"
                                    "Opening the serial list for you...")
            self.serials()
            return

        def save(v):
            return {"d": inventory.adjust_stock(self.db, self.user, r["id"], v["qty"], v["reason"])}
        res = FormDialog(self, "Adjust stock", [
            {"key": "l", "type": "label", "label": f"{r['name']}\nCurrent stock: {r['stock']}"},
            {"key": "qty", "label": "New stock quantity", "type": "int", "required": True, "default": str(r["stock"])},
            {"key": "reason", "label": "Reason (required)", "required": True, "help": "e.g. Stock take, found extra, lost"}],
            on_save=save).show()
        if res:
            self.toast("Stock adjusted")
            self.table.reload(keep_page=True)

    def damage(self):
        r = self._need()
        if not r:
            return
        if r["serialized"]:
            self.serials()
            return

        def save(v):
            inventory.mark_damaged(self.db, self.user, r["id"], v["qty"], v["reason"])
            return v
        if FormDialog(self, "Mark damaged", [
                {"key": "qty", "label": "Damaged quantity", "type": "int", "required": True, "default": "1"},
                {"key": "reason", "label": "Reason", "required": True}], on_save=save).show():
            self.toast("Moved to damaged stock", "info")
            self.table.reload(keep_page=True)

    def serials(self):
        r = self._need()
        if not r:
            return
        if not r["serialized"]:
            widgets.show_info(self, "This product does not track serial numbers.")
            return
        SerialsDialog(self, self.app, r).show()
        self.table.reload(keep_page=True)

    def show_moves(self, r):
        if not r:
            return
        self.mv_product = {"id": r["id"], "name": r["name"]}
        self.mv_lbl.configure(text=r["name"][:40])
        self.mv.reload()
        self.nb.select(1)

    def pick_mv(self):
        p = ProductPicker(self, self.app).show()
        if p:
            self.mv_product = p
            self.mv_lbl.configure(text=p["name"][:40])
            self.mv.reload()

    def check(self):
        problems = inventory.verify_consistency(self.db) + parties.verify_balances(self.db)
        if problems:
            widgets.text_preview(self, "Integrity check - problems found", "\n".join(problems), width=700, height=400)
        else:
            widgets.show_info(self, "All stock quantities match their transaction history, and all customer / supplier balances "
                                    "match their ledgers.", "Integrity check passed")
