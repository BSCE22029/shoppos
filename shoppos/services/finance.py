"""Cash register, expenses and customer payments."""
from ..util import POSError, now, today, need, clean, to_float, valid_date, like, r2
from . import audit, settings
from .auth import require
from .parties import post_ledger

DEFAULT_EXPENSE_CATEGORIES = ["Rent", "Electricity", "Internet", "Salaries", "Transport",
                              "Marketing", "Maintenance", "Office", "Other"]


def ensure_defaults(db):
    with db.tx():
        for c in DEFAULT_EXPENSE_CATEGORIES:
            db.execute("INSERT OR IGNORE INTO expense_categories(name) VALUES(?)", (c,))


# ------------------------------------------------------------ cash register
def open_register(db):
    return db.one("SELECT * FROM cash_registers WHERE status='Open' AND branch_id=1")


def cash_post(db, user, kind, amount, ref_type=None, ref_id=None, note=None):
    """Record cash entering (+) or leaving (-) the drawer against the open register."""
    if not db.in_tx:
        raise RuntimeError("cash_post must run inside a transaction")
    amount = r2(amount)
    if amount == 0:
        return None
    reg = open_register(db)
    if not reg:
        if settings.get_bool(db, "require_open_register"):
            raise POSError("Open the cash register first (Cash Register screen) before handling cash.")
        return None
    db.execute("INSERT INTO cash_transactions(register_id,date,kind,amount,ref_type,ref_id,note,user_id) "
               "VALUES(?,?,?,?,?,?,?,?)",
               (reg["id"], now(), kind, amount, ref_type, ref_id, note, user["id"] if user else None))
    return reg["id"]


def open_new_register(db, user, opening_cash):
    require(user, "cash.manage")
    opening_cash = to_float(opening_cash, "Opening cash")
    with db.tx():
        if open_register(db):
            raise POSError("A cash register is already open. Close it first.")
        rid = db.insert("INSERT INTO cash_registers(branch_id,opened_at,opened_by,opening_cash,status) "
                        "VALUES(1,?,?,?,'Open')", (now(), user["id"], opening_cash))
        audit.log(db, user, "Register opened", "cash_register", rid, None, {"opening_cash": opening_cash})
        return rid


def cash_movement(db, user, kind, amount, note):
    """Manual deposit (cash added) or withdrawal (cash removed)."""
    require(user, "cash.manage")
    if kind not in ("Deposit", "Withdrawal"):
        raise POSError("Invalid cash movement.")
    amount = to_float(amount, "Amount")
    if amount <= 0:
        raise POSError("Amount must be greater than zero.")
    note = need(note, "Note")
    with db.tx():
        reg = open_register(db)
        if not reg:
            raise POSError("Open the cash register first.")
        if kind == "Withdrawal" and amount > register_summary(db, reg["id"])["expected"] + 0.005:
            raise POSError("Withdrawal is more than the cash in the drawer.")
        cash_post(db, user, kind, amount if kind == "Deposit" else -amount, "manual", None, note)
        audit.log(db, user, f"Cash {kind.lower()}", "cash_register", reg["id"], None, {"amount": amount, "note": note})


def register_summary(db, register_id):
    reg = db.one("SELECT * FROM cash_registers WHERE id=?", (register_id,))
    if not reg:
        raise POSError("Register not found.")
    by_kind = {r["kind"]: r["s"] for r in db.q(
        "SELECT kind, ROUND(SUM(amount),2) AS s FROM cash_transactions WHERE register_id=? GROUP BY kind",
        (register_id,))}
    movement = r2(sum(by_kind.values()))
    reg["by_kind"] = by_kind
    reg["movement"] = movement
    reg["expected"] = r2(reg["opening_cash"] + movement)
    return reg


def close_register(db, user, actual_cash, note=None):
    require(user, "cash.manage")
    actual = to_float(actual_cash, "Actual cash")
    with db.tx():
        reg = open_register(db)
        if not reg:
            raise POSError("There is no open register.")
        summ = register_summary(db, reg["id"])
        variance = r2(actual - summ["expected"])
        db.execute("UPDATE cash_registers SET closed_at=?, closed_by=?, expected_cash=?, actual_cash=?, "
                   "variance=?, status='Closed', note=? WHERE id=?",
                   (now(), user["id"], summ["expected"], actual, variance, clean(note), reg["id"]))
        audit.log(db, user, "Register closed", "cash_register", reg["id"], None,
                  {"expected": summ["expected"], "actual": actual, "variance": variance})
    return register_summary(db, reg["id"])


def list_registers(db, user, limit=50):
    require(user, "cash.manage")
    return db.q("SELECT r.*, u.username AS opener FROM cash_registers r LEFT JOIN users u ON u.id=r.opened_by "
                "ORDER BY r.id DESC LIMIT ?", (limit,))


def register_transactions(db, register_id):
    return db.q("SELECT t.*, u.username FROM cash_transactions t LEFT JOIN users u ON u.id=t.user_id "
                "WHERE register_id=? ORDER BY t.id", (register_id,))


def daily_cash_report(db, register_id) -> str:
    s = register_summary(db, register_id)
    cur = settings.get(db, "currency")
    lines = [f"DAILY CASH REPORT - Register #{s['id']}", "=" * 46,
             f"Opened : {s['opened_at']}", f"Closed : {s['closed_at'] or '(still open)'}",
             "-" * 46, f"{'Opening cash':<28}{s['opening_cash']:>16,.2f}"]
    for k, v in sorted(s["by_kind"].items()):
        lines.append(f"{k:<28}{v:>16,.2f}")
    lines += ["-" * 46, f"{'Expected cash':<28}{s['expected']:>16,.2f}"]
    if s["status"] == "Closed":
        lines += [f"{'Actual cash':<28}{s['actual_cash']:>16,.2f}",
                  f"{'Variance':<28}{s['variance']:>16,.2f}"]
    lines.append(f"({cur})")
    return "\n".join(lines)


# ---------------------------------------------------------------- expenses
def expense_categories(db):
    return db.q("SELECT * FROM expense_categories ORDER BY name")


def add_expense_category(db, user, name):
    require(user, "expenses.manage")
    name = need(name, "Category name")
    if db.scalar("SELECT 1 FROM expense_categories WHERE name=?", (name,)):
        raise POSError("That expense category already exists.")
    with db.tx():
        return db.insert("INSERT INTO expense_categories(name) VALUES(?)", (name,))


def add_expense(db, user, category_id, date, amount, method, description):
    require(user, "expenses.manage")
    amount = to_float(amount, "Amount")
    if amount <= 0:
        raise POSError("Amount must be greater than zero.")
    date = valid_date(date)
    if not db.scalar("SELECT 1 FROM expense_categories WHERE id=?", (category_id,)):
        raise POSError("Select an expense category.")
    with db.tx():
        reg = open_register(db) if method == "Cash" else None
        eid = db.insert("INSERT INTO expenses(category_id,date,amount,method,description,user_id,register_id) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (category_id, date, amount, method, clean(description), user["id"], reg["id"] if reg else None))
        if method == "Cash":
            cash_post(db, user, "Expense", -amount, "expense", eid, description)
        audit.log(db, user, "Expense recorded", "expense", eid, None, {"amount": amount, "method": method})
        return eid


def delete_expense(db, user, expense_id):
    require(user, "expenses.manage")
    with db.tx():
        e = db.one("SELECT * FROM expenses WHERE id=?", (expense_id,))
        if not e:
            raise POSError("Expense not found.")
        if e["method"] == "Cash":
            cash_post(db, user, "Expense Void", e["amount"], "expense", expense_id, "Expense deleted")
        db.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
        audit.log(db, user, "Expense deleted", "expense", expense_id, e, None)


def list_expenses(db, user, date_from=None, date_to=None, category_id=None, limit=100, offset=0):
    require(user, "expenses.manage")
    where, p = ["1=1"], []
    if date_from:
        where.append("e.date>=?")
        p.append(date_from)
    if date_to:
        where.append("e.date<=?")
        p.append(date_to)
    if category_id:
        where.append("e.category_id=?")
        p.append(category_id)
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM expenses e WHERE {w}", p)
    sum_ = db.scalar(f"SELECT COALESCE(SUM(amount),0) FROM expenses e WHERE {w}", p)
    rows = db.q(f"SELECT e.*, c.name AS category, u.username FROM expenses e JOIN expense_categories c ON c.id=e.category_id "
                f"LEFT JOIN users u ON u.id=e.user_id WHERE {w} ORDER BY e.date DESC, e.id DESC LIMIT ? OFFSET ?",
                p + [limit, offset])
    return rows, total, r2(sum_)


# ----------------------------------------------------- customer payments
def receive_customer_payment(db, user, customer_id, amount, method, ref=None, note=None):
    require(user, "customers.payments")
    amount = to_float(amount, "Amount")
    if amount <= 0:
        raise POSError("Amount must be greater than zero.")
    if method not in ("Cash", "Bank Transfer", "Card", "Mobile Wallet"):
        raise POSError("Invalid payment method.")
    with db.tx():
        c = db.one("SELECT * FROM customers WHERE id=?", (customer_id,))
        if not c:
            raise POSError("Customer not found.")
        if amount > c["balance"] + 0.005:
            raise POSError(f"Payment exceeds the customer's outstanding balance ({c['balance']:,.2f}).")
        reg = open_register(db) if method == "Cash" else None
        pid = db.insert("INSERT INTO customer_payments(customer_id,date,amount,method,ref,note,user_id,register_id) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (customer_id, now(), amount, method, clean(ref), clean(note), user["id"],
                         reg["id"] if reg else None))
        post_ledger(db, "customer", customer_id, "Payment received", -amount, f"CP-{pid}", note, user)
        if method == "Cash":
            cash_post(db, user, "Customer Payment", amount, "customer_payment", pid, c["name"])
        audit.log(db, user, "Customer payment received", "customer", customer_id, None,
                  {"amount": amount, "method": method})
        return pid
