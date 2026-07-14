"""Stamp clickable document links onto the APPROVED flyer.

The flyer is the one document in this set that is NOT generated - it is the
user's final approved artwork. So this script never redraws it: it reads the
pristine copy (tools/docgen/flyer-base.pdf), overlays one line of text in the
emerald footer band, attaches URI link annotations, and writes
docs/TaskWA-Flyer.pdf. Idempotent - always stamps the base, never a stamped
file. To change the artwork itself, replace flyer-base.pdf.

    python tools/docgen/dg_flyer_links.py

Geometry note: the footer band runs from y=41pt to y=107pt; the "Free forever"
line sits at ~62pt and the QR code starts at x=490pt, so the link line goes at
y=48pt in the strip below it, left of the QR.
"""
import io
import os

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import RectangleObject
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BASE = os.path.join(HERE, "flyer-base.pdf")
OUT = os.path.join(ROOT, "docs", "TaskWA-Flyer.pdf")

REPO = "https://github.com/Sudhakar-Kadavasal/taskwa"
DOCS = f"{REPO}/blob/main/docs"
INSTALL_URL = f"{DOCS}/TaskWA-Installation-Guide.pdf"
MANUAL_URL = f"{DOCS}/TaskWA-User-Manual.pdf"
CARD_URL = f"{DOCS}/TaskWA-Command-Card.pdf"

CREAM = HexColor("#FBF1D8")
SAGE = HexColor("#CFE3D9")

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Fly", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Fly-Bold", F + "DejaVuSans-Bold.ttf"))

# --- the link line, laid out once so the overlay and the hot zones agree ----
X0, Y = 46.0, 47.5          # left margin of the footer band; baseline
SIZE = 7.0
LEAD = "Read first:  "
SEP = "   ·   "
ITEMS = [("Installation Guide", INSTALL_URL),
         ("User Manual", MANUAL_URL),
         ("Command Card", CARD_URL)]


def _w(text, bold=False):
    return pdfmetrics.stringWidth(text, "Fly-Bold" if bold else "Fly", SIZE)


def build_overlay() -> io.BytesIO:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595.2756, 841.8898))
    c.setFillColor(SAGE)
    c.setFont("Fly", SIZE)
    c.drawString(X0, Y, LEAD)
    x = X0 + _w(LEAD)
    c.setFillColor(CREAM)
    for i, (label, _url) in enumerate(ITEMS):
        if i:
            c.setFillColor(SAGE)
            c.setFont("Fly", SIZE)
            c.drawString(x, Y, SEP)
            x += _w(SEP)
            c.setFillColor(CREAM)
        c.setFont("Fly-Bold", SIZE)
        c.drawString(x, Y, label)
        w = _w(label, bold=True)
        c.setLineWidth(0.4)
        c.setStrokeColor(CREAM)
        c.line(x, Y - 1.6, x + w, Y - 1.6)      # underline: it's a link
        x += w
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def link_rects() -> list[tuple[tuple[float, float, float, float], str]]:
    """Clickable rectangles, padded a little so they're easy to hit."""
    out = []
    x = X0 + _w(LEAD)
    for i, (label, url) in enumerate(ITEMS):
        if i:
            x += _w(SEP)
        w = _w(label, bold=True)
        out.append(((x - 1, Y - 3, x + w + 1, Y + SIZE), url))
        x += w
    # the big repo line already printed on the flyer, made clickable
    out.append(((46, 72, 330, 92), REPO))
    return out


def main():
    reader = PdfReader(BASE)
    page = reader.pages[0]
    page.merge_page(PdfReader(build_overlay()).pages[0])

    writer = PdfWriter()
    writer.add_page(page)
    for rect, url in link_rects():
        writer.add_annotation(page_number=0, annotation=Link(
            rect=RectangleObject(rect), url=url))
    with open(OUT, "wb") as f:
        writer.write(f)
    print(f"OK flyer -> {OUT} ({len(link_rects())} links)")


if __name__ == "__main__":
    main()
