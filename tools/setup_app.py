"""Windows installer / uninstaller for ShopPOS (packaged by PyInstaller as ShopPOS-Setup.exe).

Wizard:   ShopPOS-Setup.exe
Silent:   ShopPOS-Setup.exe --silent [--target DIR] [--data DIR] [--no-shortcuts] [--no-launch]
Remove:   Uninstall.exe --uninstall   (installed alongside the app; also listed in Windows Apps & features)

Installs per user (no administrator rights needed), creates the application data folders, initialises the
database (schema + default Owner account) and adds Start Menu / Desktop shortcuts.
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import zipfile

APP_NAME = "ShopPOS"
EXE_NAME = "ShopPOS.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ShopPOS"
VERSION = "1.0.0"
CREATE_NO_WINDOW = 0x08000000


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def default_target():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "ShopPOS")


def default_data():
    return os.environ.get("SHOPPOS_DATA") or os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ShopPOS")


def start_menu_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME)


def desktop_dir():
    ps = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    return ps.stdout.strip() or os.path.join(os.path.expanduser("~"), "Desktop")


def make_shortcut(path, target, arguments="", workdir="", icon=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{p}');$s.TargetPath='{t}';$s.Arguments='{a}';"
              "$s.WorkingDirectory='{w}';$s.IconLocation='{i}';$s.Save()").format(
        p=path.replace("'", "''"), t=target.replace("'", "''"), a=arguments.replace("'", "''"),
        w=workdir.replace("'", "''"), i=(icon or target).replace("'", "''"))
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, creationflags=CREATE_NO_WINDOW)


def kill_running():
    subprocess.run(["taskkill", "/F", "/IM", EXE_NAME], capture_output=True, creationflags=CREATE_NO_WINDOW)


def install(target, data_dir, shortcuts=True, launch=True, progress=lambda pct, msg: None):
    exe = os.path.join(target, EXE_NAME)
    progress(2, "Closing the application if it is running...")
    kill_running()
    if os.path.isdir(target):
        progress(5, "Removing the previous version...")
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    zpath = resource("payload", "app.zip")
    with zipfile.ZipFile(zpath) as z:
        members = z.infolist()
        for i, m in enumerate(members):
            z.extract(m, target)
            if i % 25 == 0:
                progress(8 + int(72 * i / len(members)), f"Copying files... {i}/{len(members)}")
    progress(82, "Creating data folders...")
    for d in ("", "Backups", "Logs", "Invoices", "Exports", "Images"):
        os.makedirs(os.path.join(data_dir, d), exist_ok=True)
    progress(85, "Initialising the database...")
    env = dict(os.environ, SHOPPOS_DATA=data_dir)
    r = subprocess.run([exe, "--init"], env=env, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("The database could not be initialised.")
    # keep a copy of this program as the uninstaller
    shutil.copyfile(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__),
                    os.path.join(target, "Uninstall.exe" if getattr(sys, "frozen", False) else "uninstall_dev.py"))
    if shortcuts:
        progress(90, "Creating shortcuts...")
        make_shortcut(os.path.join(start_menu_dir(), f"{APP_NAME}.lnk"), exe, workdir=target)
        make_shortcut(os.path.join(desktop_dir(), f"{APP_NAME}.lnk"), exe, workdir=target)
        make_shortcut(os.path.join(start_menu_dir(), f"Uninstall {APP_NAME}.lnk"), os.path.join(target, "Uninstall.exe"),
                      "--uninstall", target, exe)
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            for name, val in (("DisplayName", APP_NAME), ("DisplayVersion", VERSION), ("Publisher", APP_NAME),
                              ("DisplayIcon", exe), ("InstallLocation", target),
                              ("UninstallString", f'"{os.path.join(target, "Uninstall.exe")}" --uninstall')):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    progress(100, "Done")
    if launch:
        subprocess.Popen([exe], cwd=target, env=env)


def uninstall(target, remove_shortcuts=True):
    kill_running()
    if remove_shortcuts:
        shutil.rmtree(start_menu_dir(), ignore_errors=True)
        try:
            os.remove(os.path.join(desktop_dir(), f"{APP_NAME}.lnk"))
        except OSError:
            pass
        try:
            import winreg
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        except OSError:
            pass
    # this program runs from inside the folder being removed: delete it from a detached helper
    subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "{target}"', shell=True, creationflags=CREATE_NO_WINDOW)


def run_gui(args):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} - Setup")
    root.geometry("600x400")
    root.resizable(False, False)
    try:
        root.iconbitmap(resource("assets", "app.ico"))
    except tk.TclError:
        pass
    bg = "#F4F6F9"
    root.configure(bg=bg)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, font=("Segoe UI", 10))
    style.configure("TCheckbutton", background=bg, font=("Segoe UI", 10))
    style.configure("H.TLabel", font=("Segoe UI", 20, "bold"), background="#1E3A5F", foreground="white")
    style.configure("S.TLabel", background="#1E3A5F", foreground="#C9D6E3")
    style.configure("Go.TButton", background="#2E86DE", foreground="white", font=("Segoe UI", 10, "bold"), padding=(18, 8))
    style.map("Go.TButton", background=[("active", "#4A9BEF"), ("disabled", "#B8C2CC")])
    head = tk.Frame(root, bg="#1E3A5F")
    head.pack(fill="x")
    ttk.Label(head, text=APP_NAME, style="H.TLabel").pack(anchor="w", padx=28, pady=(22, 0))
    ttk.Label(head, text=f"Version {VERSION}   -   POS, inventory, warranty & repairs for computer shops", style="S.TLabel").pack(anchor="w", padx=28, pady=(0, 20))
    body = ttk.Frame(root, padding=(28, 20))
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Install to:").pack(anchor="w")
    row = ttk.Frame(body)
    row.pack(fill="x", pady=(2, 12))
    target = tk.StringVar(value=args.target or default_target())
    ttk.Entry(row, textvariable=target, width=58).pack(side="left", fill="x", expand=True)
    ttk.Button(row, text="Browse...", command=lambda: target.set(os.path.normpath(filedialog.askdirectory() or target.get()))).pack(side="left", padx=6)
    sc = tk.BooleanVar(value=True)
    ln = tk.BooleanVar(value=True)
    ttk.Checkbutton(body, text="Create Desktop and Start Menu shortcuts", variable=sc).pack(anchor="w")
    ttk.Checkbutton(body, text="Start the application when setup finishes", variable=ln).pack(anchor="w")
    ttk.Label(body, text="Your shop data is stored separately in %LocalAppData%\\ShopPOS and is never touched by\n"
                         "updates or uninstalling. First sign-in:  admin  /  admin123", foreground="#6B7280").pack(anchor="w", pady=12)
    bar = ttk.Progressbar(body, maximum=100)
    status = ttk.Label(body, text="")
    btn = ttk.Button(body, text="Install", style="Go.TButton")
    btn.pack(anchor="e", side="bottom")

    def progress(p, msg):
        root.after(0, lambda: (bar.configure(value=p), status.configure(text=msg)))

    def work():
        try:
            install(target.get(), default_data(), sc.get(), False, progress)
            root.after(0, lambda: finish(None))
        except Exception as e:  # noqa: BLE001
            root.after(0, lambda: finish(e))

    def finish(err):
        if err:
            messagebox.showerror(APP_NAME, f"Installation failed:\n{err}")
            btn.state(["!disabled"])
            return
        if ln.get():
            subprocess.Popen([os.path.join(target.get(), EXE_NAME)], cwd=target.get(), env=dict(os.environ, SHOPPOS_DATA=default_data()))
        messagebox.showinfo(APP_NAME, "Installation complete.")
        root.destroy()

    def go():
        btn.state(["disabled"])
        bar.pack(fill="x", pady=(0, 4), before=btn)
        status.pack(anchor="w", before=btn)
        threading.Thread(target=work, daemon=True).start()
    btn.configure(command=go)
    root.mainloop()


def run_uninstall_gui():
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    target = os.path.dirname(sys.executable)
    if messagebox.askyesno(f"Uninstall {APP_NAME}", f"Remove {APP_NAME} from this computer?\n\nYour shop data (database, backups, "
                                                     "invoices) is kept in %LocalAppData%\\ShopPOS and will NOT be deleted."):
        uninstall(target)
        messagebox.showinfo(APP_NAME, "The application was removed.")
    root.destroy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--silent", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--target")
    ap.add_argument("--data")
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--no-launch", action="store_true")
    args = ap.parse_args()
    if args.uninstall:
        if args.silent:
            uninstall(args.target or os.path.dirname(sys.executable), not args.no_shortcuts)
        else:
            run_uninstall_gui()
    elif args.silent:
        install(args.target or default_target(), args.data or default_data(), not args.no_shortcuts, not args.no_launch,
                lambda p, m: None)
    else:
        run_gui(args)


if __name__ == "__main__":
    main()
