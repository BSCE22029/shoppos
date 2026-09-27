"""POS sales: pricing, checkout (atomic), holds and cancellation."""
import json

from ..config import SALE_METHODS
from ..util import POSError, now, to_float, to_int, like, r2, add_months, today, clean
from . import audit, inventory, settings
from .auth import require, has_perm
from .finance import cash_post, open_register
from .parties import post_ledger


# ------------------------------------------------------------------ pricing
def _lines_from_cart(db, items):
    if not items:
        raise POSError("The cart is empty.")
    lines = []
    for it in items:
        p = db.one("SELECT * FROM products WHERE id=?", (it["product_id"],))
        if not p:
            raise POSError("Product not found.")
        if not p["active"]:
            raise POSError(f"{p['name']} is inactive and cannot be sold.")
        qty = to_int(it.get("qty"), "Quantity")
        if qty <= 0:
            raise POSError(f"Quantity for {p['name']} must be greater than zero.")
        price = it.get("unit_price")
        price = p["retail_price"] if price in (None, "") else to_float(price, "Price")
        disc = to_float(it.get("discount") or 0, "Discount")
        if disc > qty * price + 0.005:
            raise POSError(f"Discount for {p['name']} is more than the line amount.")
        lines.append({"product": p, "qty": qty, "unit_price": r2(price), "discount": r2(disc),
                      "serial_ids": list(it.get("serial_ids") or [])})
    return lines


def _calc(lines, overall_discount):
    overall = r2(overall_discount)
    bases = [r2(l["qty"] * l["unit_price"] - l["discount"]) for l in lines]
    sum_base = r2(sum(bases))
    if overall < 0:
        raise POSError("Discount cannot be negative.")
    if overall > sum_base + 0.005:
        raise POSError("Overall discount cannot be more than the sale amount.")
    allocated = 0.0
    tot = {"subtotal": 0.0, "line_discount": 0.0, "overall_discount": overall, "tax": 0.0, "total": 0.0}
    for i, (l, base) in enumerate(zip(lines, bases)):
        if i == len(lines) - 1:
            alloc = r2(overall - allocated)
        else:
            alloc = r2(overall * base / sum_base) if sum_base else 0.0
            allocated += alloc
        net = r2(base - alloc)
        tax = r2(net * l["product"]["tax_percent"] / 100.0)
        l.update(base=base, alloc=alloc, net=net, tax=tax, total=r2(net + tax),
                 tax_percent=l["product"]["tax_percent"])
        tot["subtotal"] += l["qty"] * l["unit_price"]
        tot["line_discount"] += l["discount"]
        tot["tax"] += tax
        tot["total"] += l["total"]
    for k in ("subtotal", "line_discount", "tax", "total"):
        tot[k] = r2(tot[k])
    return tot


def preview_totals(db, cart):
    """Totals for the cart as shown on screen (no permission or stock checks)."""
    lines = _lines_from_cart(db, cart.get("items", []))
    tot = _calc(lines, to_float(cart.get("overall_discount") or 0, "Discount"))
    tot["lines"] = [{"base": l["base"], "alloc": l["alloc"], "net": l["net"], "tax": l["tax"], "total": l["total"]}
                    for l in lines]
    return tot


# ------------------------------------------------------------------ checkout
def complete_sale(db, user, cart):
    """cart = {customer_id, items:[{product_id, qty, unit_price?, discount?, serial_ids?}],
    overall_discount, payments:[{method, amount, ref?}], notes, held_id?}. All-or-nothing."""
    require(user, "pos.sell")
    with db.tx():
        lines = _lines_from_cart(db, cart.get("items", []))
        overall = to_float(cart.get("overall_discount") or 0, "Discount")
        if overall > 0 or any(l["discount"] > 0 for l in lines):
            require(user, "pos.discount")
        for l in lines:
            if abs(l["unit_price"] - l["product"]["retail_price"]) > 0.005:
                require(user, "pos.price_override")
        tot = _calc(lines, overall)
        for l in lines:
            unit_net = l["net"] / l["qty"]
            if l["product"]["min_price"] and unit_net < l["product"]["min_price"] - 0.005:
                if not has_perm(user, "pos.below_min"):
                    raise POSError(f"Price for {l['product']['name']} is below the minimum selling price "
                                   f"({l['product']['min_price']:,.0f}).")

        # stock and serial validation
        need_qty = {}
        for l in lines:
            need_qty[l["product"]["id"]] = need_qty.get(l["product"]["id"], 0) + l["qty"]
        allow_neg = settings.get_bool(db, "allow_negative_stock")
        for pid, q in need_qty.items():
            p = db.one("SELECT name,stock,serialized FROM products WHERE id=?", (pid,))
            if q > p["stock"] and (p["serialized"] or not allow_neg):
                raise POSError(f"Insufficient stock for {p['name']}. Available: {p['stock']}.")
        used_serials = set()
        for l in lines:
            p = l["product"]
            if p["serialized"]:
                ids = l["serial_ids"]
                if len(ids) != l["qty"]:
                    raise POSError(f"Select a serial number for each unit of {p['name']}.")
                cost = 0.0
                for sid in ids:
                    if sid in used_serials:
                        raise POSError("The same serial number is used twice in the cart.")
                    used_serials.add(sid)
                    s = db.one("SELECT * FROM serials WHERE id=?", (sid,))
                    if not s or s["product_id"] != p["id"]:
                        raise POSError(f"Serial number does not belong to {p['name']}.")
                    if s["status"] != "In Stock":
                        raise POSError(f"Serial number {s['serial']} is not in stock.")
                    cost += s["purchase_cost"]
                l["cost"] = r2(cost)
            else:
                if l["serial_ids"]:
                    raise POSError(f"{p['name']} does not use serial numbers.")
                l["cost"] = r2(l["qty"] * p["purchase_price"])

        # payments
        payments = cart.get("payments") or []
        for pay in payments:
            if pay.get("method") not in SALE_METHODS:
                raise POSError("Invalid payment method.")
            pay["amount"] = r2(to_float(pay.get("amount"), "Payment amount"))
            if pay["amount"] <= 0:
                raise POSError("Payment amounts must be greater than zero.")
        pay_sum = r2(sum(p["amount"] for p in payments))
        if abs(pay_sum - tot["total"]) > 0.01:
            raise POSError("Payment amount is incorrect.")
        credit = r2(sum(p["amount"] for p in payments if p["method"] == "Credit"))
        store_used = r2(sum(p["amount"] for p in payments if p["method"] == "Store Credit"))
        cash_amt = r2(sum(p["amount"] for p in payments if p["method"] == "Cash"))
        cust_id = cart.get("customer_id") or None
        cust = db.one("SELECT * FROM customers WHERE id=?", (cust_id,)) if cust_id else None
        if cust_id and not cust:
            raise POSError("Customer not found.")
        if credit > 0 or store_used > 0:
            if not cust:
                raise POSError("Select a customer for credit or store-credit payments.")
        if credit > 0 and cust["balance"] + credit > cust["credit_limit"] + 0.005:
            raise POSError("Customer credit limit exceeded.")
        if store_used > 0 and store_used > cust["store_credit"] + 0.005:
            raise POSError("Not enough store credit on the customer's account.")

        reg = open_register(db)
        invoice = db.next_number("invoice", settings.get(db, "invoice_prefix") or "INV-")
        sale_id = db.insert(
            "INSERT INTO sales(invoice_no,date,customer_id,user_id,subtotal,line_discount,overall_discount,tax,"
            "total,paid,credit,cost_total,status,notes,register_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'Completed',?,?)",
            (invoice, now(), cust_id, user["id"], tot["subtotal"], tot["line_discount"], tot["overall_discount"],
             tot["tax"], tot["total"], r2(tot["total"] - credit), credit, r2(sum(l["cost"] for l in lines)),
             clean(cart.get("notes")), reg["id"] if reg else None))
        sale_date = today()
        for l in lines:
            p = l["product"]
            item_id = db.insert(
                "INSERT INTO sale_items(sale_id,product_id,qty,unit_price,line_discount,overall_alloc,net,tax_percent,"
                "tax,total,cost_total,warranty_months) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (sale_id, p["id"], l["qty"], l["unit_price"], l["discount"], l["alloc"], l["net"], l["tax_percent"],
                 l["tax"], l["total"], l["cost"], p["warranty_months"]))
            expiry = add_months(sale_date, p["warranty_months"]) if p["warranty_months"] else None
            if p["serialized"]:
                for sid in l["serial_ids"]:
                    db.execute("UPDATE serials SET status='Sold', sale_id=?, sale_item_id=?, customer_id=?, sold_price=?,"
                               " sold_at=?, warranty_start=?, warranty_expiry=? WHERE id=?",
                               (sale_id, item_id, cust_id, l["unit_price"], now(),
                                sale_date if expiry else None, expiry, sid))
                    db.execute("INSERT INTO sale_serials(sale_item_id,serial_id) VALUES(?,?)", (item_id, sid))
                    if expiry:
                        db.execute("INSERT INTO warranties(sale_id,sale_item_id,product_id,serial_id,customer_id,"
                                   "start_date,expiry_date,months,status,created_at) VALUES(?,?,?,?,?,?,?,?,'Active',?)",
                                   (sale_id, item_id, p["id"], sid, cust_id, sale_date, expiry,
                                    p["warranty_months"], now()))
            elif expiry:
                db.execute("INSERT INTO warranties(sale_id,sale_item_id,product_id,serial_id,customer_id,start_date,"
                           "expiry_date,months,status,created_at) VALUES(?,?,?,NULL,?,?,?,?,'Active',?)",
                           (sale_id, item_id, p["id"], cust_id, sale_date, expiry, p["warranty_months"], now()))
            inventory.move(db, p["id"], "Sale", qty_change=-l["qty"], unit_cost=r2(l["cost"] / l["qty"]),
                           reason=invoice, ref_type="sale", ref_id=sale_id, user=user)
        for pay in payments:
            db.execute("INSERT INTO sale_payments(sale_id,method,amount,ref,date) VALUES(?,?,?,?,?)",
                       (sale_id, pay["method"], pay["amount"], clean(pay.get("ref")), now()))
        if credit > 0:
            post_ledger(db, "customer", cust_id, "Credit sale", credit, invoice, None, user)
        if store_used > 0:
            db.execute("UPDATE customers SET store_credit=ROUND(store_credit-?,2) WHERE id=?", (store_used, cust_id))
        if cash_amt > 0:
            cash_post(db, user, "Sale", cash_amt, "sale", sale_id, invoice)
        if cart.get("held_id"):
            db.execute("DELETE FROM held_sales WHERE id=?", (cart["held_id"],))
        audit.log(db, user, "Sale created", "sale", sale_id, None,
                  {"invoice": invoice, "total": tot["total"], "credit": credit})
        return {"sale_id": sale_id, "invoice_no": invoice, "total": tot["total"],
                "paid": r2(tot["total"] - credit), "credit": credit}


# ------------------------------------------------------------------ holds
def hold_cart(db, user, cart, note=None):
    require(user, "pos.sell")
    if not cart.get("items"):
        raise POSError("The cart is empty.")
    with db.tx():
        hid = db.insert("INSERT INTO held_sales(user_id,customer_id,cart_json,note,created_at) VALUES(?,?,?,?,?)",
                        (user["id"], cart.get("customer_id"), json.dumps(cart), clean(note), now()))
        audit.log(db, user, "Sale held", "held_sale", hid)
        return hid


def list_held(db):
    rows = db.q("SELECT h.*, u.username, c.name AS customer FROM held_sales h LEFT JOIN users u ON u.id=h.user_id "
                "LEFT JOIN customers c ON c.id=h.customer_id ORDER BY h.id DESC")
    for r in rows:
        try:
            r["items"] = len(json.loads(r["cart_json"]).get("items", []))
        except ValueError:
            r["items"] = 0
    return rows


def resume_held(db, user, held_id):
    """Returns the saved cart; the held record is deleted when the sale completes (or via delete_held)."""
    require(user, "pos.sell")
    r = db.one("SELECT * FROM held_sales WHERE id=?", (held_id,))
    if not r:
        raise POSError("Held sale not found.")
    cart = json.loads(r["cart_json"])
    cart["held_id"] = held_id
    return cart


def delete_held(db, user, held_id):
    require(user, "pos.sell")
    with db.tx():
        db.execute("DELETE FROM held_sales WHERE id=?", (held_id,))


# ------------------------------------------------------------------ queries
def get_sale(db, sale_id):
    s = db.one("SELECT s.*, c.name AS customer, c.phone AS customer_phone, c.address AS customer_address, "
               "u.full_name AS cashier FROM sales s LEFT JOIN customers c ON c.id=s.customer_id "
               "LEFT JOIN users u ON u.id=s.user_id WHERE s.id=?", (sale_id,))
    if not s:
        raise POSError("Sale not found.")
    s["items"] = db.q("SELECT si.*, p.name, p.sku, p.serialized FROM sale_items si JOIN products p ON p.id=si.product_id "
                      "WHERE si.sale_id=? ORDER BY si.id", (sale_id,))
    for it in s["items"]:
        it["serials"] = [r["serial"] for r in db.q(
            "SELECT se.serial FROM sale_serials ss JOIN serials se ON se.id=ss.serial_id "
            "WHERE ss.sale_item_id=? ORDER BY ss.id", (it["id"],))]
        it["serial_rows"] = db.q(
            "SELECT ss.serial_id, ss.returned, se.serial, se.status FROM sale_serials ss JOIN serials se ON se.id=ss.serial_id "
            "WHERE ss.sale_item_id=? ORDER BY ss.id", (it["id"],))
    s["payments"] = db.q("SELECT * FROM sale_payments WHERE sale_id=? ORDER BY id", (sale_id,))
    s["returns"] = db.q("SELECT * FROM returns WHERE sale_id=? ORDER BY id", (sale_id,))
    return s


def find_sale_by_invoice(db, invoice_no):
    r = db.one("SELECT id FROM sales WHERE invoice_no=? COLLATE NOCASE", ((invoice_no or "").strip(),))
    return get_sale(db, r["id"]) if r else None


def list_sales(db, user, text="", date_from=None, date_to=None, status=None, cashier_id=None,
               customer_id=None, limit=100, offset=0):
    require(user, "sales.view")
    where, p = ["1=1"], []
    if text:
        where.append("(s.invoice_no LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\' OR c.phone LIKE ? ESCAPE '\\')")
        p += [like(text)] * 3
    if date_from:
        where.append("s.date>=?")
        p.append(date_from)
    if date_to:
        where.append("s.date<date(?, '+1 day')")
        p.append(date_to)
    if status:
        where.append("s.status=?")
        p.append(status)
    if cashier_id:
        where.append("s.user_id=?")
        p.append(cashier_id)
    if customer_id:
        where.append("s.customer_id=?")
        p.append(customer_id)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE {w}", p)
    rows = db.q(f"SELECT s.*, c.name AS customer, u.username AS cashier FROM sales s "
                f"LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN users u ON u.id=s.user_id "
                f"WHERE {w} ORDER BY s.id DESC LIMIT ? OFFSET ?", p + [limit, offset])
    return rows, total


# ------------------------------------------------------------------ cancel
def cancel_sale(db, user, sale_id, reason):
    """Reverses stock, serials, warranty, customer credit and cash. Only untouched Completed sales."""
    require(user, "sales.cancel")
    reason = (reason or "").strip()
    if not reason:
        raise POSError("A reason is required to cancel a sale.")
    with db.tx():
        s = db.one("SELECT * FROM sales WHERE id=?", (sale_id,))
        if not s:
            raise POSError("Sale not found.")
        if s["status"] == "Cancelled":
            raise POSError("This sale has already been cancelled.")
        if s["status"] != "Completed":
            raise POSError("This sale has returns and cannot be cancelled. Process a return instead.")
        for it in db.q("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)):
            inventory.move(db, it["product_id"], "Cancellation", qty_change=it["qty"],
                           unit_cost=r2(it["cost_total"] / it["qty"]), reason=f"{s['invoice_no']} cancelled: {reason}",
                           ref_type="sale", ref_id=sale_id, user=user)
            for ss in db.q("SELECT * FROM sale_serials WHERE sale_item_id=? AND returned=0", (it["id"],)):
                db.execute("UPDATE serials SET status='In Stock', sale_id=NULL, sale_item_id=NULL, customer_id=NULL,"
                           " sold_price=NULL, sold_at=NULL, warranty_start=NULL, warranty_expiry=NULL WHERE id=?",
                           (ss["serial_id"],))
                db.execute("UPDATE sale_serials SET returned=1 WHERE id=?", (ss["id"],))
        db.execute("UPDATE warranties SET status='Void' WHERE sale_id=?", (sale_id,))
        if s["credit"] > 0:
            post_ledger(db, "customer", s["customer_id"], "Sale cancelled", -s["credit"], s["invoice_no"], reason, user)
        for pay in db.q("SELECT * FROM sale_payments WHERE sale_id=?", (sale_id,)):
            if pay["method"] == "Store Credit":
                db.execute("UPDATE customers SET store_credit=ROUND(store_credit+?,2) WHERE id=?",
                           (pay["amount"], s["customer_id"]))
            elif pay["method"] == "Cash":
                cash_post(db, user, "Sale Cancel", -pay["amount"], "sale", sale_id, s["invoice_no"])
        db.execute("UPDATE sales SET status='Cancelled', cancelled_at=?, cancel_reason=? WHERE id=?",
                   (now(), reason, sale_id))
        audit.log(db, user, "Sale cancelled", "sale", sale_id, {"status": "Completed"},
                  {"status": "Cancelled", "reason": reason, "invoice": s["invoice_no"]})
