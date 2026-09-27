"""Reusable widgets: DataTable (paged), FormDialog, toast, message helpers."""
import datetime as dt
import tkinter as tk
from tkinter import messagebox, ttk

from ..util import POSError, money, today
from . import theme


# ------------------------------------------------------------------ messages
def show_error(parent, msg, title="Error"):
    messagebox.showerror(title, msg, parent=parent)


def show_warn(parent, msg, title="Please check"):
    messagebox.showwarning(title, msg, parent=parent)


def show_info(parent, msg, title="Information"):
    messagebox.showinfo(title, msg, parent=parent)


def confirm(parent, msg, title="Please confirm", danger=False) -> bool:
    return messagebox.askyesno(title, msg, parent=parent, icon="warning" if danger else "question")


class Toast:
    """Non-blocking notification in the bottom-right corner."""
    _cur = None

    @classmethod
    def show(cls, root, msg, kind="ok", ms=2600):
        if cls._cur is not None:
            try:
                cls._cur.destroy()
            except tk.TclError:
                pass
        c = theme.current
        colour = {"ok": c["success"], "error": c["danger"], "warn": c["warning"], "info": c["accent"]}.get(kind, c["success"])
        mark = {"ok": "✓", "error": "✕", "warn": "!", "info": "i"}.get(kind, "✓")
        t = tk.Toplevel(root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        row = tk.Frame(t, bg=colour)
        row.pack()
        tk.Label(row, text=mark, bg=colour, fg="#FFFFFF", font=(theme.FONT, 12, "bold"), pady=10).pack(side="left", padx=(18, 6))
        tk.Label(row, text=msg, bg=colour, fg="#FFFFFF", font=(theme.FONT, 11, "bold"), pady=10,
                 wraplength=400, justify="left").pack(side="left", padx=(0, 18))
        t.update_idletasks()
        try:
            x = root.winfo_rootx() + root.winfo_width() - t.winfo_width() - 24
            y = root.winfo_rooty() + root.winfo_height() - t.winfo_height() - 44
        except tk.TclError:
            x, y = 100, 100
        t.geometry(f"+{x}+{y}")
        cls._cur = t
        t.after(ms, lambda: t.destroy() if t.winfo_exists() else None)


def add_placeholder(entry, var, text):
    """Grey hint text shown inside an empty, unfocused ttk.Entry."""
    c = theme.current
    hint = tk.Label(entry.master, text=text, fg=c["muted"], bg=c["input"], font=(theme.FONT, 10), bd=0, cursor="xterm")
    hint.bind("<Button-1>", lambda e: entry.focus_set())

    def sync(*_):
        try:
            focused = entry.focus_get() is entry
        except (KeyError, tk.TclError):
            focused = False
        if var.get() or focused:
            hint.place_forget()
        else:
            hint.place(in_=entry, x=9, rely=0.5, anchor="w")
    var.trace_add("write", sync)
    entry.bind("<FocusIn>", lambda e: hint.place_forget())
    entry.bind("<FocusOut>", sync)
    entry.after(60, sync)
    return hint


def fit_tree(tree, keys, widths):
    """Scale Treeview columns so they exactly fill the widget (no sideways scrolling)."""
    try:
        avail = tree.winfo_width() - 4
    except tk.TclError:
        return
    if avail < 120:
        return
    base = [theme.px(w) for w in widths]
    factor = avail / max(sum(base), 1)
    for k, b in zip(keys, base):
        tree.column(k, width=max(int(b * factor), theme.px(46)), stretch=False)


# ------------------------------------------------------------------ table
class DataTable(ttk.Frame):
    """Treeview with server-side pagination.
    columns: [(key, heading, width, anchor, formatter)] (anchor/formatter optional)
    loader(limit, offset) -> (rows, total)"""

    def __init__(self, parent, columns, loader, page_size=50, tag_fn=None, on_open=None, on_select=None,
                 height=14, select_mode="browse", empty_text="No records found."):
        super().__init__(parent)
        self.columns = [self._norm(c) for c in columns]
        self.loader, self.page_size, self.tag_fn = loader, page_size, tag_fn
        self.on_open, self.on_select = on_open, on_select
        self.empty_text = empty_text
        self.page = 0
        self.total = 0
        self.rows = {}
        self._sort = (None, False)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in self.columns], show="headings", height=height,
                                 selectmode=select_mode)
        for key, head, width, anchor, _ in self.columns:
            self.tree.heading(key, text=head, command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=theme.px(40), anchor=anchor, minwidth=theme.px(40), stretch=False)
        vs = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        self._fit_job = None
        self.tree.bind("<Configure>", self._schedule_fit)
        self.after(50, self._fit)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.pager = ttk.Frame(self)
        self.pager.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.lbl = ttk.Label(self.pager, style="Muted.TLabel")
        self.lbl.pack(side="left")
        self.btn_next = ttk.Button(self.pager, text="Next ›", style="Secondary.TButton", command=lambda: self.goto(self.page + 1))
        self.btn_next.pack(side="right")
        self.btn_prev = ttk.Button(self.pager, text="‹ Prev", style="Secondary.TButton", command=lambda: self.goto(self.page - 1))
        self.btn_prev.pack(side="right", padx=(0, 6))
        c = theme.current
        self.tree.tag_configure("alt", background=c["row_alt"])
        self.tree.tag_configure("warn", foreground=c["warning"])
        self.tree.tag_configure("danger", foreground=c["danger"])
        self.tree.tag_configure("muted", foreground=c["muted"])
        self.tree.tag_configure("ok", foreground=c["success"])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select and self.on_select(self.selected()))
        self.tree.bind("<Double-1>", lambda e: self._open())
        self.tree.bind("<Return>", lambda e: self._open())
        self.empty_lbl = ttk.Label(self, text=self.empty_text, style="Muted.TLabel")

    def _schedule_fit(self, _e=None):
        if self._fit_job:
            self.after_cancel(self._fit_job)
        self._fit_job = self.after(30, self._fit)

    def _fit(self):
        """Scale all columns so they always fill the table exactly (no sideways scrolling)."""
        self._fit_job = None
        fit_tree(self.tree, [c[0] for c in self.columns], [c[2] for c in self.columns])

    @staticmethod
    def _norm(c):
        key, head = c[0], c[1]
        width = c[2] if len(c) > 2 else 100
        anchor = c[3] if len(c) > 3 else "w"
        fmt = c[4] if len(c) > 4 else None
        return key, head, width, anchor, fmt

    def _open(self):
        r = self.selected()
        if r and self.on_open:
            self.on_open(r)

    def selected(self):
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def selected_all(self):
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def goto(self, page):
        pages = max((self.total + self.page_size - 1) // self.page_size, 1)
        self.page = min(max(page, 0), pages - 1)
        self.reload(keep_page=True)

    def reload(self, keep_page=False, select_id=None):
        if not keep_page:
            self.page = 0
        prev = self.selected()
        rows, total = self.loader(self.page_size, self.page * self.page_size)
        if total and self.page * self.page_size >= total:
            self.page = max((total - 1) // self.page_size, 0)
            rows, total = self.loader(self.page_size, self.page * self.page_size)
        if rows and total < len(rows):
            total = len(rows)
        self.total = total
        self.set_rows(rows)
        if total == 0:
            self.empty_lbl.place(in_=self.tree, relx=0.5, rely=0.42, anchor="center")
        else:
            self.empty_lbl.place_forget()
        target = select_id if select_id is not None else (prev.get("id") if prev else None)
        if target is not None:
            for iid, r in self.rows.items():
                if r.get("id") == target:
                    self.tree.selection_set(iid)
                    self.tree.see(iid)
                    break
        pages = max((total + self.page_size - 1) // self.page_size, 1)
        self.lbl.configure(text=f"{total:,} record(s)" + (f"   -   page {self.page + 1} of {pages}" if pages > 1 else ""))
        self.btn_prev.state(["!disabled" if self.page > 0 else "disabled"])
        self.btn_next.state(["!disabled" if self.page < pages - 1 else "disabled"])
        if pages <= 1:
            self.btn_prev.pack_forget()
            self.btn_next.pack_forget()
        else:
            self.btn_next.pack(side="right")
            self.btn_prev.pack(side="right", padx=(0, 6))

    def set_rows(self, rows):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        col, rev = self._sort
        if col:
            rows = sorted(rows, key=lambda r: (r.get(col) is None, str(r.get(col)).lower() if isinstance(r.get(col), str) else (r.get(col) or 0)),
                          reverse=rev)
        for i, r in enumerate(rows):
            vals = []
            for key, _, _, _, fmt in self.columns:
                v = r.get(key)
                vals.append(fmt(v, r) if fmt else ("" if v is None else v))
            tags = []
            if i % 2:
                tags.append("alt")
            if self.tag_fn:
                t = self.tag_fn(r)
                if t:
                    tags.append(t)
            iid = self.tree.insert("", "end", values=vals, tags=tags)
            self.rows[iid] = r

    def _sort_by(self, key):
        col, rev = self._sort
        self._sort = (key, not rev if col == key else False)
        self.set_rows(list(self.rows.values()))

    def focus_first(self):
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
            self.tree.focus(kids[0])


def fmt_money(v, r=None):
    return "" if v is None else money(v)


def fmt_int(v, r=None):
    return "" if v is None else f"{int(v):,}"


def fmt_date(v, r=None):
    return (v or "")[:16]


def fmt_yesno(v, r=None):
    return "Yes" if v else "No"


# ------------------------------------------------------------------ dialogs
class Dialog(tk.Toplevel):
    """Modal dialog base: centred, Esc closes, grabs focus."""

    def __init__(self, parent, title, width=None, height=None, resizable=False):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=theme.current["bg"])
        self.transient(parent.winfo_toplevel())
        self.resizable(resizable, resizable)
        self.result = None
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._size = (width, height)

    def show(self):
        self.update_idletasks()
        w, h = self._size
        w = theme.px(w) if w else self.winfo_reqwidth()
        h = theme.px(h) if h else self.winfo_reqheight()
        w = min(w, self.winfo_screenwidth() - 60)
        h = min(h, self.winfo_screenheight() - 100)
        p = self.master.winfo_toplevel()
        x = p.winfo_rootx() + max((p.winfo_width() - w) // 2, 0)
        y = p.winfo_rooty() + max((p.winfo_height() - h) // 3, 0)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.grab_set()
        self.focus_set()
        self.wait_window(self)
        return self.result

    def cancel(self):
        self.result = None
        self.destroy()


class ScrollFrame(ttk.Frame):
    """A frame that scrolls vertically when its content is taller than the space available."""

    def __init__(self, parent, max_height=560):
        super().__init__(parent)
        self.max_height = max_height
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=theme.current["bg"])
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._inner_changed)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _inner_changed(self, _e=None):
        h = self.inner.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), h), width=self.inner.winfo_reqwidth(),
                              height=min(h, self.max_height))
        if h > self.max_height:
            self.vsb.pack(side="right", fill="y", before=self.canvas)
        else:
            self.vsb.pack_forget()

    def _wheel(self, e):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")


def clean_num(v):
    """82000.0 -> '82000', 0.5 -> '0.5' (for editing forms)."""
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return v


class FormDialog(Dialog):
    """Generic form. fields: dicts with key,label,type,choices,required,default,help,width.
    types: text money int date choice check multiline password label."""

    def __init__(self, parent, title, fields, initial=None, on_save=None, columns=1, width=None, save_text="Save"):
        super().__init__(parent, title, width)
        self.fields, self.on_save, self.vars, self.widgets, self.choice_map = fields, on_save, {}, {}, {}
        initial = initial or {}
        foot = ttk.Frame(self, padding=(18, 0, 18, 14))
        foot.pack(side="bottom", fill="x")
        scroll = ScrollFrame(self, max_height=max(self.winfo_screenheight() - 240, 300))
        scroll.pack(side="top", fill="both", expand=True)
        body = scroll.inner
        body.configure(padding=18)
        row = col = 0
        for f in fields:
            t = f.get("type", "text")
            cell = ttk.Frame(body)
            cell.grid(row=row, column=col, sticky="ew", padx=(0, 14), pady=(0, 10))
            body.columnconfigure(col, weight=1)
            if t == "label":
                ttk.Label(cell, text=f["label"], style="Muted.TLabel", wraplength=380).pack(anchor="w")
            elif t == "check":
                v = tk.BooleanVar(value=bool(initial.get(f["key"], f.get("default", False))))
                ttk.Checkbutton(cell, text=f["label"], variable=v).pack(anchor="w")
                self.vars[f["key"]] = v
            else:
                lab = f["label"] + (" *" if f.get("required") else "")
                ttk.Label(cell, text=lab).pack(anchor="w", pady=(0, 3))
                init = clean_num(initial.get(f["key"], f.get("default", "")))
                if t == "choice":
                    ch = f["choices"]() if callable(f["choices"]) else f["choices"]
                    labels = [l for _, l in ch]
                    self.choice_map[f["key"]] = {l: v for v, l in ch}
                    var = tk.StringVar()
                    w = ttk.Combobox(cell, textvariable=var, values=labels, state="readonly", width=f.get("width", 30))
                    for v, l in ch:
                        if v == init:
                            var.set(l)
                    if not var.get() and labels and f.get("required") and init in ("", None):
                        pass
                    w.pack(fill="x")
                    self.vars[f["key"]] = var
                elif t == "multiline":
                    w = tk.Text(cell, height=f.get("height", 3), width=f.get("width", 32), wrap="word", relief="solid", bd=1,
                                font=(theme.FONT, 10), bg=theme.current["input"], fg=theme.current["text"],
                                insertbackground=theme.current["text"])
                    w.insert("1.0", "" if init is None else str(init))
                    w.pack(fill="x")
                    self.vars[f["key"]] = w
                else:
                    var = tk.StringVar(value="" if init is None else str(init))
                    w = ttk.Entry(cell, textvariable=var, width=f.get("width", 32), show="*" if t == "password" else "")
                    w.pack(fill="x")
                    self.vars[f["key"]] = var
                    if f.get("readonly"):
                        w.state(["disabled"])
                self.widgets[f["key"]] = w
                if f.get("help"):
                    ttk.Label(cell, text=f["help"], style="Muted.TLabel", font=(theme.FONT, 8)).pack(anchor="w")
            col += 1
            if col >= columns or f.get("full"):
                col = 0
                row += 1
        self.err = ttk.Label(foot, text="", style="Danger.TLabel", wraplength=560, justify="left")
        self.err.pack(anchor="w")
        bar = ttk.Frame(foot)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="Cancel", style="Secondary.TButton", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text=save_text, style="Primary.TButton", command=self.save).pack(side="right")
        self.bind("<Return>", self._enter)
        first = next((self.widgets[f["key"]] for f in fields if f["key"] in self.widgets and not f.get("readonly")), None)
        if first is not None:
            self.after(60, first.focus_set)

    def _enter(self, e):
        if isinstance(e.widget, tk.Text):
            return
        self.save()

    def values(self):
        out = {}
        for f in self.fields:
            k = f["key"] if "key" in f else None
            if k is None or k not in self.vars:
                continue
            v = self.vars[k]
            t = f.get("type", "text")
            if t == "choice":
                out[k] = self.choice_map[k].get(v.get(), None)
            elif t == "multiline":
                out[k] = v.get("1.0", "end").strip()
            elif t == "check":
                out[k] = bool(v.get())
            else:
                out[k] = v.get().strip()
        return out

    def save(self):
        vals = self.values()
        for f in self.fields:
            if f.get("required") and f.get("type") not in ("label", "check") and vals.get(f["key"]) in (None, ""):
                self.err.configure(text=f"{f['label']} is required.")
                return
        if self.on_save:
            try:
                r = self.on_save(vals)
            except POSError as e:
                self.err.configure(text=str(e))
                return
            self.result = r if r is not None else vals
        else:
            self.result = vals
        self.destroy()


def text_preview(parent, title, text, on_print=None, on_save=None, mono=True, width=560, height=620):
    """Read-only monospace preview (receipts, cash report) with optional Print/Save actions."""
    d = Dialog(parent, title, width, height, resizable=True)
    bar = ttk.Frame(d, padding=10)
    bar.pack(side="bottom", fill="x")
    ttk.Button(bar, text="Close", style="Secondary.TButton", command=d.destroy).pack(side="right")
    if on_print:
        ttk.Button(bar, text="Print", style="Primary.TButton", command=on_print).pack(side="right", padx=8)
    if on_save:
        ttk.Button(bar, text="Save as...", style="Secondary.TButton", command=on_save).pack(side="right")
    box = tk.Text(d, wrap="none", font=("Consolas", 10) if mono else (theme.FONT, 10), relief="flat", padx=14, pady=12,
                  bg="#FFFFFF", fg="#111111")
    box.insert("1.0", text)
    box.configure(state="disabled")
    box.pack(fill="both", expand=True)
    d.show()


def labeled_entry(parent, label, var=None, width=18, **kw):
    f = ttk.Frame(parent)
    ttk.Label(f, text=label, style="Muted.TLabel").pack(anchor="w")
    var = var or tk.StringVar()
    e = ttk.Entry(f, textvariable=var, width=width, **kw)
    e.pack(fill="x")
    return f, var, e


def date_range_bar(parent, on_change, default_days=30):
    """Two date entries + quick presets; returns (frame, get()->(from,to))."""
    f = ttk.Frame(parent)
    v_from = tk.StringVar(value=(dt.date.today() - dt.timedelta(days=default_days)).strftime("%Y-%m-%d"))
    v_to = tk.StringVar(value=today())
    ttk.Label(f, text="From", style="Muted.TLabel").pack(side="left")
    e1 = ttk.Entry(f, textvariable=v_from, width=11)
    e1.pack(side="left", padx=(4, 8))
    ttk.Label(f, text="To", style="Muted.TLabel").pack(side="left")
    e2 = ttk.Entry(f, textvariable=v_to, width=11)
    e2.pack(side="left", padx=(4, 8))

    def preset(days):
        v_to.set(today())
        v_from.set((dt.date.today() - dt.timedelta(days=days)).strftime("%Y-%m-%d"))
        on_change()

    for lbl, d in (("Today", 0), ("7d", 6), ("30d", 29), ("90d", 89), ("1y", 364)):
        ttk.Button(f, text=lbl, style="Secondary.TButton", width=5, command=lambda d=d: preset(d)).pack(side="left", padx=2)
    for e in (e1, e2):
        e.bind("<Return>", lambda ev: on_change())

    def get():
        return v_from.get().strip() or None, v_to.get().strip() or None
    return f, get
