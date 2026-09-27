"""Code 39 barcode generation (readable by every USB scanner) and label sheets."""
import html
import os
import webbrowser

from ..util import POSError

_C39 = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn", "4": "nnnwwnnnw",
    "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn", "9": "nnwwnnwnn",
    "A": "wnnnnwnnw", "B": "nnwnnwnnw", "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn",
    "F": "nnwnwwnnn", "G": "nnnnnwwnw", "H": "wnnnnwwnn", "I": "nnwnnwwnn", "J": "nnnnwwwnn",
    "K": "wnnnnnnww", "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww", "O": "wnnnwnnwn",
    "P": "nnwnwnnwn", "Q": "nnnnnnwww", "R": "wnnnnnwwn", "S": "nnwnnnwwn", "T": "nnnnwnwwn",
    "U": "wwnnnnnnw", "V": "nwwnnnnnw", "W": "wwwnnnnnn", "X": "nwnnwnnnw", "Y": "wwnnwnnnn",
    "Z": "nwwnwnnnn", "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "$": "nwnwnwnnn",
    "/": "nwnwnnnwn", "+": "nwnnnwnwn", "%": "nnnwnwnwn", "*": "nwnnwnwnn",
}


def normalize(text: str) -> str:
    t = (text or "").strip().upper()
    if not t:
        raise POSError("Nothing to encode.")
    bad = [c for c in t if c not in _C39 or c == "*"]
    if bad:
        raise POSError(f"Character '{bad[0]}' cannot be encoded in a Code 39 barcode.")
    return t


def bars(text: str, narrow=1.0, wide=2.5, gap=1.0):
    """Returns [(x, width)] for the dark bars, and total width."""
    t = "*" + normalize(text) + "*"
    x, out = 0.0, []
    for ci, ch in enumerate(t):
        pat = _C39[ch]
        for i, w in enumerate(pat):
            wd = wide if w == "w" else narrow
            if i % 2 == 0:
                out.append((x, wd))
            x += wd
        if ci < len(t) - 1:
            x += gap
    return out, x


def draw_on_canvas(canvas, text, x, y, height=60, scale=2.0, color="black"):
    b, total = bars(text)
    for bx, bw in b:
        canvas.create_rectangle(x + bx * scale, y, x + (bx + bw) * scale, y + height, fill=color, outline=color)
    return total * scale


def svg(text, height=40, scale=1.6):
    b, total = bars(text)
    rects = "".join(f'<rect x="{bx * scale:.2f}" y="0" width="{bw * scale:.2f}" height="{height}"/>' for bx, bw in b)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{total * scale:.1f}" height="{height}" viewBox="0 0 {total * scale:.1f} {height}">{rects}</svg>'


def labels_html(labels, shop="", cols=3):
    """labels: [{'name','code','price'}] -> printable HTML label sheet."""
    cells = []
    for lb in labels:
        cells.append(
            '<div class="l"><div class="n">%s</div>%s<div class="c">%s</div><div class="p">%s</div></div>'
            % (html.escape(lb["name"][:38]), svg(lb["code"]), html.escape(lb["code"]), html.escape(str(lb.get("price", "")))))
    return ("<!doctype html><meta charset='utf-8'><title>Barcode labels</title><style>"
            "body{font-family:Arial,sans-serif;margin:8mm}.g{display:grid;grid-template-columns:repeat(%d,1fr);gap:4mm}"
            ".l{border:1px dashed #999;padding:3mm;text-align:center;page-break-inside:avoid}.n{font-size:9pt;font-weight:bold}"
            ".c{font-size:8pt;letter-spacing:1px}.p{font-size:11pt;font-weight:bold}@media print{.l{border:none}}"
            "</style><div class='g'>%s</div>" % (cols, "".join(cells)))


def save_labels(path, labels, shop="", cols=3, open_after=True):
    with open(path, "w", encoding="utf-8") as f:
        f.write(labels_html(labels, shop, cols))
    if open_after:
        webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/"))
    return path
