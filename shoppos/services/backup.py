"""Backup and restore of the SQLite database."""
import datetime as dt
import glob
import os
import sqlite3

from ..config import ensure_dirs
from ..util import POSError, now, today
from . import audit, settings
from .auth import require


def backup_dir(db) -> str:
    d = settings.get(db, "backup_dir") or ensure_dirs()["backups"]
    os.makedirs(d, exist_ok=True)
    return d


def _verify(path):
    con = sqlite3.connect(path)
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        has = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('settings','products','sales')").fetchone()[0]
    finally:
        con.close()
    if ok != "ok" or has < 3:
        raise POSError("This file is not a valid ShopPOS backup.")


def create_backup(db, user=None, reason="manual", dest_dir=None, overwrite=False):
    """Consistent online snapshot. Never overwrites an existing backup unless overwrite=True."""
    if reason == "manual":
        require(user, "backup.manage")
    d = dest_dir or backup_dir(db)
    os.makedirs(d, exist_ok=True)
    name = f"pos-backup-{dt.datetime.now():%Y%m%d-%H%M%S}-{reason}.db"
    path = os.path.join(d, name)
    if os.path.exists(path) and not overwrite:
        raise POSError("A backup with this name already exists. It was not overwritten.")
    db.backup_to(path)
    _verify(path)
    if user:
        audit.log(db, user, "Backup created", "backup", name, None, {"path": path})
    if reason in ("auto", "close"):
        _prune(db, d)
    return path


def _prune(db, d):
    keep = max(settings.get_int(db, "backup_keep", 30), 3)
    files = sorted(glob.glob(os.path.join(d, "pos-backup-*-auto.db")) + glob.glob(os.path.join(d, "pos-backup-*-close.db")))
    for f in files[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


def list_backups(db, dest_dir=None):
    d = dest_dir or backup_dir(db)
    out = []
    for f in sorted(glob.glob(os.path.join(d, "pos-*.db")), reverse=True):
        st = os.stat(f)
        out.append({"path": f, "name": os.path.basename(f), "size": st.st_size,
                    "date": dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out


def auto_backup_if_due(db):
    """Called at startup: one automatic backup per day when frequency is 'daily'."""
    if settings.get(db, "backup_frequency") != "daily":
        return None
    d = backup_dir(db)
    stamp = dt.datetime.now().strftime("%Y%m%d")
    if glob.glob(os.path.join(d, f"pos-backup-{stamp}-*-auto.db")):
        return None
    try:
        return create_backup(db, None, "auto")
    except (POSError, OSError, sqlite3.Error):
        return None


def backup_on_close(db):
    if settings.get_bool(db, "backup_on_close"):
        try:
            return create_backup(db, None, "close")
        except (POSError, OSError, sqlite3.Error):
            return None
    return None


def restore_backup(db, user, backup_file):
    """Replace the live database with a backup. The current data is first saved as a
    'pre-restore' backup. Caller must reopen the database afterwards."""
    require(user, "backup.manage")
    if not os.path.isfile(backup_file):
        raise POSError("Backup file not found.")
    _verify(backup_file)
    path = db.path
    safety = create_backup(db, user, "pre-restore")
    db.close()
    src = sqlite3.connect(backup_file)
    dest = sqlite3.connect(path)
    try:
        src.backup(dest)
    finally:
        src.close()
        dest.close()
    for ext in ("-wal", "-shm"):
        try:
            os.remove(path + ext)
        except OSError:
            pass
    return safety


def save_backup_settings(db, user, folder, frequency, keep, on_close):
    require(user, "backup.manage")
    if frequency not in ("daily", "off"):
        raise POSError("Invalid backup frequency.")
    if folder:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write-test")
        try:
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
        except OSError:
            raise POSError("That folder is not writable. Choose another backup location.")
    vals = {"backup_dir": folder or "", "backup_frequency": frequency, "backup_keep": str(int(keep)),
            "backup_on_close": "1" if on_close else "0"}
    with db.tx():
        for k, v in vals.items():
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        audit.log(db, user, "Backup settings changed", "settings", None, None, vals)
