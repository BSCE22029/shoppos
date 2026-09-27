"""Repair / service tickets."""
from ..config import SALE_METHODS
from ..util import POSError, now, need, clean, to_float, to_int, valid_date, like, r2
from . import audit, inventory
from .auth import require
from .finance import cash_post
from .parties import post_ledger

STATUSES = ["Received", "Diagnosing", "Waiting for Customer", "Waiting for Parts", "In Repair",
            "Ready", "Delivered", "Cancelled"]
OPEN_STATUSES = STATUSES[:6]


def _recalc(db, repair_id):
    r = db.one("SELECT labor_charge FROM repairs WHERE id=?", (repair_id,))
    parts = db.scalar("SELECT COALESCE(SUM(qty*unit_price),0) FROM repair_parts WHERE repair_id=?", (repair_id,))
    db.execute("UPDATE repairs SET final_cost=? WHERE id=?", (r2(r["labor_charge"] + parts), repair_id))


def _editable(r):
    if r["status"] in ("Delivered", "Cancelled"):
        raise POSError(f"This ticket is {r['status'].lower()} and can no longer be changed.")


def create_repair(db, user, d):
    require(user, "repairs.manage")
    device = need(d.get("device"), "Device")
    complaint = need(d.get("complaint"), "Complaint")
    cid = d.get("customer_id") or None
    name, phone = clean(d.get("customer_name")), clean(d.get("customer_phone"))
    with db.tx():
        if cid:
            c = db.one("SELECT name,phone FROM customers WHERE id=?", (cid,))
            if not c:
                raise POSError("Customer not found.")
            name, phone = name or c["name"], phone or c["phone"]
        if not name:
            raise POSError("Enter the customer name or select a customer.")
        exp = valid_date(d["expected_at"], "Expected date") if d.get("expected_at") else None
        tn = db.next_number("repair", "REP-")
        rid = db.insert(
            "INSERT INTO repairs(ticket_no,customer_id,customer_name,customer_phone,device,brand,model,serial,complaint,"
            "condition,accessories,technician_id,estimated_cost,status,received_at,expected_at,user_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'Received',?,?,?)",
            (tn, cid, name, phone, device, clean(d.get("brand")), clean(d.get("model")), clean(d.get("serial")),
             complaint, clean(d.get("condition")), clean(d.get("accessories")), d.get("technician_id") or None,
             to_float(d.get("estimated_cost"), "Estimated cost"), now(), exp, user["id"]))
        audit.log(db, user, "Repair created", "repair", rid, None, {"ticket": tn, "device": device})
        return rid


def update_repair(db, user, repair_id, d):
    require(user, "repairs.manage")
    with db.tx():
        r = db.one("SELECT * FROM repairs WHERE id=?", (repair_id,))
        if not r:
            raise POSError("Repair not found.")
        _editable(r)
        exp = valid_date(d["expected_at"], "Expected date") if d.get("expected_at") else None
        db.execute("UPDATE repairs SET device=?,brand=?,model=?,serial=?,complaint=?,condition=?,accessories=?,"
                   "technician_id=?,estimated_cost=?,expected_at=? WHERE id=?",
                   (need(d.get("device"), "Device"), clean(d.get("brand")), clean(d.get("model")), clean(d.get("serial")),
                    need(d.get("complaint"), "Complaint"), clean(d.get("condition")), clean(d.get("accessories")),
                    d.get("technician_id") or None, to_float(d.get("estimated_cost"), "Estimated cost"), exp, repair_id))
        audit.log(db, user, "Repair edited", "repair", repair_id)


def set_labor(db, user, repair_id, labor):
    require(user, "repairs.manage")
    labor = to_float(labor, "Labor charge")
    with db.tx():
        r = db.one("SELECT * FROM repairs WHERE id=?", (repair_id,))
        if not r:
            raise POSError("Repair not found.")
        _editable(r)
        db.execute("UPDATE repairs SET labor_charge=? WHERE id=?", (labor, repair_id))
        _recalc(db, repair_id)
        audit.log(db, user, "Repair labor set", "repair", repair_id, {"labor": r["labor_charge"]}, {"labor": labor})


def add_note(db, user, repair_id, note):
    require(user, "repairs.manage")
    note = need(note, "Note")
    with db.tx():
        if not db.scalar("SELECT 1 FROM repairs WHERE id=?", (repair_id,)):
            raise POSError("Repair not found.")
        db.execute("INSERT INTO repair_notes(repair_id,date,user_id,note) VALUES(?,?,?,?)",
                   (repair_id, now(), user["id"], note))


def set_status(db, user, repair_id, status, note=None):
    require(user, "repairs.manage")
    if status not in STATUSES:
        raise POSError("Invalid status.")
    if status == "Delivered":
        raise POSError("Use 'Deliver & collect payment' to deliver a repair.")
    with db.tx():
        r = db.one("SELECT * FROM repairs WHERE id=?", (repair_id,))
        if not r:
            raise POSError("Repair not found.")
        _editable(r)
        completed = now() if status == "Ready" else r["completed_at"]
        if status == "Cancelled":
            for part in db.q("SELECT * FROM repair_parts WHERE repair_id=?", (repair_id,)):
                _restore_part(db, user, part, r["ticket_no"], "cancelled ticket")
            db.execute("DELETE FROM repair_parts WHERE repair_id=?", (repair_id,))
            _recalc(db, repair_id)
        db.execute("UPDATE repairs SET status=?, completed_at=? WHERE id=?", (status, completed, repair_id))
        if note:
            db.execute("INSERT INTO repair_notes(repair_id,date,user_id,note) VALUES(?,?,?,?)",
                       (repair_id, now(), user["id"], f"[{status}] {note}"))
        audit.log(db, user, "Repair status", "repair", repair_id, {"status": r["status"]}, {"status": status})


def _restore_part(db, user, part, ticket, why):
    inventory.move(db, part["product_id"], "Repair Usage", qty_change=part["qty"], unit_cost=part["unit_cost"],
                   reason=f"{ticket}: part returned ({why})", ref_type="repair", ref_id=part["repair_id"], user=user)
    if part["serial_id"]:
        db.execute("UPDATE serials SET status='In Stock', note=NULL WHERE id=?", (part["serial_id"],))


def add_part(db, user, repair_id, product_id, qty, unit_price=None, serial_id=None):
    """Consume a stocked product on a repair; stock is deducted and logged."""
    require(user, "repairs.manage")
    qty = to_int(qty, "Quantity")
    if qty <= 0:
        raise POSError("Quantity must be greater than zero.")
    with db.tx():
        r = db.one("SELECT * FROM repairs WHERE id=?", (repair_id,))
        if not r:
            raise POSError("Repair not found.")
        _editable(r)
        p = db.one("SELECT * FROM products WHERE id=?", (product_id,))
        if not p:
            raise POSError("Part not found.")
        price = p["retail_price"] if unit_price in (None, "") else to_float(unit_price, "Price")
        cost = p["purchase_price"]
        if p["serialized"]:
            if qty != 1 or not serial_id:
                raise POSError("Select exactly one serial number for a serialized part.")
            s = db.one("SELECT * FROM serials WHERE id=? AND product_id=?", (serial_id, product_id))
            if not s or s["status"] != "In Stock":
                raise POSError("That serial number is not in stock.")
            db.execute("UPDATE serials SET status='Sold', note=? WHERE id=?", (f"Used in {r['ticket_no']}", serial_id))
            cost = s["purchase_cost"]
        inventory.move(db, product_id, "Repair Usage", qty_change=-qty, unit_cost=cost, reason=r["ticket_no"],
                       ref_type="repair", ref_id=repair_id, user=user)
        db.execute("INSERT INTO repair_parts(repair_id,product_id,qty,unit_price,unit_cost,serial_id) VALUES(?,?,?,?,?,?)",
                   (repair_id, product_id, qty, r2(price), r2(cost), serial_id))
        _recalc(db, repair_id)
        audit.log(db, user, "Repair part used", "repair", repair_id, None, {"product": p["name"], "qty": qty})


def remove_part(db, user, part_id):
    require(user, "repairs.manage")
    with db.tx():
        part = db.one("SELECT * FROM repair_parts WHERE id=?", (part_id,))
        if not part:
            raise POSError("Part not found.")
        r = db.one("SELECT * FROM repairs WHERE id=?", (part["repair_id"],))
        _editable(r)
        _restore_part(db, user, part, r["ticket_no"], "removed")
        db.execute("DELETE FROM repair_parts WHERE id=?", (part_id,))
        _recalc(db, r["id"])
        audit.log(db, user, "Repair part removed", "repair", r["id"], {"part_id": part_id})


def deliver_repair(db, user, repair_id, payments):
    """Hand the device back. payments: [{'method','amount'}] must add up to the amount due;
    'Credit' puts the balance on the customer's account."""
    require(user, "repairs.manage")
    with db.tx():
        r = db.one("SELECT * FROM repairs WHERE id=?", (repair_id,))
        if not r:
            raise POSError("Repair not found.")
        if r["status"] != "Ready":
            raise POSError("Mark the repair as Ready before delivering it.")
        due = r2(r["final_cost"] - r["paid"])
        total = 0.0
        credit = 0.0
        for pay in payments or []:
            m = pay.get("method")
            a = r2(to_float(pay.get("amount"), "Amount"))
            if m not in SALE_METHODS or m == "Store Credit":
                raise POSError("Invalid payment method.")
            if a <= 0:
                continue
            total += a
            if m == "Credit":
                credit += a
        if abs(r2(total) - due) > 0.01:
            raise POSError("Payment amount is incorrect.")
        if credit > 0:
            if not r["customer_id"]:
                raise POSError("Credit needs a saved customer on the ticket.")
            c = db.one("SELECT * FROM customers WHERE id=?", (r["customer_id"],))
            if c["balance"] + credit > c["credit_limit"] + 0.005:
                raise POSError("Customer credit limit exceeded.")
            post_ledger(db, "customer", c["id"], "Repair on credit", credit, r["ticket_no"], None, user)
        paid_now = 0.0
        for pay in payments or []:
            a = r2(to_float(pay.get("amount"), "Amount"))
            if a <= 0:
                continue
            db.execute("INSERT INTO repair_payments(repair_id,date,method,amount,ref,user_id) VALUES(?,?,?,?,?,?)",
                       (repair_id, now(), pay["method"], a, clean(pay.get("ref")), user["id"]))
            if pay["method"] != "Credit":
                paid_now += a
            if pay["method"] == "Cash":
                cash_post(db, user, "Repair Payment", a, "repair", repair_id, r["ticket_no"])
        db.execute("UPDATE repairs SET status='Delivered', delivered_at=?, paid=ROUND(paid+?,2) WHERE id=?",
                   (now(), paid_now, repair_id))
        audit.log(db, user, "Repair delivered", "repair", repair_id, None, {"final_cost": r["final_cost"], "credit": credit})


def get_repair(db, repair_id):
    r = db.one("SELECT r.*, u.full_name AS technician FROM repairs r LEFT JOIN users u ON u.id=r.technician_id "
               "WHERE r.id=?", (repair_id,))
    if not r:
        raise POSError("Repair not found.")
    r["notes"] = db.q("SELECT n.*, u.username FROM repair_notes n LEFT JOIN users u ON u.id=n.user_id "
                      "WHERE n.repair_id=? ORDER BY n.id", (repair_id,))
    r["parts"] = db.q("SELECT rp.*, p.name, p.sku FROM repair_parts rp JOIN products p ON p.id=rp.product_id "
                      "WHERE rp.repair_id=? ORDER BY rp.id", (repair_id,))
    r["payments"] = db.q("SELECT * FROM repair_payments WHERE repair_id=? ORDER BY id", (repair_id,))
    return r


def list_repairs(db, user, text="", status=None, technician_id=None, open_only=False, limit=100, offset=0):
    require(user, "repairs.view")
    where, p = ["1=1"], []
    if text:
        where.append("(r.ticket_no LIKE ? ESCAPE '\\' OR r.customer_name LIKE ? ESCAPE '\\' OR r.customer_phone LIKE ? ESCAPE '\\'"
                     " OR r.device LIKE ? ESCAPE '\\' OR r.serial LIKE ? ESCAPE '\\')")
        p += [like(text)] * 5
    if status:
        where.append("r.status=?")
        p.append(status)
    if open_only:
        where.append("r.status NOT IN ('Delivered','Cancelled')")
    if technician_id:
        where.append("r.technician_id=?")
        p.append(technician_id)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM repairs r WHERE {w}", p)
    rows = db.q(f"SELECT r.*, u.full_name AS technician FROM repairs r LEFT JOIN users u ON u.id=r.technician_id "
                f"WHERE {w} ORDER BY r.id DESC LIMIT ? OFFSET ?", p + [limit, offset])
    return rows, total
