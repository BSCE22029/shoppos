"""Renders the real app window to PNG files for visual review (Win32 PrintWindow; no screen access needed).
Usage: python tests/screenshots.py <outdir> [screen,screen,...]"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
out = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
os.makedirs(out, exist_ok=True)
os.environ["SHOPPOS_DATA"] = tempfile.mkdtemp()
from shoppos.services import auth
auth.ITER = 1000
from shoppos.ui import app as appmod, widgets
appmod.enable_dpi_awareness()
from shoppos.services import demo

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32


def png(path, w, h, bgra):
    raw = bytearray()
    for y in range(h):
        row = bgra[y * w * 4:(y + 1) * w * 4]
        rgb = bytearray(len(row) // 4 * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
        raw += b"\x00" + rgb

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def grab(win, path):
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    w, h = rc.right, rc.bottom
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("x", wt.LONG), ("y", wt.LONG), ("c", wt.DWORD), ("i", wt.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    png(path, w, h, bytes(buf))
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)


app = appmod.App()
for n in ("showerror", "showwarning", "showinfo"):
    setattr(widgets.messagebox, n, lambda *a, **k: None)
widgets.messagebox.askyesno = lambda *a, **k: False


def pump(n=8):
    for _ in range(n):
        app.update_idletasks()
        app.update()


def shot(name, win=None):
    pump()
    path = os.path.join(out, name + ".png")
    grab(win or app, path)
    print("saved", path, flush=True)


def prepare():
    global user
    user = auth.login(app.db, "admin", "admin123")
    app.user = user
    demo.load_demo(app.db, user)
    app.show_shell()
    pump()


def run_pages():
    pump()
    shot("01_login")
    prepare()
    shot("02_dashboard")
    app.navigate("pos")
    pump()
    pos = app.screens["pos"]
    for p in app.db.q("SELECT * FROM products WHERE serialized=0 AND stock>5 ORDER BY id LIMIT 4"):
        pos.q.set(p["barcode"])
        pos.submit()
        pump()
    pos.q.set("logitech")
    pos.search()
    pump()
    shot("03_pos")
    for key in (only or ("products", "inventory", "purchases", "customers", "sales", "returns", "warranty", "repairs", "expenses", "cash", "reports", "users", "audit", "settings", "backup")):
        app.navigate(key)
        pump()
        if key == "reports":
            scr = app.screens["reports"]
            first = scr.tree.get_children()[0]
            scr.tree.selection_set(scr.tree.get_children(first)[0])
            pump()
        shot("04_" + key)
    app.destroy()


if __name__ == "__main__":
    run_pages()
