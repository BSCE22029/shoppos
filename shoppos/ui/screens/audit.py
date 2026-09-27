import tkinter as tk
from tkinter import ttk

from ...services import audit
from .. import widgets
from ..base import Screen
from ..widgets import DataTable, date_range_bar


class AuditScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Audit log", "Who did what, and when. Double-click a row for old / new values.")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=32)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search user, action or item...")
        e.bind("<KeyRelease>", lambda ev: self._deb())
        ttk.Label(bar, text="user, action or entity", style="Muted.TLabel").pack(side="left", padx=6)
        f, self.dates = date_range_bar(bar, lambda: self.table.reload(), 7)
        f.pack(side="left", padx=12)
        cols = [("date", "When", 140), ("username", "User", 90), ("action", "Action", 190), ("entity", "Entity", 100), ("entity_id", "ID", 70),
                ("old_value", "Old value", 240), ("new_value", "New value", 240)]
        self.table = DataTable(self, cols, self._load, page_size=100, on_open=self.detail)
        self.table.pack(fill="both", expand=True)
        self._job = None

    def _deb(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(300, self.table.reload)

    def _load(self, limit, offset):
        f, t = self.dates()
        return audit.search(self.db, self.user, self.q.get().strip(), f, t, limit, offset)

    def on_show(self):
        self.table.reload(keep_page=True)

    def detail(self, r):
        widgets.text_preview(self, "Audit entry", f"When  : {r['date']}\nUser  : {r['username']}\nAction: {r['action']}\n"
                                                 f"Entity: {r['entity']} {r['entity_id'] or ''}\n\nOLD:\n{r['old_value'] or '-'}\n\nNEW:\n{r['new_value'] or '-'}",
                             width=640, height=420)
