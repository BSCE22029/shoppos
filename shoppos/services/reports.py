"""Reports. Every report returns {'title','columns':[(key,label)],'rows':[dict],'summary':dict|None}
so the same data feeds the screen, CSV, Excel and PDF export."""
from ..util import POSError, today, r2
from . import settings
from .auth import require, has_perm

# returns are pre-aggregated once (fast) instead of one subquery per sale line
_RET = "WITH ret AS (SELECT sale_item_id, SUM(net) AS n, SUM(cost) AS c FROM return_items GROUP BY sale_item_id) "
_RETJ = "LEFT JOIN ret ON ret.sale_item_id=si.id"
_NET = "(si.net - COALESCE(ret.n,0))"
_COST = "(si.cost_total - COALESCE(ret.c,0))"
_QTY = "(si.qty - si.returned_qty)"
_LIVE = "s.status<>'Cancelled'"


def _rep(title, columns, rows, summary=None):
    return {"title": title, "columns": columns, "rows": rows, "summary": summary}


def _range(field, date_from, date_to):
    w, p = [], []
    if date_from:
        w.append(f"{field}>=?")
        p.append(date_from)
    if date_to:
        w.append(f"{field}<date(?, '+1 day')")
        p.append(date_to)
    return w, p


# ============================================================== SALES
SALES_GROUPS = {
    "day": ("Daily sales", "substr(s.date,1,10)", "Date"),
    "week": ("Weekly sales", "strftime('%Y-W%W', s.date)", "Week"),
    "month": ("Monthly sales", "substr(s.date,1,7)", "Month"),
    "product": ("Sales by product", "p.name", "Product"),
    "category": ("Sales by category", "COALESCE(c.name,'(none)')", "Category"),
    "brand": ("Sales by brand", "COALESCE(b.name,'(none)')", "Brand"),
    "cashier": ("Sales by cashier", "u.full_name", "Cashier"),
    "customer": ("Sales by customer", "COALESCE(cu.name,'Walk-in')", "Customer"),
}


def sales_report(db, user, group="day", date_from=None, date_to=None):
    require(user, "reports.view")
    if group == "payment":
        return payment_method_report(db, user, date_from, date_to)
    if group not in SALES_GROUPS:
        raise POSError("Unknown report.")
    title, expr, label = SALES_GROUPS[group]
    w, p = _range("s.date", date_from, date_to)
    where = " AND ".join([_LIVE] + w)
    fin = has_perm(user, "reports.financial")
    need = {"product": "p", "category": "pc", "brand": "pb", "cashier": "u", "customer": "cu"}.get(group)
    joins = ""
    if need in ("p", "pc", "pb"):
        joins += "JOIN products p ON p.id=si.product_id "
    if need == "pc":
        joins += "LEFT JOIN categories c ON c.id=p.category_id "
    if need == "pb":
        joins += "LEFT JOIN brands b ON b.id=p.brand_id "
    if need == "u":
        joins += "JOIN users u ON u.id=s.user_id "
    if need == "cu":
        joins += "LEFT JOIN customers cu ON cu.id=s.customer_id "
    rows = db.q(
        f"{_RET}SELECT {expr} AS grp, COUNT(DISTINCT s.id) AS invoices, SUM({_QTY}) AS qty, "
        f"ROUND(SUM({_NET}),2) AS sales, ROUND(SUM({_COST}),2) AS cost, "
        f"ROUND(SUM({_NET})-SUM({_COST}),2) AS profit FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        f"{joins}{_RETJ} WHERE {where} GROUP BY grp "
        f"ORDER BY {'grp DESC' if group in ('day','week','month') else 'sales DESC'}", p)
    cols = [("grp", label), ("invoices", "Invoices"), ("qty", "Qty"), ("sales", "Sales (ex-tax)")]
    if fin:
        cols += [("cost", "Cost"), ("profit", "Profit")]
    summary = {"sales": r2(sum(r["sales"] or 0 for r in rows)), "qty": sum(r["qty"] or 0 for r in rows)}
    if fin:
        summary["profit"] = r2(sum(r["profit"] or 0 for r in rows))
    return _rep(title, cols, rows, summary)


def payment_method_report(db, user, date_from=None, date_to=None):
    require(user, "reports.view")
    w, p = _range("s.date", date_from, date_to)
    where = " AND ".join([_LIVE] + w)
    rows = db.q(f"SELECT sp.method AS grp, COUNT(*) AS payments, ROUND(SUM(sp.amount),2) AS amount "
                f"FROM sale_payments sp JOIN sales s ON s.id=sp.sale_id WHERE {where} GROUP BY sp.method ORDER BY amount DESC", p)
    return _rep("Sales by payment method", [("grp", "Method"), ("payments", "Payments"), ("amount", "Amount")], rows,
                {"amount": r2(sum(r["amount"] for r in rows))})


def sales_detail(db, user, date_from=None, date_to=None):
    """Invoice-level listing for export."""
    require(user, "reports.view")
    w, p = _range("s.date", date_from, date_to)
    where = " AND ".join(["1=1"] + w)
    rows = db.q(f"SELECT s.invoice_no, s.date, COALESCE(c.name,'Walk-in') AS customer, u.username AS cashier, "
                f"s.subtotal, s.line_discount+s.overall_discount AS discount, s.tax, s.total, s.paid, s.credit, s.status "
                f"FROM sales s LEFT JOIN customers c ON c.id=s.customer_id JOIN users u ON u.id=s.user_id "
                f"WHERE {where} ORDER BY s.id DESC", p)
    cols = [("invoice_no", "Invoice"), ("date", "Date"), ("customer", "Customer"), ("cashier", "Cashier"),
            ("subtotal", "Subtotal"), ("discount", "Discount"), ("tax", "Tax"), ("total", "Total"),
            ("paid", "Paid"), ("credit", "On credit"), ("status", "Status")]
    return _rep("Sales register", cols, rows, {"total": r2(sum(r["total"] for r in rows if r["status"] != "Cancelled"))})


# ============================================================== INVENTORY
def stock_valuation(db, user):
    require(user, "reports.view")
    fin = has_perm(user, "reports.financial")
    rows = db.q("SELECT p.sku, p.name, p.stock, p.purchase_price AS cost, ROUND(p.stock*p.purchase_price,2) AS cost_value, "
                "p.retail_price, ROUND(p.stock*p.retail_price,2) AS retail_value FROM products p "
                "WHERE p.active=1 AND p.stock>0 ORDER BY cost_value DESC")
    cols = [("sku", "SKU"), ("name", "Product"), ("stock", "Stock")]
    if fin:
        cols += [("cost", "Unit cost"), ("cost_value", "Cost value")]
    cols += [("retail_price", "Retail"), ("retail_value", "Retail value")]
    return _rep("Stock valuation", cols, rows,
                {"units": sum(r["stock"] for r in rows), "cost_value": r2(sum(r["cost_value"] for r in rows)),
                 "retail_value": r2(sum(r["retail_value"] for r in rows))} if fin else
                {"units": sum(r["stock"] for r in rows), "retail_value": r2(sum(r["retail_value"] for r in rows))})


def low_stock(db, user):
    require(user, "reports.view")
    rows = db.q("SELECT sku, name, stock, min_stock FROM products WHERE active=1 AND stock>0 AND stock<=min_stock "
                "ORDER BY stock")
    return _rep("Low stock", [("sku", "SKU"), ("name", "Product"), ("stock", "Stock"), ("min_stock", "Minimum")], rows)


def out_of_stock(db, user):
    require(user, "reports.view")
    rows = db.q("SELECT sku, name, min_stock FROM products WHERE active=1 AND stock<=0 ORDER BY name")
    return _rep("Out of stock", [("sku", "SKU"), ("name", "Product"), ("min_stock", "Minimum")], rows)


def dead_stock(db, user, days=None):
    require(user, "reports.view")
    days = days or settings.get_int(db, "dead_stock_days", 90)
    last = {r["product_id"]: r["last_sale"] for r in db.q(
        "SELECT si.product_id, MAX(s.date) AS last_sale FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        "WHERE s.status<>'Cancelled' GROUP BY si.product_id")}
    cutoff = db.scalar("SELECT date('now','localtime', ?)", (f"-{int(days)} days",))
    rows = []
    for r in db.q("SELECT id, sku, name, stock, ROUND(stock*purchase_price,2) AS value FROM products "
                  "WHERE active=1 AND stock>0 ORDER BY value DESC"):
        ls = last.get(r["id"])
        if ls is None or ls[:10] < cutoff:
            rows.append({"sku": r["sku"], "name": r["name"], "stock": r["stock"], "value": r["value"], "last_sale": ls})
    return _rep(f"Dead stock (no sales in {days} days)",
                [("sku", "SKU"), ("name", "Product"), ("stock", "Stock"), ("value", "Cost value"), ("last_sale", "Last sale")],
                rows, {"value": r2(sum(r["value"] for r in rows))})


def fast_moving(db, user, date_from=None, date_to=None, limit=25):
    require(user, "reports.view")
    w, p = _range("s.date", date_from, date_to)
    where = " AND ".join([_LIVE] + w)
    rows = db.q(f"{_RET}SELECT p.sku, p.name, SUM({_QTY}) AS qty, ROUND(SUM({_NET}),2) AS sales, p.stock FROM sale_items si "
                f"JOIN sales s ON s.id=si.sale_id JOIN products p ON p.id=si.product_id {_RETJ} WHERE {where} "
                f"GROUP BY p.id HAVING qty>0 ORDER BY qty DESC LIMIT ?", p + [limit])
    return _rep("Fast-moving products", [("sku", "SKU"), ("name", "Product"), ("qty", "Units sold"),
                                         ("sales", "Sales"), ("stock", "In stock")], rows)


def stock_movement(db, user, product_id=None, date_from=None, date_to=None):
    require(user, "reports.view")
    w, p = _range("t.date", date_from, date_to)
    if product_id:
        w.append("t.product_id=?")
        p.append(product_id)
    where = " AND ".join(["1=1"] + w)
    rows = db.q(f"SELECT t.date, p.sku, p.name, t.type, t.qty_change, t.damaged_change, t.stock_after, t.reason "
                f"FROM inventory_transactions t JOIN products p ON p.id=t.product_id WHERE {where} "
                f"ORDER BY t.id DESC LIMIT 5000", p)
    return _rep("Stock movement", [("date", "Date"), ("sku", "SKU"), ("name", "Product"), ("type", "Type"),
                                   ("qty_change", "Change"), ("damaged_change", "Damaged"), ("stock_after", "Stock after"),
                                   ("reason", "Reason")], rows)


# ============================================================== PURCHASES
def purchases_by(db, user, group="supplier", date_from=None, date_to=None):
    require(user, "reports.view")
    w, p = _range("po.date", date_from, date_to)
    where = " AND ".join(["po.status<>'Cancelled'"] + w)
    if group == "supplier":
        rows = db.q(f"SELECT s.name AS grp, COUNT(*) AS orders, ROUND(SUM(po.total),2) AS ordered, "
                    f"ROUND(SUM(po.received_value),2) AS received, ROUND(SUM(po.paid),2) AS paid FROM purchases po "
                    f"JOIN suppliers s ON s.id=po.supplier_id WHERE {where} GROUP BY s.id ORDER BY received DESC", p)
        cols = [("grp", "Supplier"), ("orders", "Orders"), ("ordered", "Ordered"), ("received", "Received value"), ("paid", "Paid")]
    elif group == "product":
        rows = db.q(f"SELECT pr.name AS grp, SUM(pi.received_qty) AS qty, ROUND(SUM(pi.received_qty*pi.unit_cost),2) AS received "
                    f"FROM purchase_items pi JOIN purchases po ON po.id=pi.purchase_id JOIN products pr ON pr.id=pi.product_id "
                    f"WHERE {where} GROUP BY pr.id HAVING qty>0 ORDER BY received DESC", p)
        cols = [("grp", "Product"), ("qty", "Units received"), ("received", "Value")]
    else:
        rows = db.q(f"SELECT substr(po.date,1,10) AS grp, COUNT(*) AS orders, ROUND(SUM(po.total),2) AS ordered, "
                    f"ROUND(SUM(po.received_value),2) AS received FROM purchases po WHERE {where} GROUP BY grp ORDER BY grp DESC", p)
        cols = [("grp", "Date"), ("orders", "Orders"), ("ordered", "Ordered"), ("received", "Received value")]
    return _rep(f"Purchases by {group}", cols, rows)


# ============================================================== FINANCIAL
def profit_summary(db, user, date_from=None, date_to=None):
    """Revenue, COGS, gross profit, expenses and net profit for a period."""
    require(user, "reports.financial")
    w, p = _range("s.date", date_from, date_to)
    sw = " AND ".join([_LIVE] + w)
    g = db.one(f"SELECT COALESCE(SUM(si.net),0) AS gross, COALESCE(SUM(si.cost_total),0) AS cogs, "
               f"COALESCE(SUM(si.tax),0) AS tax FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE {sw}", p)
    disc = db.one(f"SELECT COALESCE(SUM(line_discount+overall_discount),0) AS d FROM sales s WHERE {sw}", p)["d"]
    rw, rp = _range("r.date", date_from, date_to)
    rw = " AND ".join(["s.status<>'Cancelled'"] + rw)
    rt = db.one(f"SELECT COALESCE(SUM(r.net),0) AS net, COALESCE(SUM(r.cost),0) AS cost, COALESCE(SUM(r.tax),0) AS tax "
                f"FROM returns r JOIN sales s ON s.id=r.sale_id WHERE {rw}", rp)
    revenue = r2(g["gross"] - rt["net"])
    cogs = r2(g["cogs"] - rt["cost"])
    gross_profit = r2(revenue - cogs)
    dw, dp = _range("delivered_at", date_from, date_to)
    rep_where = " AND ".join(["status='Delivered'"] + dw)
    rv = db.scalar(f"SELECT COALESCE(SUM(final_cost),0) FROM repairs WHERE {rep_where}", dp)
    rc = db.scalar(f"SELECT COALESCE(SUM(rp.qty*rp.unit_cost),0) FROM repair_parts rp JOIN repairs r ON r.id=rp.repair_id "
                   f"WHERE r.status='Delivered'" + "".join(f" AND r.{x}" for x in dw), dp)
    ew = ["1=1"] + (["date>=?"] if date_from else []) + (["date<=?"] if date_to else [])
    exp = db.scalar("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE " + " AND ".join(ew),
                    ([date_from] if date_from else []) + ([date_to] if date_to else []))
    repair_profit = r2(rv - rc)
    net_profit = r2(gross_profit + repair_profit - exp)
    receivables = db.scalar("SELECT COALESCE(SUM(balance),0) FROM customers WHERE balance>0")
    payables = db.scalar("SELECT COALESCE(SUM(balance),0) FROM suppliers WHERE balance>0")
    lines = [
        ("Gross sales (ex-tax)", r2(g["gross"])), ("Less: sales returns", r2(-rt["net"])),
        ("Net revenue", revenue), ("Cost of goods sold (COGS)", cogs), ("Gross profit", gross_profit),
        ("Repair revenue", r2(rv)), ("Repair parts cost", r2(rc)), ("Repair profit", repair_profit),
        ("Expenses", r2(exp)), ("NET PROFIT", net_profit),
        ("Discounts given (memo)", r2(disc)), ("Tax collected (memo)", r2(g["tax"] - rt["tax"])),
        ("Receivables (as of now)", r2(receivables)), ("Payables (as of now)", r2(payables)),
    ]
    rows = [{"item": k, "amount": v} for k, v in lines]
    summary = {"revenue": revenue, "cogs": cogs, "gross_profit": gross_profit, "expenses": r2(exp),
               "repair_profit": repair_profit, "net_profit": net_profit, "receivables": r2(receivables),
               "payables": r2(payables), "discounts": r2(disc)}
    return _rep("Profit & loss summary", [("item", "Item"), ("amount", "Amount")], rows, summary)


def receivables(db, user):
    require(user, "reports.view")
    rows = db.q("SELECT name, phone, balance, credit_limit FROM customers WHERE balance>0.005 ORDER BY balance DESC")
    return _rep("Receivables (customers owing)", [("name", "Customer"), ("phone", "Phone"), ("balance", "Owes"),
                                                 ("credit_limit", "Credit limit")], rows,
                {"total": r2(sum(r["balance"] for r in rows))})


def payables(db, user):
    require(user, "reports.view")
    rows = db.q("SELECT name, company, phone, balance FROM suppliers WHERE balance>0.005 ORDER BY balance DESC")
    return _rep("Payables (owed to suppliers)", [("name", "Supplier"), ("company", "Company"), ("phone", "Phone"),
                                                 ("balance", "We owe")], rows, {"total": r2(sum(r["balance"] for r in rows))})


# ============================================================== REPAIRS
def repair_report(db, user, kind="pending", date_from=None, date_to=None):
    require(user, "reports.view")
    if kind == "pending":
        rows = db.q("SELECT r.ticket_no, r.received_at, r.customer_name, r.device, r.status, "
                    "COALESCE(u.full_name,'') AS technician, r.expected_at FROM repairs r LEFT JOIN users u ON u.id=r.technician_id "
                    "WHERE r.status NOT IN ('Delivered','Cancelled') ORDER BY r.received_at")
        return _rep("Pending repairs", [("ticket_no", "Ticket"), ("received_at", "Received"), ("customer_name", "Customer"),
                                        ("device", "Device"), ("status", "Status"), ("technician", "Technician"),
                                        ("expected_at", "Expected")], rows)
    dw, dp = _range("r.delivered_at", date_from, date_to)
    where = " AND ".join(["r.status='Delivered'"] + dw)
    if kind == "completed":
        rows = db.q(f"SELECT r.ticket_no, r.delivered_at, r.customer_name, r.device, r.final_cost, r.paid FROM repairs r "
                    f"WHERE {where} ORDER BY r.delivered_at DESC", dp)
        return _rep("Completed repairs", [("ticket_no", "Ticket"), ("delivered_at", "Delivered"), ("customer_name", "Customer"),
                                          ("device", "Device"), ("final_cost", "Charged"), ("paid", "Paid")], rows,
                    {"revenue": r2(sum(r["final_cost"] for r in rows))})
    if kind == "technician":
        rows = db.q(f"SELECT COALESCE(u.full_name,'(unassigned)') AS technician, COUNT(*) AS jobs, "
                    f"ROUND(SUM(r.final_cost),2) AS revenue, ROUND(AVG(julianday(r.delivered_at)-julianday(r.received_at)),1) AS avg_days "
                    f"FROM repairs r LEFT JOIN users u ON u.id=r.technician_id WHERE {where} GROUP BY r.technician_id "
                    f"ORDER BY revenue DESC", dp)
        return _rep("Technician performance", [("technician", "Technician"), ("jobs", "Repairs delivered"),
                                               ("revenue", "Revenue"), ("avg_days", "Avg days")], rows)
    if kind == "revenue":
        rows = db.q(f"SELECT substr(r.delivered_at,1,10) AS day, COUNT(*) AS jobs, ROUND(SUM(r.labor_charge),2) AS labor, "
                    f"ROUND(SUM(r.final_cost-r.labor_charge),2) AS parts, ROUND(SUM(r.final_cost),2) AS revenue "
                    f"FROM repairs r WHERE {where} GROUP BY day ORDER BY day DESC", dp)
        return _rep("Repair revenue", [("day", "Date"), ("jobs", "Jobs"), ("labor", "Labor"), ("parts", "Parts"),
                                       ("revenue", "Revenue")], rows, {"revenue": r2(sum(r["revenue"] for r in rows))})
    raise POSError("Unknown report.")


# ============================================================== DASHBOARD
def dashboard(db, user):
    d = {}
    t = today()
    m = t[:7]
    live = "status<>'Cancelled'"
    d["today_sales"] = db.scalar(f"SELECT COALESCE(SUM(total),0) FROM sales WHERE {live} AND date>=?", (t,))
    d["today_count"] = db.scalar(f"SELECT COUNT(*) FROM sales WHERE {live} AND date>=?", (t,))
    d["month_sales"] = db.scalar(f"SELECT COALESCE(SUM(total),0) FROM sales WHERE {live} AND substr(date,1,7)=?", (m,))
    d["low_stock"] = db.scalar("SELECT COUNT(*) FROM products WHERE active=1 AND stock>0 AND stock<=min_stock")
    d["out_of_stock"] = db.scalar("SELECT COUNT(*) FROM products WHERE active=1 AND stock<=0")
    d["open_repairs"] = db.scalar("SELECT COUNT(*) FROM repairs WHERE status NOT IN ('Delivered','Cancelled')")
    d["ready_repairs"] = db.scalar("SELECT COUNT(*) FROM repairs WHERE status='Ready'")
    d["open_claims"] = db.scalar("SELECT COUNT(*) FROM warranty_claims WHERE status='Open'")
    soon = settings.get_int(db, "warranty_soon_days", 30)
    d["expiring_warranty"] = db.scalar("SELECT COUNT(*) FROM warranties WHERE status='Active' AND expiry_date>=? AND "
                                       "expiry_date<=date(?, ?)", (t, t, f"+{soon} days"))
    from .finance import open_register
    d["register_open"] = bool(open_register(db))
    series = db.q("SELECT substr(date,1,10) AS day, ROUND(SUM(total),2) AS total FROM sales WHERE status<>'Cancelled' AND "
                  "date>=date('now','localtime','-6 days') GROUP BY day ORDER BY day")
    d["series"] = series
    d["top_products"] = db.q(
        "SELECT p.name, SUM(si.qty-si.returned_qty) AS qty FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        "JOIN products p ON p.id=si.product_id WHERE s.status<>'Cancelled' AND s.date>=date('now','localtime','-30 days') "
        "GROUP BY p.id HAVING qty>0 ORDER BY qty DESC LIMIT 5")
    if has_perm(user, "reports.financial"):
        d["receivables"] = db.scalar("SELECT COALESCE(SUM(balance),0) FROM customers WHERE balance>0")
        d["payables"] = db.scalar("SELECT COALESCE(SUM(balance),0) FROM suppliers WHERE balance>0")
        d["today_profit"] = profit_summary(db, user, t, t)["summary"]["gross_profit"]
        d["month_profit"] = profit_summary(db, user, m + "-01", t)["summary"]["net_profit"]
    return d
