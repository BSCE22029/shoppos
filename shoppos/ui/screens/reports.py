import os
import tkinter as tk
from tkinter import filedialog, ttk

from ...services import catalog, export, printing, reports
from ...util import POSError, today
from .. import theme, widgets
from ..base import Screen
from ..widgets import DataTable, date_range_bar

# (group, label, function(db,user,from,to), needs_dates, permission)
CATALOGUE = [
    ("Sales", "Daily sales", lambda d, u, f, t: reports.sales_report(d, u, "day", f, t), True, "reports.view"),
    ("Sales", "Weekly sales", lambda d, u, f, t: reports.sales_report(d, u, "week", f, t), True, "reports.view"),
    ("Sales", "Monthly sales", lambda d, u, f, t: reports.sales_report(d, u, "month", f, t), True, "reports.view"),
    ("Sales", "Sales register (all invoices)", lambda d, u, f, t: reports.sales_detail(d, u, f, t), True, "reports.view"),
    ("Sales", "By product", lambda d, u, f, t: reports.sales_report(d, u, "product", f, t), True, "reports.view"),
    ("Sales", "By category", lambda d, u, f, t: reports.sales_report(d, u, "category", f, t), True, "reports.view"),
    ("Sales", "By brand", lambda d, u, f, t: reports.sales_report(d, u, "brand", f, t), True, "reports.view"),
    ("Sales", "By cashier", lambda d, u, f, t: reports.sales_report(d, u, "cashier", f, t), True, "reports.view"),
    ("Sales", "By customer", lambda d, u, f, t: reports.sales_report(d, u, "customer", f, t), True, "reports.view"),
    ("Sales", "By payment method", lambda d, u, f, t: reports.sales_report(d, u, "payment", f, t), True, "reports.view"),
    ("Inventory", "Stock valuation", lambda d, u, f, t: reports.stock_valuation(d, u), False, "reports.view"),
    ("Inventory", "Low stock", lambda d, u, f, t: reports.low_stock(d, u), False, "reports.view"),
    ("Inventory", "Out of stock", lambda d, u, f, t: reports.out_of_stock(d, u), False, "reports.view"),
    ("Inventory", "Dead stock", lambda d, u, f, t: reports.dead_stock(d, u), False, "reports.view"),
    ("Inventory", "Fast-moving products", lambda d, u, f, t: reports.fast_moving(d, u, f, t), True, "reports.view"),
    ("Inventory", "Stock movement", lambda d, u, f, t: reports.stock_movement(d, u, None, f, t), True, "reports.view"),
    ("Purchases", "By supplier", lambda d, u, f, t: reports.purchases_by(d, u, "supplier", f, t), True, "reports.view"),
    ("Purchases", "By product", lambda d, u, f, t: reports.purchases_by(d, u, "product", f, t), True, "reports.view"),
    ("Purchases", "By date", lambda d, u, f, t: reports.purchases_by(d, u, "date", f, t), True, "reports.view"),
    ("Financial", "Profit & loss", lambda d, u, f, t: reports.profit_summary(d, u, f, t), True, "reports.financial"),
    ("Financial", "Receivables (customers owe)", lambda d, u, f, t: reports.receivables(d, u), False, "reports.view"),
    ("Financial", "Payables (we owe suppliers)", lambda d, u, f, t: reports.payables(d, u), False, "reports.view"),
    ("Repairs", "Pending repairs", lambda d, u, f, t: reports.repair_report(d, u, "pending"), False, "reports.view"),
    ("Repairs", "Completed repairs", lambda d, u, f, t: reports.repair_report(d, u, "completed", f, t), True, "reports.view"),
    ("Repairs", "Technician performance", lambda d, u, f, t: reports.repair_report(d, u, "technician", f, t), True, "reports.view"),
    ("Repairs", "Repair revenue", lambda d, u, f, t: reports.repair_report(d, u, "revenue", f, t), True, "reports.view"),
]


class ReportsScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Reports", "Pick a report, choose the dates, then view or export it")
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Card.TFrame", padding=8, width=theme.px(250))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True)
        self.items = {}
        groups = {}
        for i, (g, label, fn, dates, perm) in enumerate(CATALOGUE):
            if perm not in self.user["permissions"]:
                continue
            if g not in groups:
                groups[g] = self.tree.insert("", "end", text=g, open=True)
            iid = self.tree.insert(groups[g], "end", text=label)
            self.items[iid] = (g, label, fn, dates)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.run())
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        self.dbar, self.get_dates = date_range_bar(bar, self.run, 29)
        self.dbar.pack(side="left")
        ttk.Button(bar, text="Run", style="Primary.TButton", command=self.run).pack(side="left", padx=8)
        trow = ttk.Frame(right)
        trow.pack(fill="x", pady=(12, 2))
        self.title = ttk.Label(trow, text="Select a report on the left", style="H2.TLabel")
        self.title.pack(side="left")
        for ext, lbl in (("csv", "CSV"), ("xlsx", "Excel"), ("pdf", "PDF")):
            ttk.Button(trow, text=f"Export {lbl}", style="Secondary.TButton", command=lambda e=ext: self.export(e)).pack(side="right", padx=(6, 0))
        ttk.Button(trow, text="Print", style="Secondary.TButton", command=self.print_pdf).pack(side="right", padx=(6, 0))
        self.summary = ttk.Label(right, text="", style="Muted.TLabel", wraplength=800)
        self.summary.pack(anchor="w", pady=(0, 6))
        self.holder = ttk.Frame(right)
        self.holder.pack(fill="both", expand=True)
        self.report = None
        self.current = None

    def run(self):
        sel = self.tree.selection()
        if not sel or sel[0] not in self.items:
            return
        g, label, fn, dates = self.items[sel[0]]
        self.current = fn
        f, t = self.get_dates() if dates else (None, None)
        with self.guard():
            rep = fn(self.db, self.user, f, t)
            self.report = rep
            self.title.configure(text=rep["title"] + (f"   ({f} to {t})" if dates else ""))
            sm = rep.get("summary") or {}
            self.summary.configure(text="     ".join(f"{k.replace('_', ' ').title()}: {v:,.2f}" if isinstance(v, float) else f"{k.replace('_', ' ').title()}: {v:,}" if isinstance(v, int) else f"{k}: {v}" for k, v in sm.items()))
            for w in self.holder.winfo_children():
                w.destroy()
            rows = rep["rows"]
            numeric = {k for k, _ in rep["columns"] if rows and all(isinstance(r.get(k), (int, float)) or r.get(k) is None for r in rows[:30])}
            cols = [(k, lbl, 130 if k in numeric else 200, "e" if k in numeric else "w",
                     (lambda v, r: "" if v is None else (f"{v:,.2f}" if isinstance(v, float) and abs(v - round(v)) > 0.004 else f"{v:,.0f}")) if k in numeric else None)
                    for k, lbl in rep["columns"]]
            tbl = DataTable(self.holder, cols, lambda l, o: (rows[o:o + l], len(rows)), page_size=100, height=16)
            tbl.pack(fill="both", expand=True)
            tbl.reload()

    def _need(self):
        if not self.report:
            widgets.show_warn(self, "Run a report first.")
        return self.report

    def export(self, ext):
        rep = self._need()
        if not rep:
            return
        name = rep["title"].lower().replace(" ", "_").replace("&", "and").replace("(", "").replace(")", "")[:40]
        path = filedialog.asksaveasfilename(parent=self, defaultextension=f".{ext}", initialfile=f"{name}_{today()}.{ext}",
                                            initialdir=self.app.paths["exports"], filetypes=[(ext.upper(), f"*.{ext}")])
        if path:
            with self.guard():
                export.export(self.db, rep, path)
                self.toast(f"Saved {os.path.basename(path)}", "info")
                if widgets.confirm(self, "Open the exported file now?"):
                    printing.open_file(path)

    def print_pdf(self):
        rep = self._need()
        if rep:
            with self.guard():
                path = os.path.join(self.app.paths["exports"], "print-preview.pdf")
                export.export(self.db, rep, path)
                printing.open_file(path)
