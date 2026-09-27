"""Warranty tracking and claims."""
from ..util import POSError, now, today, need, clean, days_between, like
from . import audit, inventory, settings
from .auth import require

_BASE = ("SELECT w.*, p.name AS product, p.sku, se.serial, s.invoice_no, s.date AS sale_date, "
         "c.name AS customer, c.phone AS customer_phone FROM warranties w JOIN products p ON p.id=w.product_id "
         "LEFT JOIN serials se ON se.id=w.serial_id LEFT JOIN sales s ON s.id=w.sale_id "
         "LEFT JOIN customers c ON c.id=w.customer_id")


def display_status(db, w) -> str:
    if w["status"] in ("Void", "Replaced", "Claimed"):
        return w["status"]
    days = days_between(today(), w["expiry_date"])
    if days < 0:
        return "Expired"
    if days <= settings.get_int(db, "warranty_soon_days", 30):
        return "Expiring Soon"
    return "Active"


def lookup(db, user, serial="", invoice="", phone="", product="", status=None, limit=100, offset=0):
    require(user, "warranty.view")
    where, p = ["w.status<>'Void'"], []
    if serial:
        where.append("se.serial LIKE ? ESCAPE '\\'")
        p.append(like(serial))
    if invoice:
        where.append("s.invoice_no LIKE ? ESCAPE '\\'")
        p.append(like(invoice))
    if phone:
        where.append("(c.phone LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\')")
        p += [like(phone)] * 2
    if product:
        where.append("(p.name LIKE ? ESCAPE '\\' OR p.sku LIKE ? ESCAPE '\\')")
        p += [like(product)] * 2
    w_ = " AND ".join(where)
    rows = db.q(f"{_BASE} WHERE {w_} ORDER BY w.id DESC LIMIT ? OFFSET ?", p + [500, 0])
    for r in rows:
        r["display_status"] = display_status(db, r)
    if status:
        rows = [r for r in rows if r["display_status"] == status]
    total = len(rows)
    return rows[offset:offset + limit], total


def get(db, warranty_id):
    w = db.one(f"{_BASE} WHERE w.id=?", (warranty_id,))
    if not w:
        raise POSError("Warranty record not found.")
    w["display_status"] = display_status(db, w)
    w["claims"] = db.q("SELECT * FROM warranty_claims WHERE warranty_id=? ORDER BY id", (warranty_id,))
    return w


def file_claim(db, user, warranty_id, issue):
    require(user, "warranty.manage")
    issue = need(issue, "Problem description")
    with db.tx():
        w = get(db, warranty_id)
        if w["status"] == "Void":
            raise POSError("This warranty is void (the item was returned or the sale cancelled).")
        if w["status"] == "Replaced":
            raise POSError("This unit was already replaced under warranty.")
        if w["display_status"] == "Expired":
            raise POSError("Warranty has expired.")
        if db.scalar("SELECT 1 FROM warranty_claims WHERE warranty_id=? AND status='Open'", (warranty_id,)):
            raise POSError("There is already an open claim for this item.")
        cid = db.insert("INSERT INTO warranty_claims(warranty_id,date,issue,status,user_id) VALUES(?,?,?,'Open',?)",
                        (warranty_id, now(), issue, user["id"]))
        db.execute("UPDATE warranties SET status='Claimed' WHERE id=?", (warranty_id,))
        audit.log(db, user, "Warranty claim filed", "warranty", warranty_id, None, {"claim": cid, "issue": issue})
        return cid


def resolve_claim(db, user, claim_id, outcome, resolution=None, replacement_serial_id=None):
    """outcome: 'Repaired' | 'Replaced' | 'Rejected'."""
    require(user, "warranty.manage")
    if outcome not in ("Repaired", "Replaced", "Rejected"):
        raise POSError("Invalid outcome.")
    with db.tx():
        c = db.one("SELECT * FROM warranty_claims WHERE id=?", (claim_id,))
        if not c:
            raise POSError("Claim not found.")
        if c["status"] != "Open":
            raise POSError("This claim is already closed.")
        w = db.one("SELECT * FROM warranties WHERE id=?", (c["warranty_id"],))
        if outcome == "Replaced":
            product = db.one("SELECT * FROM products WHERE id=?", (w["product_id"],))
            if w["serial_id"]:
                if not replacement_serial_id:
                    raise POSError("Select the replacement serial number.")
                new = db.one("SELECT * FROM serials WHERE id=?", (replacement_serial_id,))
                if not new or new["product_id"] != w["product_id"] or new["status"] != "In Stock":
                    raise POSError("The replacement must be an In Stock serial of the same product.")
                db.execute("UPDATE serials SET status='Replaced', note='Replaced under warranty' WHERE id=?",
                           (w["serial_id"],))
                db.execute("UPDATE serials SET status='Sold', sale_id=?, sale_item_id=?, customer_id=?, sold_price=0,"
                           " sold_at=?, warranty_start=?, warranty_expiry=? WHERE id=?",
                           (w["sale_id"], w["sale_item_id"], w["customer_id"], now(), w["start_date"],
                            w["expiry_date"], replacement_serial_id))
                db.execute("UPDATE sale_serials SET returned=1 WHERE sale_item_id=? AND serial_id=?",
                           (w["sale_item_id"], w["serial_id"]))
                db.execute("INSERT INTO sale_serials(sale_item_id,serial_id) VALUES(?,?)",
                           (w["sale_item_id"], replacement_serial_id))
                db.execute("INSERT INTO warranties(sale_id,sale_item_id,product_id,serial_id,customer_id,start_date,"
                           "expiry_date,months,status,created_at) VALUES(?,?,?,?,?,?,?,?,'Active',?)",
                           (w["sale_id"], w["sale_item_id"], w["product_id"], replacement_serial_id, w["customer_id"],
                            w["start_date"], w["expiry_date"], w["months"], now()))
                unit_cost = new["purchase_cost"]
            else:
                unit_cost = product["purchase_price"]
            inventory.move(db, w["product_id"], "Warranty Replacement", qty_change=-1, unit_cost=unit_cost,
                           reason=f"Warranty claim #{claim_id}", ref_type="warranty_claim", ref_id=claim_id, user=user)
            db.execute("UPDATE warranties SET status='Replaced' WHERE id=?", (w["id"],))
        else:
            db.execute("UPDATE warranties SET status='Active' WHERE id=?", (w["id"],))
        db.execute("UPDATE warranty_claims SET status=?, resolution=?, replacement_serial_id=?, closed_at=? WHERE id=?",
                   (outcome, clean(resolution), replacement_serial_id, now(), claim_id))
        audit.log(db, user, "Warranty claim resolved", "warranty", w["id"], {"status": "Open"},
                  {"claim": claim_id, "outcome": outcome})


def list_claims(db, user, status=None, limit=100, offset=0):
    require(user, "warranty.view")
    where, p = ["1=1"], []
    if status:
        where.append("cl.status=?")
        p.append(status)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM warranty_claims cl WHERE {w}", p)
    rows = db.q(f"SELECT cl.*, p.name AS product, se.serial, s.invoice_no, c.name AS customer FROM warranty_claims cl "
                f"JOIN warranties wa ON wa.id=cl.warranty_id JOIN products p ON p.id=wa.product_id "
                f"LEFT JOIN serials se ON se.id=wa.serial_id LEFT JOIN sales s ON s.id=wa.sale_id "
                f"LEFT JOIN customers c ON c.id=wa.customer_id WHERE {w} ORDER BY cl.id DESC LIMIT ? OFFSET ?",
                p + [limit, offset])
    return rows, total
