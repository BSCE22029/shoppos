"""Paths, constants and the permission catalogue."""
import os
import sys

APP_NAME = "ShopPOS"
APP_DIR_NAME = "ShopPOS"
APP_VERSION = "1.0.0"


def data_dir() -> str:
    """Application data lives outside the install directory."""
    override = os.environ.get("SHOPPOS_DATA")
    if override:
        base = override
    elif os.name == "nt":
        base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_DIR_NAME)
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share", APP_DIR_NAME)
    return base


def ensure_dirs() -> dict:
    base = data_dir()
    d = {
        "base": base,
        "db": os.path.join(base, "pos.db"),
        "backups": os.path.join(base, "Backups"),
        "logs": os.path.join(base, "Logs"),
        "invoices": os.path.join(base, "Invoices"),
        "exports": os.path.join(base, "Exports"),
        "images": os.path.join(base, "Images"),
    }
    for k, v in d.items():
        if k != "db":
            os.makedirs(v, exist_ok=True)
    return d


def app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PAYMENT_METHODS = ["Cash", "Bank Transfer", "Card", "Mobile Wallet"]
# Methods accepted at the POS (Credit = amount left on customer account)
SALE_METHODS = PAYMENT_METHODS + ["Store Credit", "Credit"]
REFUND_METHODS = ["Cash", "Bank Transfer", "Card", "Mobile Wallet", "Store Credit"]

ROLES = ["Owner", "Admin", "Manager", "Cashier", "Inventory Manager",
         "Accountant", "Sales Staff", "Technician"]

PERMISSIONS = {
    "pos.sell": "Use the POS / make sales",
    "pos.discount": "Apply discounts at POS",
    "pos.price_override": "Change selling price at POS",
    "pos.below_min": "Sell below minimum selling price",
    "products.view": "View products",
    "products.edit": "Create / edit products",
    "products.delete": "Delete products",
    "products.cost": "See purchase cost / profit per product",
    "inventory.view": "View inventory",
    "inventory.adjust": "Adjust stock",
    "purchases.manage": "Purchases and goods receiving",
    "suppliers.manage": "Manage suppliers and pay them",
    "customers.view": "View customers",
    "customers.manage": "Create / edit customers",
    "customers.payments": "Receive customer payments",
    "sales.view": "View sales history",
    "sales.cancel": "Cancel sales",
    "returns.process": "Process returns / refunds",
    "warranty.view": "View warranty",
    "warranty.manage": "File and resolve warranty claims",
    "repairs.view": "View repairs",
    "repairs.manage": "Create / update repairs",
    "expenses.manage": "Record expenses",
    "cash.manage": "Open / close cash register",
    "reports.view": "View reports",
    "reports.financial": "View profit and financial data",
    "users.manage": "Manage users and permissions",
    "audit.view": "View audit log",
    "settings.manage": "Change settings",
    "backup.manage": "Backup and restore",
}

_ALL = set(PERMISSIONS)
ROLE_DEFAULTS = {
    "Owner": set(_ALL),
    "Admin": set(_ALL),
    "Manager": _ALL - {"users.manage", "settings.manage", "backup.manage"},
    "Cashier": {"pos.sell", "products.view", "customers.view", "customers.manage",
                "customers.payments", "sales.view", "cash.manage", "warranty.view",
                "inventory.view"},
    "Inventory Manager": {"products.view", "products.edit", "products.cost", "inventory.view",
                          "inventory.adjust", "purchases.manage", "suppliers.manage",
                          "reports.view", "warranty.view"},
    "Accountant": {"reports.view", "reports.financial", "expenses.manage", "sales.view",
                   "purchases.manage", "suppliers.manage", "customers.view",
                   "customers.payments", "cash.manage", "products.view", "products.cost",
                   "inventory.view", "audit.view"},
    "Sales Staff": {"pos.sell", "pos.discount", "products.view", "customers.view",
                    "customers.manage", "sales.view", "inventory.view", "warranty.view",
                    "customers.payments"},
    "Technician": {"repairs.view", "repairs.manage", "products.view", "inventory.view",
                   "warranty.view", "warranty.manage"},
}

DEFAULT_SETTINGS = {
    "shop_name": "Demo Computer Shop",
    "shop_address": "123 Main Street, Your City",
    "shop_phone": "021-32712345",
    "shop_email": "info@example.com",
    "tax_number": "",
    "currency": "PKR",
    "invoice_prefix": "INV-",
    "default_tax": "0",
    "default_discount": "0",
    "receipt_printer": "",
    "a4_printer": "",
    "label_printer": "",
    "invoice_template": "thermal",
    "receipt_footer": "Thank you for shopping with us!",
    "terms": "Goods once sold are not returnable without invoice. Warranty as per product terms; "
             "physical/liquid damage voids warranty.",
    "low_stock_default": "3",
    "allow_negative_stock": "0",
    "require_open_register": "1",
    "backup_dir": "",
    "backup_frequency": "daily",
    "backup_on_close": "1",
    "backup_keep": "30",
    "session_timeout_min": "15",
    "logo_path": "",
    "theme": "light",
    "warranty_soon_days": "30",
    "dead_stock_days": "90",
    "auto_print_receipt": "0",
    "demo_prompted": "0",
    "label_columns": "3",
}
