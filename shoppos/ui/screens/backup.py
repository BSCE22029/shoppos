import os
import tkinter as tk
from tkinter import filedialog, ttk

from ...bootstrap import open_database
from ...services import backup, settings
from ...util import POSError
from .. import widgets
from ..base import Screen
from ..widgets import DataTable


class BackupScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Backup & restore", "Protect your shop data. Backups are complete copies of the database.")
        card = ttk.Frame(self, style="Card.TFrame", padding=16)
        card.pack(fill="x")
        ttk.Label(card, text="Backup location", style="CardH.TLabel").grid(row=0, column=0, sticky="w")
        self.folder = tk.StringVar()
        ttk.Entry(card, textvariable=self.folder, width=60).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Button(card, text="Choose folder...", style="Secondary.TButton", command=self.choose).grid(row=1, column=1, padx=8)
        ttk.Label(card, text="Example: D:\\POS Backups   (leave empty for the default folder inside the app data)", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w")
        opts = ttk.Frame(card, style="Surface.TFrame")
        opts.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.freq = tk.StringVar(value="daily")
        ttk.Label(opts, text="Automatic backup", style="Card.TLabel").pack(side="left")
        ttk.Combobox(opts, textvariable=self.freq, values=["daily", "off"], state="readonly", width=8).pack(side="left", padx=8)
        self.on_close = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Also back up when the app closes", variable=self.on_close, style="Card.TCheckbutton").pack(side="left", padx=12)
        self.keep = tk.StringVar(value="30")
        ttk.Label(opts, text="Keep last", style="Card.TLabel").pack(side="left")
        ttk.Entry(opts, textvariable=self.keep, width=5).pack(side="left", padx=6)
        ttk.Label(opts, text="automatic backups", style="Card.TLabel").pack(side="left")
        ttk.Button(opts, text="Save backup settings", style="Secondary.TButton", command=self.save_opts).pack(side="left", padx=14)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=12)
        ttk.Button(bar, text="Back up now", style="Primary.TButton", command=self.now).pack(side="left")
        ttk.Button(bar, text="Restore selected backup", style="Danger.TButton", command=self.restore).pack(side="left", padx=8)
        ttk.Button(bar, text="Restore from a file...", style="Secondary.TButton", command=self.restore_file).pack(side="left")
        ttk.Button(bar, text="Open folder", style="Secondary.TButton", command=self.open_folder).pack(side="right")
        self.table = DataTable(self, [("name", "Backup file", 380), ("date", "Date", 140), ("size", "Size", 90, "e", lambda v, r: f"{v / 1e6:,.1f} MB")],
                               lambda l, o: (self._list()[o:o + l], len(self._list())), page_size=100, height=10)
        self.table.pack(fill="both", expand=True)

    def _list(self):
        return backup.list_backups(self.db)

    def on_show(self):
        self.folder.set(settings.get(self.db, "backup_dir") or "")
        self.freq.set(settings.get(self.db, "backup_frequency") or "daily")
        self.on_close.set(settings.get_bool(self.db, "backup_on_close"))
        self.keep.set(str(settings.get_int(self.db, "backup_keep", 30)))
        self.table.reload()

    def choose(self):
        p = filedialog.askdirectory(parent=self, title="Choose backup folder")
        if p:
            self.folder.set(os.path.normpath(p))

    def save_opts(self):
        with self.guard():
            backup.save_backup_settings(self.db, self.user, self.folder.get().strip(), self.freq.get(), int(float(self.keep.get() or 30)), self.on_close.get())
            self.toast("Backup settings saved")
            self.table.reload()

    def now(self):
        with self.guard():
            path = backup.create_backup(self.db, self.user)
            self.toast(f"Backup created: {os.path.basename(path)}", "ok")
            self.table.reload()

    def open_folder(self):
        with self.guard():
            from ...services import printing
            printing.open_file(backup.backup_dir(self.db))

    def restore(self):
        r = self.table.selected()
        if not r:
            widgets.show_warn(self, "Select a backup from the list first.")
            return
        self._do_restore(r["path"])

    def restore_file(self):
        p = filedialog.askopenfilename(parent=self, title="Choose a backup file", filetypes=[("POS backup", "*.db"), ("All files", "*.*")])
        if p:
            self._do_restore(p)

    def _do_restore(self, path):
        if not widgets.confirm(self, "Restore this backup?\n\nAll data entered since that backup will be replaced. "
                                     "A safety copy of the current data is saved first, and you will be signed out.\n\n" + os.path.basename(path),
                               "Restore backup", danger=True):
            return
        with self.guard():
            dbpath = self.db.path
            safety = backup.restore_backup(self.db, self.user, path)
            self.app.db = open_database(dbpath)
            widgets.show_info(self.app, f"Backup restored.\n\nYour previous data was saved as:\n{safety}\n\nPlease sign in again.")
            self.app.user = None
            self.app.show_login("Database restored. Please sign in.")
