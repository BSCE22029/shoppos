"""CSV / Excel (.xlsx) / PDF export of report data (no third-party libraries)."""
import csv
import os
import zipfile
from xml.sax.saxutils import escape

from ..util import POSError, now
from . import pdf, settings


def _cols(report):
    return report["columns"], report["rows"]


def to_csv(path, report):
    cols, rows = _cols(report)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([lbl for _, lbl in cols])
        for r in rows:
            w.writerow(["" if r.get(k) is None else r.get(k) for k, _ in cols])
        if report.get("summary"):
            w.writerow([])
            for k, v in report["summary"].items():
                w.writerow([k.replace("_", " ").title(), v])


def _col_letter(i):
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def to_xlsx(path, report):
    cols, rows = _cols(report)
    sheet = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols>']
    for i, (k, lbl) in enumerate(cols):
        mx = max([len(str(lbl))] + [len(str(r.get(k, ""))) for r in rows[:300]])
        sheet.append(f'<col min="{i + 1}" max="{i + 1}" width="{min(max(mx + 2, 8), 60)}" customWidth="1"/>')
    sheet.append("</cols><sheetData>")

    def cell(ref, v, style=0):
        s = f' s="{style}"' if style else ""
        if v is None or v == "":
            return f'<c r="{ref}"{s}/>'
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"{s}><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'

    r = 1
    sheet.append(f'<row r="{r}">' + "".join(cell(f"{_col_letter(i)}{r}", lbl, 1) for i, (_, lbl) in enumerate(cols)) + "</row>")
    for row in rows:
        r += 1
        sheet.append(f'<row r="{r}">' + "".join(cell(f"{_col_letter(i)}{r}", row.get(k)) for i, (k, _) in enumerate(cols)) + "</row>")
    if report.get("summary"):
        r += 1
        for k, v in report["summary"].items():
            r += 1
            sheet.append(f'<row r="{r}">{cell(f"A{r}", k.replace("_", " ").title(), 1)}{cell(f"B{r}", v)}</row>')
    sheet.append("</sheetData></worksheet>")
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{escape(report["title"][:28]).replace("/", "-")}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": "".join(sheet),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)


def to_pdf(db, path, report, subtitle=""):
    shop = settings.get(db, "shop_name")
    cols, rows = _cols(report)
    sub = subtitle or f"Generated {now()}"
    pdf.table_pdf(path, report["title"], cols, rows, sub, report.get("summary"),
                  landscape=len(cols) > 5, shop=shop)


def export(db, report, path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        to_csv(path, report)
    elif ext == ".xlsx":
        to_xlsx(path, report)
    elif ext == ".pdf":
        to_pdf(db, path, report)
    else:
        raise POSError("Unsupported export format. Use .csv, .xlsx or .pdf")
    return path
