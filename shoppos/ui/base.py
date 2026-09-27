"""Base class shared by all screens."""
from tkinter import ttk


class Screen(ttk.Frame):
    title = ""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

    @property
    def db(self):
        return self.app.db

    @property
    def user(self):
        return self.app.user

    def guard(self):
        return self.app.guard()

    def toast(self, msg, kind="ok"):
        self.app.toast(msg, kind)

    def header(self, title, subtitle=None):
        """Title row; returns the frame on the right where action buttons can be packed."""
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 12))
        left = ttk.Frame(bar)
        left.pack(side="left")
        ttk.Label(left, text=title, style="H1.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(left, text=subtitle, style="Muted.TLabel").pack(anchor="w")
        actions = ttk.Frame(bar)
        actions.pack(side="right")
        return actions

    def can(self, perm) -> bool:
        return perm in self.user["permissions"]

    def on_show(self):
        """Called every time the screen is displayed."""

    def on_hide(self):
        """Called when navigating away."""
