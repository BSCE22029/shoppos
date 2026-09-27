"""Main application window: login, navigation shell, session timeout, error handling."""
import json
import logging
import os
import time
import tkinter as tk
import traceback
from contextlib import contextmanager
from tkinter import ttk

from .. import config
from ..bootstrap import open_database
from ..services import auth, backup, demo, finance, settings
from ..util import POSError
from . import theme, widgets
from .screens import (audit, backup as backup_screen, cashregister, customers, dashboard, expenses, inventory, pos,
                      products, purchases, reports, repairs, returns, sales, settings as settings_screen, suppliers,
                      users, warranty)

log = logging.getLogger("shoppos")

NAV = [  # key, label, permission, class, group
    ("dashboard", "Dashboard", None, dashboard.DashboardScreen, "OVERVIEW"),
    ("pos", "POS", "pos.sell", pos.PosScreen, "SELL"),
    ("sales", "Sales", "sales.view", sales.SalesScreen, "SELL"),
    ("returns", "Returns", "returns.process", returns.ReturnsScreen, "SELL"),
    ("products", "Products", "products.view", products.ProductsScreen, "CATALOGUE & STOCK"),
    ("inventory", "Inventory", "inventory.view", inventory.InventoryScreen, "CATALOGUE & STOCK"),
    ("purchases", "Purchases", "purchases.manage", purchases.PurchasesScreen, "CATALOGUE & STOCK"),
    ("warranty", "Warranty", "warranty.view", warranty.WarrantyScreen, "SERVICE"),
    ("repairs", "Repairs", "repairs.view", repairs.RepairsScreen, "SERVICE"),
    ("suppliers", "Suppliers", "suppliers.manage", suppliers.SuppliersScreen, "PARTNERS"),
    ("customers", "Customers", "customers.view", customers.CustomersScreen, "PARTNERS"),
    ("expenses", "Expenses", "expenses.manage", expenses.ExpensesScreen, "MONEY"),
    ("cash", "Cash Register", "cash.manage", cashregister.CashRegisterScreen, "MONEY"),
    ("reports", "Reports", "reports.view", reports.ReportsScreen, "MONEY"),
    ("users", "Users", "users.manage", users.UsersScreen, "ADMIN"),
    ("audit", "Audit Log", "audit.view", audit.AuditScreen, "ADMIN"),
    ("settings", "Settings", "settings.manage", settings_screen.SettingsScreen, "ADMIN"),
    ("backup", "Backup & Restore", "backup.manage", backup_screen.BackupScreen, "ADMIN"),
]


class App(tk.Tk):
    def __init__(self, db_path=None):
        super().__init__()
        self.paths = config.ensure_dirs()
        self.db = open_database(db_path or self.paths["db"])
        self.user = None
        self.screens, self.nav_buttons, self.current = {}, {}, None
        self.last_activity = time.time()
        self.title(config.APP_NAME)
        self.geometry("1360x780")
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.theme_name = settings.get(self.db, "theme") or "light"
        theme.apply(self, self.theme_name)
        self.minsize(theme.px(1100), theme.px(660))
        self.report_callback_exception = self._on_exception
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        for ev in ("<Any-KeyPress>", "<Any-ButtonPress>", "<Motion>"):
            self.bind_all(ev, self._activity, add="+")
        self.after(15000, self._idle_check)
        backup.auto_backup_if_due(self.db)
        self.show_login()

    # ---------------------------------------------------------------- helpers
    def toast(self, msg, kind="ok"):
        widgets.Toast.show(self, msg, kind)

    @contextmanager
    def guard(self):
        """Turn business-rule errors into friendly messages; log unexpected ones."""
        try:
            yield
        except POSError as e:
            widgets.show_warn(self, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("Unexpected error")
            widgets.show_error(self, "Something went wrong and the action was not completed.\n\n"
                                     f"({type(e).__name__}) The details were saved to the log file.")

    def _on_exception(self, exc, val, tb):
        if isinstance(val, POSError):
            widgets.show_warn(self, str(val))
            return
        log.error("Unhandled UI error\n%s", "".join(traceback.format_exception(exc, val, tb)))
        widgets.show_error(self, "Something went wrong. The problem was saved to the log file and the app is still running.")

    def refresh_user(self):
        self.user = auth.refresh_user(self.db, self.user)

    def _activity(self, _e=None):
        self.last_activity = time.time()

    def _idle_check(self):
        try:
            if self.user:
                mins = settings.get_int(self.db, "session_timeout_min", 15)
                if mins > 0 and time.time() - self.last_activity > mins * 60:
                    self.logout("Signed out after being idle.")
        finally:
            self.after(15000, self._idle_check)

    # ---------------------------------------------------------------- login
    def _clear(self):
        for w in list(self.winfo_children()):
            if isinstance(w, tk.Toplevel):
                w.destroy()
        for w in list(self.winfo_children()):
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.screens, self.nav_buttons, self.current = {}, {}, None

    def _prefs(self):
        try:
            with open(os.path.join(self.paths["base"], "prefs.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_prefs(self, d):
        try:
            with open(os.path.join(self.paths["base"], "prefs.json"), "w", encoding="utf-8") as f:
                json.dump(d, f)
        except OSError:
            pass

    def show_login(self, message=None):
        self._clear()
        c = theme.current
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)
        left = tk.Frame(root, bg=c["primary"] if self.theme_name == "light" else c["sidebar"], width=theme.px(470))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        shop = settings.get(self.db, "shop_name")
        tk.Label(left, text=shop, bg=left["bg"], fg="#FFFFFF" if self.theme_name == "light" else c["text"],
                 font=(theme.FONT, 26, "bold"), wraplength=400, justify="left").pack(anchor="w", padx=48, pady=(150, 6))
        tk.Label(left, text="Point of Sale, Inventory, Warranty & Repairs", bg=left["bg"], fg=c["sidebar_text"],
                 font=(theme.FONT, 12), wraplength=380, justify="left").pack(anchor="w", padx=48)
        tk.Label(left, text="Works fully offline.\nYour data stays on this computer.", bg=left["bg"], fg=c["sidebar_text"],
                 font=(theme.FONT, 10), justify="left").pack(anchor="w", padx=48, pady=(30, 0))
        card = ttk.Frame(root)
        card.place(relx=0.68, rely=0.5, anchor="center")
        ttk.Label(card, text="Sign in", style="H1.TLabel").pack(anchor="w")
        ttk.Label(card, text="Enter your username and password", style="Muted.TLabel").pack(anchor="w", pady=(0, 18))
        prefs = self._prefs()
        uv = tk.StringVar(value=prefs.get("username", ""))
        pv = tk.StringVar()
        rv = tk.BooleanVar(value=bool(prefs.get("username")))
        ttk.Label(card, text="Username").pack(anchor="w")
        ue = ttk.Entry(card, textvariable=uv, width=34, style="Big.TEntry")
        ue.pack(pady=(2, 12))
        ttk.Label(card, text="Password").pack(anchor="w")
        pe = ttk.Entry(card, textvariable=pv, width=34, show="*", style="Big.TEntry")
        pe.pack(pady=(2, 8))
        ttk.Checkbutton(card, text="Remember username", variable=rv).pack(anchor="w")
        err = ttk.Label(card, text=message or "", style="Danger.TLabel", wraplength=340)
        err.pack(anchor="w", pady=(8, 8))

        def do_login(_e=None):
            try:
                u = auth.login(self.db, uv.get(), pv.get())
            except POSError as e:
                err.configure(text=str(e))
                pv.set("")
                pe.focus_set()
                return
            self._save_prefs({"username": uv.get().strip()} if rv.get() else {})
            self.user = u
            self.last_activity = time.time()
            self.show_shell()
            if u["must_change_password"]:
                self.after(300, self.force_password_change)
            else:
                self.after(300, self.first_run_prompts)
        ttk.Button(card, text="Sign In", style="Primary.TButton", command=do_login).pack(fill="x", ipady=6)
        ttk.Label(card, text="First time? Username: admin   Password: admin123", style="Muted.TLabel",
                  font=(theme.FONT, 9)).pack(anchor="w", pady=(14, 0))
        pe.bind("<Return>", do_login)
        ue.bind("<Return>", lambda e: pe.focus_set())
        (pe if uv.get() else ue).focus_set()

    def force_password_change(self):
        while True:
            d = widgets.FormDialog(self, "Change your password", [
                {"key": "label", "type": "label", "label": "For security, choose a new password before you continue."},
                {"key": "old", "label": "Current password", "type": "password", "required": True},
                {"key": "new", "label": "New password (min 6 characters)", "type": "password", "required": True},
                {"key": "new2", "label": "Repeat new password", "type": "password", "required": True}],
                on_save=self._save_new_password, save_text="Change password")
            if d.show():
                self.toast("Password changed")
                break
        self.first_run_prompts()

    def _save_new_password(self, v):
        if v["new"] != v["new2"]:
            raise POSError("The new passwords do not match.")
        auth.change_password(self.db, self.user, v["old"], v["new"])
        self.refresh_user()
        return v

    def first_run_prompts(self):
        if self.user["role"] != "Owner":
            return
        if settings.get(self.db, "demo_prompted") == "1":
            return
        self.db.execute("INSERT INTO settings(key,value) VALUES('demo_prompted','1') "
                        "ON CONFLICT(key) DO UPDATE SET value='1'")
        if self.db.scalar("SELECT COUNT(*) FROM products"):
            return
        if widgets.confirm(self, "Welcome!\n\nWould you like to load DEMO DATA (sample laptops, PCs, parts, customers, "
                                 "sales, repairs) so you can try everything out?\n\nYou can delete it later from "
                                 "Settings > Delete all business data before going live."):
            with self.guard():
                r = demo.load_demo(self.db, self.user)
                self.toast(f"Demo data loaded: {r['products']} products, {r['sales']} sales", "info")
                self.navigate("dashboard")

    # ---------------------------------------------------------------- shell
    def show_shell(self):
        self._clear()
        c = theme.current
        side = ttk.Frame(self, style="Sidebar.TFrame", width=theme.px(228))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        ttk.Label(side, text=settings.get(self.db, "shop_name"), style="Sidebar.TLabel", wraplength=190,
                  justify="left").pack(anchor="w", padx=18, pady=(14, 2))
        ttk.Label(side, text=f"{config.APP_NAME}  v{config.APP_VERSION}", style="SidebarMuted.TLabel").pack(anchor="w", padx=18, pady=(0, 8))
        nav_wrap = ttk.Frame(side, style="Sidebar.TFrame")
        nav_wrap.pack(fill="both", expand=True)
        self.nav_indicators = {}
        last_group = None
        for key, label, perm, _cls, group in NAV:
            if perm and perm not in self.user["permissions"]:
                continue
            if group != last_group:
                ttk.Label(nav_wrap, text=group, style="SidebarCaption.TLabel").pack(fill="x", padx=18,
                          pady=(12 if last_group else 2, 4))
                last_group = group
            row = ttk.Frame(nav_wrap, style="Sidebar.TFrame")
            row.pack(fill="x")
            ind = tk.Frame(row, width=3, bg=theme.current["sidebar"])
            ind.pack(side="left", fill="y")
            b = ttk.Button(row, text=label, style="Nav.TButton", command=lambda k=key: self.navigate(k))
            b.pack(side="left", fill="x", expand=True, padx=(5, 8), pady=1)
            self.nav_buttons[key] = b
            self.nav_indicators[key] = ind
        main = ttk.Frame(self)
        main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(main, style="Top.TFrame", padding=(20, 10))
        top.pack(fill="x")
        self.title_lbl = ttk.Label(top, text="", style="Top.TLabel", foreground=c["muted"])
        self.title_lbl.pack(side="left")
        for text, cmd, style in (("Sign out", lambda: self.logout(), "Secondary"), ("Help (F12)", self.show_shortcuts, "Secondary"),
                                 ("Dark / light", self.toggle_theme, "Secondary"), ("Password", self.change_password, "Secondary")):
            ttk.Button(top, text=text, style=f"{style}.TButton", command=cmd).pack(side="right", padx=(6, 0))
        self.clock = ttk.Label(top, text="", style="Top.TLabel", foreground=c["muted"])
        self.clock.pack(side="right", padx=(0, 16))
        self.reg_lbl = ttk.Label(top, text="", style="Top.TLabel", cursor="hand2")
        self.reg_lbl.pack(side="right", padx=20)
        self.reg_lbl.bind("<Button-1>", lambda e: self.navigate("cash") if "cash" in self.nav_buttons else None)
        ttk.Separator(main).pack(fill="x")
        self.content = ttk.Frame(main, padding=20)
        self.content.pack(fill="both", expand=True)
        self.bind("<F12>", lambda e: self.show_shortcuts())
        self._tick()
        self.navigate("dashboard")

    def _tick(self):
        if not self.user:
            return
        import datetime as dt
        self.clock.configure(text=dt.datetime.now().strftime("%a %d %b %Y   %H:%M"))
        self.after(20000, self._tick)

    def update_register_status(self):
        try:
            r = finance.open_register(self.db)
            if r:
                self.reg_lbl.configure(text=f"● Register open since {r['opened_at'][11:16]}", foreground=theme.current["success"])
            else:
                self.reg_lbl.configure(text="● Register closed", foreground=theme.current["danger"])
        except Exception:  # noqa: BLE001
            pass

    def navigate(self, key):
        entry = next((n for n in NAV if n[0] == key), None)
        if not entry:
            return
        if self.current:
            old = self.screens.get(self.current)
            if old:
                old.on_hide()
                old.pack_forget()
        if key not in self.screens:
            self.screens[key] = entry[3](self.content, self)
        scr = self.screens[key]
        scr.pack(fill="both", expand=True)
        self.current = key
        c = theme.current
        for k, b in self.nav_buttons.items():
            active = k == key
            b.configure(style="NavActive.TButton" if active else "Nav.TButton")
            self.nav_indicators[k].configure(bg=c["accent"] if active else c["sidebar"])
        self.title_lbl.configure(text=f"{self.user['full_name']}  ·  {self.user['role']}")
        self.update_register_status()
        with self.guard():
            scr.on_show()

    # ---------------------------------------------------------------- user actions
    def change_password(self):
        widgets.FormDialog(self, "Change password", [
            {"key": "old", "label": "Current password", "type": "password", "required": True},
            {"key": "new", "label": "New password (min 6 characters)", "type": "password", "required": True},
            {"key": "new2", "label": "Repeat new password", "type": "password", "required": True}],
            on_save=self._save_new_password, save_text="Change password").show()

    def toggle_theme(self):
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.db.execute("INSERT INTO settings(key,value) VALUES('theme',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (self.theme_name,))
        theme.apply(self, self.theme_name)
        cur = self.current
        self.show_shell()
        if cur and cur in self.nav_buttons:
            self.navigate(cur)

    def show_shortcuts(self):
        widgets.text_preview(self, "Keyboard shortcuts", "\n".join([
            "POS screen",
            "  F1   Focus product search / barcode box",
            "  F2   Choose or create customer",
            "  F3   Hold sale",
            "  F4   Take payment / complete sale",
            "  F5   New sale (clear cart)",
            "  F6   Resume a held sale",
            "  Del  Remove selected cart line",
            "  + -  Change quantity of selected line",
            "  Enter  Confirm      Esc  Cancel dialog",
            "",
            "Anywhere",
            "  F12  This help",
            "  Barcode scanners: just scan - the POS search box",
            "  captures the code and adds the product."]), mono=True, width=520, height=420)

    def logout(self, message=None):
        if self.user:
            try:
                auth.logout(self.db, self.user)
            except Exception:  # noqa: BLE001
                pass
        self.user = None
        self.show_login(message)

    def quit_app(self):
        pos_screen = self.screens.get("pos")
        if self.user and pos_screen is not None and getattr(pos_screen, "cart", None):
            if not widgets.confirm(self, "There is an unfinished sale in the POS. Close anyway?", danger=True):
                return
        try:
            backup.backup_on_close(self.db)
        finally:
            self.db.close()
            self.destroy()


def setup_logging():
    from logging.handlers import RotatingFileHandler
    paths = config.ensure_dirs()
    h = RotatingFileHandler(os.path.join(paths["logs"], "app.log"), maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)


def enable_dpi_awareness():
    """Crisp text on high-DPI Windows displays."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def main():
    enable_dpi_awareness()
    setup_logging()
    app = App()
    app.mainloop()
