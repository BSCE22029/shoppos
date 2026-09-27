"""Receipts (80mm thermal text), A4 invoice PDF, repair tickets, and Windows printing."""
import os
import subprocess
import sys
import textwrap

from ..util import POSError, now, r2
from . import pdf, settings
from .sales import get_sale


def _cur(db):
    return settings.get(db, "currency") or ""


def _n(x):
    x = r2(x)
    return f"{x:,.0f}" if abs(x - round(x)) < 0.005 else f"{x:,.2f}"


def receipt_text(db, sale_id, width=42, reprint=False) -> str:
    s = get_sale(db, sale_id)
    st = settings.all_settings(db)
    L = []
    c = lambda t: L.append(t.center(width)[:width].rstrip())
    line = lambda ch="-": L.append(ch * width)
    two = lambda a, b: L.append(a[:width - len(b) - 1].ljust(width - len(b)) + b)
    c(st["shop_name"].upper())
    for part in textwrap.wrap(st["shop_address"], width):
        c(part)
    if st["shop_phone"]:
        c("Tel: " + st["shop_phone"])
    if st["tax_number"]:
        c("NTN/STRN: " + st["tax_number"])
    line("=")
    two("Invoice:", s["invoice_no"])
    two("Date:", s["date"][:16])
    two("Cashier:", s["cashier"] or "")
    two("Customer:", s["customer"] or "Walk-in")
    if s["status"] == "Cancelled":
        c("*** CANCELLED ***")
    if reprint:
        c("(Duplicate copy)")
    line()
    for it in s["items"]:
        for i, part in enumerate(textwrap.wrap(it["name"], width)):
            L.append(part)
        two(f"  {it['qty']} x {_n(it['unit_price'])}", _n(it["qty"] * it["unit_price"]))
        if it["line_discount"] or it["overall_alloc"]:
            two("  Discount", "-" + _n(it["line_discount"] + it["overall_alloc"]))
        if it["tax"]:
            two(f"  Tax {it['tax_percent']:g}%", _n(it["tax"]))
        for sn in it["serials"]:
            L.append(f"  S/N: {sn}")
        if it["warranty_months"]:
            L.append(f"  Warranty: {it['warranty_months']} month(s)")
    line()
    two("Subtotal", _n(s["subtotal"]))
    disc = s["line_discount"] + s["overall_discount"]
    if disc:
        two("Discount", "-" + _n(disc))
    if s["tax"]:
        two("Tax", _n(s["tax"]))
    two(f"TOTAL ({_cur(db)})", _n(s["total"]))
    line()
    for p in s["payments"]:
        two(p["method"], _n(p["amount"]))
        if p["ref"]:
            L.append(f"  ({p['ref']})")
    if s["credit"]:
        two("Remaining (on account)", _n(s["credit"] - s["credit_offset"]))
    line("=")
    c(st["receipt_footer"])
    for part in textwrap.wrap(st["terms"], width):
        L.append(part)
    L.append("")
    return "\n".join(L)


def repair_ticket_text(db, repair_id, width=42) -> str:
    from .repairs import get_repair
    r = get_repair(db, repair_id)
    st = settings.all_settings(db)
    L = [st["shop_name"].upper().center(width), "REPAIR TICKET".center(width), "=" * width,
         f"Ticket : {r['ticket_no']}", f"Date   : {r['received_at'][:16]}", f"Client : {r['customer_name']} {r['customer_phone'] or ''}",
         f"Device : {r['device']} {r['brand'] or ''} {r['model'] or ''}"]
    if r["serial"]:
        L.append(f"Serial : {r['serial']}")
    L += textwrap.wrap("Complaint: " + r["complaint"], width)
    if r["condition"]:
        L += textwrap.wrap("Condition: " + r["condition"], width)
    if r["accessories"]:
        L += textwrap.wrap("Accessories: " + r["accessories"], width)
    L += ["-" * width, f"Estimate: {_n(r['estimated_cost'])} {_cur(db)}"]
    if r["expected_at"]:
        L.append(f"Expected: {r['expected_at']}")
    L += ["-" * width, "Please bring this slip to collect", "your device. Unclaimed items after",
          "60 days are not our responsibility.", ""]
    return "\n".join(L)


def invoice_pdf(db, sale_id, path):
    """Professional A4 invoice with logo, serial numbers and warranty."""
    s = get_sale(db, sale_id)
    st = settings.all_settings(db)
    cur = st["currency"]
    d = pdf.PDF()
    d.add_page()
    W, M = d.w, 36
    y = 44
    logo = pdf.load_image(st["logo_path"]) if st.get("logo_path") else None
    x_text = M
    if logo:
        h = 52
        w = min(h * logo["width"] / logo["height"], 140)
        d.image(logo, M, 30, w, h)
        x_text = M + w + 12
    d.text(x_text, y, st["shop_name"], 18, bold=True, color=(0.12, 0.23, 0.37))
    d.text(x_text, y + 15, st["shop_address"], 9, color=(0.3, 0.3, 0.3))
    d.text(x_text, y + 27, f"Tel: {st['shop_phone']}   {st['shop_email']}", 9, color=(0.3, 0.3, 0.3))
    if st["tax_number"]:
        d.text(x_text, y + 39, f"NTN/STRN: {st['tax_number']}", 9, color=(0.3, 0.3, 0.3))
    d.text(W - M, y, "INVOICE", 20, bold=True, align="right", color=(0.18, 0.53, 0.87))
    d.text(W - M, y + 16, s["invoice_no"], 11, bold=True, align="right")
    d.text(W - M, y + 30, s["date"][:16], 9, align="right")
    if s["status"] != "Completed":
        d.text(W - M, y + 44, s["status"].upper(), 10, bold=True, align="right", color=(0.8, 0.1, 0.1))
    y = 112
    d.line(M, y, W - M, y, 1.2, (0.12, 0.23, 0.37))
    d.text(M, y + 16, "Bill to", 8, color=(0.4, 0.4, 0.4))
    d.text(M, y + 30, s["customer"] or "Walk-in customer", 11, bold=True)
    if s["customer_phone"]:
        d.text(M, y + 43, s["customer_phone"], 9)
    if s["customer_address"]:
        d.text(M, y + 55, s["customer_address"][:70], 9)
    d.text(W - M, y + 16, "Cashier", 8, align="right", color=(0.4, 0.4, 0.4))
    d.text(W - M, y + 30, s["cashier"] or "", 10, align="right")
    y = 190
    cols = [("Product", M, "l"), ("Qty", 318, "r"), ("Unit", 368, "r"), ("Disc.", 418, "r"),
            ("Tax", 466, "r"), ("Total", W - M, "r")]
    d.rect(M, y - 12, W - 2 * M, 18, fill=(0.12, 0.23, 0.37), stroke=False)
    for lbl, x, al in cols:
        d.text(x + (3 if al == "l" else 0), y, lbl, 9, bold=True, align="left" if al == "l" else "right", color=(1, 1, 1))
    y += 20
    for it in s["items"]:
        if y > 700:
            d.add_page()
            y = 60
        name = it["name"]
        while pdf.text_width(name, 9.5, True) > 270 and len(name) > 4:
            name = name[:-1]
        d.text(M + 3, y, name, 9.5, bold=True)
        d.text(318, y, str(it["qty"]), 9.5, align="right")
        d.text(368, y, _n(it["unit_price"]), 9.5, align="right")
        d.text(418, y, _n(it["line_discount"] + it["overall_alloc"]), 9.5, align="right")
        d.text(466, y, _n(it["tax"]), 9.5, align="right")
        d.text(W - M, y, _n(it["total"]), 9.5, bold=True, align="right")
        y += 12
        sub = f"SKU {it['sku']}"
        if it["serials"]:
            sub += "   S/N: " + ", ".join(it["serials"])
        for chunk in textwrap.wrap(sub, 95):
            d.text(M + 3, y, chunk, 8, color=(0.35, 0.35, 0.35))
            y += 10
        if it["warranty_months"]:
            from ..util import add_months
            exp = add_months(s["date"][:10], it["warranty_months"])
            d.text(M + 3, y, f"Warranty: {it['warranty_months']} month(s), valid until {exp}", 8, color=(0.1, 0.45, 0.2))
            y += 10
        d.line(M, y + 2, W - M, y + 2, 0.3, (0.8, 0.8, 0.8))
        y += 10
    y += 8
    bx = W - M - 200

    def row(label, val, bold=False, color=(0, 0, 0)):
        nonlocal y
        d.text(bx, y, label, 10, bold=bold, color=color)
        d.text(W - M, y, val, 10, bold=bold, align="right", color=color)
        y += 15

    row("Subtotal", _n(s["subtotal"]))
    disc = s["line_discount"] + s["overall_discount"]
    if disc:
        row("Discount", "-" + _n(disc))
    if s["tax"]:
        row("Tax", _n(s["tax"]))
    d.line(bx, y - 8, W - M, y - 8, 0.8)
    row(f"TOTAL ({cur})", _n(s["total"]), True)
    for p in s["payments"]:
        if p["method"] != "Credit":
            row(f"Paid - {p['method']}", _n(p["amount"]))
    remaining = r2(s["credit"] - s["credit_offset"])
    row("Remaining balance", _n(remaining), True, (0.75, 0.1, 0.1) if remaining > 0 else (0, 0, 0))
    y += 16
    d.text(M, y, "Terms & conditions", 9, bold=True)
    y += 12
    for chunk in textwrap.wrap(st["terms"], 120):
        d.text(M, y, chunk, 8, color=(0.3, 0.3, 0.3))
        y += 10
    d.text(W / 2, d.h - 30, st["receipt_footer"], 9, align="center", color=(0.4, 0.4, 0.4))
    d.save(path)
    return path


# -------------------------------------------------------------- Windows output
def open_file(path):
    if os.name == "nt":
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def print_text(path, printer=""):
    """Send a text file to a printer (the default printer if none is configured)."""
    if os.name != "nt":
        raise POSError("Direct printing is only available on Windows. The receipt was saved to: " + path)
    try:
        if printer:
            subprocess.Popen(["notepad.exe", "/pt", path, printer])
        else:
            os.startfile(path, "print")  # noqa
    except OSError as e:
        raise POSError(f"Could not print: {e}")


def print_receipt(db, sale_id, reprint=False):
    from ..config import ensure_dirs
    text = receipt_text(db, sale_id, reprint=reprint)
    path = os.path.join(ensure_dirs()["invoices"], f"receipt-{sale_id}.txt")
    with open(path, "w", encoding="cp1252", errors="replace") as f:
        f.write(text)
    print_text(path, settings.get(db, "receipt_printer") or "")
    return path


def save_invoice_pdf(db, sale_id):
    from ..config import ensure_dirs
    s = get_sale(db, sale_id)
    path = os.path.join(ensure_dirs()["invoices"], f"{s['invoice_no']}.pdf")
    invoice_pdf(db, sale_id, path)
    return path


def list_printers():
    """Installed Windows printers (empty list elsewhere or on error)."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Printer).Name"], capture_output=True,
                             text=True, timeout=15, creationflags=0x08000000)
        return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        return []
