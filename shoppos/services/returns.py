"""Customer returns, refunds and store credit."""
from ..config import REFUND_METHODS
from ..util import POSError, now, to_int, clean, r2, like
from . import audit, inventory
from .auth import require
from .finance import cash_post
from .parties import post_ledger


def returnable(db, sale_id):
    """Sale lines with what can still be returned (used by the Returns screen)."""
    from .sales import get_sale
    s = get_sale(db, sale_id)
    for it in s["items"]:
        it["remaining"] = it["qty"] - it["returned_qty"]
        it["sold_serials"] = [r for r in it["serial_rows"] if not r["returned"] and r["status"] == "Sold"]
    return s


def process_return(db, user, sale_id, items, refund_method, note=None):
    """items: [{'sale_item_id', 'qty', 'serial_ids': [...], 'condition': 'Good'|'Damaged'}]"""
    require(user, "returns.process")
    if not items:
        raise POSError("Select at least one item to return.")
    with db.tx():
        sale = db.one("SELECT * FROM sales WHERE id=?", (sale_id,))
        if not sale:
            raise POSError("Sale not found.")
        if sale["status"] == "Returned":
            raise POSError("Invoice cannot be returned because it has already been returned.")
        if sale["status"] == "Cancelled":
            raise POSError("Invoice cannot be returned because the sale was cancelled.")
        if refund_method not in REFUND_METHODS:
            raise POSError("Choose a refund method.")
        cust = db.one("SELECT * FROM customers WHERE id=?", (sale["customer_id"],)) if sale["customer_id"] else None
        if refund_method == "Store Credit" and not cust:
            raise POSError("Store credit needs a customer on the sale.")

        rn = db.next_number("return", "RET-")
        rid = db.insert("INSERT INTO returns(return_no,sale_id,customer_id,date,user_id,refund_method,amount,net,tax,note) "
                        "VALUES(?,?,?,?,?,?,0,0,0,?)",
                        (rn, sale_id, sale["customer_id"], now(), user["id"], refund_method, clean(note)))
        tot_amt = tot_net = tot_tax = tot_cost = 0.0
        seen_items = set()
        for it in items:
            if it["sale_item_id"] in seen_items:
                raise POSError("The same sale line was selected twice.")
            seen_items.add(it["sale_item_id"])
            si = db.one("SELECT si.*, p.name, p.serialized FROM sale_items si JOIN products p ON p.id=si.product_id "
                        "WHERE si.id=? AND si.sale_id=?", (it["sale_item_id"], sale_id))
            if not si:
                raise POSError("Item does not belong to this invoice.")
            qty = to_int(it.get("qty"), "Return quantity")
            remaining = si["qty"] - si["returned_qty"]
            if qty <= 0:
                continue
            if qty > remaining:
                raise POSError(f"Only {remaining} unit(s) of {si['name']} can still be returned.")
            condition = it.get("condition") or "Good"
            if condition not in ("Good", "Damaged"):
                raise POSError("Condition must be Good or Damaged.")
            serial_ids = list(it.get("serial_ids") or [])
            if si["serialized"]:
                if len(serial_ids) != qty:
                    raise POSError(f"Select the serial number of each returned {si['name']}.")
                for sid in serial_ids:
                    ss = db.one("SELECT ss.*, se.serial, se.status FROM sale_serials ss JOIN serials se ON se.id=ss.serial_id "
                                "WHERE ss.sale_item_id=? AND ss.serial_id=?", (si["id"], sid))
                    if not ss:
                        raise POSError("That serial number was not sold on this invoice.")
                    if ss["returned"] or ss["status"] != "Sold":
                        raise POSError(f"Serial number {ss['serial']} has already been returned.")
            # money: proportional, exact on the final unit so nothing is lost to rounding
            prev = db.one("SELECT COALESCE(SUM(amount),0) a, COALESCE(SUM(net),0) n, COALESCE(SUM(tax),0) t, "
                          "COALESCE(SUM(cost),0) c FROM return_items WHERE sale_item_id=?", (si["id"],))
            if qty == remaining:
                amt, net, tax = r2(si["total"] - prev["a"]), r2(si["net"] - prev["n"]), r2(si["tax"] - prev["t"])
                cost = r2(si["cost_total"] - prev["c"])
            else:
                f = qty / si["qty"]
                amt, net, tax, cost = r2(si["total"] * f), r2(si["net"] * f), r2(si["tax"] * f), r2(si["cost_total"] * f)
            if si["serialized"]:
                cost = r2(sum(db.scalar("SELECT purchase_cost FROM serials WHERE id=?", (s,)) for s in serial_ids))
            restock_cost = cost if condition == "Good" else 0.0
            db.execute("INSERT INTO return_items(return_id,sale_item_id,product_id,qty,amount,net,tax,cost,condition,serial_id) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (rid, si["id"], si["product_id"], qty, amt, net, tax, restock_cost, condition,
                        serial_ids[0] if len(serial_ids) == 1 else None))
            for sid in serial_ids:
                if condition == "Good":
                    db.execute("UPDATE serials SET status='In Stock', sale_id=NULL, sale_item_id=NULL, customer_id=NULL,"
                               " sold_price=NULL, sold_at=NULL, warranty_start=NULL, warranty_expiry=NULL WHERE id=?", (sid,))
                else:
                    db.execute("UPDATE serials SET status='Damaged', sale_id=NULL, sale_item_id=NULL, customer_id=NULL,"
                               " sold_price=NULL, sold_at=NULL, warranty_start=NULL, warranty_expiry=NULL, "
                               "note='Returned damaged' WHERE id=?", (sid,))
                db.execute("UPDATE sale_serials SET returned=1 WHERE sale_item_id=? AND serial_id=?", (si["id"], sid))
                db.execute("UPDATE warranties SET status='Void' WHERE serial_id=? AND sale_id=?", (sid, sale_id))
            db.execute("UPDATE sale_items SET returned_qty=returned_qty+? WHERE id=?", (qty, si["id"]))
            if not si["serialized"] and qty == remaining:
                db.execute("UPDATE warranties SET status='Void' WHERE sale_item_id=?", (si["id"],))
            if condition == "Good":
                inventory.move(db, si["product_id"], "Return", qty_change=qty, unit_cost=r2(cost / qty),
                               reason=f"{rn} for {sale['invoice_no']}", ref_type="return", ref_id=rid, user=user)
            else:
                inventory.move(db, si["product_id"], "Return", qty_change=0, damaged_change=qty,
                               reason=f"{rn} for {sale['invoice_no']} (damaged)", ref_type="return", ref_id=rid, user=user)
            tot_amt += amt
            tot_net += net
            tot_tax += tax
            tot_cost += restock_cost
        if tot_amt <= 0:
            raise POSError("Select at least one item to return.")
        tot_amt = r2(tot_amt)
        owed = r2(sale["credit"] - sale["credit_offset"])
        offset = min(tot_amt, owed) if (cust and owed > 0) else 0.0
        refund = r2(tot_amt - offset)
        if offset > 0:
            post_ledger(db, "customer", cust["id"], "Return credit", -offset, rn, sale["invoice_no"], user)
            db.execute("UPDATE sales SET credit_offset=ROUND(credit_offset+?,2) WHERE id=?", (offset, sale_id))
        if refund > 0:
            if refund_method == "Store Credit":
                db.execute("UPDATE customers SET store_credit=ROUND(store_credit+?,2) WHERE id=?", (refund, cust["id"]))
            elif refund_method == "Cash":
                cash_post(db, user, "Refund", -refund, "return", rid, rn)
        db.execute("UPDATE returns SET amount=?, net=?, tax=?, cost=?, refund_amount=?, credit_offset=? WHERE id=?",
                   (tot_amt, r2(tot_net), r2(tot_tax), r2(tot_cost), refund, offset, rid))
        left = db.scalar("SELECT COUNT(*) FROM sale_items WHERE sale_id=? AND returned_qty<qty", (sale_id,))
        db.execute("UPDATE sales SET status=? WHERE id=?", ("Partially Returned" if left else "Returned", sale_id))
        audit.log(db, user, "Sale returned", "sale", sale_id, {"status": sale["status"]},
                  {"return_no": rn, "amount": tot_amt, "refund": refund, "offset": offset, "method": refund_method})
        return {"return_id": rid, "return_no": rn, "amount": tot_amt, "refund_amount": refund, "credit_offset": offset}


def list_returns(db, user, text="", date_from=None, date_to=None, limit=100, offset=0):
    require(user, "returns.process")
    where, p = ["1=1"], []
    if text:
        where.append("(r.return_no LIKE ? ESCAPE '\\' OR s.invoice_no LIKE ? ESCAPE '\\')")
        p += [like(text)] * 2
    if date_from:
        where.append("r.date>=?")
        p.append(date_from)
    if date_to:
        where.append("r.date<date(?, '+1 day')")
        p.append(date_to)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM returns r JOIN sales s ON s.id=r.sale_id WHERE {w}", p)
    rows = db.q(f"SELECT r.*, s.invoice_no, c.name AS customer FROM returns r JOIN sales s ON s.id=r.sale_id "
                f"LEFT JOIN customers c ON c.id=r.customer_id WHERE {w} ORDER BY r.id DESC LIMIT ? OFFSET ?",
                p + [limit, offset])
    return rows, total
