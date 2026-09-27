"""ShopPOS - entry point.

  ShopPOS.exe             start the application
  ShopPOS.exe --selftest  headless self-check (used to verify a packaged build)
  ShopPOS.exe --init      create/upgrade the database and default account, then exit (used by the installer)
"""
import os
import sys
import tempfile


def selftest() -> int:
    """Create a scratch database, load the demo data, verify integrity, render a PDF/XLSX and open a Tk window."""
    tmp = tempfile.mkdtemp(prefix="shoppos-selftest-")
    os.environ["SHOPPOS_DATA"] = tmp
    from shoppos import config
    from shoppos.bootstrap import open_database
    from shoppos.services import auth, backup, demo, export, inventory, parties, printing, reports, sales

    auth.ITER = 1000
    paths = config.ensure_dirs()
    db = open_database(paths["db"])
    user = auth.login(db, "admin", "admin123")
    info = demo.load_demo(db, user)
    problems = inventory.verify_consistency(db) + parties.verify_balances(db)
    assert not problems, problems
    rep = reports.sales_report(db, user, "product")
    export.export(db, rep, os.path.join(tmp, "r.pdf"))
    export.export(db, rep, os.path.join(tmp, "r.xlsx"))
    export.export(db, rep, os.path.join(tmp, "r.csv"))
    sale_id = db.scalar("SELECT id FROM sales ORDER BY id DESC LIMIT 1")
    printing.save_invoice_pdf(db, sale_id)
    assert "TOTAL" in printing.receipt_text(db, sale_id)
    b = backup.create_backup(db, user)
    assert os.path.getsize(b) > 10000
    db.close()
    import tkinter as tk
    root = tk.Tk()
    root.update()
    root.destroy()
    print(f"SELFTEST OK  products={info['products']} sales={info['sales']}  data={tmp}")
    return 0


def init_only() -> int:
    from shoppos import config
    from shoppos.bootstrap import open_database
    paths = config.ensure_dirs()
    db = open_database(paths["db"])
    print("database ready:", paths["db"], "schema version", db.version)
    db.close()
    return 0


if __name__ == "__main__":
    if "--init" in sys.argv:
        sys.exit(init_only())
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from shoppos.ui.app import main
    sys.exit(main())
