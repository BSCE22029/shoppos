"""Versioned schema migrations. Each entry is applied once, in order, and
recorded in PRAGMA user_version. Add new schema changes as new list items;
never edit an existing one after release."""

V1 = """
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sequences(name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);

-- multi-store ready ---------------------------------------------------------
CREATE TABLE branches(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, address TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE warehouses(
  id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL REFERENCES branches(id),
  name TEXT NOT NULL, UNIQUE(branch_id, name));
CREATE TABLE stock_transfers(
  id INTEGER PRIMARY KEY, transfer_no TEXT UNIQUE, from_warehouse_id INTEGER REFERENCES warehouses(id),
  to_warehouse_id INTEGER REFERENCES warehouses(id), product_id INTEGER, qty INTEGER,
  date TEXT, user_id INTEGER, status TEXT, note TEXT);

-- security -----------------------------------------------------------------
CREATE TABLE roles(name TEXT PRIMARY KEY, description TEXT);
CREATE TABLE role_permissions(
  role TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE ON UPDATE CASCADE,
  permission TEXT NOT NULL, PRIMARY KEY(role, permission));
CREATE TABLE users(
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, full_name TEXT NOT NULL,
  password_hash TEXT NOT NULL, salt TEXT NOT NULL,
  role TEXT NOT NULL REFERENCES roles(name) ON UPDATE CASCADE,
  active INTEGER NOT NULL DEFAULT 1, failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT, last_login TEXT, must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);

-- catalogue -----------------------------------------------------------------
CREATE TABLE categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, parent_id INTEGER REFERENCES categories(id),
  UNIQUE(name, parent_id));
CREATE UNIQUE INDEX ux_categories_top ON categories(name) WHERE parent_id IS NULL;
CREATE TABLE brands(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
CREATE TABLE suppliers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT, phone TEXT, email TEXT, address TEXT,
  payment_terms TEXT, opening_balance REAL NOT NULL DEFAULT 0, balance REAL NOT NULL DEFAULT 0,
  notes TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE customers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT, phone TEXT, email TEXT, address TEXT,
  credit_limit REAL NOT NULL DEFAULT 0, opening_balance REAL NOT NULL DEFAULT 0,
  balance REAL NOT NULL DEFAULT 0, store_credit REAL NOT NULL DEFAULT 0,
  notes TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE products(
  id INTEGER PRIMARY KEY,
  sku TEXT NOT NULL UNIQUE COLLATE NOCASE,
  barcode TEXT COLLATE NOCASE,
  name TEXT NOT NULL,
  brand_id INTEGER REFERENCES brands(id),
  category_id INTEGER REFERENCES categories(id),
  subcategory_id INTEGER REFERENCES categories(id),
  model TEXT, description TEXT,
  purchase_price REAL NOT NULL DEFAULT 0,
  wholesale_price REAL NOT NULL DEFAULT 0,
  retail_price REAL NOT NULL DEFAULT 0,
  min_price REAL NOT NULL DEFAULT 0,
  stock INTEGER NOT NULL DEFAULT 0,
  damaged INTEGER NOT NULL DEFAULT 0,
  min_stock INTEGER NOT NULL DEFAULT 0,
  warranty_months INTEGER NOT NULL DEFAULT 0,
  tax_percent REAL NOT NULL DEFAULT 0,
  discount_percent REAL NOT NULL DEFAULT 0,
  supplier_id INTEGER REFERENCES suppliers(id),
  image_path TEXT, rack TEXT, location TEXT,
  serialized INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX ux_products_barcode ON products(barcode) WHERE barcode IS NOT NULL;
CREATE INDEX ix_products_name ON products(name COLLATE NOCASE);
CREATE INDEX ix_products_cat ON products(category_id);
CREATE INDEX ix_products_brand ON products(brand_id);
CREATE INDEX ix_products_active ON products(active);
CREATE TABLE product_variants(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  name TEXT NOT NULL, sku TEXT UNIQUE, barcode TEXT, price_delta REAL NOT NULL DEFAULT 0);
CREATE TABLE serials(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  serial TEXT NOT NULL UNIQUE COLLATE NOCASE,
  status TEXT NOT NULL DEFAULT 'In Stock'
     CHECK(status IN ('In Stock','Sold','Damaged','Returned to Supplier','Replaced')),
  purchase_id INTEGER, supplier_id INTEGER, purchase_cost REAL NOT NULL DEFAULT 0,
  sale_id INTEGER, sale_item_id INTEGER, customer_id INTEGER, sold_price REAL, sold_at TEXT,
  warranty_start TEXT, warranty_expiry TEXT, note TEXT, created_at TEXT NOT NULL);
CREATE INDEX ix_serials_prod ON serials(product_id, status);
CREATE INDEX ix_serials_sale ON serials(sale_id);

-- stock ledger ---------------------------------------------------------------
CREATE TABLE inventory_transactions(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  date TEXT NOT NULL, type TEXT NOT NULL, qty_change INTEGER NOT NULL DEFAULT 0,
  damaged_change INTEGER NOT NULL DEFAULT 0, unit_cost REAL, stock_after INTEGER,
  reason TEXT, ref_type TEXT, ref_id INTEGER, user_id INTEGER);
CREATE INDEX ix_invtx_prod ON inventory_transactions(product_id, date);
CREATE INDEX ix_invtx_date ON inventory_transactions(date);

-- ledger for customers and suppliers ------------------------------------------
CREATE TABLE ledger(
  id INTEGER PRIMARY KEY, party_type TEXT NOT NULL CHECK(party_type IN ('customer','supplier')),
  party_id INTEGER NOT NULL, date TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT,
  amount REAL NOT NULL, note TEXT, user_id INTEGER);
CREATE INDEX ix_ledger_party ON ledger(party_type, party_id, date);

-- cash -----------------------------------------------------------------------
CREATE TABLE cash_registers(
  id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL DEFAULT 1, opened_at TEXT NOT NULL,
  opened_by INTEGER, opening_cash REAL NOT NULL DEFAULT 0, closed_at TEXT, closed_by INTEGER,
  expected_cash REAL, actual_cash REAL, variance REAL,
  status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Closed')), note TEXT);
CREATE UNIQUE INDEX ux_register_open ON cash_registers(branch_id) WHERE status='Open';
CREATE TABLE cash_transactions(
  id INTEGER PRIMARY KEY, register_id INTEGER NOT NULL REFERENCES cash_registers(id),
  date TEXT NOT NULL, kind TEXT NOT NULL, amount REAL NOT NULL, ref_type TEXT, ref_id INTEGER,
  note TEXT, user_id INTEGER);
CREATE INDEX ix_cash_reg ON cash_transactions(register_id);

-- sales ------------------------------------------------------------------------
CREATE TABLE sales(
  id INTEGER PRIMARY KEY, invoice_no TEXT NOT NULL UNIQUE, date TEXT NOT NULL,
  customer_id INTEGER REFERENCES customers(id), user_id INTEGER NOT NULL REFERENCES users(id),
  branch_id INTEGER NOT NULL DEFAULT 1,
  subtotal REAL NOT NULL, line_discount REAL NOT NULL DEFAULT 0, overall_discount REAL NOT NULL DEFAULT 0,
  tax REAL NOT NULL DEFAULT 0, total REAL NOT NULL, paid REAL NOT NULL DEFAULT 0,
  credit REAL NOT NULL DEFAULT 0, credit_offset REAL NOT NULL DEFAULT 0, cost_total REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'Completed'
     CHECK(status IN ('Completed','Cancelled','Partially Returned','Returned')),
  notes TEXT, register_id INTEGER, cancelled_at TEXT, cancel_reason TEXT);
CREATE INDEX ix_sales_date ON sales(date);
CREATE INDEX ix_sales_customer ON sales(customer_id);
CREATE INDEX ix_sales_user ON sales(user_id);
CREATE TABLE sale_items(
  id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL,
  unit_price REAL NOT NULL, line_discount REAL NOT NULL DEFAULT 0, overall_alloc REAL NOT NULL DEFAULT 0,
  net REAL NOT NULL, tax_percent REAL NOT NULL DEFAULT 0, tax REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL, cost_total REAL NOT NULL DEFAULT 0, returned_qty INTEGER NOT NULL DEFAULT 0,
  warranty_months INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ix_saleitems_sale ON sale_items(sale_id);
CREATE INDEX ix_saleitems_prod ON sale_items(product_id);
CREATE TABLE sale_serials(
  id INTEGER PRIMARY KEY, sale_item_id INTEGER NOT NULL REFERENCES sale_items(id) ON DELETE CASCADE,
  serial_id INTEGER NOT NULL REFERENCES serials(id), returned INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ix_saleserials_item ON sale_serials(sale_item_id);
CREATE INDEX ix_saleserials_serial ON sale_serials(serial_id);
CREATE TABLE sale_payments(
  id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  method TEXT NOT NULL, amount REAL NOT NULL, ref TEXT, date TEXT NOT NULL);
CREATE INDEX ix_salepay_sale ON sale_payments(sale_id);
CREATE TABLE held_sales(
  id INTEGER PRIMARY KEY, user_id INTEGER, customer_id INTEGER, cart_json TEXT NOT NULL,
  note TEXT, created_at TEXT NOT NULL);
CREATE TABLE customer_payments(
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), date TEXT NOT NULL,
  amount REAL NOT NULL, method TEXT NOT NULL, ref TEXT, note TEXT, user_id INTEGER, register_id INTEGER);

-- returns ----------------------------------------------------------------------
CREATE TABLE returns(
  id INTEGER PRIMARY KEY, return_no TEXT NOT NULL UNIQUE, sale_id INTEGER NOT NULL REFERENCES sales(id),
  customer_id INTEGER, date TEXT NOT NULL, user_id INTEGER, refund_method TEXT,
  refund_amount REAL NOT NULL DEFAULT 0, credit_offset REAL NOT NULL DEFAULT 0,
  amount REAL NOT NULL, net REAL NOT NULL, tax REAL NOT NULL, cost REAL NOT NULL DEFAULT 0,
  note TEXT, branch_id INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_returns_sale ON returns(sale_id);
CREATE TABLE return_items(
  id INTEGER PRIMARY KEY, return_id INTEGER NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
  sale_item_id INTEGER NOT NULL REFERENCES sale_items(id), product_id INTEGER NOT NULL,
  qty INTEGER NOT NULL, amount REAL NOT NULL, net REAL NOT NULL, tax REAL NOT NULL,
  cost REAL NOT NULL DEFAULT 0, condition TEXT NOT NULL DEFAULT 'Good', serial_id INTEGER);

-- purchasing ---------------------------------------------------------------------
CREATE TABLE purchases(
  id INTEGER PRIMARY KEY, po_number TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  supplier_invoice TEXT, date TEXT NOT NULL, expected_date TEXT,
  status TEXT NOT NULL DEFAULT 'Ordered'
     CHECK(status IN ('Ordered','Partially Received','Received','Cancelled')),
  total REAL NOT NULL DEFAULT 0, received_value REAL NOT NULL DEFAULT 0, paid REAL NOT NULL DEFAULT 0,
  notes TEXT, user_id INTEGER, branch_id INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_purchases_supplier ON purchases(supplier_id);
CREATE TABLE purchase_items(
  id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL, unit_cost REAL NOT NULL,
  received_qty INTEGER NOT NULL DEFAULT 0);
CREATE TABLE purchase_payments(
  id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), purchase_id INTEGER,
  date TEXT NOT NULL, amount REAL NOT NULL, method TEXT NOT NULL, ref TEXT, note TEXT, user_id INTEGER);
CREATE TABLE purchase_returns(
  id INTEGER PRIMARY KEY, return_no TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  date TEXT NOT NULL, total REAL NOT NULL, note TEXT, user_id INTEGER);
CREATE TABLE purchase_return_items(
  id INTEGER PRIMARY KEY, return_id INTEGER NOT NULL REFERENCES purchase_returns(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL, qty INTEGER NOT NULL, unit_cost REAL NOT NULL, serial_id INTEGER);

-- warranty -------------------------------------------------------------------------
CREATE TABLE warranties(
  id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL, sale_item_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL, serial_id INTEGER, customer_id INTEGER,
  start_date TEXT NOT NULL, expiry_date TEXT NOT NULL, months INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'Active' CHECK(status IN ('Active','Claimed','Replaced','Void')),
  created_at TEXT NOT NULL);
CREATE INDEX ix_warranty_serial ON warranties(serial_id);
CREATE INDEX ix_warranty_sale ON warranties(sale_id);
CREATE INDEX ix_warranty_cust ON warranties(customer_id);
CREATE TABLE warranty_claims(
  id INTEGER PRIMARY KEY, warranty_id INTEGER NOT NULL REFERENCES warranties(id),
  date TEXT NOT NULL, issue TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Repaired','Replaced','Rejected')),
  resolution TEXT, replacement_serial_id INTEGER, user_id INTEGER, closed_at TEXT);

-- repairs --------------------------------------------------------------------------
CREATE TABLE repairs(
  id INTEGER PRIMARY KEY, ticket_no TEXT NOT NULL UNIQUE, customer_id INTEGER REFERENCES customers(id),
  customer_name TEXT, customer_phone TEXT,
  device TEXT NOT NULL, brand TEXT, model TEXT, serial TEXT, complaint TEXT NOT NULL,
  condition TEXT, accessories TEXT, technician_id INTEGER REFERENCES users(id),
  estimated_cost REAL NOT NULL DEFAULT 0, labor_charge REAL NOT NULL DEFAULT 0,
  final_cost REAL NOT NULL DEFAULT 0, paid REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'Received'
     CHECK(status IN ('Received','Diagnosing','Waiting for Customer','Waiting for Parts',
                      'In Repair','Ready','Delivered','Cancelled')),
  received_at TEXT NOT NULL, expected_at TEXT, completed_at TEXT, delivered_at TEXT, user_id INTEGER);
CREATE INDEX ix_repairs_status ON repairs(status);
CREATE TABLE repair_notes(
  id INTEGER PRIMARY KEY, repair_id INTEGER NOT NULL REFERENCES repairs(id) ON DELETE CASCADE,
  date TEXT NOT NULL, user_id INTEGER, note TEXT NOT NULL);
CREATE TABLE repair_parts(
  id INTEGER PRIMARY KEY, repair_id INTEGER NOT NULL REFERENCES repairs(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL,
  unit_price REAL NOT NULL, unit_cost REAL NOT NULL DEFAULT 0, serial_id INTEGER);
CREATE TABLE repair_payments(
  id INTEGER PRIMARY KEY, repair_id INTEGER NOT NULL REFERENCES repairs(id) ON DELETE CASCADE,
  date TEXT NOT NULL, method TEXT NOT NULL, amount REAL NOT NULL, ref TEXT, user_id INTEGER);

-- expenses ------------------------------------------------------------------------
CREATE TABLE expense_categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
CREATE TABLE expenses(
  id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES expense_categories(id),
  date TEXT NOT NULL, amount REAL NOT NULL, method TEXT NOT NULL, description TEXT,
  user_id INTEGER, register_id INTEGER, branch_id INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_expenses_date ON expenses(date);

-- audit ------------------------------------------------------------------------------
CREATE TABLE audit_logs(
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, user_id INTEGER, username TEXT,
  action TEXT NOT NULL, entity TEXT, entity_id TEXT, old_value TEXT, new_value TEXT);
CREATE INDEX ix_audit_date ON audit_logs(date);
CREATE INDEX ix_audit_entity ON audit_logs(entity, entity_id);

INSERT INTO branches(id, name) VALUES (1, 'Main Shop');
INSERT INTO warehouses(id, branch_id, name) VALUES (1, 1, 'Main Warehouse');
"""

V2 = """
-- performance: indexes for report joins and lookups
CREATE INDEX ix_return_items_si ON return_items(sale_item_id);
CREATE INDEX ix_return_items_ret ON return_items(return_id);
CREATE INDEX ix_purchase_items_po ON purchase_items(purchase_id);
CREATE INDEX ix_purchase_items_prod ON purchase_items(product_id);
CREATE INDEX ix_repair_parts_repair ON repair_parts(repair_id);
CREATE INDEX ix_returns_date ON returns(date)
"""

MIGRATIONS = [V1, V2]
