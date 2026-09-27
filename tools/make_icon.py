"""Draws the application icon (assets/app.ico + assets/app.png) with no third-party libraries."""
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")


def png_rgba(w, h, px):
    raw = bytearray()
    for y in range(h):
        raw += b"\x00" + bytes(px[y * w * 4:(y + 1) * w * 4])

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def sample(u, v):
    """Colour (r,g,b,a) of the icon at normalised coordinates."""
    # rounded-square background with vertical gradient
    r = 0.2
    dx = max(abs(u - 0.5) - (0.5 - r), 0)
    dy = max(abs(v - 0.5) - (0.5 - r), 0)
    if dx * dx + dy * dy > r * r:
        return (0, 0, 0, 0)
    t = v
    col = (int(30 + 16 * t), int(58 + 76 * t), int(95 + 127 * t), 255)
    # receipt with zig-zag bottom
    zig = 0.035 * abs(((u * 9) % 2) - 1)
    if 0.27 <= u <= 0.73 and 0.15 <= v <= 0.80 + zig - 0.035:
        col = (255, 255, 255, 255)
        for a, b, c, d, rgb in ((0.34, 0.66, 0.26, 0.30, (90, 100, 115)), (0.34, 0.66, 0.37, 0.41, (90, 100, 115)),
                                (0.34, 0.56, 0.48, 0.52, (90, 100, 115)), (0.34, 0.66, 0.60, 0.68, (30, 158, 90))):
            if a <= u <= b and c <= v <= d:
                col = rgb + (255,)
    return col


def render(size):
    ss = 3 if size <= 64 else 2
    px = bytearray()
    for y in range(size):
        for x in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    r, g, b, a = sample((x + (sx + .5) / ss) / size, (y + (sy + .5) / ss) / size)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            n = ss * ss
            a = acc[3] / n
            if acc[3]:
                px += bytes((int(acc[0] / acc[3]), int(acc[1] / acc[3]), int(acc[2] / acc[3]), int(a)))
            else:
                px += b"\x00\x00\x00\x00"
    return png_rgba(size, size, px)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [(s, render(s)) for s in sizes]
    with open(os.path.join(ASSETS, "app.png"), "wb") as f:
        f.write(images[-1][1])
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    with open(os.path.join(ASSETS, "app.ico"), "wb") as f:
        f.write(header + entries + blobs)
    print("icon written to", ASSETS)


if __name__ == "__main__":
    main()
