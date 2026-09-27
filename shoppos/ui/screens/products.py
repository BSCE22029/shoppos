import os
import tkinter as tk
from tkinter import filedialog, ttk

from ...services import barcode, catalog, inventory, parties, settings
from ...util import POSError, money
from .. import theme, widgets
from ..base import Screen
from ..widgets import DataTable, Dialog, FormDialog


def category_choices(db, with_none=True):
    """Flat list: top-level categories and 'Parent > Child' subcategories."""
    out = [(None, "(none)")] if with_none else []
    for c in catalog.categories(db):
        out.append((c["id"], c["name"]))
        for s in catalog.categories(db, c["id"]):
            out.append((s["id"], f"{c['name']}  ›  {s['name']}"))
    return out


class ProductDialog:
    """Create / edit a product."""

    def __init__(self, screen, product=None):
        self.screen, self.product = screen, product

    def show(self):
        s, db, user = self.screen, self.screen.db, self.screen.user
        p = self.product
        cats = category_choices(db)
        cat_by_id = {c[0]: c for c in cats}
        init = {}
        if p:
            init = dict(p)
            init["cat"] = p["subcategory_id"] or p["category_id"]
            init["serialized"] = bool(p["serialized"])
            init["active"] = bool(p["active"])
        else:
            init = {"active": True, "tax_percent": settings.get(db, "default_tax"), "min_stock": settings.get(db, "low_stock_default"),
                    "warranty_months": 0, "auto_barcode": True}
        show_cost = "products.cost" in user["permissions"]
        fields = [
            {"key": "sku", "label": "SKU", "required": True}, {"key": "barcode", "label": "Barcode", "help": "Leave empty to auto-generate"},
            {"key": "name", "label": "Product name", "required": True, "width": 44, "full": True},
            {"key": "brand_id", "label": "Brand", "type": "choice", "choices": [(None, "(none)")] + [(b["id"], b["name"]) for b in catalog.brands(db)]},
            {"key": "cat", "label": "Category / subcategory", "type": "choice", "choices": cats},
            {"key": "model", "label": "Model"}, {"key": "rack", "label": "Rack / shelf"},
            {"key": "location", "label": "Location"},
            {"key": "supplier_id", "label": "Preferred supplier", "type": "choice",
             "choices": [(None, "(none)")] + [(x["id"], x["name"]) for x in parties.all_suppliers(db)]},
        ]
        if show_cost:
            fields.append({"key": "purchase_price", "label": "Purchase price (cost)", "type": "money", "default": "0"})
        fields += [
            {"key": "wholesale_price", "label": "Wholesale price", "type": "money", "default": "0"},
            {"key": "retail_price", "label": "Retail price", "type": "money", "required": True},
            {"key": "min_price", "label": "Minimum selling price", "type": "money", "default": "0"},
            {"key": "min_stock", "label": "Minimum stock (alert)", "type": "int", "default": "0"},
            {"key": "warranty_months", "label": "Warranty (months)", "type": "int", "default": "0"},
            {"key": "tax_percent", "label": "Tax %", "type": "money", "default": "0"},
            {"key": "discount_percent", "label": "Default discount %", "type": "money", "default": "0"},
            {"key": "image_path", "label": "Image file path (optional)"},
            {"key": "description", "label": "Description", "type": "multiline", "full": True, "width": 44},
            {"key": "serialized", "label": "Track serial numbers (laptops, PCs, monitors, GPUs, CPUs, printers...)", "type": "check", "full": True},
            {"key": "active", "label": "Active (can be sold)", "type": "check", "full": True},
        ]
        if not p:
            fields.append({"key": "auto_barcode", "label": "Auto-generate a barcode if left empty", "type": "check", "full": True})

        def save(v):
            sel = v.pop("cat", None)
            v["category_id"], v["subcategory_id"] = None, None
            if sel:
                row = db.one("SELECT id,parent_id FROM categories WHERE id=?", (sel,))
                if row["parent_id"]:
                    v["category_id"], v["subcategory_id"] = row["parent_id"], row["id"]
                else:
                    v["category_id"] = row["id"]
            if p and not show_cost:
                v["purchase_price"] = p["purchase_price"]
            v.setdefault("purchase_price", 0)
            return {"id": catalog.save_product(db, user, v, p["id"] if p else None)}
        dlg = FormDialog(s, "Edit product" if p else "New product", fields, init, on_save=save, columns=2, width=780)
        return dlg.show()


class ManageDialog(Dialog):
    """Categories, subcategories and brands."""

    def __init__(self, parent, app):
        super().__init__(parent, "Categories & brands", 640, 520, resizable=True)
        self.app = app
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=14)
        self.cat_tab = ttk.Frame(nb, padding=10)
        self.brand_tab = ttk.Frame(nb, padding=10)
        nb.add(self.cat_tab, text="Categories")
        nb.add(self.brand_tab, text="Brands")
        self.cat_tree = ttk.Treeview(self.cat_tab, show="tree", height=14)
        self.cat_tree.pack(fill="both", expand=True)
        bar = ttk.Frame(self.cat_tab)
        bar.pack(fill="x", pady=8)
        for t, c in (("+ Category", lambda: self.add_cat(False)), ("+ Subcategory", lambda: self.add_cat(True)),
                     ("Rename", self.rename), ("Delete", self.delete_cat)):
            ttk.Button(bar, text=t, style="Secondary.TButton", command=c).pack(side="left", padx=(0, 6))
        self.brand_tree = ttk.Treeview(self.brand_tab, show="tree", height=14)
        self.brand_tree.pack(fill="both", expand=True)
        bar2 = ttk.Frame(self.brand_tab)
        bar2.pack(fill="x", pady=8)
        ttk.Button(bar2, text="+ Brand", style="Secondary.TButton", command=self.add_brand).pack(side="left", padx=(0, 6))
        ttk.Button(bar2, text="Delete", style="Secondary.TButton", command=self.delete_brand).pack(side="left")
        ttk.Button(self, text="Close", style="Primary.TButton", command=self.destroy).pack(pady=(0, 12))
        self.reload()

    def reload(self):
        db = self.app.db
        self.cat_tree.delete(*self.cat_tree.get_children())
        for c in catalog.categories(db):
            n = self.cat_tree.insert("", "end", iid=f"c{c['id']}", text=c["name"], open=True)
            for s in catalog.categories(db, c["id"]):
                self.cat_tree.insert(n, "end", iid=f"c{s['id']}", text=s["name"])
        self.brand_tree.delete(*self.brand_tree.get_children())
        for b in catalog.brands(db):
            self.brand_tree.insert("", "end", iid=f"b{b['id']}", text=b["name"])

    def _sel(self, tree):
        s = tree.selection()
        return int(s[0][1:]) if s else None

    def add_cat(self, sub):
        parent = self._sel(self.cat_tree) if sub else None
        if sub and not parent:
            widgets.show_warn(self, "Select the parent category first.")
            return
        if sub and self.app.db.scalar("SELECT parent_id FROM categories WHERE id=?", (parent,)):
            widgets.show_warn(self, "Select a top-level category as the parent.")
            return
        r = FormDialog(self, "New subcategory" if sub else "New category", [{"key": "n", "label": "Name", "required": True}]).show()
        if r:
            with self.app.guard():
                catalog.add_category(self.app.db, self.app.user, r["n"], parent)
                self.reload()

    def rename(self):
        cid = self._sel(self.cat_tree)
        if not cid:
            return
        cur = self.app.db.scalar("SELECT name FROM categories WHERE id=?", (cid,))
        r = FormDialog(self, "Rename", [{"key": "n", "label": "Name", "required": True}], {"n": cur}).show()
        if r:
            with self.app.guard():
                catalog.rename_category(self.app.db, self.app.user, cid, r["n"])
                self.reload()

    def delete_cat(self):
        cid = self._sel(self.cat_tree)
        if cid and widgets.confirm(self, "Delete this category?", danger=True):
            with self.app.guard():
                catalog.delete_category(self.app.db, self.app.user, cid)
                self.reload()

    def add_brand(self):
        r = FormDialog(self, "New brand", [{"key": "n", "label": "Brand name", "required": True}]).show()
        if r:
            with self.app.guard():
                catalog.add_brand(self.app.db, self.app.user, r["n"])
                self.reload()

    def delete_brand(self):
        bid = self._sel(self.brand_tree)
        if bid and widgets.confirm(self, "Delete this brand?", danger=True):
            with self.app.guard():
                catalog.delete_brand(self.app.db, self.app.user, bid)
                self.reload()


class SerialsDialog(Dialog):
    """All serial numbers of one product: filter, add, mark damaged, see history."""

    def __init__(self, parent, app, product):
        super().__init__(parent, f"Serial numbers - {product['name']}", 820, 560, resizable=True)
        self.app, self.product = app, product
        bar = ttk.Frame(self, padding=(16, 14, 16, 0))
        bar.pack(fill="x")
        self.status = tk.StringVar(value="")
        cb = ttk.Combobox(bar, textvariable=self.status, state="readonly", width=20,
                          values=["", "In Stock", "Sold", "Damaged", "Returned to Supplier", "Replaced"])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.table.reload())
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=28)
        e.pack(side="left", padx=8)
        widgets.add_placeholder(e, self.q, "Filter serial numbers...")
        e.bind("<KeyRelease>", lambda ev: self.table.reload())
        ttk.Label(bar, text="(status / search serial)", style="Muted.TLabel").pack(side="left")
        cols = [("serial", "Serial number", 220), ("status", "Status", 130), ("purchase_cost", "Cost", 90, "e", widgets.fmt_money),
                ("sold_price", "Sold price", 90, "e", widgets.fmt_money), ("warranty_expiry", "Warranty until", 110),
                ("created_at", "Added", 130, "w", widgets.fmt_date)]
        self.table = DataTable(self, cols, self._load, height=13, on_open=lambda r: self.history(),
                               tag_fn=lambda r: {"Sold": "muted", "Damaged": "danger", "Replaced": "warn"}.get(r["status"]))
        self.table.pack(fill="both", expand=True, padx=16, pady=10)
        b2 = ttk.Frame(self, padding=(16, 0, 16, 14))
        b2.pack(fill="x")
        if "inventory.adjust" in app.user["permissions"]:
            ttk.Button(b2, text="+ Add serial numbers", style="Primary.TButton", command=self.add).pack(side="left")
            ttk.Button(b2, text="Mark damaged", style="Secondary.TButton", command=self.damage).pack(side="left", padx=8)
        ttk.Button(b2, text="History of selected", style="Secondary.TButton", command=self.history).pack(side="left")
        ttk.Button(b2, text="Close", style="Secondary.TButton", command=self.destroy).pack(side="right")
        self.table.reload()

    def _load(self, limit, offset):
        return catalog.list_serials(self.app.db, self.app.user, self.product["id"], self.status.get() or None,
                                    self.q.get().strip(), limit, offset)

    def add(self):
        p = self.product
        fields = [{"key": "serials", "label": "Serial numbers (one per line, or separated by commas)", "type": "multiline", "height": 8,
                   "required": True, "width": 50}]
        if "products.cost" in self.app.user["permissions"]:
            fields.append({"key": "cost", "label": "Cost per unit", "type": "money", "default": str(p["purchase_price"] or 0)})

        def save(v):
            n = catalog.add_opening_serials(self.app.db, self.app.user, p["id"], v["serials"], v.get("cost") or p["purchase_price"] or 0)
            return {"n": n}
        r = FormDialog(self, "Add serial numbers", fields, on_save=save, save_text="Add").show()
        if r:
            self.app.toast(f"{r['n']} serial number(s) added")
            self.table.reload()

    def damage(self):
        r = self.table.selected()
        if not r:
            return
        reason = FormDialog(self, "Mark damaged", [{"key": "r", "label": "Reason", "required": True}]).show()
        if reason:
            with self.app.guard():
                inventory.mark_damaged(self.app.db, self.app.user, self.product["id"], 1, reason["r"], r["id"])
                self.table.reload()

    def history(self):
        r = self.table.selected()
        if not r:
            return
        with self.app.guard():
            h = catalog.serial_history(self.app.db, self.app.user, r["serial"])
            L = [f"Serial : {h['serial']}", f"Product: {h['product']}  ({h['sku']})", f"Status : {h['status']}"]
            if h.get("purchase"):
                L.append(f"Bought : {h['purchase']['po_number']} from {h['purchase']['supplier']}")
            if h["purchase_cost"] is not None:
                L.append(f"Cost   : {money(h['purchase_cost'])}")
            for s in h["sales"]:
                L.append(f"Sold   : {s['invoice_no']} on {s['date'][:10]} to {s['customer'] or 'Walk-in'} for {money(s['total'])}"
                         + ("  (returned)" if s["returned"] else ""))
            for w in h["warranties"]:
                L.append(f"Warranty: {w['start_date']} -> {w['expiry_date']}  [{w['status']}]")
            widgets.text_preview(self, "Serial history", "\n".join(L), mono=True, width=560, height=320)


class BarcodeDialog(Dialog):
    def __init__(self, parent, app, product):
        super().__init__(parent, "Barcode label", 520, 430)
        self.app, self.product = app, product
        code = product["barcode"] or product["sku"]
        ttk.Label(self, text=product["name"], style="H2.TLabel", wraplength=460).pack(anchor="w", padx=20, pady=(16, 2))
        try:
            self.code = barcode.normalize(code)
            err = ""
        except POSError as e:
            self.code, err = None, str(e)
        cv = tk.Canvas(self, width=460, height=120, bg="#FFFFFF", highlightthickness=1, highlightbackground=theme.current["border"])
        cv.pack(padx=20, pady=10)
        if self.code:
            w = barcode.draw_on_canvas(cv, self.code, 10, 10, 80, 1.0)
            scale = min(440 / (w or 1), 3.0)
            cv.delete("all")
            w = barcode.draw_on_canvas(cv, self.code, (460 - w * scale) / 2, 10, 80, scale)
            cv.create_text(230, 104, text=self.code, font=("Consolas", 10))
        else:
            cv.create_text(230, 60, text=err, fill="red", width=420)
        row = ttk.Frame(self)
        row.pack(fill="x", padx=20)
        ttk.Label(row, text="Copies").pack(side="left")
        self.copies = tk.StringVar(value="12")
        ttk.Entry(row, textvariable=self.copies, width=6).pack(side="left", padx=8)
        ttk.Label(row, text="Columns").pack(side="left", padx=(12, 0))
        self.cols = tk.StringVar(value=settings.get(app.db, "label_columns") or "3")
        ttk.Entry(row, textvariable=self.cols, width=4).pack(side="left", padx=8)
        ttk.Label(self, text="Opens a printable label sheet in your browser. Print it on your label printer (Ctrl+P).",
                  style="Muted.TLabel", wraplength=460).pack(anchor="w", padx=20, pady=8)
        bar = ttk.Frame(self, padding=20)
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="Close", style="Secondary.TButton", command=self.destroy).pack(side="right", padx=(8, 0))
        b = ttk.Button(bar, text="Open printable labels", style="Primary.TButton", command=self.labels)
        b.pack(side="right")
        if not self.code:
            b.state(["disabled"])

    def labels(self):
        with self.app.guard():
            n = max(1, min(int(self.copies.get()), 500))
            cols = max(1, min(int(self.cols.get()), 8))
            item = {"name": self.product["name"], "code": self.code, "price": money(self.product["retail_price"], settings.get(self.app.db, "currency"))}
            path = os.path.join(self.app.paths["exports"], f"labels-{self.product['sku']}.html")
            barcode.save_labels(path, [item] * n, cols=cols)


class ProductsScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Products", "Catalogue, prices and serial-numbered stock")
        if self.can("products.edit"):
            ttk.Button(act, text="+ New product", style="Primary.TButton", command=self.new).pack(side="right")
            ttk.Button(act, text="Categories & brands", style="Secondary.TButton", command=self.manage).pack(side="right", padx=8)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=34)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search name, SKU, barcode or model...")
        e.bind("<KeyRelease>", lambda ev: self._debounce())
        self.cat = tk.StringVar(value="All categories")
        self.cat_cb = ttk.Combobox(bar, textvariable=self.cat, state="readonly", width=22)
        self.cat_cb.pack(side="left", padx=8)
        self.cat_cb.bind("<<ComboboxSelected>>", lambda ev: self.table.reload())
        self.brand = tk.StringVar(value="All brands")
        self.brand_cb = ttk.Combobox(bar, textvariable=self.brand, state="readonly", width=18)
        self.brand_cb.pack(side="left")
        self.brand_cb.bind("<<ComboboxSelected>>", lambda ev: self.table.reload())
        self.inactive = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show inactive", variable=self.inactive, command=lambda: self.table.reload()).pack(side="left", padx=12)
        cols = [("sku", "SKU", 120), ("barcode", "Barcode", 120), ("name", "Product", 300), ("brand", "Brand", 90), ("category", "Category", 100),
                ("retail_price", "Retail", 90, "e", widgets.fmt_money)]
        if self.can("products.cost"):
            cols.append(("purchase_price", "Cost", 90, "e", widgets.fmt_money))
        cols += [("stock", "Stock", 60, "e"), ("serialized", "Serial #", 60, "center", widgets.fmt_yesno),
                 ("warranty_months", "Warranty", 70, "e", lambda v, r: f"{v} mo" if v else "-"), ("active", "Active", 55, "center", widgets.fmt_yesno)]
        self.table = DataTable(self, cols, self._load, page_size=60, on_open=lambda r: self.edit(),
                               empty_text="No products match your search. Try a different term, or click + New product.",
                               tag_fn=lambda r: "muted" if not r["active"] else ("danger" if r["stock"] <= 0 else ("warn" if r["stock"] <= r["min_stock"] else None)))
        self.table.pack(fill="both", expand=True)
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(10, 0))
        if self.can("products.edit"):
            ttk.Button(b, text="Edit", style="Secondary.TButton", command=self.edit).pack(side="left")
        if self.can("products.delete"):
            ttk.Button(b, text="Delete", style="Danger.TButton", command=self.delete).pack(side="left", padx=8)
        ttk.Button(b, text="Serial numbers", style="Secondary.TButton", command=self.serials).pack(side="left")
        ttk.Button(b, text="Barcode label", style="Secondary.TButton", command=self.label).pack(side="left", padx=8)
        self._job = None

    def _debounce(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(250, self.table.reload)

    def _ids(self):
        cats = {"All categories": None}
        cats.update({c["name"]: c["id"] for c in catalog.categories(self.db)})
        brands = {"All brands": None}
        brands.update({b["name"]: b["id"] for b in catalog.brands(self.db)})
        return cats.get(self.cat.get()), brands.get(self.brand.get())

    def _load(self, limit, offset):
        c, b = self._ids()
        return catalog.search_products(self.db, self.user, self.q.get().strip(), c, b, self.inactive.get(), limit, offset)

    def on_show(self):
        self.cat_cb["values"] = ["All categories"] + [c["name"] for c in catalog.categories(self.db)]
        self.brand_cb["values"] = ["All brands"] + [b["name"] for b in catalog.brands(self.db)]
        self.table.reload(keep_page=True)

    def new(self):
        r = ProductDialog(self).show()
        if r:
            self.toast("Product saved")
            self.table.reload(select_id=r["id"])

    def edit(self):
        p = self.table.selected()
        if not p or not self.can("products.edit"):
            return
        full = catalog.get_product(self.db, p["id"])
        r = ProductDialog(self, full).show()
        if r:
            self.toast("Product saved")
            self.table.reload(keep_page=True, select_id=r["id"])

    def delete(self):
        p = self.table.selected()
        if p and widgets.confirm(self, f"Delete '{p['name']}'?\n\nProducts that have sales or stock history are deactivated instead.", danger=True):
            with self.guard():
                res = catalog.delete_product(self.db, self.user, p["id"])
                self.toast("Product deleted" if res == "deleted" else "Product deactivated (it has history)", "info")
                self.table.reload(keep_page=True)

    def manage(self):
        ManageDialog(self, self.app).show()
        self.on_show()

    def serials(self):
        p = self.table.selected()
        if not p:
            return
        if not p["serialized"]:
            widgets.show_info(self, "This product does not track serial numbers.\n(Edit the product and tick 'Track serial numbers'.)")
            return
        SerialsDialog(self, self.app, p).show()
        self.table.reload(keep_page=True)

    def label(self):
        p = self.table.selected()
        if p:
            BarcodeDialog(self, self.app, p).show()
