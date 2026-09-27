"""The point-of-sale screen: scan/search, cart, customer, hold/resume, split payments, receipts."""
import tkinter as tk
from tkinter import ttk

from ...config import SALE_METHODS
from ...services import catalog, parties, printing, sales, settings
from ...util import POSError, money, r2, to_float
from .. import theme, widgets
from ..base import Screen
from ..widgets import DataTable, Dialog, FormDialog


def ask_text(parent, title, label, initial="", required=True):
    r = FormDialog(parent, title, [{"key": "v", "label": label, "required": required}], {"v": initial}).show()
    return None if r is None else r["v"]


class SerialPicker(Dialog):
    """Pick serial numbers (multi-select) from the units in stock. Typing/scanning a serial selects it."""

    def __init__(self, parent, product, available, need=1):
        super().__init__(parent, f"Select serial number - {product['name']}", 560, 520, resizable=True)
        self.available = available
        self.need = need
        ttk.Label(self, text=product["name"], style="H2.TLabel").pack(anchor="w", padx=16, pady=(14, 0))
        ttk.Label(self, text=f"{len(available)} unit(s) in stock. Scan or type a serial, or pick from the list.",
                  style="Muted.TLabel").pack(anchor="w", padx=16)
        self.q = tk.StringVar()
        e = ttk.Entry(self, textvariable=self.q)
        e.pack(fill="x", padx=16, pady=8)
        widgets.add_placeholder(e, self.q, "Scan or type a serial number...")
        e.bind("<KeyRelease>", lambda ev: self.fill())
        e.bind("<Return>", self._enter)
        self.tree = ttk.Treeview(self, columns=("serial",), show="headings", selectmode="extended", height=12)
        self.tree.heading("serial", text="Serial number")
        self.tree.column("serial", width=400)
        self.tree.pack(fill="both", expand=True, padx=16)
        self.tree.bind("<Double-1>", lambda ev: self.ok())
        self.tree.bind("<Return>", lambda ev: self.ok())
        bar = ttk.Frame(self, padding=16)
        bar.pack(fill="x")
        self.info = ttk.Label(bar, text="", style="Muted.TLabel")
        self.info.pack(side="left")
        ttk.Button(bar, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Add to sale", style="Primary.TButton", command=self.ok).pack(side="right")
        self.iids = {}
        self.fill()
        self.after(80, e.focus_set)

    def fill(self):
        txt = self.q.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self.iids = {}
        for s in self.available:
            if txt in s["serial"].lower():
                self.iids[self.tree.insert("", "end", values=(s["serial"],))] = s
        kids = self.tree.get_children()
        if txt and len(kids) == 1:
            self.tree.selection_set(kids[0])
        self.info.configure(text=f"{len(kids)} shown")

    def _enter(self, _e):
        txt = self.q.get().strip().lower()
        exact = [i for i, s in self.iids.items() if s["serial"].lower() == txt]
        if exact:
            self.tree.selection_set(exact[0])
        elif len(self.iids) == 1:
            self.tree.selection_set(next(iter(self.iids)))
        self.ok()

    def ok(self):
        sel = [self.iids[i] for i in self.tree.selection() if i in self.iids]
        if not sel:
            widgets.show_warn(self, "Select a serial number first.")
            return
        self.result = sel
        self.destroy()


class CustomerPicker(Dialog):
    def __init__(self, parent, app):
        super().__init__(parent, "Customer", 640, 480, resizable=True)
        self.app = app
        ttk.Label(self, text="Find a customer by name or phone", style="H2.TLabel").pack(anchor="w", padx=16, pady=(14, 6))
        self.q = tk.StringVar()
        e = ttk.Entry(self, textvariable=self.q)
        e.pack(fill="x", padx=16)
        widgets.add_placeholder(e, self.q, "Type a customer name or phone number...")
        e.bind("<KeyRelease>", lambda ev: self.reload())
        e.bind("<Return>", lambda ev: self.pick())
        e.bind("<Down>", lambda ev: self.table.tree.focus_set())
        self.table = DataTable(self, [("name", "Name", 220), ("phone", "Phone", 120), ("balance", "Owes", 90, "e", widgets.fmt_money),
                                      ("credit_limit", "Credit limit", 100, "e", widgets.fmt_money),
                                      ("store_credit", "Store credit", 90, "e", widgets.fmt_money)],
                               lambda lim, off: (parties.quick_customers(app.db, self.q.get().strip()), 0), on_open=lambda r: self.pick(),
                               height=10)
        self.table.pack(fill="both", expand=True, padx=16, pady=10)
        bar = ttk.Frame(self, padding=(16, 0, 16, 14))
        bar.pack(fill="x")
        ttk.Button(bar, text="Walk-in (no customer)", style="Secondary.TButton", command=self.walkin).pack(side="left")
        ttk.Button(bar, text="+ New customer", style="Secondary.TButton", command=self.new).pack(side="left", padx=8)
        ttk.Button(bar, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Select", style="Primary.TButton", command=self.pick).pack(side="right")
        self.reload()
        self.after(80, e.focus_set)

    def reload(self):
        rows = parties.quick_customers(self.app.db, self.q.get().strip())
        self.table.set_rows(rows)
        self.table.total = len(rows)
        self.table.lbl.configure(text=f"{len(rows)} shown")
        self.table.focus_first()

    def pick(self):
        r = self.table.selected()
        if not r:
            widgets.show_warn(self, "Select a customer, or choose Walk-in.")
            return
        self.result = r
        self.destroy()

    def walkin(self):
        self.result = "walkin"
        self.destroy()

    def new(self):
        def save(v):
            v["credit_limit"] = v.get("credit_limit") or 0
            cid = parties.save_customer(self.app.db, self.app.user, v)
            return {"id": cid}
        r = FormDialog(self, "New customer", [
            {"key": "name", "label": "Name", "required": True}, {"key": "phone", "label": "Phone"},
            {"key": "email", "label": "Email"}, {"key": "address", "label": "Address"},
            {"key": "credit_limit", "label": "Credit limit", "type": "money", "default": "0"}], on_save=save).show()
        if r:
            self.result = parties.get_customer(self.app.db, r["id"])
            self.destroy()


class PayDialog(Dialog):
    """Split payments: add several methods until nothing remains. Cash over-tender gives change."""

    def __init__(self, parent, total, customer, currency):
        super().__init__(parent, "Payment", 640, 640)
        self.total, self.customer, self.currency = r2(total), customer, currency
        self.payments, self.change = [], 0.0
        c = theme.current
        top = ttk.Frame(self, style="Card.TFrame", padding=16)
        top.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(top, text="TOTAL DUE", style="CardMuted.TLabel", font=(theme.FONT, 9, "bold")).pack(anchor="w")
        ttk.Label(top, text=money(self.total, currency), style="Total.TLabel").pack(anchor="w")
        cust = ("Walk-in customer" if not customer else
                f"{customer['name']}   |   owes {money(customer['balance'])}   |   credit limit {money(customer['credit_limit'])}"
                f"   |   store credit {money(customer['store_credit'])}")
        ttk.Label(top, text=cust, style="CardMuted.TLabel").pack(anchor="w", pady=(4, 0))
        quick = ttk.Frame(self)
        quick.pack(fill="x", padx=16, pady=(4, 0))
        for label, m in (("Cash - full", "Cash"), ("Card - full", "Card"), ("Bank transfer - full", "Bank Transfer"),
                         ("Wallet - full", "Mobile Wallet")):
            ttk.Button(quick, text=label, style="Secondary.TButton", command=lambda m=m: self.quick(m)).pack(side="left", padx=(0, 6))
        ttk.Button(quick, text="Rest on credit", style="Secondary.TButton", command=lambda: self.quick("Credit")).pack(side="left")
        row = ttk.Frame(self)
        row.pack(fill="x", padx=16, pady=12)
        self.method = tk.StringVar(value="Cash")
        ttk.Combobox(row, textvariable=self.method, values=SALE_METHODS, state="readonly", width=14).pack(side="left")
        self.amount = tk.StringVar()
        self.ae = ttk.Entry(row, textvariable=self.amount, width=14, justify="right", style="Big.TEntry")
        self.ae.pack(side="left", padx=8)
        self.ref = tk.StringVar()
        ttk.Entry(row, textvariable=self.ref, width=16).pack(side="left")
        ttk.Label(row, text="ref (optional)", style="Muted.TLabel").pack(side="left", padx=4)
        ttk.Button(row, text="Add", style="Primary.TButton", command=self.add).pack(side="right")
        self.tree = ttk.Treeview(self, columns=("m", "a", "r"), show="headings", height=6)
        for k, t, w, a in (("m", "Method", 160, "w"), ("a", "Amount", 140, "e"), ("r", "Reference", 260, "w")):
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor=a)
        self.tree.pack(fill="x", padx=16)
        self.tree.bind("<Delete>", lambda e: self.remove())
        ttk.Button(self, text="Remove selected payment", style="Secondary.TButton", command=self.remove).pack(anchor="e", padx=16, pady=6)
        self.rem_lbl = ttk.Label(self, text="", font=(theme.FONT, 16, "bold"))
        self.rem_lbl.pack(anchor="w", padx=16)
        self.msg = ttk.Label(self, text="", style="Danger.TLabel", wraplength=580)
        self.msg.pack(anchor="w", padx=16)
        bar = ttk.Frame(self, padding=16)
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        self.done_btn = ttk.Button(bar, text="Complete sale", style="Success.TButton", command=self.finish)
        self.done_btn.pack(side="right")
        self.ae.bind("<Return>", lambda e: self.enter())
        self.bind("<F4>", lambda e: self.finish())
        self.refresh()
        self.after(80, self.ae.focus_set)

    @property
    def remaining(self):
        return r2(self.total - sum(p["amount"] for p in self.payments))

    def enter(self):
        if self.remaining <= 0.004 and not self.amount.get().strip():
            self.finish()
        else:
            self.add()

    def quick(self, method):
        self.method.set(method)
        self.amount.set(f"{max(self.remaining, 0):.2f}".rstrip("0").rstrip("."))
        self.add()

    def add(self):
        self.msg.configure(text="")
        try:
            m = self.method.get()
            amt = to_float(self.amount.get() or self.remaining, "Amount")
            if amt <= 0:
                raise POSError("Enter an amount greater than zero.")
            if self.remaining <= 0.004:
                raise POSError("The sale is already fully paid.")
            ref = self.ref.get().strip() or None
            if m in ("Credit", "Store Credit") and not self.customer:
                raise POSError("Choose a customer first (F2) to use credit or store credit.")
            if m == "Credit":
                amt = min(amt, self.remaining)
                already = sum(p["amount"] for p in self.payments if p["method"] == "Credit")
                room = self.customer["credit_limit"] - self.customer["balance"] - already
                if amt > room + 0.005:
                    raise POSError(f"Customer credit limit exceeded. Available credit: {money(max(room, 0))}.")
            if m == "Store Credit":
                already = sum(p["amount"] for p in self.payments if p["method"] == "Store Credit")
                avail = self.customer["store_credit"] - already
                if avail <= 0.004:
                    raise POSError("This customer has no store credit.")
                amt = min(amt, self.remaining, avail)
            if m == "Cash" and amt > self.remaining + 0.004:
                self.change += r2(amt - self.remaining)
                ref = f"Tendered {amt:,.0f}, change {amt - self.remaining:,.0f}"
                amt = self.remaining
            elif amt > self.remaining + 0.004:
                raise POSError("Amount is more than the balance due. Only cash can be over-tendered.")
            self.payments.append({"method": m, "amount": r2(amt), "ref": ref})
            self.amount.set("")
            self.ref.set("")
            self.refresh()
        except POSError as e:
            self.msg.configure(text=str(e))

    def remove(self):
        sel = self.tree.selection()
        if sel:
            idx = self.tree.index(sel[0])
            gone = self.payments.pop(idx)
            if gone["method"] == "Cash" and self.change:
                self.change = 0.0
            self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for p in self.payments:
            self.tree.insert("", "end", values=(p["method"], money(p["amount"]), p["ref"] or ""))
        rem = self.remaining
        if rem > 0.004:
            self.rem_lbl.configure(text=f"Remaining: {money(rem, self.currency)}", foreground=theme.current["danger"])
            self.amount.set(f"{rem:.2f}".rstrip("0").rstrip("."))
            self.ae.selection_range(0, "end")
            self.done_btn.state(["disabled"])
        else:
            txt = "Fully paid" + (f"    CHANGE DUE: {money(self.change, self.currency)}" if self.change else "")
            self.rem_lbl.configure(text=txt, foreground=theme.current["success"])
            self.done_btn.state(["!disabled"])
            self.done_btn.focus_set()

    def finish(self):
        if self.remaining > 0.004:
            self.msg.configure(text="There is still an amount remaining. Add a payment for the balance.")
            return
        self.result = {"payments": self.payments, "change": self.change}
        self.destroy()


class ResumeDialog(Dialog):
    def __init__(self, parent, app):
        super().__init__(parent, "Held sales", 700, 420, resizable=True)
        self.app = app
        ttk.Label(self, text="Held sales", style="H2.TLabel").pack(anchor="w", padx=16, pady=(14, 8))
        self.table = DataTable(self, [("created_at", "Held at", 140, "w", widgets.fmt_date), ("customer", "Customer", 150),
                                      ("items", "Lines", 60, "e"), ("username", "By", 90), ("note", "Note", 220)],
                               lambda lim, off: (sales.list_held(app.db), 0), on_open=lambda r: self.resume(), height=8)
        self.table.pack(fill="both", expand=True, padx=16)
        bar = ttk.Frame(self, padding=16)
        bar.pack(fill="x")
        ttk.Button(bar, text="Delete held sale", style="Danger.TButton", command=self.delete).pack(side="left")
        ttk.Button(bar, text="Close", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Resume", style="Primary.TButton", command=self.resume).pack(side="right")
        self.reload()

    def reload(self):
        rows = sales.list_held(self.app.db)
        self.table.set_rows(rows)
        self.table.total = len(rows)
        self.table.lbl.configure(text=f"{len(rows)} held sale(s)")

    def resume(self):
        r = self.table.selected()
        if not r:
            widgets.show_warn(self, "Select a held sale.")
            return
        self.result = r["id"]
        self.destroy()

    def delete(self):
        r = self.table.selected()
        if r and widgets.confirm(self, "Delete this held sale?", danger=True):
            sales.delete_held(self.app.db, self.app.user, r["id"])
            self.reload()


class SaleDoneDialog(Dialog):
    def __init__(self, parent, app, res, change):
        super().__init__(parent, "Sale completed", 460, 330)
        self.app, self.res = app, res
        c = theme.current
        ttk.Label(self, text="✔  Sale completed", font=(theme.FONT, 18, "bold"), foreground=c["success"]).pack(pady=(22, 2))
        ttk.Label(self, text=res["invoice_no"], font=(theme.FONT, 14, "bold")).pack()
        ttk.Label(self, text=f"Total {money(res['total'])}", style="Muted.TLabel", font=(theme.FONT, 12)).pack(pady=(4, 0))
        if change:
            ttk.Label(self, text=f"CHANGE DUE  {money(change)}", font=(theme.FONT, 20, "bold"), foreground=c["danger"]).pack(pady=12)
        bar = ttk.Frame(self)
        bar.pack(pady=14)
        ttk.Button(bar, text="Print receipt", style="Secondary.TButton", command=self.print_receipt).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(bar, text="Preview", style="Secondary.TButton", command=self.preview).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(bar, text="A4 invoice (PDF)", style="Secondary.TButton", command=self.pdf).grid(row=0, column=2, padx=4, pady=4)
        nb = ttk.Button(self, text="New sale  (Enter)", style="Primary.TButton", command=self.destroy)
        nb.pack(pady=6, ipadx=20)
        self.bind("<Return>", lambda e: self.destroy())
        nb.focus_set()

    def print_receipt(self):
        with self.app.guard():
            printing.print_receipt(self.app.db, self.res["sale_id"])
            self.app.toast("Receipt sent to printer", "info")

    def preview(self):
        with self.app.guard():
            text = printing.receipt_text(self.app.db, self.res["sale_id"])
            widgets.text_preview(self, "Receipt", text, on_print=self.print_receipt, width=460, height=640)

    def pdf(self):
        with self.app.guard():
            path = printing.save_invoice_pdf(self.app.db, self.res["sale_id"])
            printing.open_file(path)


class PosScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.cart = []           # [{'product','qty','unit_price','discount','serials':[{id,serial}]}]
        self.customer = None
        self.held_id = None
        self._job = None
        self._binds = []
        self.build()

    # ------------------------------------------------------------- layout
    def build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        right = ttk.Frame(self, width=theme.px(360))
        right.grid(row=0, column=1, sticky="ns")
        right.grid_propagate(False)
        # search
        left.columnconfigure(0, weight=1)
        left.rowconfigure(4, weight=1)
        srow = ttk.Frame(left)
        srow.grid(row=0, column=0, sticky="ew")
        self.q = tk.StringVar()
        self.entry = ttk.Entry(srow, textvariable=self.q, style="Big.TEntry")
        self.entry.pack(side="left", fill="x", expand=True)
        widgets.add_placeholder(self.entry, self.q, "Scan a barcode, or type a product name / SKU / model...")
        self.cat = tk.StringVar(value="All categories")
        cats = [("", "All categories")] + [(c["id"], c["name"]) for c in catalog.categories(self.db)]
        self.cat_map = {l: v for v, l in cats}
        cb = ttk.Combobox(srow, textvariable=self.cat, values=[l for _, l in cats], state="readonly", width=18)
        cb.pack(side="left", padx=(8, 0), ipady=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.search())
        ttk.Label(left, text="Press Enter to add   ·   F1 to jump here   ·   F2 customer   ·   F3 hold   ·   F4 pay",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 6))
        self.entry.bind("<Return>", self.submit)
        self.entry.bind("<KeyRelease>", self._typed)
        self.entry.bind("<Down>", lambda e: self._focus_results())
        self._rows = []
        self.results = DataTable(left, [("name", "Product", 340), ("sku", "SKU", 120), ("retail_price", "Price", 90, "e", widgets.fmt_money),
                                        ("stock", "Stock", 60, "e"), ("rack", "Rack", 70)],
                                 lambda lim, off: (self._rows, len(self._rows)), page_size=100, height=4,
                                 tag_fn=lambda r: "danger" if r["stock"] <= 0 else ("warn" if r["stock"] <= r["min_stock"] else None),
                                 on_open=lambda r: self.add_product(r))
        self.results.pager.grid_remove()
        self.results.grid(row=2, column=0, sticky="ew")
        self.results.tree.bind("<Return>", lambda e: self._add_selected_result())
        ttk.Label(left, text="Cart", style="H2.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 4))
        cols = [("n", "#", 36, "e"), ("name", "Item", 300), ("serials", "Serial number(s)", 200), ("qty", "Qty", 50, "e"),
                ("price", "Price", 90, "e"), ("disc", "Disc.", 80, "e"), ("total", "Total", 100, "e")]
        wrap = ttk.Frame(left)
        wrap.grid(row=4, column=0, sticky="nsew")
        self.cart_tree = ttk.Treeview(wrap, columns=[c[0] for c in cols], show="headings", height=4, selectmode="browse")
        for k, t, w, *a2 in cols:
            self.cart_tree.heading(k, text=t)
            self.cart_tree.column(k, width=theme.px(40), anchor=a2[0] if a2 else "w", stretch=False)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.cart_tree.yview)
        self.cart_tree.configure(yscrollcommand=sb.set)
        self._cart_cols = ([c[0] for c in cols], [c[2] for c in cols])
        self.cart_tree.bind("<Configure>", lambda e: widgets.fit_tree(self.cart_tree, *self._cart_cols))
        sb.pack(side="right", fill="y")
        self.cart_tree.pack(side="left", fill="both", expand=True)
        self.after(50, lambda: widgets.fit_tree(self.cart_tree, *self._cart_cols))
        self.cart_tree.tag_configure("alt", background=theme.current["row_alt"])
        self.cart_empty_lbl = ttk.Label(wrap, text="Cart is empty — scan a barcode or search above to add a product",
                                        style="Muted.TLabel")
        btns = ttk.Frame(left)
        btns.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        for text, cmd, style in (("+ Qty", self.qty_up, "Secondary"), ("− Qty", self.qty_down, "Secondary"),
                                 ("Set qty", self.set_qty, "Secondary"), ("Line discount", self.line_discount, "Secondary"),
                                 ("Change price", self.change_price, "Secondary"), ("Remove (Del)", self.remove_line, "Danger")):
            ttk.Button(btns, text=text, style=f"{style}.TButton", command=cmd).pack(side="left", padx=(0, 6))
        # right panel
        card = ttk.Frame(right, style="Card.TFrame", padding=14)
        card.pack(fill="x")
        ttk.Label(card, text="CUSTOMER  (F2)", style="CardMuted.TLabel", font=(theme.FONT, 8, "bold")).pack(anchor="w")
        self.cust_lbl = ttk.Label(card, text="Walk-in customer", style="CardH.TLabel", wraplength=300)
        self.cust_lbl.pack(anchor="w")
        self.cust_sub = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=300)
        self.cust_sub.pack(anchor="w")
        ttk.Button(card, text="Choose / add customer", style="Secondary.TButton", command=self.pick_customer).pack(fill="x", pady=(8, 0))
        tot = ttk.Frame(right, style="Card.TFrame", padding=14)
        tot.pack(fill="x", pady=12)
        self.t_sub = self._row(tot, "Subtotal")
        self.t_disc = self._row(tot, "Discounts")
        self.t_tax = self._row(tot, "Tax")
        ttk.Separator(tot).pack(fill="x", pady=8)
        ttk.Label(tot, text="TOTAL", style="CardMuted.TLabel", font=(theme.FONT, 9, "bold")).pack(anchor="w")
        self.t_total = ttk.Label(tot, text="0", style="Total.TLabel")
        self.t_total.pack(anchor="w")
        self.t_err = ttk.Label(tot, text="", style="CardDanger.TLabel", wraplength=310)
        self.t_err.pack(anchor="w")
        opts = ttk.Frame(right)
        opts.pack(fill="x")
        ttk.Label(opts, text="Overall discount", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.overall = tk.StringVar(value="0")
        self.overall_e = ttk.Entry(opts, textvariable=self.overall, width=12, justify="right")
        self.overall_e.grid(row=0, column=1, sticky="e", pady=2)
        self.overall_e.bind("<KeyRelease>", lambda e: self.refresh())
        if not self.can("pos.discount"):
            self.overall_e.state(["disabled"])
        ttk.Label(opts, text="Note", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.notes = tk.StringVar()
        ttk.Entry(opts, textvariable=self.notes, width=24).grid(row=1, column=1, sticky="e", pady=2)
        opts.columnconfigure(0, weight=1)
        self.pay_btn = ttk.Button(right, text="PAY  (F4)", style="Big.Success.TButton", command=self.pay)
        self.pay_btn.pack(fill="x", pady=(14, 8))
        row = ttk.Frame(right)
        row.pack(fill="x")
        for i, (text, cmd) in enumerate((("Hold (F3)", self.hold), ("Resume (F6)", self.resume), ("New sale (F5)", self.new_sale))):
            ttk.Button(row, text=text, style="Secondary.TButton", command=cmd).grid(row=0, column=i, padx=2, sticky="ew")
            row.columnconfigure(i, weight=1)
        ttk.Button(right, text="Cancel sale", style="Danger.TButton", command=lambda: self.new_sale(ask=True)).pack(fill="x", pady=(8, 0))
        self.refresh()

    def _row(self, parent, label):
        f = ttk.Frame(parent, style="Surface.TFrame")
        f.pack(fill="x", pady=1)
        ttk.Label(f, text=label, style="CardMuted.TLabel").pack(side="left")
        v = ttk.Label(f, text="0", style="Card.TLabel", font=(theme.FONT, 11))
        v.pack(side="right")
        return v

    # ------------------------------------------------------------- lifecycle
    def on_show(self):
        a = self.app
        self._binds = []
        for key, fn in (("<F1>", self.focus_search), ("<F2>", self.pick_customer), ("<F3>", self.hold), ("<F4>", self.pay),
                        ("<F5>", self.new_sale), ("<F6>", self.resume)):
            self._binds.append((key, a.bind(key, lambda e, fn=fn: (fn(), "break")[1])))
        self._binds.append(("<Delete>", a.bind("<Delete>", self._delete_key)))
        self._binds.append(("<Key>", a.bind("<Key>", self._redirect_key, add="+")))
        self.search()
        self.focus_search()

    def on_hide(self):
        for key, fid in self._binds:
            try:
                self.app.unbind(key, fid)
            except tk.TclError:
                pass
        self._binds = []

    def focus_search(self):
        self.entry.focus_set()
        self.entry.selection_range(0, "end")

    def _delete_key(self, e):
        if e.widget is self.cart_tree:
            self.remove_line()

    def _redirect_key(self, e):
        """Barcode scanners type like a keyboard: make sure characters land in the search box."""
        try:
            if e.widget.winfo_toplevel() is not self.app or not e.char or not e.char.isprintable():
                return
            if e.state & 0x4 or isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
                return
            self.entry.focus_set()
            self.entry.insert("end", e.char)
            self._typed(None)
        except tk.TclError:
            pass

    # ------------------------------------------------------------- search & scan
    def _typed(self, e):
        if e is not None and e.keysym in ("Return", "Up", "Down", "Tab", "Escape", "F1", "F2", "F3", "F4", "F5", "F6"):
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(220, self.search)

    def search(self):
        self._job = None
        text = self.q.get().strip()
        cat = self.cat_map.get(self.cat.get()) or None
        rows = catalog.pos_search(self.db, text, 60)
        if cat:
            rows = [r for r in rows if r["category_id"] == cat] if text else \
                self.db.q("SELECT p.*, b.name AS brand FROM products p LEFT JOIN brands b ON b.id=p.brand_id "
                          "WHERE p.active=1 AND p.category_id=? ORDER BY p.name LIMIT 60", (cat,))
        self._rows = rows
        self.results.reload()

    def _focus_results(self):
        self.results.tree.focus_set()
        self.results.focus_first()

    def _add_selected_result(self):
        r = self.results.selected()
        if r:
            self.add_product(r)

    def submit(self, _e=None):
        code = self.q.get().strip()
        if not code:
            self._add_selected_result()
            return
        hit = catalog.find_by_code(self.db, code)
        if hit:
            if hit["serial"] is not None and hit["product"]["serialized"]:
                self.add_product(hit["product"], hit["serial"])
            else:
                self.add_product(hit["product"])
            return
        if self._job:
            self.after_cancel(self._job)
        self.search()
        if len(self._rows) == 1:
            self.add_product(self._rows[0])
        elif self._rows:
            self._focus_results()
        else:
            self.toast(f"Product not found: {code}", "error")
            self.entry.selection_range(0, "end")

    # ------------------------------------------------------------- cart
    def _line(self, pid):
        return next((l for l in self.cart if l["product"]["id"] == pid), None)

    def add_product(self, row, serial=None):
        with self.guard():
            p = catalog.get_product(self.db, row["id"])
            if not p or not p["active"]:
                raise POSError("Product not found.")
            line = self._line(p["id"])
            in_cart = line["qty"] if line else 0
            if p["serialized"]:
                taken = {s["id"] for l in self.cart for s in l["serials"]}
                if serial is not None:
                    if serial["status"] != "In Stock":
                        raise POSError(f"Serial {serial['serial']} is not in stock (status: {serial['status']}).")
                    if serial["id"] in taken:
                        raise POSError("That serial number is already in the cart.")
                    chosen = [serial]
                else:
                    avail = [s for s in catalog.available_serials(self.db, p["id"]) if s["id"] not in taken]
                    if not avail:
                        raise POSError(f"No more units of {p['name']} in stock.")
                    chosen = SerialPicker(self, p, avail).show()
                    if not chosen:
                        return
                if line is None:
                    line = {"product": p, "qty": 0, "unit_price": p["retail_price"], "discount": 0.0, "serials": []}
                    self.cart.append(line)
                line["serials"].extend({"id": s["id"], "serial": s["serial"]} for s in chosen)
                line["qty"] = len(line["serials"])
            else:
                if in_cart + 1 > p["stock"] and not settings.get_bool(self.db, "allow_negative_stock"):
                    raise POSError(f"Insufficient stock. Only {p['stock']} of {p['name']} available.")
                if line is None:
                    line = {"product": p, "qty": 0, "unit_price": p["retail_price"], "discount": 0.0, "serials": []}
                    self.cart.append(line)
                line["qty"] += 1
            self.q.set("")
            self.refresh(select=p["id"])
        self.focus_search()

    def _sel(self):
        sel = self.cart_tree.selection()
        if not sel:
            return None
        return self.cart[self.cart_tree.index(sel[0])]

    def qty_up(self):
        l = self._sel()
        if l:
            self.add_product(l["product"])

    def qty_down(self):
        l = self._sel()
        if not l:
            return
        if l["qty"] <= 1:
            self.remove_line()
            return
        l["qty"] -= 1
        if l["serials"]:
            l["serials"].pop()
        self.refresh(select=l["product"]["id"])

    def set_qty(self):
        l = self._sel()
        if not l:
            return
        if l["product"]["serialized"]:
            widgets.show_info(self, "Serialized items change quantity by adding or removing serial numbers.\n"
                                    "Use + Qty to add another unit, or − Qty / Remove.")
            return
        v = ask_text(self, "Quantity", f"Quantity for {l['product']['name']}", str(l["qty"]))
        if v is None:
            return
        with self.guard():
            q = int(to_float(v, "Quantity"))
            if q <= 0:
                raise POSError("Quantity must be greater than zero.")
            if q > l["product"]["stock"] and not settings.get_bool(self.db, "allow_negative_stock"):
                raise POSError(f"Insufficient stock. Only {l['product']['stock']} available.")
            l["qty"] = q
            self.refresh(select=l["product"]["id"])

    def line_discount(self):
        l = self._sel()
        if not l:
            return
        if not self.can("pos.discount"):
            widgets.show_warn(self, "You do not have permission to give discounts.")
            return
        v = ask_text(self, "Line discount", f"Discount amount for {l['product']['name']} (total for the line)", str(l["discount"] or 0))
        if v is None:
            return
        with self.guard():
            d = to_float(v, "Discount")
            if d > l["qty"] * l["unit_price"]:
                raise POSError("Discount is more than the line amount.")
            l["discount"] = d
            self.refresh(select=l["product"]["id"])

    def change_price(self):
        l = self._sel()
        if not l:
            return
        if not self.can("pos.price_override"):
            widgets.show_warn(self, "You do not have permission to change prices.")
            return
        v = ask_text(self, "Change price", f"Unit price for {l['product']['name']}  (retail {money(l['product']['retail_price'])})",
                     str(l["unit_price"]))
        if v is None:
            return
        with self.guard():
            pr = to_float(v, "Price")
            if pr <= 0:
                raise POSError("Price must be greater than zero.")
            l["unit_price"] = pr
            self.refresh(select=l["product"]["id"])

    def remove_line(self):
        l = self._sel()
        if l:
            self.cart.remove(l)
            self.refresh()
        self.focus_search()

    def cart_dict(self, payments=None):
        return {
            "customer_id": self.customer["id"] if self.customer else None,
            "items": [{"product_id": l["product"]["id"], "qty": l["qty"], "unit_price": l["unit_price"], "discount": l["discount"],
                       "serial_ids": [s["id"] for s in l["serials"]]} for l in self.cart],
            "overall_discount": (self.overall.get().strip() or "0"), "notes": self.notes.get(),
            "held_id": self.held_id, "payments": payments or []}

    def refresh(self, select=None):
        cur = self.cart_tree.selection()
        self.cart_tree.delete(*self.cart_tree.get_children())
        totals, err = None, ""
        if self.cart:
            try:
                totals = sales.preview_totals(self.db, self.cart_dict())
            except POSError as e:
                err = str(e)
        for i, l in enumerate(self.cart):
            lt = totals["lines"][i]["total"] if totals else l["qty"] * l["unit_price"] - l["discount"]
            iid = self.cart_tree.insert("", "end", values=(
                i + 1, l["product"]["name"], ", ".join(s["serial"] for s in l["serials"]), l["qty"], money(l["unit_price"]),
                money(l["discount"]) if l["discount"] else "", money(lt)), tags=("alt",) if i % 2 else ())
            if select is not None and l["product"]["id"] == select:
                self.cart_tree.selection_set(iid)
                self.cart_tree.see(iid)
        if select is None and cur and self.cart_tree.get_children():
            kids = self.cart_tree.get_children()
            self.cart_tree.selection_set(kids[min(len(kids) - 1, 0)])
        if self.cart:
            self.cart_empty_lbl.place_forget()
        else:
            self.cart_empty_lbl.place(relx=0.5, rely=0.15, anchor="n")
        cur_sym = settings.get(self.db, "currency")
        t = totals or {"subtotal": 0, "line_discount": 0, "overall_discount": 0, "tax": 0, "total": 0}
        self.t_sub.configure(text=money(t["subtotal"]))
        self.t_disc.configure(text=money(t["line_discount"] + t["overall_discount"]))
        self.t_tax.configure(text=money(t["tax"]))
        self.t_total.configure(text=money(t["total"], cur_sym))
        self.t_err.configure(text=err)
        self.pay_btn.state(["!disabled" if (self.cart and totals) else "disabled"])

    # ------------------------------------------------------------- customer
    def pick_customer(self):
        with self.guard():
            r = CustomerPicker(self, self.app).show()
            if r is None:
                return
            self.set_customer(None if r == "walkin" else r)
        self.focus_search()

    def set_customer(self, c):
        self.customer = parties.get_customer(self.db, c["id"]) if c else None
        if not self.customer:
            self.cust_lbl.configure(text="Walk-in customer")
            self.cust_sub.configure(text="")
        else:
            c = self.customer
            self.cust_lbl.configure(text=c["name"])
            self.cust_sub.configure(text=f"{c['phone'] or ''}   owes {money(c['balance'])}   credit limit {money(c['credit_limit'])}"
                                         + (f"   store credit {money(c['store_credit'])}" if c["store_credit"] else ""))

    # ------------------------------------------------------------- hold / resume / new
    def new_sale(self, ask=False):
        if self.cart:
            if not widgets.confirm(self, "Clear the current sale and start a new one?", danger=True):
                return
        self.reset()

    def reset(self):
        self.cart, self.held_id = [], None
        self.set_customer(None)
        self.overall.set("0")
        self.notes.set("")
        self.q.set("")
        self.refresh()
        self.search()
        self.focus_search()

    def hold(self):
        if not self.cart:
            widgets.show_warn(self, "The cart is empty.")
            return
        with self.guard():
            note = ask_text(self, "Hold sale", "Note (optional, e.g. customer name)", required=False)
            if note is None:
                return
            if self.held_id:
                sales.delete_held(self.db, self.user, self.held_id)
            sales.hold_cart(self.db, self.user, self.cart_dict(), note)
            self.toast("Sale put on hold", "info")
            self.reset()

    def resume(self):
        with self.guard():
            if not sales.list_held(self.db):
                self.toast("There are no held sales.", "info")
                return
            hid = ResumeDialog(self, self.app).show()
            if hid is None:
                return
            if self.cart and not widgets.confirm(self, "Replace the current cart with the held sale?", danger=True):
                return
            saved = sales.resume_held(self.db, self.user, hid)
            self.reset()
            dropped = 0
            for it in saved["items"]:
                p = catalog.get_product(self.db, it["product_id"])
                if not p or not p["active"]:
                    dropped += 1
                    continue
                line = {"product": p, "qty": int(it["qty"]), "unit_price": it.get("unit_price") or p["retail_price"],
                        "discount": float(it.get("discount") or 0), "serials": []}
                if p["serialized"]:
                    for sid in it.get("serial_ids", []):
                        s = self.db.one("SELECT id,serial,status FROM serials WHERE id=?", (sid,))
                        if s and s["status"] == "In Stock":
                            line["serials"].append({"id": s["id"], "serial": s["serial"]})
                        else:
                            dropped += 1
                    line["qty"] = len(line["serials"])
                    if not line["qty"]:
                        continue
                else:
                    line["qty"] = min(line["qty"], max(p["stock"], 0)) if not settings.get_bool(self.db, "allow_negative_stock") else line["qty"]
                    if line["qty"] <= 0:
                        dropped += 1
                        continue
                self.cart.append(line)
            self.held_id = hid
            if saved.get("customer_id"):
                self.set_customer(parties.get_customer(self.db, saved["customer_id"]))
            self.overall.set(str(saved.get("overall_discount") or "0"))
            self.notes.set(saved.get("notes") or "")
            self.refresh()
            if dropped:
                widgets.show_warn(self, f"{dropped} item(s)/serial(s) from the held sale are no longer available and were removed.")

    # ------------------------------------------------------------- payment
    def pay(self):
        if not self.cart:
            widgets.show_warn(self, "The cart is empty. Scan or search for a product first.")
            return
        with self.guard():
            totals = sales.preview_totals(self.db, self.cart_dict())
            cur = settings.get(self.db, "currency")
            r = PayDialog(self, totals["total"], self.customer, cur).show()
            if not r:
                return
            res = sales.complete_sale(self.db, self.user, self.cart_dict(r["payments"]))
            self.reset()
            self.app.update_register_status()
            if settings.get_bool(self.db, "auto_print_receipt"):
                try:
                    printing.print_receipt(self.db, res["sale_id"])
                except POSError as e:
                    self.toast(str(e), "warn")
            SaleDoneDialog(self, self.app, res, r["change"]).show()
            self.focus_search()
