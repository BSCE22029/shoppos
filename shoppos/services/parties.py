"""Customers, suppliers and their running-balance ledgers."""
from ..util import POSError, now, need, clean, to_float, like, r2
from . import audit
from .auth import require

_TABLE = {"customer": "customers", "supplier": "suppliers"}


def post_ledger(db, party_type, party_id, kind, amount, ref=None, note=None, user=None):
    """Append a ledger row and keep the cached balance in step (both in the caller's transaction).
    customer: +amount = customer owes us more.  supplier: +amount = we owe supplier more."""
    if not db.in_tx:
        raise RuntimeError("post_ledger must run inside a transaction")
    amount = r2(amount)
    db.execute("INSERT INTO ledger(party_type,party_id,date,kind,ref,amount,note,user_id) VALUES(?,?,?,?,?,?,?,?)",
               (party_type, party_id, now(), kind, ref, amount, note, user["id"] if user else None))
    db.execute(f"UPDATE {_TABLE[party_type]} SET balance=ROUND(balance+?,2) WHERE id=?", (amount, party_id))


def ledger(db, party_type, party_id):
    rows = db.q("SELECT * FROM ledger WHERE party_type=? AND party_id=? ORDER BY date,id", (party_type, party_id))
    bal = 0.0
    for r in rows:
        bal = r2(bal + r["amount"])
        r["balance"] = bal
    return rows


def verify_balances(db) -> list:
    out = []
    for pt, tbl in _TABLE.items():
        for r in db.q(f"SELECT id,name,balance,(SELECT COALESCE(SUM(amount),0) FROM ledger "
                      f"WHERE party_type='{pt}' AND party_id={tbl}.id) AS l FROM {tbl}"):
            if abs(r["balance"] - r["l"]) > 0.01:
                out.append(f"{pt} {r['name']}: balance {r['balance']} != ledger {r['l']}")
    return out


# ---------------------------------------------------------------- customers
def _cust_fields(d):
    name = need(d.get("name"), "Customer name")
    limit = to_float(d.get("credit_limit"), "Credit limit")
    return name, limit


def list_customers(db, user, text="", limit=100, offset=0, only_owing=False):
    require(user, "customers.view")
    where, p = ["active=1"], []
    if text:
        where.append("(name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\')")
        p += [like(text)] * 3
    if only_owing:
        where.append("balance>0.005")
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM customers WHERE {w}", p)
    rows = db.q(
        f"SELECT c.*, (SELECT COALESCE(SUM(total),0) FROM sales WHERE customer_id=c.id AND status<>'Cancelled') AS total_purchases,"
        f"(SELECT COALESCE(SUM(paid),0) FROM sales WHERE customer_id=c.id AND status<>'Cancelled') AS total_paid "
        f"FROM customers c WHERE {w} ORDER BY name LIMIT ? OFFSET ?", p + [limit, offset])
    return rows, total


def quick_customers(db, text="", limit=30):
    """Lightweight lookup for POS pickers (no permission needed beyond selling)."""
    if text:
        return db.q("SELECT id,name,phone,balance,credit_limit,store_credit FROM customers WHERE active=1 AND "
                    "(name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\') ORDER BY name LIMIT ?",
                    (like(text), like(text), limit))
    return db.q("SELECT id,name,phone,balance,credit_limit,store_credit FROM customers WHERE active=1 "
                "ORDER BY name LIMIT ?", (limit,))


def get_customer(db, cid):
    return db.one("SELECT * FROM customers WHERE id=?", (cid,))


def save_customer(db, user, d, customer_id=None):
    require(user, "customers.manage")
    name, limit = _cust_fields(d)
    opening = to_float(d.get("opening_balance"), "Opening balance", allow_negative=True)
    vals = (name, clean(d.get("company")), clean(d.get("phone")), clean(d.get("email")),
            clean(d.get("address")), limit, clean(d.get("notes")))
    with db.tx():
        if customer_id is None:
            cid = db.insert(
                "INSERT INTO customers(name,company,phone,email,address,credit_limit,notes,opening_balance,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)", vals + (opening, now()))
            if opening:
                post_ledger(db, "customer", cid, "Opening balance", opening, None, None, user)
            audit.log(db, user, "Customer created", "customer", cid, None, {"name": name})
            return cid
        old = db.one("SELECT * FROM customers WHERE id=?", (customer_id,))
        if not old:
            raise POSError("Customer not found.")
        db.execute("UPDATE customers SET name=?,company=?,phone=?,email=?,address=?,credit_limit=?,notes=? WHERE id=?",
                   vals + (customer_id,))
        audit.log(db, user, "Customer edited", "customer", customer_id,
                  {"name": old["name"], "phone": old["phone"], "credit_limit": old["credit_limit"]},
                  {"name": name, "phone": clean(d.get("phone")), "credit_limit": limit})
        return customer_id


def customer_history(db, user, customer_id):
    require(user, "customers.view")
    return db.q("SELECT id,invoice_no,date,total,paid,credit,status FROM sales WHERE customer_id=? "
                "ORDER BY date DESC, id DESC LIMIT 500", (customer_id,))


def deactivate_customer(db, user, customer_id):
    require(user, "customers.manage")
    c = get_customer(db, customer_id)
    if not c:
        raise POSError("Customer not found.")
    if abs(c["balance"]) > 0.005:
        raise POSError("This customer has an outstanding balance and cannot be removed.")
    with db.tx():
        db.execute("UPDATE customers SET active=0 WHERE id=?", (customer_id,))
        audit.log(db, user, "Customer removed", "customer", customer_id, {"name": c["name"]})


# ---------------------------------------------------------------- suppliers
def list_suppliers(db, user, text="", limit=100, offset=0):
    require(user, "suppliers.manage")
    where, p = ["active=1"], []
    if text:
        where.append("(name LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\')")
        p += [like(text)] * 3
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM suppliers WHERE {w}", p)
    rows = db.q(
        f"SELECT s.*,(SELECT COALESCE(SUM(received_value),0) FROM purchases WHERE supplier_id=s.id AND status<>'Cancelled') AS total_purchases,"
        f"(SELECT COALESCE(SUM(amount),0) FROM purchase_payments WHERE supplier_id=s.id) AS total_payments "
        f"FROM suppliers s WHERE {w} ORDER BY name LIMIT ? OFFSET ?", p + [limit, offset])
    return rows, total


def all_suppliers(db):
    return db.q("SELECT id,name,company FROM suppliers WHERE active=1 ORDER BY name")


def save_supplier(db, user, d, supplier_id=None):
    require(user, "suppliers.manage")
    name = need(d.get("name"), "Supplier name")
    opening = to_float(d.get("opening_balance"), "Opening balance", allow_negative=True)
    vals = (name, clean(d.get("company")), clean(d.get("phone")), clean(d.get("email")),
            clean(d.get("address")), clean(d.get("payment_terms")), clean(d.get("notes")))
    with db.tx():
        if supplier_id is None:
            sid = db.insert(
                "INSERT INTO suppliers(name,company,phone,email,address,payment_terms,notes,opening_balance,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)", vals + (opening, now()))
            if opening:
                post_ledger(db, "supplier", sid, "Opening balance", opening, None, None, user)
            audit.log(db, user, "Supplier created", "supplier", sid, None, {"name": name})
            return sid
        old = db.one("SELECT * FROM suppliers WHERE id=?", (supplier_id,))
        if not old:
            raise POSError("Supplier not found.")
        db.execute("UPDATE suppliers SET name=?,company=?,phone=?,email=?,address=?,payment_terms=?,notes=? WHERE id=?",
                   vals + (supplier_id,))
        audit.log(db, user, "Supplier edited", "supplier", supplier_id,
                  {"name": old["name"], "phone": old["phone"]}, {"name": name, "phone": clean(d.get("phone"))})
        return supplier_id
