"""Stock. Every stock change goes through move() so it is always logged."""
import json

from ..util import POSError, now, need, to_int, like
from . import audit, settings
from .auth import require

TX_TYPES = ["Purchase", "Sale", "Return", "Adjustment", "Damage", "Transfer", "Repair Usage",
            "Warranty Replacement", "Cancellation", "Purchase Return", "Opening Stock"]


def move(db, product_id, type_, qty_change=0, damaged_change=0, unit_cost=None,
         reason=None, ref_type=None, ref_id=None, user=None):
    """The single choke point that changes products.stock / products.damaged."""
    if not db.in_tx:
        raise RuntimeError("inventory.move must run inside a transaction")
    p = db.one("SELECT id,name,stock,damaged,serialized FROM products WHERE id=?", (product_id,))
    if not p:
        raise POSError("Product not found.")
    new_stock = p["stock"] + qty_change
    new_damaged = p["damaged"] + damaged_change
    if new_stock < 0 and (p["serialized"] or not settings.get_bool(db, "allow_negative_stock")):
        raise POSError(f"Insufficient stock for {p['name']}.")
    if new_damaged < 0:
        raise POSError(f"Damaged stock for {p['name']} cannot go below zero.")
    db.execute("UPDATE products SET stock=?, damaged=?, updated_at=? WHERE id=?",
               (new_stock, new_damaged, now(), product_id))
    db.execute(
        "INSERT INTO inventory_transactions(product_id,date,type,qty_change,damaged_change,unit_cost,"
        "stock_after,reason,ref_type,ref_id,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (product_id, now(), type_, qty_change, damaged_change, unit_cost, new_stock, reason,
         ref_type, ref_id, user["id"] if user else None))
    return new_stock


def adjust_stock(db, user, product_id, new_qty, reason):
    """Set a non-serialized product's on-hand quantity. A reason is mandatory."""
    require(user, "inventory.adjust")
    reason = need(reason, "Reason")
    new_qty = to_int(new_qty, "Quantity")
    with db.tx():
        p = db.one("SELECT * FROM products WHERE id=?", (product_id,))
        if not p:
            raise POSError("Product not found.")
        if p["serialized"]:
            raise POSError("Serialized products are adjusted by adding, removing or marking serial numbers.")
        delta = new_qty - p["stock"]
        if delta == 0:
            return 0
        move(db, product_id, "Adjustment", qty_change=delta, reason=reason, ref_type="adjustment", user=user)
        audit.log(db, user, "Stock adjusted", "product", product_id, {"stock": p["stock"]},
                  {"stock": new_qty, "reason": reason})
        return delta


def mark_damaged(db, user, product_id, qty, reason, serial_id=None):
    """Move units from sellable stock to damaged stock."""
    require(user, "inventory.adjust")
    reason = need(reason, "Reason")
    with db.tx():
        p = db.one("SELECT * FROM products WHERE id=?", (product_id,))
        if not p:
            raise POSError("Product not found.")
        if p["serialized"]:
            if not serial_id:
                raise POSError("Select the serial number that is damaged.")
            s = db.one("SELECT * FROM serials WHERE id=? AND product_id=?", (serial_id, product_id))
            if not s or s["status"] != "In Stock":
                raise POSError("Only serials that are In Stock can be marked damaged.")
            db.execute("UPDATE serials SET status='Damaged', note=? WHERE id=?", (reason, serial_id))
            qty = 1
        else:
            qty = to_int(qty, "Quantity")
            if qty <= 0:
                raise POSError("Quantity must be greater than zero.")
        move(db, product_id, "Damage", qty_change=-qty, damaged_change=qty, reason=reason,
             ref_type="serial" if serial_id else "adjustment", ref_id=serial_id, user=user)
        audit.log(db, user, "Stock marked damaged", "product", product_id, None, {"qty": qty, "reason": reason})


def reserved_map(db) -> dict:
    """Quantity held in on-hold carts, per product."""
    out = {}
    for r in db.q("SELECT cart_json FROM held_sales"):
        try:
            cart = json.loads(r["cart_json"])
        except ValueError:
            continue
        for it in cart.get("items", []):
            out[it["product_id"]] = out.get(it["product_id"], 0) + int(it.get("qty", 0))
    return out


def stock_list(db, user, text="", category_id=None, brand_id=None, status=None, limit=100, offset=0):
    """Inventory grid: current, available (= current - reserved), damaged, sold, low/out flags."""
    require(user, "inventory.view")
    where, p = ["p.active=1"], []
    if text:
        where.append("(p.name LIKE ? ESCAPE '\\' OR p.sku LIKE ? ESCAPE '\\' OR p.barcode LIKE ? ESCAPE '\\')")
        p += [like(text)] * 3
    if category_id:
        where.append("p.category_id=?")
        p.append(category_id)
    if brand_id:
        where.append("p.brand_id=?")
        p.append(brand_id)
    if status == "low":
        where.append("p.stock > 0 AND p.stock <= p.min_stock")
    elif status == "out":
        where.append("p.stock <= 0")
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM products p WHERE {w}", p)
    rows = db.q(
        f"SELECT p.id,p.sku,p.name,p.stock,p.damaged,p.min_stock,p.purchase_price,p.serialized,"
        f"(SELECT COALESCE(SUM(si.qty-si.returned_qty),0) FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        f" WHERE si.product_id=p.id AND s.status<>'Cancelled') AS sold "
        f"FROM products p WHERE {w} ORDER BY p.name LIMIT ? OFFSET ?", p + [limit, offset])
    res = reserved_map(db)
    for r in rows:
        r["reserved"] = min(res.get(r["id"], 0), max(r["stock"], 0))
        r["available"] = r["stock"] - r["reserved"]
        r["value"] = round(r["stock"] * r["purchase_price"], 2)
        r["state"] = "Out of stock" if r["stock"] <= 0 else ("Low" if r["stock"] <= r["min_stock"] else "OK")
    return rows, total


def transactions(db, user, product_id=None, type_=None, date_from=None, date_to=None, limit=100, offset=0):
    require(user, "inventory.view")
    where, p = ["1=1"], []
    if product_id:
        where.append("t.product_id=?")
        p.append(product_id)
    if type_:
        where.append("t.type=?")
        p.append(type_)
    if date_from:
        where.append("t.date>=?")
        p.append(date_from)
    if date_to:
        where.append("t.date<date(?, '+1 day')")
        p.append(date_to)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM inventory_transactions t WHERE {w}", p)
    rows = db.q(
        f"SELECT t.*, p.name AS product, p.sku, u.username FROM inventory_transactions t "
        f"JOIN products p ON p.id=t.product_id LEFT JOIN users u ON u.id=t.user_id WHERE {w} "
        f"ORDER BY t.id DESC LIMIT ? OFFSET ?", p + [limit, offset])
    return rows, total


def verify_consistency(db) -> list:
    """Integrity check used by tests and the Inventory screen: stock must equal the transaction
    history, and for serialized products the count of In Stock serials."""
    problems = []
    for r in db.q(
        "SELECT p.id,p.sku,p.stock,p.damaged,p.serialized,"
        "COALESCE((SELECT SUM(qty_change) FROM inventory_transactions WHERE product_id=p.id),0) AS s,"
        "COALESCE((SELECT SUM(damaged_change) FROM inventory_transactions WHERE product_id=p.id),0) AS d,"
        "(SELECT COUNT(*) FROM serials WHERE product_id=p.id AND status='In Stock') AS instock,"
        "(SELECT COUNT(*) FROM serials WHERE product_id=p.id AND status='Damaged') AS dmg FROM products p"):
        if r["stock"] != r["s"]:
            problems.append(f"{r['sku']}: stock {r['stock']} != transaction total {r['s']}")
        if r["damaged"] != r["d"]:
            problems.append(f"{r['sku']}: damaged {r['damaged']} != transaction total {r['d']}")
        if r["serialized"] and r["stock"] != r["instock"]:
            problems.append(f"{r['sku']}: stock {r['stock']} != In Stock serial count {r['instock']}")
        if r["serialized"] and r["damaged"] != r["dmg"]:
            problems.append(f"{r['sku']}: damaged {r['damaged']} != Damaged serial count {r['dmg']}")
    return problems
