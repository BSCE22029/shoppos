import os
import tkinter as tk
from tkinter import ttk

from ...services import finance, settings
from ...util import money
from .. import theme, widgets
from ..base import Screen
from ..widgets import DataTable, FormDialog


class CashRegisterScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Cash register", "Open the till, track cash in and out, and reconcile at closing")
        self.card = ttk.Frame(self, style="Card.TFrame", padding=18)
        self.card.pack(fill="x")
        ttk.Label(self, text="Register history  (double-click for the daily cash report)", style="H2.TLabel").pack(anchor="w", pady=(16, 6))
        cols = [("id", "#", 50), ("opened_at", "Opened", 130, "w", widgets.fmt_date), ("closed_at", "Closed", 130, "w", widgets.fmt_date), ("opener", "Opened by", 90),
                ("opening_cash", "Opening", 100, "e", widgets.fmt_money), ("expected_cash", "Expected", 100, "e", widgets.fmt_money),
                ("actual_cash", "Counted", 100, "e", widgets.fmt_money), ("variance", "Variance", 100, "e", widgets.fmt_money), ("status", "Status", 80)]
        self.hist = DataTable(self, cols, lambda l, o: (finance.list_registers(self.db, self.user, 100)[o:o + l], 0), page_size=100, height=8,
                              on_open=lambda r: self.report(r["id"]),
                              tag_fn=lambda r: "danger" if (r["variance"] or 0) < -0.005 else ("warn" if (r["variance"] or 0) > 0.005 else None))
        self.hist.pack(fill="both", expand=True)

    def on_show(self):
        for w in self.card.winfo_children():
            w.destroy()
        reg = finance.open_register(self.db)
        cur = settings.get(self.db, "currency")
        if not reg:
            ttk.Label(self.card, text="Register is CLOSED", font=(theme.FONT, 16, "bold"), foreground=theme.current["danger"], background=theme.current["surface"]).pack(anchor="w")
            ttk.Label(self.card, text="Open the register before taking cash payments.", style="CardMuted.TLabel").pack(anchor="w", pady=(2, 10))
            ttk.Button(self.card, text="Open register", style="Success.TButton", command=self.open).pack(anchor="w")
        else:
            s = finance.register_summary(self.db, reg["id"])
            top = ttk.Frame(self.card, style="Surface.TFrame")
            top.pack(fill="x")
            ttk.Label(top, text=f"Register OPEN since {s['opened_at'][:16]}", font=(theme.FONT, 14, "bold"), foreground=theme.current["success"],
                      background=theme.current["surface"]).pack(side="left")
            ttk.Label(top, text=f"Expected cash in drawer: {money(s['expected'], cur)}", style="CardH.TLabel", font=(theme.FONT, 14, "bold")).pack(side="right")
            grid = ttk.Frame(self.card, style="Surface.TFrame")
            grid.pack(fill="x", pady=10)
            items = [("Opening cash", s["opening_cash"])] + sorted(s["by_kind"].items())
            for i, (k, v) in enumerate(items):
                f = ttk.Frame(grid, style="Surface.TFrame")
                f.grid(row=0, column=i, padx=(0, 26))
                ttk.Label(f, text=k, style="CardMuted.TLabel").pack(anchor="w")
                ttk.Label(f, text=f"{v:+,.0f}" if k != "Opening cash" else f"{v:,.0f}", style="Card.TLabel", font=(theme.FONT, 12, "bold"),
                          foreground=theme.current["danger"] if v < 0 else theme.current["text"]).pack(anchor="w")
            bar = ttk.Frame(self.card, style="Surface.TFrame")
            bar.pack(fill="x")
            ttk.Button(bar, text="Cash deposit (add cash)", style="Secondary.TButton", command=lambda: self.move("Deposit")).pack(side="left")
            ttk.Button(bar, text="Cash withdrawal", style="Secondary.TButton", command=lambda: self.move("Withdrawal")).pack(side="left", padx=8)
            ttk.Button(bar, text="Movements", style="Secondary.TButton", command=lambda: self.moves(reg["id"])).pack(side="left")
            ttk.Button(bar, text="Close register", style="Danger.TButton", command=self.close).pack(side="right")
        self.hist.reload()
        self.app.update_register_status()

    def open(self):
        def save(v):
            return {"id": finance.open_new_register(self.db, self.user, v["cash"])}
        if FormDialog(self, "Open register", [{"key": "cash", "label": "Opening cash in the drawer", "type": "money", "required": True, "default": "0"}],
                      on_save=save, save_text="Open").show():
            self.toast("Register opened")
            self.on_show()

    def move(self, kind):
        def save(v):
            finance.cash_movement(self.db, self.user, kind, v["amount"], v["note"])
            return v
        if FormDialog(self, f"Cash {kind.lower()}", [
                {"key": "amount", "label": "Amount", "type": "money", "required": True},
                {"key": "note", "label": "Reason / note (required)", "required": True, "width": 40}], on_save=save).show():
            self.toast(f"Cash {kind.lower()} recorded")
            self.on_show()

    def close(self):
        reg = finance.open_register(self.db)
        s = finance.register_summary(self.db, reg["id"])

        def save(v):
            return {"id": finance.close_register(self.db, self.user, v["actual"], v["note"])["id"]}
        r = FormDialog(self, "Close register", [
            {"key": "l", "type": "label", "label": f"Expected cash: {money(s['expected'])}\nCount the drawer and enter the actual amount."},
            {"key": "actual", "label": "Actual cash counted", "type": "money", "required": True},
            {"key": "note", "label": "Note (optional)", "width": 40}], on_save=save, save_text="Close register").show()
        if r:
            self.on_show()
            self.report(r["id"])

    def report(self, rid):
        with self.guard():
            text = finance.daily_cash_report(self.db, rid)

            def save():
                from tkinter import filedialog
                p = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=f"cash-report-{rid}.txt", filetypes=[("Text", "*.txt")])
                if p:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(text)
            widgets.text_preview(self, "Daily cash report", text, on_save=save, width=560, height=520)

    def moves(self, rid):
        d = widgets.Dialog(self, "Register movements", 760, 480, resizable=True)
        rows = finance.register_transactions(self.db, rid)
        t = DataTable(d, [("date", "Time", 130, "w", widgets.fmt_date), ("kind", "Type", 140), ("amount", "Amount", 110, "e", lambda v, r: f"{v:+,.2f}"),
                          ("note", "Note", 260), ("username", "User", 90)],
                      lambda l, o: (rows[o:o + l], len(rows)), page_size=200, height=14, tag_fn=lambda r: "danger" if r["amount"] < 0 else "ok")
        t.pack(fill="both", expand=True, padx=16, pady=16)
        t.reload()
        d.show()
