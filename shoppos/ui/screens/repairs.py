import os
import tkinter as tk
from tkinter import ttk

from ...services import auth, catalog, parties, printing, repairs, settings
from ...util import POSError, money, to_float, to_int
from .. import theme, widgets
from ..base import Screen
from ..pickers import ProductPicker
from ..widgets import DataTable, Dialog, FormDialog
from .pos import PayDialog, SerialPicker

STATUS_TAG = {"Ready": "ok", "Waiting for Parts": "warn", "Waiting for Customer": "warn", "Delivered": "muted", "Cancelled": "muted"}


def staff_choices(db):
    return [(None, "(unassigned)")] + [(u["id"], f"{u['full_name']} ({u['role']})") for u in auth.list_staff(db)]


class TicketDialog(Dialog):
    """Everything about one repair ticket."""

    def __init__(self, parent, app, repair_id):
        super().__init__(parent, "Repair ticket", 960, 640, resizable=True)
        self.app, self.rid = app, repair_id
        self.head = ttk.Label(self, text="", style="H1.TLabel")
        self.head.pack(anchor="w", padx=18, pady=(14, 0))
        self.sub = ttk.Label(self, text="", style="Muted.TLabel", wraplength=880)
        self.sub.pack(anchor="w", padx=18)
        row = ttk.Frame(self, padding=(18, 10, 18, 0))
        row.pack(fill="x")
        self.status = tk.StringVar()
        ttk.Label(row, text="Status").pack(side="left")
        self.cb = ttk.Combobox(row, textvariable=self.status, state="readonly", width=22, values=[s for s in repairs.STATUSES if s != "Delivered"])
        self.cb.pack(side="left", padx=8)
        self.snote = tk.StringVar()
        ttk.Entry(row, textvariable=self.snote, width=34).pack(side="left")
        ttk.Label(row, text="(note, optional)", style="Muted.TLabel").pack(side="left", padx=4)
        ttk.Button(row, text="Update status", style="Primary.TButton", command=self.set_status).pack(side="left", padx=8)
        self.deliver_btn = ttk.Button(row, text="Deliver + collect payment", style="Success.TButton", command=self.deliver)
        self.deliver_btn.pack(side="right")
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        ttk.Label(left, text="Parts used (deducted from stock)", style="H2.TLabel").pack(anchor="w")
        self.parts = ttk.Treeview(left, columns=("name", "qty", "price", "total"), show="headings", height=5)
        _pc = (("name", "Part", 240, "w"), ("qty", "Qty", 50, "e"), ("price", "Price", 90, "e"), ("total", "Total", 100, "e"))
        for k, t, w, a in _pc:
            self.parts.heading(k, text=t)
            self.parts.column(k, width=theme.px(40), anchor=a, stretch=False)
        self.parts.bind("<Configure>", lambda e: widgets.fit_tree(self.parts, [c[0] for c in _pc], [c[2] for c in _pc]))
        self.parts.pack(fill="x", pady=6)
        pb = ttk.Frame(left)
        pb.pack(fill="x")
        ttk.Button(pb, text="+ Add part", style="Secondary.TButton", command=self.add_part).pack(side="left")
        ttk.Button(pb, text="Remove part", style="Secondary.TButton", command=self.remove_part).pack(side="left", padx=8)
        lab = ttk.Frame(left)
        lab.pack(fill="x", pady=10)
        ttk.Label(lab, text="Labor charge").pack(side="left")
        self.labor = tk.StringVar()
        ttk.Entry(lab, textvariable=self.labor, width=12, justify="right").pack(side="left", padx=8)
        ttk.Button(lab, text="Set", style="Secondary.TButton", command=self.set_labor).pack(side="left")
        self.cost = ttk.Label(left, text="", style="H2.TLabel")
        self.cost.pack(anchor="w")
        self.pay_lbl = ttk.Label(left, text="", style="Muted.TLabel")
        self.pay_lbl.pack(anchor="w")
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Technician notes", style="H2.TLabel").pack(anchor="w")
        self.notes = tk.Text(right, height=9, wrap="word", state="disabled", relief="solid", bd=1, font=(theme.FONT, 9),
                             bg=theme.current["surface"], fg=theme.current["text"])
        self.notes.pack(fill="both", expand=True, pady=6)
        nb = ttk.Frame(right)
        nb.pack(fill="x")
        self.new_note = tk.StringVar()
        e = ttk.Entry(nb, textvariable=self.new_note)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda ev: self.add_note())
        ttk.Button(nb, text="Add note", style="Secondary.TButton", command=self.add_note).pack(side="left", padx=(6, 0))
        foot = ttk.Frame(self, padding=(18, 0, 18, 14))
        foot.pack(fill="x")
        ttk.Button(foot, text="Print ticket slip", style="Secondary.TButton", command=self.slip).pack(side="left")
        ttk.Button(foot, text="Close", style="Secondary.TButton", command=self.destroy).pack(side="right")
        self.reload()

    def reload(self):
        r = repairs.get_repair(self.app.db, self.rid)
        self.r = r
        self.head.configure(text=f"{r['ticket_no']}  -  {r['device']} {r['brand'] or ''} {r['model'] or ''}")
        self.sub.configure(text=f"Customer: {r['customer_name']} {r['customer_phone'] or ''}   |   Received {r['received_at'][:16]}   |   "
                                f"Technician: {r['technician'] or '-'}   |   Serial: {r['serial'] or '-'}\nComplaint: {r['complaint']}")
        self.status.set(r["status"] if r["status"] != "Delivered" else "")
        closed = r["status"] in ("Delivered", "Cancelled")
        self.cb.configure(state="disabled" if closed else "readonly")
        self.deliver_btn.state(["!disabled" if r["status"] == "Ready" else "disabled"])
        self.parts.delete(*self.parts.get_children())
        self.part_rows = r["parts"]
        for p in r["parts"]:
            self.parts.insert("", "end", values=(p["name"], p["qty"], money(p["unit_price"]), money(p["qty"] * p["unit_price"])))
        self.labor.set(f"{r['labor_charge']:.2f}".rstrip("0").rstrip("."))
        self.cost.configure(text=f"Total cost: {money(r['final_cost'], settings.get(self.app.db, 'currency'))}   (estimate {money(r['estimated_cost'])})")
        self.pay_lbl.configure(text=f"Paid {money(r['paid'])}   |   Status: {r['status']}")
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        for n in r["notes"]:
            self.notes.insert("end", f"{n['date'][:16]}  {n['username'] or ''}\n  {n['note']}\n\n")
        self.notes.configure(state="disabled")

    def set_status(self):
        with self.app.guard():
            repairs.set_status(self.app.db, self.app.user, self.rid, self.status.get(), self.snote.get().strip() or None)
            self.snote.set("")
            self.reload()

    def set_labor(self):
        with self.app.guard():
            repairs.set_labor(self.app.db, self.app.user, self.rid, self.labor.get())
            self.reload()

    def add_note(self):
        if self.new_note.get().strip():
            with self.app.guard():
                repairs.add_note(self.app.db, self.app.user, self.rid, self.new_note.get())
                self.new_note.set("")
                self.reload()

    def add_part(self):
        with self.app.guard():
            p = ProductPicker(self, self.app, "Choose part", in_stock_only=True).show()
            if not p:
                return
            serial_id, qty = None, 1
            if p["serialized"]:
                avail = catalog.available_serials(self.app.db, p["id"])
                got = SerialPicker(self, p, avail).show()
                if not got:
                    return
                serial_id = got[0]["id"]
            else:
                r = FormDialog(self, "Quantity", [{"key": "q", "label": f"Quantity of {p['name']} (in stock: {p['stock']})", "type": "int", "required": True, "default": "1"}]).show()
                if not r:
                    return
                qty = to_int(r["q"])
            repairs.add_part(self.app.db, self.app.user, self.rid, p["id"], qty, None, serial_id)
            self.reload()

    def remove_part(self):
        sel = self.parts.selection()
        if sel and widgets.confirm(self, "Remove this part and return it to stock?"):
            with self.app.guard():
                repairs.remove_part(self.app.db, self.app.user, self.part_rows[self.parts.index(sel[0])]["id"])
                self.reload()

    def deliver(self):
        with self.app.guard():
            r = self.r
            cust = parties.get_customer(self.app.db, r["customer_id"]) if r["customer_id"] else None
            due = r["final_cost"] - r["paid"]
            if due <= 0:
                res = {"payments": [], "change": 0}
            else:
                res = PayDialog(self, due, cust, settings.get(self.app.db, "currency")).show()
                if not res:
                    return
            repairs.deliver_repair(self.app.db, self.app.user, self.rid, res["payments"])
            self.app.toast("Repair delivered", "ok")
            self.app.update_register_status()
            self.reload()

    def slip(self):
        with self.app.guard():
            text = printing.repair_ticket_text(self.app.db, self.rid)

            def prn():
                path = os.path.join(self.app.paths["invoices"], f"repair-{self.r['ticket_no']}.txt")
                with open(path, "w", encoding="cp1252", errors="replace") as f:
                    f.write(text)
                printing.print_text(path, settings.get(self.app.db, "receipt_printer") or "")
            widgets.text_preview(self, "Repair slip", text, on_print=prn, width=460, height=560)


class RepairsScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        act = self.header("Repairs", "Service tickets from drop-off to delivery")
        if self.can("repairs.manage"):
            ttk.Button(act, text="+ New repair ticket", style="Primary.TButton", command=self.new).pack()
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=30)
        e.pack(side="left")
        widgets.add_placeholder(e, self.q, "Search ticket, customer, phone or device...")
        e.bind("<KeyRelease>", lambda ev: self.table.reload())
        self.status = tk.StringVar(value="Open jobs")
        cb = ttk.Combobox(bar, textvariable=self.status, state="readonly", width=20, values=["Open jobs", "All"] + repairs.STATUSES)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda ev: self.table.reload())
        cols = [("ticket_no", "Ticket", 95), ("received_at", "Received", 120, "w", widgets.fmt_date), ("customer_name", "Customer", 150), ("customer_phone", "Phone", 100),
                ("device", "Device", 140), ("brand", "Brand", 80), ("complaint", "Complaint", 220), ("technician", "Technician", 110), ("status", "Status", 130),
                ("final_cost", "Cost", 90, "e", widgets.fmt_money), ("expected_at", "Expected", 90)]
        self.table = DataTable(self, cols, self._load, page_size=50, on_open=lambda r: self.open(), tag_fn=lambda r: STATUS_TAG.get(r["status"]),
                               empty_text="No repair tickets match this filter.")
        self.table.pack(fill="both", expand=True)
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(10, 0))
        ttk.Button(b, text="Open ticket", style="Primary.TButton", command=self.open).pack(side="left", padx=(0, 8))
        if self.can("repairs.manage"):
            ttk.Button(b, text="Edit details", style="Secondary.TButton", command=self.edit).pack(side="left")

    def _load(self, limit, offset):
        s = self.status.get()
        return repairs.list_repairs(self.db, self.user, self.q.get().strip(), None if s in ("Open jobs", "All") else s, None, s == "Open jobs", limit, offset)

    def on_show(self):
        self.table.reload(keep_page=True)

    def _form(self, r=None):
        cust = [(None, "(walk-in / not saved)")] + [(c["id"], f"{c['name']}  {c['phone'] or ''}") for c in parties.quick_customers(self.db, "", 300)]
        fields = [
            {"key": "customer_id", "label": "Customer", "type": "choice", "choices": cust},
            {"key": "customer_name", "label": "Customer name (if not saved)"}, {"key": "customer_phone", "label": "Phone"},
            {"key": "device", "label": "Device", "required": True, "help": "Laptop, Desktop, Printer..."}, {"key": "brand", "label": "Brand"},
            {"key": "model", "label": "Model"}, {"key": "serial", "label": "Serial number"},
            {"key": "complaint", "label": "Complaint / problem", "type": "multiline", "required": True, "full": True, "width": 60},
            {"key": "condition", "label": "Physical condition", "full": True, "width": 60, "help": "scratches, cracked screen, missing screws..."},
            {"key": "accessories", "label": "Accessories received", "full": True, "width": 60},
            {"key": "technician_id", "label": "Technician", "type": "choice", "choices": staff_choices(self.db)},
            {"key": "estimated_cost", "label": "Estimated cost", "type": "money", "default": "0"},
            {"key": "expected_at", "label": "Expected completion (YYYY-MM-DD)"}]

        def save(v):
            if r:
                repairs.update_repair(self.db, self.user, r["id"], v)
                return {"id": r["id"]}
            return {"id": repairs.create_repair(self.db, self.user, v)}
        return FormDialog(self, "Edit repair" if r else "New repair ticket", fields, r, on_save=save, columns=2, width=780).show()

    def new(self):
        res = self._form()
        if res:
            self.toast("Ticket created - print the slip for the customer", "ok")
            self.table.reload(select_id=res["id"])
            TicketDialog(self, self.app, res["id"]).show()
            self.table.reload(keep_page=True)

    def edit(self):
        r = self.table.selected()
        if r:
            full = repairs.get_repair(self.db, r["id"])
            if self._form(full):
                self.table.reload(keep_page=True)

    def open(self):
        r = self.table.selected()
        if r:
            TicketDialog(self, self.app, r["id"]).show()
            self.table.reload(keep_page=True)
