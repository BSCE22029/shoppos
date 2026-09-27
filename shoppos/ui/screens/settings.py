import os
import shutil
import tkinter as tk
from tkinter import filedialog, ttk

from ...services import demo, printing, settings
from ...util import POSError
from .. import theme, widgets
from ..base import Screen
from ..widgets import FormDialog

TABS = {
    "Business": [("shop_name", "Shop name", "text"), ("shop_address", "Address", "text"), ("shop_phone", "Phone", "text"),
                 ("shop_email", "Email", "text"), ("tax_number", "Tax number (NTN / STRN)", "text"), ("currency", "Currency", "text"),
                 ("invoice_prefix", "Invoice prefix", "text"), ("receipt_footer", "Receipt footer", "text"), ("terms", "Terms & conditions (on invoices)", "multi"),
                 ("logo_path", "Logo (PNG or JPEG)", "logo")],
    "POS": [("default_tax", "Default tax % for new products", "text"), ("default_discount", "Default discount % for new products", "text"),
            ("invoice_template", "Default invoice type", ("thermal", "a4")), ("auto_print_receipt", "Print receipt automatically after each sale", "check"),
            ("require_open_register", "Require an open cash register for cash payments", "check"), ("label_columns", "Barcode labels per row", "text")],
    "Inventory": [("low_stock_default", "Default low-stock threshold", "text"), ("allow_negative_stock", "Allow selling below zero stock", "check"),
                  ("dead_stock_days", "Dead stock = no sales for (days)", "text"), ("warranty_soon_days", "Warranty 'expiring soon' window (days)", "text")],
    "Hardware": [("receipt_printer", "Receipt printer (80mm thermal)", "printer"), ("a4_printer", "A4 invoice printer", "printer"),
                 ("label_printer", "Barcode label printer", "printer")],
    "Security": [("session_timeout_min", "Sign out after idle minutes (0 = never)", "text")],
}


class SettingsScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Settings", "Shop details, POS behaviour, hardware and data")
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.vars = {}
        printers = None
        for tab, fields in TABS.items():
            f = ttk.Frame(self.nb, padding=20)
            self.nb.add(f, text=f"  {tab}  ")
            for i, (key, label, kind) in enumerate(fields):
                ttk.Label(f, text=label).grid(row=i, column=0, sticky="nw", pady=6, padx=(0, 16))
                if kind == "check":
                    v = tk.BooleanVar()
                    ttk.Checkbutton(f, variable=v).grid(row=i, column=1, sticky="w")
                elif kind == "multi":
                    v = tk.StringVar()
                    w = tk.Text(f, height=3, width=60, wrap="word", relief="solid", bd=1, font=(theme.FONT, 10))
                    w.grid(row=i, column=1, sticky="w")
                    self.vars[key] = ("multi", w)
                    continue
                elif isinstance(kind, tuple):
                    v = tk.StringVar()
                    ttk.Combobox(f, textvariable=v, values=list(kind), state="readonly", width=20).grid(row=i, column=1, sticky="w")
                elif kind == "printer":
                    if printers is None:
                        printers = printing.list_printers()
                    v = tk.StringVar()
                    ttk.Combobox(f, textvariable=v, values=[""] + printers, width=50).grid(row=i, column=1, sticky="w")
                elif kind == "logo":
                    v = tk.StringVar()
                    row = ttk.Frame(f)
                    row.grid(row=i, column=1, sticky="w")
                    ttk.Entry(row, textvariable=v, width=46).pack(side="left")
                    ttk.Button(row, text="Browse...", style="Secondary.TButton", command=self.browse_logo).pack(side="left", padx=6)
                else:
                    v = tk.StringVar()
                    ttk.Entry(f, textvariable=v, width=62 if key in ("shop_address", "receipt_footer") else 30).grid(row=i, column=1, sticky="w")
                self.vars[key] = (kind if kind == "check" else "text", v)
            if tab == "Hardware":
                ttk.Button(f, text="Print a test receipt", style="Secondary.TButton", command=self.test_print).grid(row=len(fields), column=1, sticky="w", pady=12)
                ttk.Label(f, text="Barcode scanners need no setup: they act like a keyboard. Cash drawers connected to the receipt printer "
                                  "open when the printer driver is set to 'open drawer on print'.", style="Muted.TLabel", wraplength=560).grid(
                    row=len(fields) + 1, column=0, columnspan=2, sticky="w")
        data = ttk.Frame(self.nb, padding=20)
        self.nb.add(data, text="  Data  ")
        ttk.Label(data, text="Demo data", style="H2.TLabel").pack(anchor="w")
        ttk.Label(data, text="Fill an empty shop with realistic sample products, customers, sales, repairs and warranty records.",
                  style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(2, 8))
        ttk.Button(data, text="Load demo data", style="Secondary.TButton", command=self.load_demo).pack(anchor="w")
        ttk.Separator(data).pack(fill="x", pady=20)
        ttk.Label(data, text="Delete all business data", style="H2.TLabel").pack(anchor="w")
        ttk.Label(data, text="Removes every product, customer, supplier, sale, purchase, repair and expense so you can start fresh "
                             "(use this to delete the demo data before going live). Users, roles and settings are kept. "
                             "A backup is taken first. Owner only.", style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(2, 8))
        ttk.Button(data, text="Delete all business data...", style="Danger.TButton", command=self.clear).pack(anchor="w")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Save settings", style="Primary.TButton", command=self.save).pack(side="right")

    def on_show(self):
        s = settings.all_settings(self.db)
        for k, (kind, v) in self.vars.items():
            if kind == "multi":
                v.delete("1.0", "end")
                v.insert("1.0", s.get(k, ""))
            elif kind == "check":
                v.set(str(s.get(k, "0")) in ("1", "true", "True"))
            else:
                v.set(s.get(k, ""))

    def _collect(self):
        out = {}
        for k, (kind, v) in self.vars.items():
            out[k] = v.get("1.0", "end").strip() if kind == "multi" else ("1" if v.get() else "0") if kind == "check" else v.get().strip()
        return out

    def save(self):
        with self.guard():
            vals = self._collect()
            for k in ("session_timeout_min", "low_stock_default", "dead_stock_days", "warranty_soon_days", "label_columns"):
                try:
                    int(float(vals[k]))
                except ValueError:
                    raise POSError("Please enter whole numbers in the numeric settings.")
            settings.save(self.db, self.user, vals)
            self.toast("Settings saved")
            self.app.show_shell()
            self.app.navigate("settings")

    def browse_logo(self):
        p = filedialog.askopenfilename(parent=self, filetypes=[("Images", "*.png *.jpg *.jpeg")])
        if not p:
            return
        dest = os.path.join(self.app.paths["images"], "logo" + os.path.splitext(p)[1].lower())
        shutil.copyfile(p, dest)
        self.vars["logo_path"][1].set(dest)

    def test_print(self):
        with self.guard():
            path = os.path.join(self.app.paths["invoices"], "test-receipt.txt")
            with open(path, "w", encoding="cp1252") as f:
                f.write(f"{settings.get(self.db, 'shop_name')}\nTEST RECEIPT\n{'-' * 32}\nIf you can read this,\nthe printer works.\n\n\n")
            printing.print_text(path, self.vars["receipt_printer"][1].get().strip())

    def load_demo(self):
        with self.guard():
            r = demo.load_demo(self.db, self.user)
            self.toast(f"Demo data loaded: {r['products']} products, {r['sales']} sales", "info")

    def clear(self):
        def save(v):
            return {"path": demo.clear_business_data(self.db, self.user, v["c"])}
        r = FormDialog(self, "Delete all business data", [
            {"key": "l", "type": "label", "label": "This permanently deletes all products, customers, suppliers, sales, purchases, repairs "
                                                    "and expenses. A backup is saved first."},
            {"key": "c", "label": "Type DELETE to confirm", "required": True}], on_save=save, save_text="Delete everything").show()
        if r:
            widgets.show_info(self, f"All business data was deleted.\n\nA backup was saved to:\n{r['path']}")
            self.app.show_shell()
