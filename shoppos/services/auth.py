"""Users, roles, permissions, password hashing, login."""
import datetime as dt
import hashlib
import hmac
import secrets

from ..config import PERMISSIONS, ROLE_DEFAULTS, ROLES
from ..util import POSError, now, need
from . import audit

MAX_FAILED = 5
LOCK_MINUTES = 5
ITER = 200_000


def hash_password(password: str, salt: str = None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITER).hex()
    return h, salt


def verify_password(password: str, h: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return hmac.compare_digest(calc, h)


def _check_password_policy(pw: str):
    if len(pw or "") < 6:
        raise POSError("Password must be at least 6 characters.")


def ensure_defaults(db):
    """Create roles, default permissions and the initial Owner account."""
    with db.tx():
        for r in ROLES:
            db.execute("INSERT OR IGNORE INTO roles(name,description) VALUES(?,?)", (r, r))
            if not db.scalar("SELECT COUNT(*) FROM role_permissions WHERE role=?", (r,)):
                for p in ROLE_DEFAULTS[r]:
                    db.execute("INSERT OR IGNORE INTO role_permissions(role,permission) VALUES(?,?)", (r, p))
        if not db.scalar("SELECT COUNT(*) FROM users"):
            h, s = hash_password("admin123")
            db.execute(
                "INSERT INTO users(username,full_name,password_hash,salt,role,active,must_change_password,created_at)"
                " VALUES('admin','Shop Owner',?,?,'Owner',1,1,?)", (h, s, now()))


def permissions_for(db, role: str) -> set:
    if role == "Owner":
        return set(PERMISSIONS)
    return {r["permission"] for r in db.q("SELECT permission FROM role_permissions WHERE role=?", (role,))}


def _user_dict(db, row) -> dict:
    return {
        "id": row["id"], "username": row["username"], "full_name": row["full_name"],
        "role": row["role"], "must_change_password": bool(row["must_change_password"]),
        "permissions": permissions_for(db, row["role"]),
    }


def refresh_user(db, user) -> dict:
    row = db.one("SELECT * FROM users WHERE id=?", (user["id"],))
    return _user_dict(db, row)


def has_perm(user, perm: str) -> bool:
    return bool(user) and (perm in user["permissions"])


def require(user, perm: str):
    if not user:
        raise POSError("You must be logged in.")
    if perm not in user["permissions"]:
        raise POSError("You do not have permission to do that.")


def login(db, username: str, password: str) -> dict:
    username = (username or "").strip()
    if not username or not password:
        raise POSError("Enter your username and password.")
    row = db.one("SELECT * FROM users WHERE username=?", (username,))
    if not row:
        raise POSError("Invalid username or password.")
    if not row["active"]:
        raise POSError("This account has been disabled.")
    if row["locked_until"] and row["locked_until"] > now():
        raise POSError(f"Account locked until {row['locked_until'][11:16]} after too many failed attempts.")
    if not verify_password(password, row["password_hash"], row["salt"]):
        fails = row["failed_attempts"] + 1
        locked = None
        if fails >= MAX_FAILED:
            locked = (dt.datetime.now() + dt.timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
            fails = 0
        with db.tx():
            db.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (fails, locked, row["id"]))
            audit.log(db, {"id": row["id"], "username": row["username"]}, "Login failed", "user", row["id"])
        if locked:
            raise POSError(f"Too many failed attempts. Account locked for {LOCK_MINUTES} minutes.")
        raise POSError("Invalid username or password.")
    with db.tx():
        db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? WHERE id=?",
                   (now(), row["id"]))
        u = _user_dict(db, row)
        audit.log(db, u, "User login", "user", row["id"])
    return u


def logout(db, user):
    if user:
        with db.tx():
            audit.log(db, user, "User logout", "user", user["id"])


def change_password(db, user, old: str, new: str):
    row = db.one("SELECT * FROM users WHERE id=?", (user["id"],))
    if not verify_password(old, row["password_hash"], row["salt"]):
        raise POSError("Current password is incorrect.")
    _check_password_policy(new)
    if new == old:
        raise POSError("New password must be different from the current one.")
    h, s = hash_password(new)
    with db.tx():
        db.execute("UPDATE users SET password_hash=?, salt=?, must_change_password=0 WHERE id=?",
                   (h, s, user["id"]))
        audit.log(db, user, "Password changed", "user", user["id"])


def list_users(db, user):
    require(user, "users.manage")
    return db.q("SELECT id,username,full_name,role,active,last_login,created_at FROM users ORDER BY username")


def list_staff(db):
    """Minimal list (no permission needed) for pickers such as technician."""
    return db.q("SELECT id,username,full_name,role FROM users WHERE active=1 ORDER BY full_name")


def create_user(db, user, username, full_name, password, role):
    require(user, "users.manage")
    username = need(username, "Username")
    full_name = need(full_name, "Full name")
    _check_password_policy(password)
    if role not in ROLES:
        raise POSError("Invalid role.")
    if role == "Owner" and user["role"] != "Owner":
        raise POSError("Only an Owner can create another Owner.")
    if db.scalar("SELECT 1 FROM users WHERE username=?", (username,)):
        raise POSError("That username already exists.")
    h, s = hash_password(password)
    with db.tx():
        uid = db.insert("INSERT INTO users(username,full_name,password_hash,salt,role,active,created_at)"
                        " VALUES(?,?,?,?,?,1,?)", (username, full_name, h, s, role, now()))
        audit.log(db, user, "User created", "user", uid, None, {"username": username, "role": role})
    return uid


def update_user(db, user, user_id, full_name, role, active):
    require(user, "users.manage")
    old = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    if not old:
        raise POSError("User not found.")
    if role not in ROLES:
        raise POSError("Invalid role.")
    if (old["role"] == "Owner" or role == "Owner") and user["role"] != "Owner":
        raise POSError("Only an Owner can change Owner accounts.")
    if user_id == user["id"] and not active:
        raise POSError("You cannot disable your own account.")
    if old["role"] == "Owner" and (role != "Owner" or not active):
        others = db.scalar("SELECT COUNT(*) FROM users WHERE role='Owner' AND active=1 AND id<>?", (user_id,))
        if not others:
            raise POSError("There must be at least one active Owner.")
    with db.tx():
        db.execute("UPDATE users SET full_name=?, role=?, active=? WHERE id=?",
                   (need(full_name, "Full name"), role, 1 if active else 0, user_id))
        audit.log(db, user, "User updated", "user", user_id,
                  {"role": old["role"], "active": old["active"]}, {"role": role, "active": int(bool(active))})


def reset_password(db, user, user_id, new_password):
    require(user, "users.manage")
    _check_password_policy(new_password)
    target = db.one("SELECT role FROM users WHERE id=?", (user_id,))
    if not target:
        raise POSError("User not found.")
    if target["role"] == "Owner" and user["role"] != "Owner":
        raise POSError("Only an Owner can reset an Owner's password.")
    h, s = hash_password(new_password)
    with db.tx():
        db.execute("UPDATE users SET password_hash=?, salt=?, must_change_password=1, failed_attempts=0, "
                   "locked_until=NULL WHERE id=?", (h, s, user_id))
        audit.log(db, user, "Password reset", "user", user_id)


def set_role_permissions(db, user, role, perms):
    require(user, "users.manage")
    if role == "Owner":
        raise POSError("Owner permissions cannot be changed.")
    if role not in ROLES:
        raise POSError("Invalid role.")
    bad = [p for p in perms if p not in PERMISSIONS]
    if bad:
        raise POSError(f"Unknown permission: {bad[0]}")
    old = sorted(permissions_for(db, role))
    with db.tx():
        db.execute("DELETE FROM role_permissions WHERE role=?", (role,))
        for p in perms:
            db.execute("INSERT INTO role_permissions(role,permission) VALUES(?,?)", (role, p))
        audit.log(db, user, "Role permissions changed", "role", role, old, sorted(perms))
