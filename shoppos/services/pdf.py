"""Tiny dependency-free PDF writer (text, lines, rectangles, images) + table export."""
import struct
import zlib

_HELV = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191, "(": 333, ")": 333, "*": 389,
    "+": 584, ",": 278, "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556,
    "@": 1015, "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "I": 278, "J": 500,
    "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722,
    "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556, "h": 556, "i": 222, "j": 222, "k": 500,
    "l": 222, "m": 833, "n": 556, "o": 556, "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500,
    "w": 722, "x": 500, "y": 500, "z": 500, "{": 334, "|": 260, "}": 334, "~": 584,
}
for _d in "0123456789":
    _HELV[_d] = 556


def text_width(s: str, size: float, bold: bool = False, mono: bool = False) -> float:
    if mono:
        return len(s) * 0.6 * size
    w = sum(_HELV.get(ch, 556) for ch in s) / 1000.0 * size
    return w * (1.06 if bold else 1.0)


def _esc(s: str) -> bytes:
    b = s.encode("cp1252", errors="replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def load_image(path):
    """Returns dict(width,height,filter,colorspace,data) for PNG (8-bit, non-interlaced) or JPEG; else None."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    try:
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return _png(raw)
        if raw[:2] == b"\xff\xd8":
            return _jpeg(raw)
    except Exception:
        return None
    return None


def _jpeg(raw):
    i = 2
    while i < len(raw):
        if raw[i] != 0xFF:
            i += 1
            continue
        m = raw[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", raw[i + 5:i + 9])
            comps = raw[i + 9]
            cs = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}.get(comps)
            if not cs:
                return None
            return {"width": w, "height": h, "filter": "/DCTDecode", "colorspace": cs, "data": raw, "bpc": 8}
        seg = struct.unpack(">H", raw[i + 2:i + 4])[0]
        i += 2 + seg
    return None


def _png(raw):
    pos = 8
    idat, plte = b"", None
    w = h = depth = ctype = interlace = None
    while pos < len(raw):
        ln, typ = struct.unpack(">I4s", raw[pos:pos + 8])
        body = raw[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif typ == b"PLTE":
            plte = body
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if depth != 8 or interlace != 0 or ctype not in (0, 2, 3, 4, 6):
        return None
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    data = zlib.decompress(idat)
    stride = w * ch
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _ in range(h):
        f = data[p]
        line = bytearray(data[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out += line
        prev = line
    rgb = bytearray()
    if ctype == 2:
        rgb = out
    elif ctype == 0:
        for v in out:
            rgb += bytes((v, v, v))
    elif ctype == 3 and plte:
        for v in out:
            rgb += plte[v * 3:v * 3 + 3]
    elif ctype in (4, 6):
        step = ch
        for i in range(0, len(out), step):
            if ctype == 4:
                g, a = out[i], out[i + 1]
                r_, g_, b_ = g, g, g
            else:
                r_, g_, b_, a = out[i], out[i + 1], out[i + 2], out[i + 3]
            rgb += bytes(((r_ * a + 255 * (255 - a)) // 255, (g_ * a + 255 * (255 - a)) // 255,
                          (b_ * a + 255 * (255 - a)) // 255))
    else:
        return None
    return {"width": w, "height": h, "filter": "/FlateDecode", "colorspace": "/DeviceRGB",
            "data": zlib.compress(bytes(rgb)), "bpc": 8}


class PDF:
    def __init__(self, width=595.28, height=841.89):
        self.w, self.h = width, height
        self.pages = []
        self.images = []
        self.cur = None

    def add_page(self):
        self.cur = []
        self.pages.append(self.cur)

    def _y(self, y):
        return self.h - y

    def text(self, x, y, s, size=10, bold=False, mono=False, color=(0, 0, 0), align="left"):
        """y is measured from the top of the page (baseline)."""
        font = "F3" if mono else ("F2" if bold else "F1")
        if align != "left":
            wd = text_width(s, size, bold, mono)
            x = x - wd if align == "right" else x - wd / 2
        r, g, b = color
        self.cur.append(b"BT /%s %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td (" % (font.encode(), size, r, g, b, x, self._y(y))
                        + _esc(s) + b") Tj ET")

    def line(self, x1, y1, x2, y2, width=0.5, color=(0, 0, 0)):
        r, g, b = color
        self.cur.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" %
                        (r, g, b, width, x1, self._y(y1), x2, self._y(y2)))

    def rect(self, x, y, w, h, fill=None, stroke=True, width=0.5):
        ops = b""
        if fill:
            ops += b"%.3f %.3f %.3f rg " % fill
        ops += b"%.2f w %.2f %.2f %.2f %.2f re " % (width, x, self._y(y + h), w, h)
        ops += b"B" if (fill and stroke) else (b"f" if fill else b"S")
        self.cur.append(ops)

    def image(self, img, x, y, w, h):
        self.images.append(img)
        idx = len(self.images)
        self.cur.append(b"q %.2f 0 0 %.2f %.2f %.2f cm /Im%d Do Q" % (w, h, x, self._y(y + h), idx))

    def save(self, path):
        objs = []

        def add(b):
            objs.append(b)
            return len(objs)

        add(b"")  # catalog placeholder (1)
        add(b"")  # pages placeholder (2)
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        f3 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
        img_ids = []
        for im in self.images:
            hdr = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent %d "
                   b"/Filter %s /Length %d >>\nstream\n" % (im["width"], im["height"], im["colorspace"].encode(),
                                                            im["bpc"], im["filter"].encode(), len(im["data"])))
            img_ids.append(add(hdr + im["data"] + b"\nendstream"))
        xobj = b"".join(b"/Im%d %d 0 R " % (i + 1, oid) for i, oid in enumerate(img_ids))
        page_ids = []
        for ops in self.pages:
            content = zlib.compress(b"\n".join(ops))
            cid = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream")
            pid = add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                      b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R /F3 %d 0 R >> /XObject << %s>> >> >>"
                      % (self.w, self.h, cid, f1, f2, f3, xobj))
            page_ids.append(pid)
        objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = b" ".join(b"%d 0 R" % p for p in page_ids)
        objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, o in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
        with open(path, "wb") as f:
            f.write(out)


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v - round(v)) > 0.004 else f"{v:,.0f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


def table_pdf(path, title, columns, rows, subtitle="", summary=None, landscape=True, shop=""):
    """Paginated table report. columns=[(key,label)]."""
    pw, ph = (841.89, 595.28) if landscape else (595.28, 841.89)
    pdf = PDF(pw, ph)
    margin, size = 32, 8.5
    cells = [[_fmt(r.get(k)) for k, _ in columns] for r in rows]
    widths = []
    for ci, (_, label) in enumerate(columns):
        mx = text_width(label, size, True)
        for row in cells[:400]:
            mx = max(mx, text_width(row[ci], size))
        widths.append(mx + 10)
    avail = pw - 2 * margin
    total = sum(widths)
    if total > avail:
        widths = [w * avail / total for w in widths]
    numeric = [all(isinstance(r.get(k), (int, float)) or r.get(k) is None for r in rows[:50]) for k, _ in columns]

    def clip(s, w):
        if text_width(s, size) <= w - 6:
            return s
        while s and text_width(s + "...", size) > w - 6:
            s = s[:-1]
        return s + "..."

    y = 0
    page_no = 0

    def header():
        nonlocal y, page_no
        pdf.add_page()
        page_no += 1
        pdf.text(margin, 40, shop or "", 9, color=(0.4, 0.4, 0.4))
        pdf.text(margin, 62, title, 16, bold=True)
        if subtitle:
            pdf.text(margin, 78, subtitle, 9, color=(0.35, 0.35, 0.35))
        pdf.text(pw - margin, 40, f"Page {page_no}", 8, align="right", color=(0.4, 0.4, 0.4))
        y = 96
        pdf.rect(margin, y - 12, sum(widths), 18, fill=(0.93, 0.95, 0.98), stroke=False)
        x = margin
        for ci, (_, label) in enumerate(columns):
            if numeric[ci]:
                pdf.text(x + widths[ci] - 4, y, clip(label, widths[ci]), size, bold=True, align="right")
            else:
                pdf.text(x + 3, y, clip(label, widths[ci]), size, bold=True)
            x += widths[ci]
        y += 16

    header()
    for ri, row in enumerate(cells):
        if y > ph - 50:
            header()
        x = margin
        if ri % 2:
            pdf.rect(margin, y - 9.5, sum(widths), 13, fill=(0.975, 0.98, 0.985), stroke=False)
        for ci, val in enumerate(row):
            if numeric[ci]:
                pdf.text(x + widths[ci] - 4, y, clip(val, widths[ci]), size, align="right")
            else:
                pdf.text(x + 3, y, clip(val, widths[ci]), size)
            x += widths[ci]
        y += 13
    if summary:
        y += 10
        if y > ph - 60:
            header()
        pdf.line(margin, y - 8, margin + sum(widths), y - 8, 0.8)
        for k, v in summary.items():
            pdf.text(margin + 3, y + 4, f"{k.replace('_', ' ').title()}: {_fmt(v)}", 9, bold=True)
            y += 13
    pdf.save(path)
