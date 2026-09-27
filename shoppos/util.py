"""Small shared helpers: errors, money rounding, dates, validation."""
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP


class POSError(Exception):
    """A business-rule / user-mistake error. The message is safe to show to users."""


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return dt.date.today().strftime("%Y-%m-%d")


def r2(x) -> float:
    if x is None:
        return 0.0
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money(x, cur: str = "") -> str:
    x = r2(x)
    s = f"{x:,.0f}" if abs(x - round(x)) < 0.005 else f"{x:,.2f}"
    return f"{cur} {s}".strip()


def to_float(s, field="Value", allow_negative=False) -> float:
    if isinstance(s, (int, float)):
        v = float(s)
    else:
        txt = str(s or "").replace(",", "").strip()
        if txt == "":
            return 0.0
        try:
            v = float(txt)
        except ValueError:
            raise POSError(f"{field} must be a number.")
    if v < 0 and not allow_negative:
        raise POSError(f"{field} cannot be negative.")
    return v


def to_int(s, field="Value", allow_negative=False) -> int:
    v = to_float(s, field, allow_negative)
    if abs(v - round(v)) > 1e-9:
        raise POSError(f"{field} must be a whole number.")
    return int(round(v))


def clean(s):
    s = (s or "").strip() if isinstance(s, str) else s
    return s or None


def need(s, field):
    s = (s or "").strip() if isinstance(s, str) else s
    if not s:
        raise POSError(f"{field} is required.")
    return s


def valid_date(s, field="Date") -> str:
    s = (s or "").strip()
    try:
        dt.datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        raise POSError(f"{field} must be in YYYY-MM-DD format.")
    return s[:10]


def like(s: str) -> str:
    s = (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{s}%"


def add_months(date_str: str, months: int) -> str:
    d = dt.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    import calendar
    day = min(d.day, calendar.monthrange(y, m)[1])
    return dt.date(y, m, day).strftime("%Y-%m-%d")


def days_between(a: str, b: str) -> int:
    da = dt.datetime.strptime(a[:10], "%Y-%m-%d").date()
    db_ = dt.datetime.strptime(b[:10], "%Y-%m-%d").date()
    return (db_ - da).days


def rows(cursor_rows):
    return [dict(r) for r in cursor_rows]
