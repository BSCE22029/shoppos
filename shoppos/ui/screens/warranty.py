import tkinter as tk
from tkinter import ttk

from ...services import catalog, warranty
from ...util import POSError
from .. import theme, widgets
from ..base import Screen
from ..widgets import DataTable, Dialog, FormDialog

STATUS_TAG = {"Active": "ok", "Expiring Soon": "warn", "Expired": "danger", "Claimed": "warn", "Replaced": "muted", "Void": "muted"}


class WarrantyScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Warranty", "Look up coverage by serial number, invoice, customer phone or product")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        a = ttk.Frame(nb, padding=12)
        b = ttk.Frame(nb, padding=12)
        nb.add(a, text="  Lookup  ")
        nb.add(b, text="  Claims  ")
        self.nb = nb
        grid = ttk.Frame(a)
        grid.pack(fill="x", pady=(0, 10))
        self.vars = {}
        for i, (k, lbl, w) in enumerate((("serial", "Serial number", 22), ("invoice", "Invoice", 14), ("phone", "Customer phone / name", 20), ("product", "Product", 20))):
            f = ttk.Frame(grid)
            f.pack(side="left", padx=(0, 12))
            ttk.Label(f, text=lbl, style="Muted.TLabel").pack(anchor="w")
            v = tk.StringVar()
            e = ttk.Entry(f, textvariable=v, width=w)
            e.pack()
            e.bind("<Return>", lambda ev: self.table.reload())
            self.vars[k] = v
        f = ttk.Frame(grid)
        f.pack(side="left", padx=(0, 12))
        ttk.Label(f, text="Status", style="Muted.TLabel").pack(anchor="w")
        self.status = tk.StringVar(value="All")
        cb = ttk.Combobox(f, textvariable=self.status, state="readonly", width=14, values=["All", "Active", "Expiring Soon", "Expired", "Claimed", "Replaced"])
        cb.pack()
        cb.bind("<<ComboboxSelected>>", lambda ev: self.table.reload())
        ttk.Button(grid, text="Search", style="Primary.TButton", command=lambda: self.table.reload()).pack(side="left", pady=(16, 0))
        ttk.Button(grid, text="Clear", style="Secondary.TButton", command=self.clear).pack(side="left", padx=6, pady=(16, 0))
        cols = [("product", "Product", 230), ("serial", "Serial number", 160), ("customer", "Customer", 140), ("invoice_no", "Invoice", 100),
                ("sale_date", "Purchased", 90, "w", lambda v, r: (v or "")[:10]), ("start_date", "Start", 90), ("months", "Months", 60, "e"),
                ("expiry_date", "Expires", 90), ("display_status", "Status", 100)]
        self.table = DataTable(a, cols, self._load, page_size=50, tag_fn=lambda r: STATUS_TAG.get(r["display_status"]), on_open=lambda r: self.detail())
        self.table.pack(fill="both", expand=True)
        bb = ttk.Frame(a)
        bb.pack(fill="x", pady=(10, 0))
        ttk.Button(bb, text="Details / history", style="Secondary.TButton", command=self.detail).pack(side="left", padx=(0, 8))
        if self.can("warranty.manage"):
            ttk.Button(bb, text="File a warranty claim", style="Primary.TButton", command=self.claim).pack(side="left")
        # claims tab
        cs = ttk.Frame(b)
        cs.pack(fill="x", pady=(0, 10))
        self.cstatus = tk.StringVar(value="Open")
        cb2 = ttk.Combobox(cs, textvariable=self.cstatus, state="readonly", width=14, values=["All", "Open", "Repaired", "Replaced", "Rejected"])
        cb2.pack(side="left")
        cb2.bind("<<ComboboxSelected>>", lambda ev: self.claims.reload())
        self.claims = DataTable(b, [("id", "Claim #", 70), ("date", "Filed", 130, "w", widgets.fmt_date), ("product", "Product", 220), ("serial", "Serial", 150),
                                    ("customer", "Customer", 130), ("invoice_no", "Invoice", 100), ("issue", "Problem", 220), ("status", "Status", 90),
                                    ("resolution", "Resolution", 200)],
                                lambda l, o: warranty.list_claims(self.db, self.user, None if self.cstatus.get() == "All" else self.cstatus.get(), l, o),
                                page_size=50, tag_fn=lambda r: "warn" if r["status"] == "Open" else None, on_open=lambda r: self.resolve())
        self.claims.pack(fill="both", expand=True)
        if self.can("warranty.manage"):
            ttk.Button(b, text="Resolve selected claim", style="Primary.TButton", command=self.resolve).pack(anchor="w", pady=(10, 0))

    def on_show(self):
        self.table.reload(keep_page=True)
        self.claims.reload(keep_page=True)

    def clear(self):
        for v in self.vars.values():
            v.set("")
        self.status.set("All")
        self.table.reload()

    def _load(self, limit, offset):
        v = {k: x.get().strip() for k, x in self.vars.items()}
        st = None if self.status.get() == "All" else self.status.get()
        return warranty.lookup(self.db, self.user, v["serial"], v["invoice"], v["phone"], v["product"], st, limit, offset)

    def detail(self):
        r = self.table.selected()
        if not r:
            return
        with self.guard():
            w = warranty.get(self.db, r["id"])
            L = [f"Product : {w['product']}", f"Serial  : {w['serial'] or '-'}", f"Customer: {w['customer'] or 'Walk-in'} {w['customer_phone'] or ''}",
                 f"Invoice : {w['invoice_no']}  ({(w['sale_date'] or '')[:10]})", f"Warranty: {w['months']} months  {w['start_date']} -> {w['expiry_date']}",
                 f"Status  : {w['display_status']}", "", "Claims:"]
            if not w["claims"]:
                L.append("  none")
            for c in w["claims"]:
                L.append(f"  #{c['id']} {c['date'][:10]}  {c['status']:<9} {c['issue']}" + (f"  ->  {c['resolution']}" if c["resolution"] else ""))
            widgets.text_preview(self, "Warranty details", "\n".join(L), width=640, height=360)

    def claim(self):
        r = self.table.selected()
        if not r:
            widgets.show_warn(self, "Select the item first.")
            return

        def save(v):
            return {"id": warranty.file_claim(self.db, self.user, r["id"], v["issue"])}
        if FormDialog(self, "File warranty claim", [
                {"key": "l", "type": "label", "label": f"{r['product']}\nSerial: {r['serial'] or '-'}   Expires: {r['expiry_date']}"},
                {"key": "issue", "label": "Describe the problem", "type": "multiline", "required": True, "height": 4, "width": 46}],
                on_save=save, save_text="File claim").show():
            self.toast("Claim filed")
            self.on_show()

    def resolve(self):
        c = self.claims.selected()
        if not c:
            widgets.show_warn(self, "Select a claim first.")
            return
        if c["status"] != "Open":
            widgets.show_info(self, f"This claim is already {c['status']}.\n{c['resolution'] or ''}")
            return
        d = Dialog(self, "Resolve warranty claim", 520, 460)
        ttk.Label(d, text=f"{c['product']}", style="H2.TLabel", wraplength=470).pack(anchor="w", padx=18, pady=(16, 0))
        ttk.Label(d, text=f"Serial {c['serial'] or '-'}   |   {c['issue']}", style="Muted.TLabel", wraplength=470).pack(anchor="w", padx=18)
        outcome = tk.StringVar(value="Repaired")
        for o in ("Repaired", "Replaced", "Rejected"):
            ttk.Radiobutton(d, text={"Repaired": "Repaired in-house / by supplier", "Replaced": "Replace with a new unit from stock",
                                     "Rejected": "Rejected (not covered)"}[o], variable=outcome, value=o).pack(anchor="w", padx=18, pady=2)
        ttk.Label(d, text="Resolution notes").pack(anchor="w", padx=18, pady=(10, 2))
        note = tk.StringVar()
        ttk.Entry(d, textvariable=note, width=56).pack(padx=18)
        rep = {"id": None}
        rl = ttk.Label(d, text="", style="Muted.TLabel")

        def pick():
            wr = self.db.one("SELECT wa.product_id, p.name, p.serialized FROM warranty_claims cl JOIN warranties wa ON wa.id=cl.warranty_id "
                             "JOIN products p ON p.id=wa.product_id WHERE cl.id=?", (c["id"],))
            avail = catalog.available_serials(self.db, wr["product_id"])
            if not avail:
                widgets.show_warn(d, "There are no units of this product in stock to use as a replacement.")
                return
            from .pos import SerialPicker
            got = SerialPicker(d, {"name": wr["name"]}, avail).show()
            if got:
                rep["id"] = got[0]["id"]
                rl.configure(text=f"Replacement: {got[0]['serial']}")
        ttk.Button(d, text="Choose replacement serial number...", style="Secondary.TButton", command=pick).pack(anchor="w", padx=18, pady=(10, 0))
        rl.pack(anchor="w", padx=18)
        msg = ttk.Label(d, text="", style="Danger.TLabel", wraplength=470)
        msg.pack(anchor="w", padx=18, pady=6)

        def go():
            try:
                warranty.resolve_claim(self.db, self.user, c["id"], outcome.get(), note.get(), rep["id"])
            except POSError as e:
                msg.configure(text=str(e))
                return
            d.result = True
            d.destroy()
        bar = ttk.Frame(d)
        bar.pack(side="bottom", fill="x", padx=18, pady=16)
        ttk.Button(bar, text="Cancel", style="Secondary.TButton", command=d.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Save resolution", style="Primary.TButton", command=go).pack(side="right")
        if d.show():
            self.toast("Claim resolved")
            self.on_show()
