import tkinter as tk
from tkinter import ttk

from ...services import reports, settings
from ...util import money
from .. import theme
from ..base import Screen


class DashboardScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Dashboard", "How the shop is doing today")
        ttk.Button(act, text="Refresh", style="Secondary.TButton", command=self.on_show).pack()
        self.cards = ttk.Frame(self)
        self.cards.pack(fill="x")
        self.lower = ttk.Frame(self)
        self.lower.pack(fill="both", expand=True, pady=(16, 0))

    def _card(self, parent, col, title, value, sub="", colour=None, small=False):
        c = theme.current
        f = ttk.Frame(parent, style="Card.TFrame", padding=16)
        f.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 12, 0))
        parent.columnconfigure(col, weight=1, uniform="c")
        ttk.Label(f, text=title if small else title.upper(), style="CardMuted.TLabel", font=(theme.FONT, 9 if small else 8, "bold")).pack(anchor="w")
        lbl = ttk.Label(f, text=value, style="Mid.TLabel" if small else "Big.TLabel")
        if colour:
            lbl.configure(foreground=c[colour])
        lbl.pack(anchor="w", pady=(4, 0))
        if sub:
            ttk.Label(f, text=sub, style="CardMuted.TLabel").pack(anchor="w")

    def _card_at(self, parent, row, col, title, value, colour=None):
        c = theme.current
        f = ttk.Frame(parent, style="Card.TFrame", padding=(14, 10))
        f.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 12, 0), pady=(0 if row == 0 else 10, 0))
        parent.columnconfigure(col, weight=1, uniform="c2")
        ttk.Label(f, text=title, style="CardMuted.TLabel").pack(side="left")
        lbl = ttk.Label(f, text=value, style="Mid.TLabel")
        if colour:
            lbl.configure(foreground=c[colour])
        lbl.pack(side="right")

    def on_show(self):
        for w in list(self.cards.winfo_children()) + list(self.lower.winfo_children()):
            w.destroy()
        d = reports.dashboard(self.db, self.user)
        cur = settings.get(self.db, "currency")
        self._card(self.cards, 0, "Today's sales", money(d["today_sales"], cur), f"{d['today_count']} invoice(s)")
        self._card(self.cards, 1, "This month", money(d["month_sales"], cur))
        if "today_profit" in d:
            self._card(self.cards, 2, "Gross profit today", money(d["today_profit"], cur), "before expenses", "success")
            self._card(self.cards, 3, "Net profit this month", money(d["month_profit"], cur), "after expenses", "success")
        else:
            self._card(self.cards, 2, "Low stock items", str(d["low_stock"]), "need reordering", "warning")
            self._card(self.cards, 3, "Out of stock", str(d["out_of_stock"]), "", "danger")
        row2 = ttk.Frame(self.cards)
        row2.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        items = [("Low stock", str(d["low_stock"]), "warning"), ("Out of stock", str(d["out_of_stock"]), "danger"),
                 ("Open repairs", str(d["open_repairs"]), None), ("Ready to collect", str(d["ready_repairs"]), "success"),
                 ("Warranty claims", str(d["open_claims"]), None), ("Expiring warranty", str(d["expiring_warranty"]), "warning")]
        if "receivables" in d:
            items += [("Receivables", money(d["receivables"], cur), "danger"), ("Payables", money(d["payables"], cur), "warning")]
        for i, (t, v, col) in enumerate(items):
            self._card_at(row2, i // 4, i % 4, t, v, col)
        left = ttk.Frame(self.lower, style="Card.TFrame", padding=16)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Sales - last 7 days", style="CardH.TLabel").pack(anchor="w")
        cv = tk.Canvas(left, height=theme.px(210), bg=theme.current["surface"], highlightthickness=0)
        cv.pack(fill="both", expand=True, pady=(8, 0))
        cv.bind("<Configure>", lambda e, s=d["series"]: self._chart(cv, s))
        right = ttk.Frame(self.lower, style="Card.TFrame", padding=16, width=theme.px(340))
        right.pack(side="left", fill="y", padx=(12, 0))
        right.pack_propagate(False)
        ttk.Label(right, text="Top sellers (30 days)", style="CardH.TLabel").pack(anchor="w")
        if not d["top_products"]:
            ttk.Label(right, text="No sales yet.", style="CardMuted.TLabel").pack(anchor="w", pady=8)
        for i, p in enumerate(d["top_products"], 1):
            r = ttk.Frame(right, style="Surface.TFrame")
            r.pack(fill="x", pady=3)
            ttk.Label(r, text=f"{i}. {p['name'][:32]}", style="Card.TLabel").pack(side="left")
            ttk.Label(r, text=f"{p['qty']}", style="Card.TLabel", font=(theme.FONT, 10, "bold")).pack(side="right")
        self.app.update_register_status()

    def _chart(self, cv, series):
        cv.delete("all")
        c = theme.current
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 60 or h < 60:
            return
        if not series:
            cv.create_text(w / 2, h / 2, text="No sales in the last 7 days", fill=c["muted"], font=(theme.FONT, 11))
            return
        mx = max(s["total"] for s in series) or 1
        n = len(series)
        bw = min((w - 60) / n * 0.6, 70)
        gap = (w - 60) / n
        for i, s in enumerate(series):
            x = 40 + i * gap + (gap - bw) / 2
            bh = (h - 50) * s["total"] / mx
            cv.create_rectangle(x, h - 28 - bh, x + bw, h - 28, fill=c["accent"], outline="")
            cv.create_text(x + bw / 2, h - 14, text=s["day"][5:], fill=c["muted"], font=(theme.FONT, 8))
            cv.create_text(x + bw / 2, h - 34 - bh, text=f"{s['total'] / 1000:,.0f}k" if s["total"] >= 1000 else f"{s['total']:,.0f}",
                           fill=c["text"], font=(theme.FONT, 8, "bold"))
