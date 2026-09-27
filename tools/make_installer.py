"""Builds dist/ShopPOS-Setup.exe: a self-contained Windows setup wizard (see tools/setup_app.py)
that carries the built application (dist/ShopPOS) as a zip payload. Run via build_exe.bat."""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
APP_DIR = os.path.join(DIST, "ShopPOS")
BUILD = os.path.join(ROOT, "build", "setup")


def main():
    if not os.path.isfile(os.path.join(APP_DIR, "ShopPOS.exe")):
        sys.exit("dist\\ShopPOS\\ShopPOS.exe not found - run build_exe.bat first.")
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(os.path.join(BUILD, "payload"))
    zpath = os.path.join(BUILD, "payload", "app.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _, files in os.walk(APP_DIR):
            for f in files:
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, APP_DIR))
    print(f"payload: {os.path.getsize(zpath) / 1e6:.1f} MB")
    sep = ";"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--name", "ShopPOS-Setup", "--icon", os.path.join(ROOT, "assets", "app.ico"),
           "--add-data", f"{zpath}{sep}payload", "--add-data", f"{os.path.join(ROOT, 'assets')}{sep}assets",
           "--distpath", DIST, "--workpath", os.path.join(BUILD, "work"), "--specpath", BUILD,
           "--exclude-module", "numpy", "--exclude-module", "pandas", "--exclude-module", "matplotlib",
           os.path.join(ROOT, "tools", "setup_app.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    out = os.path.join(DIST, "ShopPOS-Setup.exe")
    print(f"Installer: {out}  ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
