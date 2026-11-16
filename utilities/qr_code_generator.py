"""
QR code label sheet generator.

Creates a grid of sequential QR codes (for example, bin or asset labels) and
saves it as one printable PNG.

    pip install qrcode pillow
    python qr_code_generator.py --start 555555555 --count 200 --cols 20
"""

import argparse

import qrcode
from PIL import Image


def build_sheet(start_num, count, cols=20, qr_size=100):
    rows = (count + cols - 1) // cols
    sheet = Image.new("RGB", (cols * qr_size, rows * qr_size), "white")
    for i in range(count):
        code = qrcode.make(str(start_num + i)).resize((qr_size, qr_size), Image.Resampling.LANCZOS)
        sheet.paste(code, ((i % cols) * qr_size, (i // cols) * qr_size))
    return sheet


def main():
    ap = argparse.ArgumentParser(description="Generate a sheet of sequential QR codes.")
    ap.add_argument("--start", type=int, default=555555555, help="first number to encode")
    ap.add_argument("--count", type=int, default=200, help="how many codes")
    ap.add_argument("--cols", type=int, default=20, help="codes per row")
    ap.add_argument("--size", type=int, default=100, help="pixel size of each code")
    ap.add_argument("--out", default="qr_codes_grid.png", help="output file")
    a = ap.parse_args()

    build_sheet(a.start, a.count, a.cols, a.size).save(a.out)
    print(f"Saved {a.count} QR codes to {a.out}")


if __name__ == "__main__":
    main()
