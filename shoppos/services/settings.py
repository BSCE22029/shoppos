"""Key/value settings stored in the database."""
from ..config import DEFAULT_SETTINGS
from ..util import POSError
from . import audit
from .auth import require


def ensure_defaults(db):
    with db.tx():
        for k, v in DEFAULT_SETTINGS.items():
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


def get(db, key, default=None):
    r = db.scalar("SELECT value FROM settings WHERE key=?", (key,))
    if r is None:
        return DEFAULT_SETTINGS.get(key, default)
    return r


def get_bool(db, key) -> bool:
    return str(get(db, key, "0")).strip().lower() in ("1", "true", "yes")


def get_int(db, key, default=0) -> int:
    try:
        return int(float(get(db, key, default)))
    except (TypeError, ValueError):
        return default


def get_float(db, key, default=0.0) -> float:
    try:
        return float(get(db, key, default))
    except (TypeError, ValueError):
        return default


def all_settings(db) -> dict:
    d = dict(DEFAULT_SETTINGS)
    d.update({r["key"]: r["value"] for r in db.q("SELECT key,value FROM settings")})
    return d


def save(db, user, values: dict):
    require(user, "settings.manage")
    old = all_settings(db)
    with db.tx():
        for k, v in values.items():
            if k not in DEFAULT_SETTINGS:
                raise POSError(f"Unknown setting: {k}")
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
        changed = {k: (old.get(k), str(v)) for k, v in values.items() if old.get(k) != str(v)}
        if changed:
            audit.log(db, user, "Settings changed", "settings", None,
                      {k: a for k, (a, b) in changed.items()}, {k: b for k, (a, b) in changed.items()})
