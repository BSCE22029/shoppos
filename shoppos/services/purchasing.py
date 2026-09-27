"""Purchase orders, goods receiving, supplier payments and purchase returns."""
from ..config import PAYMENT_METHODS
from ..util import POSError, now, today, need, clean, to_float, to_int, valid_date, like, r2
from . import audit, catalog, inventory
from .auth import require
from .finance import cash_post
from .parties import post_ledger


def create_purchase(db, user, supplier_id, items, supplier_invoice=None, expected_date=None, notes=None):
    require(user, "purchases.manage")
    if not items:
        raise POSError("Add at least one product to the purchase order.")
    clean_items, total = [], 0.0
    for it in items:
        qty = to_int(it.get("qty"), "Quantity")
        cost = to_float(it.get("unit_cost"), "Unit cost")
        if qty <= 0:
            raise POSError("Quantity must be greater than zero.")
        if cost <= 0:
            raise POSError("Unit cost must be greater than zero.")
        clean_items.append((it["product_id"], qty, cost))
        total += qty * cost
    if expected_date:
        expected_date = valid_date(expected_date, "Expected date")
    with db.tx():
        if not db.scalar("SELECT 1 FROM suppliers WHERE id=? AND active=1", (supplier_id,)):
            raise POSError("Select a supplier.")
        for pid, _, _ in clean_items:
            if not db.scalar("SELECT 1 FROM products WHERE id=?", (pid,)):
                raise POSError("A product on the order no longer exists.")
        po = db.next_number("po", "PO-")
        purchase_id = db.insert(
            "INSERT INTO purchases(po_number,supplier_id,supplier_invoice,date,expected_date,status,total,notes,user_id)"
            " VALUES(?,?,?,?,?,'Ordered',?,?,?)",
            (po, supplier_id, clean(supplier_invoice), now(), expected_date, r2(total), clean(notes), user["id"]))
        for pid, qty, cost in clean_items:
            db.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,unit_cost) VALUES(?,?,?,?)",
                       (purchase_id, pid, qty, cost))
        audit.log(db, user, "Purchase created", "purchase", purchase_id, None, {"po": po, "total": r2(total)})
        return purchase_id


def get_purchase(db, purchase_id):
    p = db.one("SELECT po.*, s.name AS supplier FROM purchases po JOIN suppliers s ON s.id=po.supplier_id "
               "WHERE po.id=?", (purchase_id,))
    if not p:
        raise POSError("Purchase not found.")
    p["items"] = db.q("SELECT pi.*, pr.name AS product, pr.sku, pr.serialized FROM purchase_items pi "
                      "JOIN products pr ON pr.id=pi.product_id WHERE pi.purchase_id=? ORDER BY pi.id", (purchase_id,))
    p["payments"] = db.q("SELECT * FROM purchase_payments WHERE purchase_id=? ORDER BY id", (purchase_id,))
    return p


def list_purchases(db, user, text="", status=None, supplier_id=None, date_from=None, date_to=None,
                   limit=100, offset=0):
    require(user, "purchases.manage")
    where, p = ["1=1"], []
    if text:
        where.append("(po.po_number LIKE ? ESCAPE '\\' OR s.name LIKE ? ESCAPE '\\' OR po.supplier_invoice LIKE ? ESCAPE '\\')")
        p += [like(text)] * 3
    if status:
        where.append("po.status=?")
        p.append(status)
    if supplier_id:
        where.append("po.supplier_id=?")
        p.append(supplier_id)
    if date_from:
        where.append("po.date>=?")
        p.append(date_from)
    if date_to:
        where.append("po.date<date(?, '+1 day')")
        p.append(date_to)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM purchases po JOIN suppliers s ON s.id=po.supplier_id WHERE {w}", p)
    rows = db.q(f"SELECT po.*, s.name AS supplier FROM purchases po JOIN suppliers s ON s.id=po.supplier_id "
                f"WHERE {w} ORDER BY po.id DESC LIMIT ? OFFSET ?", p + [limit, offset])
    return rows, total


def receive_purchase(db, user, purchase_id, receipts, supplier_invoice=None):
    """receipts: [{'item_id':..,'qty':..,'serials': text|list}]. Partial receiving is allowed."""
    require(user, "purchases.manage")
    with db.tx():
        po = db.one("SELECT * FROM purchases WHERE id=?", (purchase_id,))
        if not po:
            raise POSError("Purchase not found.")
        if po["status"] in ("Cancelled", "Received"):
            raise POSError(f"This purchase is already {po['status'].lower()}.")
        received_value, any_qty = 0.0, False
        all_serials = []
        for rc in receipts:
            qty = to_int(rc.get("qty"), "Received quantity")
            if qty <= 0:
                continue
            any_qty = True
            item = db.one("SELECT * FROM purchase_items WHERE id=? AND purchase_id=?", (rc["item_id"], purchase_id))
            if not item:
                raise POSError("Item does not belong to this purchase.")
            product = db.one("SELECT * FROM products WHERE id=?", (item["product_id"],))
            if qty > item["qty"] - item["received_qty"]:
                raise POSError(f"Cannot receive more than ordered for {product['name']}.")
            serial_ids = []
            if product["serialized"]:
                serials = catalog.parse_serials(rc.get("serials"))
                if len(serials) != qty:
                    raise POSError(f"Enter exactly {qty} serial number(s) for {product['name']} "
                                   f"(you entered {len(serials)}).")
                for s in serials:
                    if s.lower() in all_serials:
                        raise POSError(f"Duplicate serial number in the list: {s}")
                    all_serials.append(s.lower())
                catalog.insert_serials(db, product["id"], serials, item["unit_cost"], purchase_id, po["supplier_id"])
            # weighted-average cost for stock valuation and profit
            old_stock = max(product["stock"], 0)
            if product["serialized"] or old_stock == 0:
                new_cost = item["unit_cost"]
            else:
                new_cost = (old_stock * product["purchase_price"] + qty * item["unit_cost"]) / (old_stock + qty)
            db.execute("UPDATE products SET purchase_price=? WHERE id=?", (r2(new_cost), product["id"]))
            inventory.move(db, product["id"], "Purchase", qty_change=qty, unit_cost=item["unit_cost"],
                           reason=po["po_number"], ref_type="purchase", ref_id=purchase_id, user=user)
            db.execute("UPDATE purchase_items SET received_qty=received_qty+? WHERE id=?", (qty, item["id"]))
            received_value += qty * item["unit_cost"]
        if not any_qty:
            raise POSError("Enter the quantity received for at least one item.")
        remaining = db.scalar("SELECT COUNT(*) FROM purchase_items WHERE purchase_id=? AND received_qty<qty",
                              (purchase_id,))
        status = "Partially Received" if remaining else "Received"
        db.execute("UPDATE purchases SET status=?, received_value=ROUND(received_value+?,2), "
                   "supplier_invoice=COALESCE(?,supplier_invoice) WHERE id=?",
                   (status, received_value, clean(supplier_invoice), purchase_id))
        post_ledger(db, "supplier", po["supplier_id"], "Goods received", received_value, po["po_number"], None, user)
        audit.log(db, user, "Goods received", "purchase", purchase_id, None,
                  {"po": po["po_number"], "value": r2(received_value), "status": status})
        return status


def cancel_purchase(db, user, purchase_id):
    require(user, "purchases.manage")
    with db.tx():
        po = db.one("SELECT * FROM purchases WHERE id=?", (purchase_id,))
        if not po:
            raise POSError("Purchase not found.")
        if po["status"] != "Ordered":
            raise POSError("Only purchase orders with nothing received can be cancelled.")
        db.execute("UPDATE purchases SET status='Cancelled' WHERE id=?", (purchase_id,))
        audit.log(db, user, "Purchase cancelled", "purchase", purchase_id, {"po": po["po_number"]})


def pay_supplier(db, user, supplier_id, amount, method, purchase_id=None, ref=None, note=None):
    require(user, "suppliers.manage")
    amount = to_float(amount, "Amount")
    if amount <= 0:
        raise POSError("Amount must be greater than zero.")
    if method not in PAYMENT_METHODS:
        raise POSError("Invalid payment method.")
    with db.tx():
        s = db.one("SELECT * FROM suppliers WHERE id=?", (supplier_id,))
        if not s:
            raise POSError("Supplier not found.")
        if amount > s["balance"] + 0.005:
            raise POSError(f"Payment exceeds the outstanding balance ({s['balance']:,.2f}).")
        if purchase_id and not db.scalar("SELECT 1 FROM purchases WHERE id=? AND supplier_id=?",
                                         (purchase_id, supplier_id)):
            raise POSError("That purchase does not belong to this supplier.")
        pid = db.insert("INSERT INTO purchase_payments(supplier_id,purchase_id,date,amount,method,ref,note,user_id) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (supplier_id, purchase_id, now(), amount, method, clean(ref), clean(note), user["id"]))
        if purchase_id:
            db.execute("UPDATE purchases SET paid=ROUND(paid+?,2) WHERE id=?", (amount, purchase_id))
        post_ledger(db, "supplier", supplier_id, "Payment made", -amount, f"SP-{pid}", note, user)
        if method == "Cash":
            cash_post(db, user, "Supplier Payment", -amount, "supplier_payment", pid, s["name"])
        audit.log(db, user, "Supplier payment", "supplier", supplier_id, None, {"amount": amount, "method": method})
        return pid


def supplier_payments(db, supplier_id):
    return db.q("SELECT * FROM purchase_payments WHERE supplier_id=? ORDER BY id DESC", (supplier_id,))


def purchase_return(db, user, supplier_id, items, note=None):
    """items: [{'product_id', 'qty', 'unit_cost', 'serial_ids': [...]}] - goods sent back to a supplier."""
    require(user, "purchases.manage")
    if not items:
        raise POSError("Nothing to return.")
    with db.tx():
        if not db.scalar("SELECT 1 FROM suppliers WHERE id=?", (supplier_id,)):
            raise POSError("Select a supplier.")
        total = 0.0
        rn = db.next_number("pret", "PRT-")
        rid = db.insert("INSERT INTO purchase_returns(return_no,supplier_id,date,total,note,user_id) VALUES(?,?,?,0,?,?)",
                        (rn, supplier_id, now(), clean(note), user["id"]))
        for it in items:
            p = db.one("SELECT * FROM products WHERE id=?", (it["product_id"],))
            if not p:
                raise POSError("Product not found.")
            cost = to_float(it.get("unit_cost"), "Unit cost")
            if p["serialized"]:
                ids = it.get("serial_ids") or []
                if not ids:
                    raise POSError(f"Select the serial numbers being returned for {p['name']}.")
                for sid in ids:
                    s = db.one("SELECT * FROM serials WHERE id=? AND product_id=?", (sid, p["id"]))
                    if not s or s["status"] != "In Stock":
                        raise POSError(f"Serial {s['serial'] if s else sid} is not in stock and cannot be returned.")
                    db.execute("UPDATE serials SET status='Returned to Supplier' WHERE id=?", (sid,))
                    db.execute("INSERT INTO purchase_return_items(return_id,product_id,qty,unit_cost,serial_id) "
                               "VALUES(?,?,1,?,?)", (rid, p["id"], cost, sid))
                qty = len(ids)
            else:
                qty = to_int(it.get("qty"), "Quantity")
                if qty <= 0:
                    raise POSError("Quantity must be greater than zero.")
                if qty > p["stock"]:
                    raise POSError(f"Insufficient stock for {p['name']}.")
                db.execute("INSERT INTO purchase_return_items(return_id,product_id,qty,unit_cost) VALUES(?,?,?,?)",
                           (rid, p["id"], qty, cost))
            inventory.move(db, p["id"], "Purchase Return", qty_change=-qty, unit_cost=cost, reason=rn,
                           ref_type="purchase_return", ref_id=rid, user=user)
            total += qty * cost
        db.execute("UPDATE purchase_returns SET total=? WHERE id=?", (r2(total), rid))
        post_ledger(db, "supplier", supplier_id, "Purchase return", -total, rn, note, user)
        audit.log(db, user, "Purchase return", "purchase_return", rid, None, {"return_no": rn, "total": r2(total)})
        return rid
