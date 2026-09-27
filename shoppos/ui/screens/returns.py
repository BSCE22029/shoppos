import tkinter as tk
from tkinter import ttk

from ...config import REFUND_METHODS
from ...services import returns, sales
from ...util import POSError, money, to_int
from .. import theme, widgets
from ..base import Screen
from ..widgets import DataTable
from .pos import SerialPicker


class ReturnsScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Returns & refunds", "Find the invoice, choose what comes back, and refund or give store credit")
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.inv = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.inv, width=26, style="Big.TEntry")
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.find())
        ttk.Button(top, text="Find invoice", style="Primary.TButton", command=self.find).pack(side="left", padx=8)
        ttk.Label(top, text="e.g. INV-000123  (or scan the receipt barcode)", style="Muted.TLabel").pack(side="left")
        self.info = ttk.Label(self, text="", style="H2.TLabel")
        self.info.pack(anchor="w", pady=(12, 4))
        self.body = ttk.Frame(self, style="Card.TFrame", padding=12)
        self.body.pack(fill="x")
        self.foot = ttk.Frame(self)
        self.foot.pack(fill="x", pady=8)
        ttk.Label(self, text="Return history", style="H2.TLabel").pack(anchor="w", pady=(8, 4))
        self.hist = DataTable(self, [("return_no", "Return", 100), ("date", "Date", 130, "w", widgets.fmt_date), ("invoice_no", "Invoice", 100),
                                     ("customer", "Customer", 160), ("amount", "Value", 100, "e", widgets.fmt_money),
                                     ("refund_amount", "Refunded", 100, "e", widgets.fmt_money), ("credit_offset", "Off balance", 100, "e", widgets.fmt_money),
                                     ("refund_method", "Method", 110), ("note", "Note", 200)],
                              lambda l, o: returns.list_returns(self.db, self.user, "", None, None, l, o), page_size=30, height=6)
        self.hist.pack(fill="both", expand=True)
        self.sale = None
        self.rows = []

    def on_show(self):
        self.hist.reload(keep_page=True)

    def load_invoice(self, invoice_no):
        self.inv.set(invoice_no)
        self.find()

    def find(self):
        with self.guard():
            s = sales.find_sale_by_invoice(self.db, self.inv.get())
            if not s:
                raise POSError("Invoice not found.")
            self.sale = returns.returnable(self.db, s["id"])
            self.build()

    def build(self):
        for w in list(self.body.winfo_children()) + list(self.foot.winfo_children()):
            w.destroy()
        s = self.sale
        self.info.configure(text=f"{s['invoice_no']}   {s['date'][:16]}   {s['customer'] or 'Walk-in'}   total {money(s['total'])}   [{s['status']}]")
        if s["status"] in ("Cancelled", "Returned"):
            ttk.Label(self.body, text="This invoice has been " + ("cancelled." if s["status"] == "Cancelled" else "fully returned - nothing left to return."),
                      style="Card.TLabel", foreground=theme.current["danger"]).pack(anchor="w")
            return
        for c, h in enumerate(("Product", "Sold", "Returned", "Return qty", "Condition", "Serial numbers being returned")):
            ttk.Label(self.body, text=h, style="CardMuted.TLabel").grid(row=0, column=c, sticky="w", padx=6, pady=(0, 4))
        self.rows = []
        n = 0
        for it in s["items"]:
            n += 1
            ttk.Label(self.body, text=it["name"], style="Card.TLabel").grid(row=n, column=0, sticky="w", padx=6, pady=3)
            ttk.Label(self.body, text=str(it["qty"]), style="Card.TLabel").grid(row=n, column=1, sticky="w", padx=6)
            ttk.Label(self.body, text=str(it["returned_qty"]), style="Card.TLabel").grid(row=n, column=2, sticky="w", padx=6)
            row = {"item": it, "qty": tk.StringVar(value="0"), "cond": tk.StringVar(value="Good"), "serials": []}
            if it["remaining"] > 0:
                if it["serialized"]:
                    lbl = ttk.Label(self.body, text="(pick serials)", style="CardMuted.TLabel")
                    ttk.Label(self.body, textvariable=row["qty"], style="Card.TLabel").grid(row=n, column=3, sticky="w", padx=6)
                    ttk.Button(self.body, text="Choose serials...", style="Secondary.TButton",
                               command=lambda r_=row, l_=lbl: self.pick_serials(r_, l_)).grid(row=n, column=5, sticky="w", padx=6)
                    lbl.grid(row=n, column=6, sticky="w")
                else:
                    ttk.Spinbox(self.body, from_=0, to=it["remaining"], textvariable=row["qty"], width=6).grid(row=n, column=3, sticky="w", padx=6)
                ttk.Combobox(self.body, textvariable=row["cond"], values=["Good", "Damaged"], state="readonly", width=10).grid(row=n, column=4, padx=6)
            else:
                ttk.Label(self.body, text="fully returned", style="CardMuted.TLabel").grid(row=n, column=3, sticky="w", padx=6)
            self.rows.append(row)
        ttk.Label(self.foot, text="Refund as").pack(side="left")
        self.method = tk.StringVar(value="Cash")
        ttk.Combobox(self.foot, textvariable=self.method, values=REFUND_METHODS, state="readonly", width=16).pack(side="left", padx=8)
        self.note = tk.StringVar()
        ttk.Label(self.foot, text="Reason").pack(side="left", padx=(12, 0))
        ttk.Entry(self.foot, textvariable=self.note, width=34).pack(side="left", padx=8)
        ttk.Button(self.foot, text="Process return", style="Danger.TButton", command=lambda: self.process(False)).pack(side="left", padx=(12, 6))
        ttk.Button(self.foot, text="Exchange (store credit, then sell)", style="Secondary.TButton", command=lambda: self.process(True)).pack(side="left")

    def pick_serials(self, row, lbl):
        it = row["item"]
        avail = [{"id": r["serial_id"], "serial": r["serial"]} for r in it["sold_serials"]]
        if not avail:
            widgets.show_warn(self, "There are no returnable serial numbers on this line.")
            return
        picked = SerialPicker(self, {"name": it["name"]}, avail).show()
        if picked:
            row["serials"] = [s["id"] for s in picked]
            row["qty"].set(str(len(picked)))
            lbl.configure(text=", ".join(s["serial"] for s in picked))

    def process(self, exchange):
        with self.guard():
            items = []
            for r in self.rows:
                q = to_int(r["qty"].get() or 0, "Return quantity")
                if q > 0:
                    items.append({"sale_item_id": r["item"]["id"], "qty": q, "serial_ids": r["serial_ids"] if "serial_ids" in r else r["serials"],
                                  "condition": r["cond"].get()})
            if not items:
                raise POSError("Enter a return quantity for at least one item.")
            method = "Store Credit" if exchange else self.method.get()
            if exchange and not self.sale["customer_id"]:
                raise POSError("Exchange needs a customer on the invoice (store credit is kept on the customer's account).")
            if not widgets.confirm(self, f"Process this return and refund by {method}?", "Confirm return"):
                return
            res = returns.process_return(self.db, self.user, self.sale["id"], items, method, self.note.get())
            msg = f"{res['return_no']}: value {money(res['amount'])}"
            if res["credit_offset"]:
                msg += f", {money(res['credit_offset'])} taken off the customer's balance"
            if res["refund_amount"]:
                msg += f", {money(res['refund_amount'])} refunded by {method}"
            self.toast(msg, "info")
            self.app.update_register_status()
            cust = self.sale["customer_id"]
            self.load_invoice(self.sale["invoice_no"])
            self.hist.reload()
            if exchange:
                self.app.navigate("pos")
                pos = self.app.screens["pos"]
                pos.reset()
                from ...services import parties
                pos.set_customer(parties.get_customer(self.db, cust))
                widgets.show_info(self, "Store credit added. Now scan the new item and choose 'Store Credit' when paying.")
