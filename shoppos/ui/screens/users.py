import tkinter as tk
from tkinter import ttk

from ...config import PERMISSIONS, ROLES
from ...services import auth
from .. import theme, widgets
from ..base import Screen
from ..widgets import DataTable, FormDialog


class UsersScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Users & permissions", "Who can sign in, and what each role is allowed to do")
        ttk.Button(act, text="+ New user", style="Primary.TButton", command=self.new).pack()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        a = ttk.Frame(nb, padding=12)
        b = ttk.Frame(nb, padding=12)
        nb.add(a, text="  Users  ")
        nb.add(b, text="  Role permissions  ")
        cols = [("username", "Username", 130), ("full_name", "Name", 200), ("role", "Role", 140), ("active", "Active", 60, "center", widgets.fmt_yesno),
                ("last_login", "Last login", 140, "w", widgets.fmt_date), ("created_at", "Created", 130, "w", widgets.fmt_date)]
        self.table = DataTable(a, cols, lambda l, o: (auth.list_users(self.db, self.user), 0), page_size=200,
                               tag_fn=lambda r: None if r["active"] else "muted", on_open=lambda r: self.edit())
        self.table.pack(fill="both", expand=True)
        bb = ttk.Frame(a)
        bb.pack(fill="x", pady=(10, 0))
        ttk.Button(bb, text="Edit", style="Secondary.TButton", command=self.edit).pack(side="left", padx=(0, 8))
        ttk.Button(bb, text="Reset password", style="Secondary.TButton", command=self.reset).pack(side="left")
        # permissions tab
        top = ttk.Frame(b)
        top.pack(fill="x")
        ttk.Label(top, text="Role").pack(side="left")
        self.role = tk.StringVar(value=ROLES[3])
        cb = ttk.Combobox(top, textvariable=self.role, values=ROLES, state="readonly", width=22)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self.load_role())
        ttk.Label(top, text="Owner always has every permission.", style="Muted.TLabel").pack(side="left", padx=12)
        ttk.Button(top, text="Save permissions", style="Primary.TButton", command=self.save_role).pack(side="right")
        canvas = tk.Canvas(b, highlightthickness=0, bg=theme.current["bg"])
        sb = ttk.Scrollbar(b, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, pady=10)
        sb.pack(side="right", fill="y", pady=10)
        self.vars = {}
        for i, (k, desc) in enumerate(PERMISSIONS.items()):
            v = tk.BooleanVar()
            ttk.Checkbutton(self.inner, text=f"{desc}", variable=v).grid(row=i // 2, column=i % 2, sticky="w", padx=14, pady=3)
            self.vars[k] = v
        self.load_role()

    def on_show(self):
        self.table.reload(keep_page=True)

    def load_role(self):
        perms = auth.permissions_for(self.db, self.role.get())
        for k, v in self.vars.items():
            v.set(k in perms)

    def save_role(self):
        with self.guard():
            auth.set_role_permissions(self.db, self.user, self.role.get(), [k for k, v in self.vars.items() if v.get()])
            self.toast(f"Permissions saved for {self.role.get()}")
            self.app.refresh_user()

    def new(self):
        def save(v):
            if v["pw"] != v["pw2"]:
                from ...util import POSError
                raise POSError("The passwords do not match.")
            return {"id": auth.create_user(self.db, self.user, v["username"], v["name"], v["pw"], v["role"])}
        r = FormDialog(self, "New user", [
            {"key": "username", "label": "Username", "required": True}, {"key": "name", "label": "Full name", "required": True},
            {"key": "role", "label": "Role", "type": "choice", "choices": [(r_, r_) for r_ in ROLES], "required": True, "default": "Cashier"},
            {"key": "pw", "label": "Password (min 6)", "type": "password", "required": True},
            {"key": "pw2", "label": "Repeat password", "type": "password", "required": True}], on_save=save).show()
        if r:
            self.toast("User created")
            self.table.reload()

    def edit(self):
        u = self.table.selected()
        if not u:
            return

        def save(v):
            auth.update_user(self.db, self.user, u["id"], v["name"], v["role"], v["active"])
            return v
        if FormDialog(self, f"Edit {u['username']}", [
                {"key": "name", "label": "Full name", "required": True, "default": u["full_name"]},
                {"key": "role", "label": "Role", "type": "choice", "choices": [(r_, r_) for r_ in ROLES], "default": u["role"], "required": True},
                {"key": "active", "label": "Account is active", "type": "check", "default": bool(u["active"])}], on_save=save).show():
            self.toast("User updated")
            self.table.reload(keep_page=True)

    def reset(self):
        u = self.table.selected()
        if not u:
            return

        def save(v):
            auth.reset_password(self.db, self.user, u["id"], v["pw"])
            return v
        if FormDialog(self, f"Reset password - {u['username']}", [
                {"key": "pw", "label": "New temporary password (min 6)", "type": "password", "required": True},
                {"key": "l", "type": "label", "label": "The user must choose a new password at next sign-in."}], on_save=save).show():
            self.toast("Password reset")
