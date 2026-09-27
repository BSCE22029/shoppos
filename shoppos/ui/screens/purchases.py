import tkinter as tk
from tkinter import ttk

from ...services import catalog, parties, purchasing, settings
from ...util import POSError, money, to_float, to_int, today
from .. import theme, widgets
from ..base import Screen
from ..party_dialogs import payment_form
from ..pickers import ProductPicker
from ..widgets import DataTable, Dialog, FormDialog, date_range_bar


class PurchaseDialog(Dialog):
    """Create a purchase order."""

    def __init__(self, parent, app):
        super().__init__(parent, "New purchase order", 820, 620, resizable=True)
        self.app = app
        self.items = []
        top = ttk.Frame(self, padding=(16, 14, 16, 0))
        top.pack(fill="x")
        sup = parties.all_suppliers(app.db)
        self.sup_map = {s["name"]: s["id"] for s in sup}
        self.sup = tk.StringVar()
        ttk.Label(top, text="Supplier *").grid(row=0, column=0, sticky="w")
        ttk.Combobox(top, textvariable=self.sup, values=list(self.sup_map), state="readonly", width=32).grid(row=1, column=0, padx=(0, 12))
        self.inv = tk.StringVar()
        ttk.Label(top, text="Supplier invoice no.").grid(row=0, column=1, sticky="w")
        ttk.Entry(top, textvariable=self.inv, width=22).grid(row=1, column=1, padx=(0, 12))
        self.exp = tk.StringVar()
        ttk.Label(top, text="Expected date (YYYY-MM-DD)").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.exp, width=16).grid(row=1, column=2)
        self.notes = tk.StringVar()
        ttk.Label(top, text="Notes").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.notes, width=80).grid(row=3, column=0, columnspan=3, sticky="ew")
        bar = ttk.Frame(self, padding=(16, 12, 16, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="+ Add product", style="Primary.TButton", command=self.add).pack(side="left")
        ttk.Button(bar, text="Edit qty / cost", style="Secondary.TButton", command=self.edit).pack(side="left", padx=8)
        ttk.Button(bar, text="Remove", style="Secondary.TButton", command=self.remove).pack(side="left")
        self.tree = ttk.Treeview(self, columns=("sku", "name", "qty", "cost", "total"), show="headings", height=11)
        for k, t, w, a in (("sku", "SKU", 110, "w"), ("name", "Product", 340, "w"), ("qty", "Qty", 60, "e"),
                           ("cost", "Unit cost", 100, "e"), ("total", "Line total", 110, "e")):
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor=a)
        self.tree.pack(fill="both", expand=True, padx=16)
        foot = ttk.Frame(self, padding=16)
        foot.pack(fill="x")
        self.total = ttk.Label(foot, text="Total: 0", font=(theme.FONT, 14, "bold"))
        self.total.pack(side="left")
        ttk.Button(foot, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="Create purchase order", style="Success.TButton", command=self.save).pack(side="right")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        tot = 0
        for it in self.items:
            lt = it["qty"] * it["unit_cost"]
            tot += lt
            self.tree.insert("", "end", values=(it["sku"], it["name"], it["qty"], money(it["unit_cost"]), money(lt)))
        self.total.configure(text=f"Total: {money(tot, settings.get(self.app.db, 'currency'))}")

    def _qc(self, title, qty="1", cost="0"):
        def chk(v):
            if to_int(v["qty"], "Quantity") <= 0:
                raise POSError("Quantity must be greater than zero.")
            if to_float(v["cost"], "Unit cost") <= 0:
                raise POSError("Unit cost must be greater than zero.")
            return v
        return FormDialog(self, title, [{"key": "qty", "label": "Quantity", "type": "int", "required": True, "default": qty},
                                        {"key": "cost", "label": "Unit cost", "type": "money", "required": True, "default": cost}], on_save=chk).show()

    def add(self):
        p = ProductPicker(self, self.app, "Add product to purchase", show_cost=True).show()
        if not p:
            return
        cost = p.get("purchase_price") or 0
        r = self._qc(p["name"], "1", f"{cost:.2f}".rstrip("0").rstrip("."))
        if r:
            ex = next((i for i in self.items if i["product_id"] == p["id"]), None)
            if ex:
                ex["qty"] += to_int(r["qty"])
                ex["unit_cost"] = to_float(r["cost"])
            else:
                self.items.append({"product_id": p["id"], "sku": p["sku"], "name": p["name"], "qty": to_int(r["qty"]), "unit_cost": to_float(r["cost"])})
            self.refresh()

    def edit(self):
        sel = self.tree.selection()
        if sel:
            it = self.items[self.tree.index(sel[0])]
            r = self._qc(it["name"], str(it["qty"]), str(it["unit_cost"]))
            if r:
                it["qty"], it["unit_cost"] = to_int(r["qty"]), to_float(r["cost"])
                self.refresh()

    def remove(self):
        sel = self.tree.selection()
        if sel:
            self.items.pop(self.tree.index(sel[0]))
            self.refresh()

    def save(self):
        with self.app.guard():
            sid = self.sup_map.get(self.sup.get())
            if not sid:
                raise POSError("Select a supplier.")
            pid = purchasing.create_purchase(self.app.db, self.app.user, sid, self.items, self.inv.get(), self.exp.get().strip() or None, self.notes.get())
            self.result = pid
            self.destroy()


class ReceiveDialog(Dialog):
    """Goods receiving: quantities and serial numbers."""

    def __init__(self, parent, app, purchase_id):
        super().__init__(parent, "Receive goods", 860, 560, resizable=True)
        self.app, self.pid = app, purchase_id
        po = purchasing.get_purchase(app.db, purchase_id)
        self.po = po
        ttk.Label(self, text=f"{po['po_number']}  -  {po['supplier']}", style="H2.TLabel").pack(anchor="w", padx=16, pady=(14, 0))
        ttk.Label(self, text="Enter what has arrived. Serial-numbered items need one serial number per unit.", style="Muted.TLabel").pack(anchor="w", padx=16)
        self.inv = tk.StringVar(value=po.get("supplier_invoice") or "")
        r = ttk.Frame(self)
        r.pack(fill="x", padx=16, pady=8)
        ttk.Label(r, text="Supplier invoice no.").pack(side="left")
        ttk.Entry(r, textvariable=self.inv, width=24).pack(side="left", padx=8)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=16)
        heads = ("Product", "Ordered", "Received", "Receive now", "Serial numbers")
        for c, h in enumerate(heads):
            ttk.Label(body, text=h, style="Muted.TLabel").grid(row=0, column=c, sticky="w", padx=4, pady=4)
        self.rows = []
        n = 0
        for it in po["items"]:
            remaining = it["qty"] - it["received_qty"]
            if remaining <= 0:
                continue
            n += 1
            ttk.Label(body, text=it["product"]).grid(row=n, column=0, sticky="w", padx=4, pady=3)
            ttk.Label(body, text=str(it["qty"])).grid(row=n, column=1, sticky="w", padx=4)
            ttk.Label(body, text=str(it["received_qty"])).grid(row=n, column=2, sticky="w", padx=4)
            qv = tk.StringVar(value=str(remaining))
            ttk.Entry(body, textvariable=qv, width=8).grid(row=n, column=3, sticky="w", padx=4)
            row = {"item": it, "qty": qv, "serials": ""}
            if it["serialized"]:
                lbl = ttk.Label(body, text="(none entered)", style="Muted.TLabel")
                lbl.grid(row=n, column=4, sticky="w", padx=4)
                ttk.Button(body, text="Enter serials...", style="Secondary.TButton", command=lambda r_=row, l_=lbl: self.enter_serials(r_, l_)).grid(row=n, column=5, padx=4)
            self.rows.append(row)
        foot = ttk.Frame(self, padding=16)
        foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="Receive into stock", style="Success.TButton", command=self.receive).pack(side="right")

    def enter_serials(self, row, lbl):
        qty = to_int(row["qty"].get() or 0, "Quantity")
        r = FormDialog(self, f"Serial numbers - {row['item']['product']}", [
            {"key": "l", "type": "label", "label": f"Enter {qty} serial number(s): one per line, or separated by commas. "
                                                    "You can scan them with the barcode scanner (Enter after each)."},
            {"key": "s", "label": "Serial numbers", "type": "multiline", "height": 10, "width": 52, "default": row["serials"]}], width=560).show()
        if r is not None:
            row["serials"] = r["s"]
            n = len(catalog.parse_serials(r["s"]))
            lbl.configure(text=f"{n} entered" + ("" if n == qty else f"  (need {qty})"))

    def receive(self):
        with self.app.guard():
            rec = [{"item_id": r["item"]["id"], "qty": to_int(r["qty"].get() or 0, "Quantity"), "serials": r["serials"]} for r in self.rows]
            st = purchasing.receive_purchase(self.app.db, self.app.user, self.pid, rec, self.inv.get())
            self.result = st
            self.destroy()


class PurchaseReturnDialog(Dialog):
    def __init__(self, parent, app):
        super().__init__(parent, "Return goods to supplier", 700, 520, resizable=True)
        self.app = app
        self.items = []
        sup = parties.all_suppliers(app.db)
        self.sup_map = {s["name"]: s["id"] for s in sup}
        top = ttk.Frame(self, padding=(16, 14, 16, 0))
        top.pack(fill="x")
        self.sup = tk.StringVar()
        ttk.Label(top, text="Supplier *").pack(anchor="w")
        ttk.Combobox(top, textvariable=self.sup, values=list(self.sup_map), state="readonly", width=34).pack(anchor="w")
        self.note = tk.StringVar()
        ttk.Label(top, text="Reason / note").pack(anchor="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.note, width=60).pack(anchor="w")
        bar = ttk.Frame(self, padding=(16, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="+ Add product", style="Primary.TButton", command=self.add).pack(side="left")
        ttk.Button(bar, text="Remove", style="Secondary.TButton", command=self.remove).pack(side="left", padx=8)
        self.tree = ttk.Treeview(self, columns=("name", "qty", "cost", "serials"), show="headings", height=9)
        for k, t, w, a in (("name", "Product", 260, "w"), ("qty", "Qty", 50, "e"), ("cost", "Unit cost", 90, "e"), ("serials", "Serials", 220, "w")):
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor=a)
        self.tree.pack(fill="both", expand=True, padx=16)
        foot = ttk.Frame(self, padding=16)
        foot.pack(fill="x")
        ttk.Button(foot, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="Return to supplier", style="Danger.TButton", command=self.save).pack(side="right")

    def add(self):
        p = ProductPicker(self, self.app, "Product to return", in_stock_only=True, show_cost=True).show()
        if not p:
            return
        cost = f"{(p.get('purchase_price') or 0):.2f}".rstrip("0").rstrip(".")
        fields = [{"key": "cost", "label": "Unit cost", "type": "money", "required": True, "default": cost}]
        if p["serialized"]:
            fields.insert(0, {"key": "serials", "label": "Serial numbers being returned (one per line)", "type": "multiline", "height": 6, "required": True, "width": 44})
        else:
            fields.insert(0, {"key": "qty", "label": "Quantity", "type": "int", "required": True, "default": "1"})
        r = FormDialog(self, p["name"], fields).show()
        if not r:
            return
        with self.app.guard():
            it = {"product_id": p["id"], "name": p["name"], "unit_cost": to_float(r["cost"]), "qty": 0, "serial_ids": [], "serials": ""}
            if p["serialized"]:
                names = catalog.parse_serials(r["serials"])
                for n in names:
                    s = self.app.db.one("SELECT id FROM serials WHERE serial=? AND product_id=?", (n, p["id"]))
                    if not s:
                        raise POSError(f"Serial number {n} was not found for this product.")
                    it["serial_ids"].append(s["id"])
                it["qty"], it["serials"] = len(names), ", ".join(names)
            else:
                it["qty"] = to_int(r["qty"])
            self.items.append(it)
            self.tree.insert("", "end", values=(it["name"], it["qty"], money(it["unit_cost"]), it["serials"]))

    def remove(self):
        sel = self.tree.selection()
        if sel:
            self.items.pop(self.tree.index(sel[0]))
            self.tree.delete(sel[0])

    def save(self):
        with self.app.guard():
            sid = self.sup_map.get(self.sup.get())
            if not sid:
                raise POSError("Select a supplier.")
            purchasing.purchase_return(self.app.db, self.app.user, sid, self.items, self.note.get())
            self.result = True
            self.destroy()


class PurchasesScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Purchases", "Purchase order  →  goods received  →  stock updated  →  supplier payable  →  payment")
        ttk.Button(act, text="+ New purchase order", style="Primary.TButton", command=self.new).pack(side="right")
        ttk.Button(act, text="Return to supplier", style="Secondary.TButton", command=self.ret).pack(side="right", padx=8)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=28)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search PO, supplier or invoice...")
        e.bind("<KeyRelease>", lambda ev: self.table.reload())
        self.status = tk.StringVar(value="All")
        cb = ttk.Combobox(bar, textvariable=self.status, state="readonly", width=18,
                          values=["All", "Ordered", "Partially Received", "Received", "Cancelled"])
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda ev: self.table.reload())
        f, self.dates = date_range_bar(bar, lambda: self.table.reload(), 365)
        f.pack(side="left", padx=8)
        cols = [("po_number", "PO", 100), ("date", "Date", 130, "w", widgets.fmt_date), ("supplier", "Supplier", 190), ("supplier_invoice", "Supplier inv.", 110),
                ("status", "Status", 130), ("total", "Ordered", 100, "e", widgets.fmt_money), ("received_value", "Received", 100, "e", widgets.fmt_money),
                ("paid", "Paid", 100, "e", widgets.fmt_money)]
        self.table = DataTable(self, cols, self._load, page_size=50, on_open=lambda r: self.view(),
                               empty_text="No purchase orders yet. Click + New purchase order to start one.",
                               tag_fn=lambda r: {"Cancelled": "muted", "Ordered": "warn", "Partially Received": "warn"}.get(r["status"]))
        self.table.pack(fill="both", expand=True)
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(10, 0))
        for t, c, s in (("Receive goods", self.receive, "Success"), ("View", self.view, "Secondary"), ("Pay supplier", self.pay, "Secondary"),
                        ("Cancel PO", self.cancel_po, "Danger")):
            ttk.Button(b, text=t, style=f"{s}.TButton", command=c).pack(side="left", padx=(0, 8))

    def _load(self, limit, offset):
        f, t = self.dates()
        st = None if self.status.get() == "All" else self.status.get()
        return purchasing.list_purchases(self.db, self.user, self.q.get().strip(), st, None, f, t, limit, offset)

    def on_show(self):
        self.table.reload(keep_page=True)

    def new(self):
        pid = PurchaseDialog(self, self.app).show()
        if pid:
            self.toast("Purchase order created")
            self.table.reload(select_id=pid)

    def receive(self):
        p = self.table.selected()
        if not p:
            return
        with self.guard():
            if p["status"] in ("Received", "Cancelled"):
                raise POSError(f"This purchase is already {p['status'].lower()}.")
            st = ReceiveDialog(self, self.app, p["id"]).show()
            if st:
                self.toast(f"Goods received - order is now {st}")
                self.table.reload(keep_page=True)

    def view(self):
        p = self.table.selected()
        if not p:
            return
        with self.guard():
            po = purchasing.get_purchase(self.db, p["id"])
            L = [f"{po['po_number']}    {po['status']}", f"Supplier: {po['supplier']}", f"Date: {po['date'][:16]}",
                 f"Supplier invoice: {po['supplier_invoice'] or '-'}", "-" * 64]
            for it in po["items"]:
                L.append(f"{it['product'][:34]:<34} {it['received_qty']:>3}/{it['qty']:<3} x {it['unit_cost']:>10,.0f} = {it['qty'] * it['unit_cost']:>12,.0f}")
            L += ["-" * 64, f"Ordered  : {po['total']:>14,.2f}", f"Received : {po['received_value']:>14,.2f}", f"Paid     : {po['paid']:>14,.2f}"]
            for pay in po["payments"]:
                L.append(f"   payment {pay['date'][:10]} {pay['method']}: {pay['amount']:,.2f}")
            widgets.text_preview(self, po["po_number"], "\n".join(L), width=720, height=460)

    def pay(self):
        p = self.table.selected()
        if not p:
            return
        with self.guard():
            sup = self.db.one("SELECT * FROM suppliers WHERE id=?", (p["supplier_id"],))
            if payment_form(self, self.app, "supplier", sup, p["id"]):
                self.table.reload(keep_page=True)

    def cancel_po(self):
        p = self.table.selected()
        if p and widgets.confirm(self, f"Cancel purchase order {p['po_number']}?", danger=True):
            with self.guard():
                purchasing.cancel_purchase(self.db, self.user, p["id"])
                self.table.reload(keep_page=True)

    def ret(self):
        if PurchaseReturnDialog(self, self.app).show():
            self.toast("Goods returned to supplier", "info")
            self.table.reload(keep_page=True)
