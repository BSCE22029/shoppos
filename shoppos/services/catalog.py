"""Categories, brands, products and serial numbers."""
import re

from ..util import POSError, now, need, clean, to_float, to_int, like
from . import audit, inventory
from .auth import require, has_perm

PRICE_FIELDS = ("purchase_price", "wholesale_price", "retail_price", "min_price")


# ---------------------------------------------------------------- lookups
def categories(db, parent_id="top"):
    if parent_id == "top":
        return db.q("SELECT * FROM categories WHERE parent_id IS NULL ORDER BY name")
    if parent_id is None:
        return db.q("SELECT * FROM categories ORDER BY name")
    return db.q("SELECT * FROM categories WHERE parent_id=? ORDER BY name", (parent_id,))


def add_category(db, user, name, parent_id=None):
    require(user, "products.edit")
    name = need(name, "Category name")
    if db.scalar("SELECT 1 FROM categories WHERE name=? COLLATE NOCASE AND parent_id IS ?", (name, parent_id)):
        raise POSError("That category already exists.")
    with db.tx():
        cid = db.insert("INSERT INTO categories(name,parent_id) VALUES(?,?)", (name, parent_id))
        audit.log(db, user, "Category created", "category", cid, None, {"name": name, "parent_id": parent_id})
        return cid


def rename_category(db, user, category_id, name):
    require(user, "products.edit")
    name = need(name, "Category name")
    with db.tx():
        old = db.one("SELECT * FROM categories WHERE id=?", (category_id,))
        if not old:
            raise POSError("Category not found.")
        dup = db.scalar("SELECT 1 FROM categories WHERE name=? COLLATE NOCASE AND parent_id IS ? AND id<>?",
                        (name, old["parent_id"], category_id))
        if dup:
            raise POSError("That category already exists.")
        db.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))
        audit.log(db, user, "Category renamed", "category", category_id, {"name": old["name"]}, {"name": name})


def delete_category(db, user, category_id):
    require(user, "products.delete")
    if db.scalar("SELECT 1 FROM products WHERE category_id=? OR subcategory_id=?", (category_id, category_id)):
        raise POSError("This category is used by products and cannot be deleted.")
    if db.scalar("SELECT 1 FROM categories WHERE parent_id=?", (category_id,)):
        raise POSError("Delete its subcategories first.")
    with db.tx():
        db.execute("DELETE FROM categories WHERE id=?", (category_id,))
        audit.log(db, user, "Category deleted", "category", category_id)


def brands(db):
    return db.q("SELECT * FROM brands ORDER BY name")


def add_brand(db, user, name):
    require(user, "products.edit")
    name = need(name, "Brand name")
    if db.scalar("SELECT 1 FROM brands WHERE name=?", (name,)):
        raise POSError("That brand already exists.")
    with db.tx():
        bid = db.insert("INSERT INTO brands(name) VALUES(?)", (name,))
        audit.log(db, user, "Brand created", "brand", bid, None, {"name": name})
        return bid


def delete_brand(db, user, brand_id):
    require(user, "products.delete")
    if db.scalar("SELECT 1 FROM products WHERE brand_id=?", (brand_id,)):
        raise POSError("This brand is used by products and cannot be deleted.")
    with db.tx():
        db.execute("DELETE FROM brands WHERE id=?", (brand_id,))
        audit.log(db, user, "Brand deleted", "brand", brand_id)


# ---------------------------------------------------------------- products
_SELECT = ("SELECT p.*, b.name AS brand, c.name AS category, sc.name AS subcategory "
           "FROM products p LEFT JOIN brands b ON b.id=p.brand_id "
           "LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN categories sc ON sc.id=p.subcategory_id")


def _mask(user, rows):
    if has_perm(user, "products.cost"):
        return rows
    for r in rows:
        r["purchase_price"] = None
    return rows


def get_product(db, product_id):
    return db.one(_SELECT + " WHERE p.id=?", (product_id,))


def search_products(db, user, text="", category_id=None, brand_id=None, include_inactive=False,
                    limit=100, offset=0):
    require(user, "products.view")
    where, p = [], []
    if not include_inactive:
        where.append("p.active=1")
    if text:
        where.append("(p.name LIKE ? ESCAPE '\\' OR p.sku LIKE ? ESCAPE '\\' OR p.barcode LIKE ? ESCAPE '\\' "
                     "OR p.model LIKE ? ESCAPE '\\')")
        p += [like(text)] * 4
    if category_id:
        where.append("p.category_id=?")
        p.append(category_id)
    if brand_id:
        where.append("p.brand_id=?")
        p.append(brand_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.scalar(f"SELECT COUNT(*) FROM products p {w}", p)
    rows = db.q(f"{_SELECT} {w} ORDER BY p.name LIMIT ? OFFSET ?", p + [limit, offset])
    return _mask(user, rows), total


def pos_search(db, text, limit=40):
    """Fast search for the POS screen (active products only)."""
    text = (text or "").strip()
    if not text:
        return db.q(f"{_SELECT} WHERE p.active=1 ORDER BY p.name LIMIT ?", (limit,))
    return db.q(f"{_SELECT} WHERE p.active=1 AND (p.name LIKE ? ESCAPE '\\' OR p.sku LIKE ? ESCAPE '\\' "
                f"OR p.barcode LIKE ? ESCAPE '\\' OR p.model LIKE ? ESCAPE '\\') ORDER BY p.name LIMIT ?",
                [like(text)] * 4 + [limit])


def find_by_code(db, code):
    """Resolve a scanned/typed code: barcode or SKU (exact), or a serial number.
    Returns {'product':..., 'serial':...|None} or None."""
    code = (code or "").strip()
    if not code:
        return None
    p = db.one(_SELECT + " WHERE p.barcode=? OR p.sku=?", (code, code))
    if p:
        return {"product": p, "serial": None}
    s = db.one("SELECT * FROM serials WHERE serial=?", (code,))
    if s:
        return {"product": get_product(db, s["product_id"]), "serial": s}
    return None


def generate_barcode(db) -> str:
    """Next free internal barcode (numeric, Code 39 friendly)."""
    while True:
        code = db.next_number("barcode", "8960", 9)
        if not db.scalar("SELECT 1 FROM products WHERE barcode=?", (code,)):
            return code


def _validate(db, d, product_id, old=None):
    sku = need(d.get("sku"), "SKU")
    name = need(d.get("name"), "Product name")
    barcode = clean(d.get("barcode"))
    if db.scalar("SELECT 1 FROM products WHERE sku=? AND id IS NOT ?", (sku, product_id)):
        raise POSError("SKU already exists.")
    if barcode and db.scalar("SELECT 1 FROM products WHERE barcode=? AND id IS NOT ?", (barcode, product_id)):
        raise POSError("Barcode already exists.")
    v = {
        "sku": sku, "name": name, "barcode": barcode,
        "brand_id": d.get("brand_id") or None, "category_id": d.get("category_id") or None,
        "subcategory_id": d.get("subcategory_id") or None,
        "model": clean(d.get("model")), "description": clean(d.get("description")),
        "purchase_price": to_float(d.get("purchase_price"), "Purchase price"),
        "wholesale_price": to_float(d.get("wholesale_price"), "Wholesale price"),
        "retail_price": to_float(d.get("retail_price"), "Retail price"),
        "min_price": to_float(d.get("min_price"), "Minimum selling price"),
        "min_stock": to_int(d.get("min_stock"), "Minimum stock"),
        "warranty_months": to_int(d.get("warranty_months"), "Warranty months"),
        "tax_percent": to_float(d.get("tax_percent"), "Tax %"),
        "discount_percent": to_float(d.get("discount_percent"), "Discount %"),
        "supplier_id": d.get("supplier_id") or None, "image_path": clean(d.get("image_path")),
        "rack": clean(d.get("rack")), "location": clean(d.get("location")),
        "serialized": 1 if d.get("serialized") else 0,
        "active": 1 if d.get("active", True) else 0,
    }
    if v["retail_price"] <= 0:
        raise POSError("Retail price must be greater than zero.")
    if v["tax_percent"] > 100 or v["discount_percent"] > 100:
        raise POSError("Percentages cannot exceed 100.")
    if v["min_price"] > v["retail_price"]:
        raise POSError("Minimum selling price cannot be higher than the retail price.")
    if v["subcategory_id"]:
        sub = db.one("SELECT parent_id FROM categories WHERE id=?", (v["subcategory_id"],))
        if not sub or sub["parent_id"] != v["category_id"]:
            raise POSError("Subcategory does not belong to the selected category.")
    if old and old["serialized"] != v["serialized"]:
        has = db.scalar("SELECT 1 FROM serials WHERE product_id=?", (old["id"],)) or old["stock"] or \
              db.scalar("SELECT 1 FROM inventory_transactions WHERE product_id=?", (old["id"],))
        if has:
            raise POSError("Serial tracking cannot be changed once a product has stock or history.")
    return v


def save_product(db, user, d, product_id=None):
    require(user, "products.edit")
    with db.tx():
        old = db.one("SELECT * FROM products WHERE id=?", (product_id,)) if product_id else None
        if product_id and not old:
            raise POSError("Product not found.")
        if d.get("auto_barcode") and not (d.get("barcode") or "").strip():
            d = dict(d, barcode=generate_barcode(db))
        v = _validate(db, d, product_id, old)
        if not has_perm(user, "products.cost") and old:
            v["purchase_price"] = old["purchase_price"]
        if old is None:
            cols = ",".join(v)
            ph = ",".join("?" * len(v))
            pid = db.insert(f"INSERT INTO products({cols},created_at,updated_at) VALUES({ph},?,?)",
                            list(v.values()) + [now(), now()])
            audit.log(db, user, "Product created", "product", pid, None,
                      {"sku": v["sku"], "name": v["name"], "retail_price": v["retail_price"]})
            return pid
        sets = ",".join(f"{k}=?" for k in v)
        db.execute(f"UPDATE products SET {sets}, updated_at=? WHERE id=?", list(v.values()) + [now(), product_id])
        changes_old = {k: old[k] for k in v if old[k] != v[k]}
        changes_new = {k: v[k] for k in changes_old}
        if changes_old:
            price_change = any(k in PRICE_FIELDS for k in changes_old)
            audit.log(db, user, "Price changed" if price_change else "Product edited", "product",
                      product_id, changes_old, changes_new)
        return product_id


def delete_product(db, user, product_id):
    """Delete if never used; otherwise deactivate (history must stay intact)."""
    require(user, "products.delete")
    with db.tx():
        p = db.one("SELECT * FROM products WHERE id=?", (product_id,))
        if not p:
            raise POSError("Product not found.")
        used = (db.scalar("SELECT 1 FROM sale_items WHERE product_id=? LIMIT 1", (product_id,)) or
                db.scalar("SELECT 1 FROM purchase_items WHERE product_id=? LIMIT 1", (product_id,)) or
                db.scalar("SELECT 1 FROM repair_parts WHERE product_id=? LIMIT 1", (product_id,)) or
                db.scalar("SELECT 1 FROM serials WHERE product_id=? LIMIT 1", (product_id,)) or
                p["stock"] != 0 or
                db.scalar("SELECT 1 FROM inventory_transactions WHERE product_id=? LIMIT 1", (product_id,)))
        if used:
            db.execute("UPDATE products SET active=0, updated_at=? WHERE id=?", (now(), product_id))
            audit.log(db, user, "Product deactivated", "product", product_id, {"sku": p["sku"]})
            return "deactivated"
        db.execute("DELETE FROM products WHERE id=?", (product_id,))
        audit.log(db, user, "Product deleted", "product", product_id, {"sku": p["sku"], "name": p["name"]})
        return "deleted"


# ---------------------------------------------------------------- serials
def parse_serials(text) -> list:
    if isinstance(text, (list, tuple)):
        items = text
    else:
        items = re.split(r"[\n\r,;\t]+", text or "")
    return [s.strip() for s in items if s and s.strip()]


def check_new_serials(db, serials):
    seen = set()
    for s in serials:
        k = s.lower()
        if k in seen:
            raise POSError(f"Duplicate serial number in the list: {s}")
        seen.add(k)
        if db.scalar("SELECT 1 FROM serials WHERE serial=?", (s,)):
            raise POSError(f"Serial number already exists: {s}")


def insert_serials(db, product_id, serials, cost, purchase_id=None, supplier_id=None):
    """Create serial rows (status In Stock). Caller adjusts stock via inventory.move."""
    check_new_serials(db, serials)
    ids = []
    for s in serials:
        ids.append(db.insert(
            "INSERT INTO serials(product_id,serial,status,purchase_id,supplier_id,purchase_cost,created_at) "
            "VALUES(?,?,'In Stock',?,?,?,?)", (product_id, s, purchase_id, supplier_id, cost, now())))
    return ids


def add_opening_serials(db, user, product_id, serials_text, cost, reason="Opening stock"):
    require(user, "inventory.adjust")
    serials = parse_serials(serials_text)
    if not serials:
        raise POSError("Enter at least one serial number.")
    cost = to_float(cost, "Cost")
    with db.tx():
        p = db.one("SELECT * FROM products WHERE id=?", (product_id,))
        if not p:
            raise POSError("Product not found.")
        if not p["serialized"]:
            raise POSError("This product does not use serial numbers.")
        insert_serials(db, product_id, serials, cost)
        inventory.move(db, product_id, "Opening Stock", qty_change=len(serials), unit_cost=cost,
                       reason=reason, ref_type="serials", user=user)
        if p["purchase_price"] == 0 and cost:
            db.execute("UPDATE products SET purchase_price=? WHERE id=?", (cost, product_id))
        audit.log(db, user, "Serials added", "product", product_id, None, {"count": len(serials), "reason": reason})
    return len(serials)


def available_serials(db, product_id):
    return db.q("SELECT id,serial,purchase_cost FROM serials WHERE product_id=? AND status='In Stock' "
                "ORDER BY serial", (product_id,))


def list_serials(db, user, product_id=None, status=None, text="", limit=100, offset=0):
    require(user, "products.view")
    where, p = ["1=1"], []
    if product_id:
        where.append("s.product_id=?")
        p.append(product_id)
    if status:
        where.append("s.status=?")
        p.append(status)
    if text:
        where.append("s.serial LIKE ? ESCAPE '\\'")
        p.append(like(text))
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM serials s WHERE {w}", p)
    rows = db.q(f"SELECT s.*, p.name AS product, p.sku FROM serials s JOIN products p ON p.id=s.product_id "
                f"WHERE {w} ORDER BY s.id DESC LIMIT ? OFFSET ?", p + [limit, offset])
    if not has_perm(user, "products.cost"):
        for r in rows:
            r["purchase_cost"] = None
    return rows, total


def serial_history(db, user, serial):
    """Everything known about one serial number."""
    require(user, "products.view")
    s = db.one("SELECT s.*, p.name AS product, p.sku FROM serials s JOIN products p ON p.id=s.product_id "
               "WHERE s.serial=?", (serial.strip(),))
    if not s:
        raise POSError("Serial number not found.")
    out = dict(s)
    if s["purchase_id"]:
        out["purchase"] = db.one("SELECT po.po_number, su.name AS supplier FROM purchases po "
                                 "JOIN suppliers su ON su.id=po.supplier_id WHERE po.id=?", (s["purchase_id"],))
    out["sales"] = db.q(
        "SELECT sa.invoice_no, sa.date, sa.total, c.name AS customer, ss.returned FROM sale_serials ss "
        "JOIN sale_items si ON si.id=ss.sale_item_id JOIN sales sa ON sa.id=si.sale_id "
        "LEFT JOIN customers c ON c.id=sa.customer_id WHERE ss.serial_id=? ORDER BY sa.id", (s["id"],))
    out["warranties"] = db.q("SELECT * FROM warranties WHERE serial_id=? ORDER BY id", (s["id"],))
    if not has_perm(user, "products.cost"):
        out["purchase_cost"] = None
    return out
