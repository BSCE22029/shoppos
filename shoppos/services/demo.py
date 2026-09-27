"""Realistic demo data (created through the real services, so every rule is exercised)
and a one-click reset that removes all business data before going live."""
import random
import string

from ..util import POSError, now, today, add_months
from . import (audit, backup, catalog, finance, inventory, parties, purchasing, repairs, returns, sales,
               warranty)
from .auth import require

SUPPLIERS = [
    ("ABC Computers", "ABC Computers (Pvt) Ltd", "0300-1112233", "Saddar, Karachi", "30 days"),
    ("Star Peripherals", "Star Peripherals", "0321-2223344", "Hafeez Center, Lahore", "15 days"),
    ("Tech Distributors", "Tech Distributors Pakistan", "0333-4445566", "Clifton, Karachi", "Cash"),
    ("Network Hub", "Network Hub Trading", "0345-7778899", "Rawalpindi", "7 days"),
]
CUSTOMERS = [
    ("Muhammad Ali", "0300-1234567", 50000), ("Ayesha Traders", "0321-9876543", 300000),
    ("Bilal Ahmed", "0333-1112221", 0), ("Sana Khan", "0345-5556677", 0),
    ("Al-Noor Solutions", "0312-3334445", 500000), ("Usman Malik", "0302-8889990", 20000),
    ("Fatima Zahra", "0311-2223331", 0), ("City School System", "0322-6667778", 400000),
]
# sku, name, brand, category, subcategory, cost, wholesale, retail, min, min_stock, warranty, serialized, qty
P = [
    ("LAP-DL-5440", "Dell Latitude 5440 i5 16GB 512GB", "Dell", "Laptops", "Business", 145000, 158000, 165000, 150000, 2, 12, 1, 6),
    ("LAP-DL-3520", "Dell Inspiron 15 3520 i3 8GB 256GB", "Dell", "Laptops", "Business", 98000, 106000, 112000, 100000, 2, 12, 1, 5),
    ("LAP-HP-840G9", "HP EliteBook 840 G9 i7 16GB 512GB", "HP", "Laptops", "Business", 178000, 192000, 199000, 182000, 2, 12, 1, 4),
    ("LAP-HP-250G9", "HP 250 G9 i5 8GB 512GB", "HP", "Laptops", "Business", 82000, 89000, 94500, 84000, 2, 12, 1, 8),
    ("LAP-LN-T14", "Lenovo ThinkPad T14 Gen3 i5 16GB", "Lenovo", "Laptops", "Business", 168000, 178000, 185000, 170000, 2, 12, 1, 5),
    ("LAP-LN-IP3", "Lenovo IdeaPad Slim 3 Ryzen 5 8GB", "Lenovo", "Laptops", "Business", 89000, 96000, 102000, 91000, 2, 12, 1, 7),
    ("LAP-LN-LOQ", "Lenovo LOQ 15 Gaming i5 RTX 3050", "Lenovo", "Laptops", "Gaming", 215000, 229000, 239000, 220000, 1, 12, 1, 3),
    ("PC-GAM-R5", "Gaming PC Ryzen 5 5600 / RTX 3060 / 16GB", "Custom", "Desktops", None, 165000, 178000, 189000, 168000, 1, 12, 1, 3),
    ("PC-GAM-I7", "Gaming PC Core i7-13700F / RTX 4070 / 32GB", "Custom", "Desktops", None, 320000, 342000, 355000, 325000, 1, 12, 1, 2),
    ("PC-OFF-I3", "Office PC Core i3-12100 / 8GB / 256GB SSD", "Custom", "Desktops", None, 62000, 68000, 72000, 63000, 2, 12, 1, 6),
    ("CPU-I5-13400F", "Intel Core i5-13400F", "Intel", "Components", "CPU", 38500, 41000, 42500, 39000, 2, 36, 1, 8),
    ("CPU-I7-13700K", "Intel Core i7-13700K", "Intel", "Components", "CPU", 84000, 88500, 91000, 85000, 1, 36, 1, 4),
    ("CPU-R5-5600", "AMD Ryzen 5 5600", "AMD", "Components", "CPU", 24500, 26500, 27500, 25000, 2, 36, 1, 8),
    ("CPU-R7-7700X", "AMD Ryzen 7 7700X", "AMD", "Components", "CPU", 56000, 59500, 61500, 57000, 1, 36, 1, 4),
    ("GPU-RTX3060", "NVIDIA GeForce RTX 3060 12GB", "NVIDIA", "Components", "GPU", 84000, 89000, 92000, 85000, 1, 36, 1, 4),
    ("GPU-RTX4060", "NVIDIA GeForce RTX 4060 8GB", "NVIDIA", "Components", "GPU", 98000, 104000, 108000, 99000, 1, 36, 1, 4),
    ("GPU-RTX4070", "NVIDIA GeForce RTX 4070 12GB", "NVIDIA", "Components", "GPU", 172000, 183000, 189000, 175000, 1, 36, 1, 2),
    ("RAM-KF-8D4", "Kingston Fury 8GB DDR4 3200", "Kingston", "Components", "RAM", 6200, 6900, 7300, 6400, 10, 60, 0, 40),
    ("RAM-KF-16D5", "Kingston Fury 16GB DDR5 5600", "Kingston", "Components", "RAM", 13500, 14800, 15500, 13900, 8, 60, 0, 25),
    ("SSD-SM-980-1T", "Samsung 980 NVMe SSD 1TB", "Samsung", "Components", "Storage", 16500, 18000, 19000, 17000, 6, 60, 0, 30),
    ("SSD-SM-870-500", "Samsung 870 EVO SSD 500GB", "Samsung", "Components", "Storage", 11000, 12200, 12800, 11400, 6, 60, 0, 20),
    ("HDD-WD-1T", "WD Blue 1TB HDD", "WD", "Components", "Storage", 7800, 8700, 9200, 8000, 6, 24, 0, 25),
    ("HDD-WD-2T", "WD Blue 2TB HDD", "WD", "Components", "Storage", 11500, 12800, 13500, 11900, 4, 24, 0, 15),
    ("KB-LG-K120", "Logitech K120 USB Keyboard", "Logitech", "Peripherals", "Keyboards", 1250, 1450, 1600, 1300, 10, 12, 0, 60),
    ("KB-LG-MK270", "Logitech MK270 Keyboard + Mouse", "Logitech", "Peripherals", "Keyboards", 4200, 4800, 5200, 4400, 5, 12, 0, 20),
    ("MS-LG-B100", "Logitech B100 USB Mouse", "Logitech", "Peripherals", "Mice", 650, 800, 950, 700, 15, 12, 0, 80),
    ("MS-LG-M185", "Logitech M185 Wireless Mouse", "Logitech", "Peripherals", "Mice", 1900, 2200, 2400, 2000, 8, 12, 0, 40),
    ("NET-TP-C6", "TP-Link Archer C6 AC1200 Router", "TP-Link", "Networking", None, 5600, 6300, 6800, 5800, 4, 24, 1, 20),
    ("NET-TP-SG108", "TP-Link TL-SG108 8-Port Switch", "TP-Link", "Networking", None, 3800, 4300, 4700, 3900, 4, 24, 0, 15),
    ("NET-TP-WN725", "TP-Link TL-WN725N WiFi Adapter", "TP-Link", "Networking", None, 1400, 1700, 1900, 1500, 6, 12, 0, 30),
    ("ACC-CHG-DL", "Dell 65W Laptop Charger", "Dell", "Accessories", "Chargers", 2600, 3200, 3600, 2800, 5, 6, 0, 25),
    ("ACC-CHG-HP", "HP 65W Laptop Charger", "HP", "Accessories", "Chargers", 2500, 3100, 3400, 2700, 5, 6, 0, 20),
    ("ACC-CHG-LN", "Lenovo 65W Laptop Charger", "Lenovo", "Accessories", "Chargers", 2700, 3300, 3700, 2900, 5, 6, 0, 20),
    ("CBL-HDMI-2M", "HDMI Cable 2 Meter", "Generic", "Accessories", "Cables", 320, 480, 600, 350, 20, 3, 0, 100),
    ("CBL-HDMI-5M", "HDMI Cable 5 Meter", "Generic", "Accessories", "Cables", 650, 900, 1100, 700, 10, 3, 0, 50),
    ("ACC-BAG-15", "Laptop Backpack 15.6 inch", "Generic", "Accessories", None, 1500, 2000, 2400, 1600, 5, 0, 0, 30),
    ("MON-DL-24", "Dell 24 inch Monitor P2422H", "Dell", "Peripherals", "Monitors", 38000, 41500, 44000, 39000, 2, 36, 1, 6),
    ("PRN-HP-M111", "HP LaserJet M111a Printer", "HP", "Peripherals", "Printers", 28000, 30500, 33500, 29000, 2, 12, 1, 5),
]
PREFIX = {"LAP-DL": "DL", "LAP-HP": "HPL", "LAP-LN": "LNV", "PC-GAM": "GPC", "PC-OFF": "OPC", "CPU-I5": "CPUI5",
          "CPU-I7": "CPUI7", "CPU-R5": "CPUR5", "CPU-R7": "CPUR7", "GPU-RT": "GPU", "NET-TP": "TPL",
          "MON-DL": "MON", "PRN-HP": "PRN"}


def _serial(rnd, sku, used):
    pre = next((v for k, v in PREFIX.items() if sku.startswith(k)), "SN")
    while True:
        s = pre + "".join(rnd.choices(string.ascii_uppercase + string.digits, k=8))
        if s not in used:
            used.add(s)
            return s


def _backdate_sale(db, sale_id, days, hour):
    stamp = db.scalar("SELECT strftime('%Y-%m-%d %H:%M:%S', datetime('now','localtime', ?, ?))",
                      (f"-{days} days", f"-{hour} hours"))
    day = stamp[:10]
    db.execute("UPDATE sales SET date=? WHERE id=?", (stamp, sale_id))
    db.execute("UPDATE sale_payments SET date=? WHERE sale_id=?", (stamp, sale_id))
    db.execute("UPDATE inventory_transactions SET date=? WHERE ref_type='sale' AND ref_id=?", (stamp, sale_id))
    db.execute("UPDATE serials SET sold_at=? WHERE sale_id=?", (stamp, sale_id))
    for w in db.q("SELECT * FROM warranties WHERE sale_id=?", (sale_id,)):
        exp = add_months(day, w["months"])
        db.execute("UPDATE warranties SET start_date=?, expiry_date=? WHERE id=?", (day, exp, w["id"]))
        if w["serial_id"]:
            db.execute("UPDATE serials SET warranty_start=?, warranty_expiry=? WHERE id=?", (day, exp, w["serial_id"]))
    inv = db.scalar("SELECT invoice_no FROM sales WHERE id=?", (sale_id,))
    db.execute("UPDATE ledger SET date=? WHERE ref=?", (stamp, inv))


def load_demo(db, user, seed=7):
    """Populate a fresh database with demo data. Refuses if products already exist."""
    require(user, "settings.manage")
    if db.scalar("SELECT COUNT(*) FROM products"):
        raise POSError("Demo data can only be loaded into an empty shop (no products yet).")
    rnd = random.Random(seed)
    used_serials = set()
    if not finance.open_register(db):
        finance.open_new_register(db, user, 50000)

    sup_ids = [parties.save_supplier(db, user, {"name": n, "company": c, "phone": ph, "address": ad, "payment_terms": t})
               for n, c, ph, ad, t in SUPPLIERS]
    cust_ids = [parties.save_customer(db, user, {"name": n, "phone": ph, "credit_limit": lim,
                                                 "address": "Karachi"}) for n, ph, lim in CUSTOMERS]
    cats, subs, brands = {}, {}, {}
    for _, _, br, cat, sub, *_ in P:
        if br not in brands:
            brands[br] = catalog.add_brand(db, user, br)
        if cat not in cats:
            cats[cat] = catalog.add_category(db, user, cat)
        if sub and (cat, sub) not in subs:
            subs[(cat, sub)] = catalog.add_category(db, user, sub, cats[cat])
    prod_ids = {}
    for i, (sku, name, br, cat, sub, cost, whl, retail, minp, mins, warr, ser, qty) in enumerate(P):
        prod_ids[sku] = catalog.save_product(db, user, {
            "sku": sku, "name": name, "barcode": f"89600{i + 1:08d}", "brand_id": brands[br], "category_id": cats[cat],
            "subcategory_id": subs.get((cat, sub)), "purchase_price": cost, "wholesale_price": whl, "retail_price": retail,
            "min_price": minp, "min_stock": mins, "warranty_months": warr, "serialized": ser,
            "rack": f"R{(i % 8) + 1}", "location": "Main Shop", "supplier_id": sup_ids[i % len(sup_ids)]})

    # purchases: receive everything (serials for serialized products), pay most of it
    for si, sid in enumerate(sup_ids):
        items = [(sku, qty, cost, ser) for k, (sku, _n, _b, _c, _s, cost, _w, _r, _m, _ms, _wa, ser, qty) in enumerate(P)
                 if k % len(sup_ids) == si]
        pid = purchasing.create_purchase(db, user, sid, [
            {"product_id": prod_ids[s], "qty": q, "unit_cost": c} for s, q, c, _ in items],
            supplier_invoice=f"SI-{1000 + si}", notes="Demo stock")
        po = purchasing.get_purchase(db, pid)
        receipts = []
        for it in po["items"]:
            sku = next(s for s, q, c, ser in items if prod_ids[s] == it["product_id"])
            serials = [_serial(rnd, sku, used_serials) for _ in range(it["qty"])] if it["serialized"] else None
            receipts.append({"item_id": it["id"], "qty": it["qty"], "serials": serials})
        purchasing.receive_purchase(db, user, pid, receipts)
        days = 60 - si * 5
        db.execute("UPDATE purchases SET date=datetime('now','localtime',?) WHERE id=?", (f"-{days} days", pid))
        db.execute("UPDATE inventory_transactions SET date=datetime('now','localtime',?) WHERE ref_type='purchase' AND ref_id=?",
                   (f"-{days} days", pid))
        db.execute("UPDATE ledger SET date=datetime('now','localtime',?) WHERE ref=?", (f"-{days} days", po["po_number"]))
        owed =db.scalar("SELECT balance FROM suppliers WHERE id=?", (sid,))
        if si != 3:
            purchasing.pay_supplier(db, user, sid, round(owed * 0.7, 2), "Bank Transfer", pid, ref=f"TT{rnd.randint(1000, 9999)}")

    # sales over the last ~35 days
    ids = list(prod_ids.values())
    made = []
    for n in range(70):
        for _try in range(10):
            try:
                cart_items, seen = [], set()
                for _ in range(rnd.choice([1, 1, 1, 2, 2, 3])):
                    pid = rnd.choice(ids)
                    if pid in seen:
                        continue
                    seen.add(pid)
                    p = db.one("SELECT * FROM products WHERE id=?", (pid,))
                    if p["stock"] <= 0:
                        continue
                    q = 1 if p["serialized"] else min(p["stock"], rnd.choice([1, 1, 2, 3]))
                    it = {"product_id": pid, "qty": q}
                    if p["serialized"]:
                        it["serial_ids"] = [s["id"] for s in catalog.available_serials(db, pid)[:q]]
                    if rnd.random() < 0.12:
                        it["discount"] = round(p["retail_price"] * 0.02 * q, 0)
                    cart_items.append(it)
                if not cart_items:
                    continue
                cust = rnd.choice(cust_ids + [None, None, None])
                cart = {"customer_id": cust, "items": cart_items, "overall_discount": 0}
                total = sales.preview_totals(db, cart)["total"]
                c = parties.get_customer(db, cust) if cust else None
                mode = rnd.random()
                if c and c["credit_limit"] - c["balance"] > total * 0.5 and mode < 0.25:
                    credit = round(total * rnd.choice([0.3, 0.5, 1.0]), 0)
                    pays = [{"method": "Credit", "amount": credit}]
                    if total - credit > 0:
                        pays.append({"method": "Cash", "amount": round(total - credit, 2)})
                elif mode < 0.55:
                    pays = [{"method": "Cash", "amount": total}]
                elif mode < 0.75:
                    pays = [{"method": "Card", "amount": total}]
                elif mode < 0.9:
                    half = round(total / 2, 2)
                    pays = [{"method": "Cash", "amount": half}, {"method": "Bank Transfer", "amount": round(total - half, 2)}]
                else:
                    pays = [{"method": "Mobile Wallet", "amount": total}]
                cart["payments"] = pays
                res = sales.complete_sale(db, user, cart)
                _backdate_sale(db, res["sale_id"], rnd.randint(0, 35), rnd.randint(0, 9))
                made.append(res)
                break
            except POSError:
                continue

    # returns, a cancellation, and warranty claim
    done = made
    if len(done) >= 6:
        s1 = sales.get_sale(db, done[1]["sale_id"])
        it = s1["items"][0]
        sids = [r["serial_id"] for r in it["serial_rows"]][:1] if it["serialized"] else []
        returns.process_return(db, user, s1["id"], [{"sale_item_id": it["id"], "qty": 1, "serial_ids": sids,
                                                     "condition": "Good"}],
                               "Cash" if not s1["customer_id"] else "Store Credit", "Customer changed mind")
        s2 = sales.get_sale(db, done[3]["sale_id"])
        it2 = s2["items"][0]
        sids2 = [r["serial_id"] for r in it2["serial_rows"]][:1] if it2["serialized"] else []
        returns.process_return(db, user, s2["id"], [{"sale_item_id": it2["id"], "qty": 1, "serial_ids": sids2,
                                                     "condition": "Damaged"}],
                               "Cash" if not s2["customer_id"] else "Store Credit", "Faulty on arrival")
        try:
            sales.cancel_sale(db, user, done[5]["sale_id"], "Wrong item entered")
        except POSError:
            pass
        for r in db.q("SELECT id FROM warranties WHERE status='Active' AND serial_id IS NOT NULL ORDER BY id LIMIT 1"):
            warranty.file_claim(db, user, r["id"], "Laptop does not power on after a week")
    for r in db.q("SELECT r.id, s.date FROM returns r JOIN sales s ON s.id=r.sale_id"):
        db.execute("UPDATE returns SET date=? WHERE id=?", (r["date"], r["id"]))
        db.execute("UPDATE inventory_transactions SET date=? WHERE ref_type='return' AND ref_id=?", (r["date"], r["id"]))
    # customer payments on credit
    for c in db.q("SELECT id,balance FROM customers WHERE balance>1000 LIMIT 2"):
        finance.receive_customer_payment(db, user, c["id"], round(c["balance"] / 2, 0), "Cash", note="Part payment")

    # repairs
    techs = [u["id"] for u in db.q("SELECT id FROM users WHERE active=1")]
    tid = techs[0]
    demo_repairs = [
        ("Laptop", "Dell", "Inspiron 5570", "Screen flickering", "Received", 3500),
        ("Desktop PC", "Custom", "", "Not booting - no display", "Diagnosing", 2500),
        ("Laptop", "HP", "Pavilion 15", "Battery not charging", "Waiting for Parts", 4500),
        ("Printer", "HP", "LaserJet 1020", "Paper jam / rollers worn", "In Repair", 2000),
        ("Laptop", "Lenovo", "IdeaPad 320", "Keyboard replacement + OS reinstall", "Ready", 6000),
    ]
    for dev, br, mdl, comp, st, est in demo_repairs:
        rid = repairs.create_repair(db, user, {"customer_id": rnd.choice(cust_ids), "device": dev, "brand": br, "model": mdl,
                                               "complaint": comp, "condition": "Minor scratches", "accessories": "Charger",
                                               "technician_id": tid, "estimated_cost": est, "expected_at": today()})
        if st != "Received":
            repairs.set_status(db, user, rid, st, "Updated during demo setup")
        if st == "Ready":
            kb = db.scalar("SELECT id FROM products WHERE sku='ACC-CHG-LN'")
            repairs.add_part(db, user, rid, kb, 1)
            repairs.set_labor(db, user, rid, 2500)
    ready = db.scalar("SELECT id FROM repairs WHERE status='Ready' LIMIT 1")
    if ready:
        due = repairs.get_repair(db, ready)["final_cost"]
        repairs.deliver_repair(db, user, ready, [{"method": "Cash", "amount": due}])

    # expenses
    cats_e = {c["name"]: c["id"] for c in finance.expense_categories(db)}
    for cat, amt, meth, d in [("Rent", 60000, "Bank Transfer", 30), ("Electricity", 18500, "Cash", 20),
                              ("Internet", 4500, "Bank Transfer", 18), ("Salaries", 95000, "Bank Transfer", 5),
                              ("Transport", 3200, "Cash", 12), ("Marketing", 8000, "Cash", 9),
                              ("Maintenance", 2500, "Cash", 4), ("Office", 1800, "Cash", 2)]:
        finance.add_expense(db, user, cats_e[cat], _days_ago(db, d), amt, meth, f"{cat} - demo")
    audit.log(db, user, "Demo data loaded", "system")
    return {"products": len(P), "sales": len(made)}


def _days_ago(db, d):
    return db.scalar("SELECT date('now','localtime',?)", (f"-{d} days",))


BUSINESS_TABLES = [
    "return_items", "returns", "sale_serials", "sale_payments", "warranty_claims", "warranties", "sale_items", "sales",
    "held_sales", "customer_payments", "repair_payments", "repair_parts", "repair_notes", "repairs",
    "purchase_return_items", "purchase_returns", "purchase_payments", "purchase_items", "purchases",
    "cash_transactions", "expenses", "cash_registers", "ledger", "inventory_transactions", "stock_transfers",
    "serials", "product_variants", "products", "customers", "suppliers", "brands", "categories",
]


def clear_business_data(db, user, confirm_text):
    """Delete ALL products, customers, suppliers and transactions (keeps users, roles, settings).
    A backup is taken first. Used to remove demo data before production."""
    require(user, "settings.manage")
    if user["role"] != "Owner":
        raise POSError("Only an Owner can clear business data.")
    if (confirm_text or "").strip().upper() != "DELETE":
        raise POSError("Type DELETE to confirm.")
    path = backup.create_backup(db, user, "before-clear")
    with db.tx():
        for t in BUSINESS_TABLES:
            db.execute(f"DELETE FROM {t}")
        db.execute("DELETE FROM sequences")
        db.execute("DELETE FROM audit_logs WHERE action IN ('Demo data loaded')")
        audit.log(db, user, "Business data cleared", "system", None, None, {"backup": path})
    return path
