"""Audit trail."""
import json

from ..util import now, like


def _j(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, default=str, ensure_ascii=False)


def log(db, user, action, entity=None, entity_id=None, old=None, new=None):
    uid = user["id"] if user else None
    uname = user["username"] if user else None
    db.execute(
        "INSERT INTO audit_logs(date,user_id,username,action,entity,entity_id,old_value,new_value) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (now(), uid, uname, action, entity, None if entity_id is None else str(entity_id), _j(old), _j(new)))


def search(db, user, text="", date_from=None, date_to=None, limit=100, offset=0):
    from .auth import require
    require(user, "audit.view")
    where, p = ["1=1"], []
    if text:
        where.append("(action LIKE ? ESCAPE '\\' OR username LIKE ? ESCAPE '\\' OR entity LIKE ? ESCAPE '\\' "
                     "OR entity_id LIKE ? ESCAPE '\\')")
        p += [like(text)] * 4
    if date_from:
        where.append("date >= ?")
        p.append(date_from)
    if date_to:
        where.append("date < date(?, '+1 day')")
        p.append(date_to)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM audit_logs WHERE {w}", p)
    rows = db.q(f"SELECT * FROM audit_logs WHERE {w} ORDER BY id DESC LIMIT ? OFFSET ?", p + [limit, offset])
    return rows, total
