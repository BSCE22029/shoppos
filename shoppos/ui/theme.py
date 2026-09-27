"""Light / dark themes for ttk."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

PALETTES = {
    "light": dict(bg="#F4F6F9", surface="#FFFFFF", text="#1F2937", muted="#6B7280", border="#DDE2E8",
                  primary="#1E3A5F", accent="#2E86DE", accent_hover="#4A9BEF", success="#1E9E5A", danger="#D64545",
                  warning="#E08E0B", sidebar="#16294A", sidebar_hover="#22406B", sidebar_text="#C9D6E3",
                  row_alt="#F7F9FC", select="#D6E8FB", header="#EDF1F6", input="#FFFFFF"),
    "dark": dict(bg="#0F172A", surface="#1B2436", text="#E5E7EB", muted="#94A3B8", border="#2E3A50",
                 primary="#93C5FD", accent="#3B82F6", accent_hover="#5B9BF8", success="#22B26A", danger="#E5645F",
                 warning="#E9A23B", sidebar="#0A1020", sidebar_hover="#17233C", sidebar_text="#A9B8CE",
                 row_alt="#1F2A3F", select="#27406B", header="#243049", input="#243049"),
}
FONT = "Segoe UI"
current = dict(PALETTES["light"])
current_name = "light"
SCALE = 1.0


def px(n):
    """Scale a pixel size for the display DPI."""
    return int(round(n * SCALE))


def apply(root: tk.Tk, name: str = "light"):
    global current_name, SCALE
    try:
        SCALE = max(root.winfo_fpixels("1i") / 96.0, 1.0)
    except tk.TclError:
        SCALE = 1.0
    current_name = name if name in PALETTES else "light"
    current.clear()
    current.update(PALETTES[current_name])
    c = current
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=c["bg"])
    for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        try:
            tkfont.nametofont(fname).configure(family=FONT, size=10)
        except tk.TclError:
            pass
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
    root.option_add("*TCombobox*Listbox.background", c["input"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
    s.configure(".", background=c["bg"], foreground=c["text"], fieldbackground=c["input"], font=(FONT, 10),
                bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"], troughcolor=c["header"])
    s.configure("TFrame", background=c["bg"])
    s.configure("Card.TFrame", background=c["surface"], relief="solid", borderwidth=1, bordercolor=c["border"])
    s.configure("Surface.TFrame", background=c["surface"])
    s.configure("Sidebar.TFrame", background=c["sidebar"])
    s.configure("Top.TFrame", background=c["surface"])
    s.configure("TLabel", background=c["bg"], foreground=c["text"])
    s.configure("Surface.TLabel", background=c["surface"])
    s.configure("Card.TLabel", background=c["surface"], foreground=c["text"])
    s.configure("Muted.TLabel", foreground=c["muted"])
    s.configure("CardMuted.TLabel", background=c["surface"], foreground=c["muted"])
    s.configure("H1.TLabel", font=(FONT, 18, "bold"))
    s.configure("H2.TLabel", font=(FONT, 13, "bold"))
    s.configure("CardH.TLabel", background=c["surface"], font=(FONT, 11, "bold"))
    s.configure("Big.TLabel", background=c["surface"], font=(FONT, 22, "bold"))
    s.configure("Mid.TLabel", background=c["surface"], font=(FONT, 15, "bold"))
    s.configure("Total.TLabel", background=c["surface"], font=(FONT, 26, "bold"), foreground=c["accent"])
    s.configure("Danger.TLabel", foreground=c["danger"])
    s.configure("CardDanger.TLabel", background=c["surface"], foreground=c["danger"])
    s.configure("Sidebar.TLabel", background=c["sidebar"], foreground="#FFFFFF", font=(FONT, 13, "bold"))
    s.configure("Mini.TButton", background=c["sidebar_hover"], foreground=c["sidebar_text"], padding=(4, 4), borderwidth=0,
                font=(FONT, 9))
    s.map("Mini.TButton", background=[("active", c["accent"])], foreground=[("active", "#FFFFFF")])
    s.configure("SidebarMuted.TLabel", background=c["sidebar"], foreground=c["sidebar_text"], font=(FONT, 9))
    s.configure("SidebarCaption.TLabel", background=c["sidebar"], foreground=c["sidebar_text"], font=(FONT, 8, "bold"))
    s.configure("Top.TLabel", background=c["surface"])
    s.configure("TCheckbutton", background=c["bg"])
    s.configure("Card.TCheckbutton", background=c["surface"])
    s.configure("TRadiobutton", background=c["bg"])
    for name_, bg, hover, fg in (("Primary", c["accent"], c["accent_hover"], "#FFFFFF"),
                                 ("Success", c["success"], c["success"], "#FFFFFF"),
                                 ("Danger", c["danger"], c["danger"], "#FFFFFF"),
                                 ("Secondary", c["header"], c["border"], c["text"])):
        s.configure(f"{name_}.TButton", background=bg, foreground=fg, padding=(14, 7), borderwidth=0, focusthickness=0,
                    font=(FONT, 10, "bold" if name_ != "Secondary" else "normal"))
        s.map(f"{name_}.TButton", background=[("disabled", c["border"]), ("active", hover)],
              foreground=[("disabled", c["muted"])])
    s.configure("Big.Success.TButton", padding=(18, 14), font=(FONT, 13, "bold"), background=c["success"], foreground="#FFFFFF",
                borderwidth=0)
    s.map("Big.Success.TButton", background=[("disabled", c["border"]), ("active", c["success"])])
    s.configure("Nav.TButton", background=c["sidebar"], foreground=c["sidebar_text"], padding=(16, 5), anchor="w",
                borderwidth=0, font=(FONT, 10))
    s.map("Nav.TButton", background=[("active", c["sidebar_hover"])], foreground=[("active", "#FFFFFF")])
    s.configure("NavActive.TButton", background=c["accent"], foreground="#FFFFFF", padding=(16, 5), anchor="w",
                borderwidth=0, font=(FONT, 10, "bold"))
    s.map("NavActive.TButton", background=[("active", c["accent"])])
    s.configure("TEntry", padding=6, fieldbackground=c["input"], foreground=c["text"], bordercolor=c["border"])
    s.configure("Big.TEntry", padding=10, font=(FONT, 14))
    s.configure("TCombobox", padding=5, fieldbackground=c["input"], foreground=c["text"], arrowcolor=c["text"])
    s.map("TCombobox", fieldbackground=[("readonly", c["input"])], foreground=[("readonly", c["text"])])
    s.configure("Treeview", rowheight=px(27), background=c["surface"], fieldbackground=c["surface"], foreground=c["text"],
                bordercolor=c["border"], borderwidth=1, font=(FONT, 10))
    s.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["text"])])
    s.configure("Treeview.Heading", background=c["header"], foreground=c["text"], padding=(8, 7), font=(FONT, 9, "bold"),
                relief="flat", borderwidth=0)
    s.map("Treeview.Heading", background=[("active", c["border"])])
    s.configure("TNotebook", background=c["bg"], borderwidth=0)
    s.configure("TNotebook.Tab", padding=(16, 8), background=c["header"], foreground=c["text"])
    s.map("TNotebook.Tab", background=[("selected", c["surface"])], foreground=[("selected", c["accent"])])
    s.configure("Vertical.TScrollbar", background=c["header"], troughcolor=c["bg"], arrowcolor=c["muted"])
    s.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])
    s.configure("TLabelframe.Label", background=c["bg"], foreground=c["muted"], font=(FONT, 9, "bold"))
    s.configure("TSeparator", background=c["border"])
    return s
