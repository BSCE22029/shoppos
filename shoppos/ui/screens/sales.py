import tkinter as tk
from tkinter import ttk

from ...services import printing, sales
from ...util import POSError, money
from .. import widgets
from ..base import Screen
from ..widgets import DataTable, FormDialog, date_range_bar


class SalesScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Sales", "Every invoice, with receipt reprint, cancellation and returns")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=30)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search invoice, customer or phone...")
        e.bind("<KeyRelease>", lambda ev: self._deb())
        ttk.Label(bar, text="invoice, customer or phone", style="Muted.TLabel").pack(side="left", padx=6)
        self.status = tk.StringVar(value="All")
        cb = ttk.Combobox(bar, textvariable=self.status, state="readonly", width=17,
                          values=["All", "Completed", "Partially Returned", "Returned", "Cancelled"])
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda ev: self.table.reload())
        f, self.dates = date_range_bar(bar, lambda: self.table.reload(), 30)
        f.pack(side="left", padx=8)
        cols = [("invoice_no", "Invoice", 100), ("date", "Date", 130, "w", widgets.fmt_date), ("customer", "Customer", 170), ("cashier", "Cashier", 90),
                ("total", "Total", 100, "e", widgets.fmt_money), ("paid", "Paid", 100, "e", widgets.fmt_money),
                ("credit", "On credit", 90, "e", widgets.fmt_money), ("status", "Status", 120)]
        self.table = DataTable(self, cols, self._load, page_size=50, on_open=lambda r: self.view(),
                               empty_text="No sales in this date range.",
                               tag_fn=lambda r: {"Cancelled": "muted", "Returned": "warn", "Partially Returned": "warn"}.get(r["status"]))
        self.table.pack(fill="both", expand=True)
        self.foot = ttk.Label(self, text="", style="Muted.TLabel")
        self.foot.pack(anchor="w", pady=(6, 0))
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="View / receipt", style="Primary.TButton", command=self.view).pack(side="left", padx=(0, 8))
        ttk.Button(b, text="A4 invoice (PDF)", style="Secondary.TButton", command=self.pdf).pack(side="left", padx=(0, 8))
        if self.can("returns.process"):
            ttk.Button(b, text="Return items...", style="Secondary.TButton", command=self.to_return).pack(side="left", padx=(0, 8))
        if self.can("sales.cancel"):
            ttk.Button(b, text="Cancel sale", style="Danger.TButton", command=self.cancel).pack(side="left")
        self._job = None

    def _deb(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(250, self.table.reload)

    def _load(self, limit, offset):
        f, t = self.dates()
        st = None if self.status.get() == "All" else self.status.get()
        rows, total = sales.list_sales(self.db, self.user, self.q.get().strip(), f, t, st, None, None, limit, offset)
        live = self.db.scalar("SELECT COALESCE(SUM(total),0) FROM sales WHERE status<>'Cancelled' AND date>=? AND date<date(?, '+1 day')",
                              (f or "0000-01-01", t or "9999-12-31"))
        self.foot.configure(text=f"Sales total in this date range (excluding cancelled): {money(live)}")
        return rows, total

    def on_show(self):
        self.table.reload(keep_page=True)

    def _sel(self):
        s = self.table.selected()
        if not s:
            widgets.show_warn(self, "Select an invoice first.")
        return s

    def view(self):
        s = self._sel()
        if not s:
            return
        with self.guard():
            text = printing.receipt_text(self.db, s["id"], reprint=True)
            widgets.text_preview(self, s["invoice_no"], text, on_print=lambda: self._print(s["id"]), width=460, height=680)

    def _print(self, sid):
        with self.guard():
            printing.print_receipt(self.db, sid, reprint=True)
            self.toast("Sent to printer", "info")

    def pdf(self):
        s = self._sel()
        if s:
            with self.guard():
                printing.open_file(printing.save_invoice_pdf(self.db, s["id"]))

    def to_return(self):
        s = self._sel()
        if s:
            self.app.navigate("returns")
            self.app.screens["returns"].load_invoice(s["invoice_no"])

    def cancel(self):
        s = self._sel()
        if not s:
            return
        if s["status"] != "Completed":
            widgets.show_warn(self, f"Only untouched Completed sales can be cancelled (this one is {s['status']}).")
            return

        def save(v):
            sales.cancel_sale(self.db, self.user, s["id"], v["reason"])
            return v
        if FormDialog(self, f"Cancel {s['invoice_no']}", [
                {"key": "l", "type": "label", "label": "Stock, serial numbers, warranty, customer credit and cash will be reversed. "
                                                        "Card / bank payments must be refunded manually."},
                {"key": "reason", "label": "Reason (required)", "required": True, "width": 44}], on_save=save, save_text="Cancel sale").show():
            self.toast("Sale cancelled", "info")
            self.app.update_register_status()
            self.table.reload(keep_page=True)
