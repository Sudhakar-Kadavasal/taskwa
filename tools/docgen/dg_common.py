# -*- coding: utf-8 -*-
"""Shared design system: charcoal + burnt orange, serif headings, paper tone."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, PageBreak, Flowable,
                                HRFlowable, NextPageTemplate, XPreformatted)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Serif", F + "DejaVuSerif.ttf"))
pdfmetrics.registerFont(TTFont("Serif-Bold", F + "DejaVuSerif-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Serif-Italic", F + "DejaVuSerif-Italic.ttf"))
pdfmetrics.registerFont(TTFont("SerifC-Bold", F + "DejaVuSerifCondensed-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Mono", F + "DejaVuSansMono.ttf"))
pdfmetrics.registerFont(TTFont("Mono-Bold", F + "DejaVuSansMono-Bold.ttf"))

# ---------------- palette: Mint Ledger (matches flyer + dashboard) --------
PAPER   = colors.HexColor("#EEF6F0")   # mint page
PAPER2  = colors.HexColor("#E2EEE7")   # mint, one step deeper
SAND    = colors.HexColor("#D8E8DE")   # soft sage fill (tables, cmd cells)
LINE    = colors.HexColor("#BAD2C4")   # sage rule lines
INK     = colors.HexColor("#0E241C")   # deep forest text
CHAR    = colors.HexColor("#2C4237")   # secondary text
MUTED   = colors.HexColor("#64796E")   # captions, footers
ORANGE  = colors.HexColor("#147152")   # emerald accent (kept name)
ORANGE_D= colors.HexColor("#0E5A40")   # emerald dark (kept name)
CREAM   = colors.HexColor("#FBF1D8")   # warm cream (callouts, bubbles)
DARKBOX = colors.HexColor("#0E241C")   # forest code box
DARKTXT = colors.HexColor("#DDEBE2")   # code text on forest
AMBER   = colors.HexColor("#B07C1E")   # warm highlight when needed

PAGE_W, PAGE_H = A4
ML, MR, MT, MB = 2.2*cm, 2.2*cm, 2.6*cm, 2.2*cm
FW = PAGE_W - ML - MR


def st(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.6, leading=14.2, textColor=INK,
                alignment=TA_JUSTIFY, spaceAfter=6)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
 "body":   st("body"),
 "bodyL":  st("bodyL", alignment=TA_LEFT),
 "lede":   st("lede", fontName="Serif", fontSize=10.6, leading=16.4,
              textColor=CHAR, alignment=TA_LEFT),
 "h1":     st("h1", fontName="Serif-Bold", fontSize=17, leading=21,
              textColor=INK, spaceBefore=4, spaceAfter=2, alignment=TA_LEFT),
 "h2":     st("h2", fontName="Serif-Bold", fontSize=11.5, leading=15,
              textColor=ORANGE_D, spaceBefore=12, spaceAfter=4, alignment=TA_LEFT),
 "bullet": st("bullet", alignment=TA_LEFT, leftIndent=13, spaceAfter=3.5),
 "tcell":  st("tcell", fontSize=8.7, leading=12, alignment=TA_LEFT, spaceAfter=0),
 "thead":  st("thead", fontName="SerifC-Bold", fontSize=9.2, leading=12,
              alignment=TA_LEFT, spaceAfter=0, textColor=CREAM),
 "mono":   st("mono", fontName="Mono", fontSize=8.2, leading=11.6,
              alignment=TA_LEFT, textColor=DARKTXT, spaceAfter=0),
 "monoIn": st("monoIn", fontName="Mono", fontSize=8.4, leading=12,
              alignment=TA_LEFT, textColor=ORANGE_D, spaceAfter=0),
 "toc":    st("toc", fontName="Serif", fontSize=10.4, leading=19,
              alignment=TA_LEFT, textColor=CHAR),
 "cap":    st("cap", fontSize=8.2, leading=11, textColor=MUTED,
              alignment=TA_CENTER, spaceAfter=2),
 "step":   st("step", fontName="Serif-Bold", fontSize=12.5, leading=16,
              textColor=INK, alignment=TA_LEFT, spaceBefore=8, spaceAfter=3),
}

def P(t, s="body"):
    return Paragraph(t, S[s])


# ---------------- page furniture ----------------
def make_doc(path, doc_title, header_right, cover_fn):
    def later(cv, doc):
        cv.saveState()
        cv.setFillColor(PAPER); cv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        cv.setFillColor(ORANGE); cv.rect(0, PAGE_H-0.28*cm, PAGE_W, 0.28*cm,
                                         stroke=0, fill=1)
        cv.setFillColor(CHAR); cv.setFont("SerifC-Bold", 8.2)
        cv.drawString(ML, PAGE_H-1.55*cm, "SUDHAKAR KADAVASAL")
        cv.setFillColor(MUTED); cv.setFont("Helvetica", 8)
        cv.drawRightString(PAGE_W-MR, PAGE_H-1.55*cm, header_right)
        cv.setStrokeColor(LINE); cv.setLineWidth(0.6)
        cv.line(ML, PAGE_H-1.75*cm, PAGE_W-MR, PAGE_H-1.75*cm)
        cv.setFillColor(MUTED); cv.setFont("Helvetica", 7.6)
        cv.drawString(ML, 1.25*cm, doc_title)
        cv.setFillColor(ORANGE_D); cv.setFont("Serif-Bold", 8.6)
        cv.drawRightString(PAGE_W-MR, 1.25*cm, "%d" % doc.page)
        cv.restoreState()

    def cover(cv, doc):
        cv.saveState()
        cv.setFillColor(PAPER); cv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        cover_fn(cv)
        cv.restoreState()

    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=ML, rightMargin=MR,
                          topMargin=MT, bottomMargin=MB,
                          title=doc_title, author="Sudhakar Kadavasal")
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[Frame(0, 0, PAGE_W, PAGE_H)], onPage=cover),
        PageTemplate(id="Body",
                     frames=[Frame(ML, MB, FW, PAGE_H-MT-MB)], onPage=later)])
    return doc


def start_body(E):
    E.append(NextPageTemplate("Body"))
    E.append(Spacer(1, 10))
    E.append(PageBreak())


def section(num, title):
    row = Table([[Paragraph(f'<font color="#C2502D">{num}</font>',
                            st("sn", fontName="Serif-Bold", fontSize=17,
                               alignment=TA_LEFT, textColor=ORANGE, spaceAfter=0)),
                  Paragraph(title, S["h1"])]],
                colWidths=[1.15*cm, FW-1.15*cm])
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 1.1, INK),
    ]))
    return [Spacer(1, 10), row, Spacer(1, 9)]


def table(header, rows, widths, style_extra=None):
    data = [[Paragraph(h, S["thead"]) for h in header]]
    for r in rows:
        data.append([c if not isinstance(c, str) else Paragraph(c, S["tcell"])
                     for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), CHAR),
        ("LINEBELOW", (0, 0), (-1, 0), 1.6, ORANGE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), PAPER2))
    if style_extra:
        style += style_extra
    t.setStyle(TableStyle(style))
    return t


def callout(txt):
    t = Table([[Paragraph(txt, st("co", fontName="Serif", fontSize=9.8,
                                  leading=14.6, textColor=CHAR,
                                  alignment=TA_LEFT, spaceAfter=0))]],
              colWidths=[FW])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SAND),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ORANGE),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def codebox(lines, width=FW):
    t = Table([[XPreformatted("\n".join(lines), S["mono"])]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARKBOX),
        ("LINEBELOW", (0, -1), (-1, -1), 2, ORANGE),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def chat_bubble(lines, sender="them", width=FW*0.8):
    """WhatsApp-style message rendering."""
    bg = colors.HexColor("#E7F3DF") if sender == "me" else CREAM
    t = Table([[XPreformatted("\n".join(lines),
                              st("cb", fontName="Helvetica", fontSize=8.8,
                                 leading=12.4, textColor=INK, spaceAfter=0,
                                 alignment=TA_LEFT))]],
              colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]))
    wrap = Table([[t]], colWidths=[FW])
    align = "RIGHT" if sender == "me" else "LEFT"
    wrap.setStyle(TableStyle([("ALIGN", (0, 0), (0, 0), align),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 2),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return wrap


# ---------------- illustration flowable ----------------
class Illu(Flowable):
    def __init__(self, fn, height, width=FW):
        super().__init__()
        self.fn, self.height, self.width = fn, height, width

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        self.fn(self.canv, self.width, self.height)


# drawing helpers -----------------------------------------------------------
def win_frame(cv, x, y, w, h, title, bar=colors.HexColor("#D8E8DE")):
    """macOS-style window with traffic lights."""
    cv.setFillColor(CREAM); cv.setStrokeColor(LINE); cv.setLineWidth(1)
    cv.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    cv.setFillColor(bar)
    cv.roundRect(x, y+h-16, w, 16, 6, stroke=0, fill=1)
    cv.rect(x, y+h-10, w, 10, stroke=0, fill=1)
    for i, col in enumerate(("#E5604D", "#E5B549", "#5BB960")):
        cv.setFillColor(colors.HexColor(col))
        cv.circle(x+12+i*13, y+h-8, 3.4, stroke=0, fill=1)
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 7)
    cv.drawCentredString(x+w/2, y+h-11, title)


def term_frame(cv, x, y, w, h, lines, title="Terminal"):
    win_frame(cv, x, y, w, h, title, bar=colors.HexColor("#132E24"))
    cv.setFillColor(DARKBOX)
    cv.rect(x+1, y+1, w-2, h-18, stroke=0, fill=1)
    cv.setFont("Mono", 7.2)
    ty = y + h - 28
    for ln in lines:
        if ln.startswith("$"):
            cv.setFillColor(colors.HexColor("#8FCBAF"))
        else:
            cv.setFillColor(DARKTXT)
        cv.drawString(x+10, ty, ln[:int((w-20)/4.4)])
        ty -= 10.5
        if ty < y + 6:
            break


def phone_frame(cv, x, y, w, h, title="WhatsApp"):
    cv.setFillColor(INK)
    cv.roundRect(x, y, w, h, 10, stroke=0, fill=1)
    cv.setFillColor(CREAM)
    cv.roundRect(x+3, y+3, w-6, h-6, 8, stroke=0, fill=1)
    cv.setFillColor(colors.HexColor("#0E7C66"))
    cv.roundRect(x+3, y+h-21, w-6, 18, 8, stroke=0, fill=1)
    cv.rect(x+3, y+h-14, w-6, 11, stroke=0, fill=1)
    cv.setFillColor(CREAM); cv.setFont("Helvetica-Bold", 7)
    cv.drawString(x+10, y+h-16, title)


def qr_block(cv, x, y, size):
    import random
    rnd = random.Random(7)
    cv.setFillColor(CREAM); cv.rect(x, y, size, size, stroke=0, fill=1)
    n = 15
    cell = size / n
    cv.setFillColor(INK)
    for i in range(n):
        for j in range(n):
            if rnd.random() < 0.42:
                cv.rect(x+i*cell, y+j*cell, cell, cell, stroke=0, fill=1)
    for cx, cy in ((0, n-4), (n-4, n-4), (0, 0)):
        cv.setFillColor(INK)
        cv.rect(x+cx*cell, y+cy*cell, 4*cell, 4*cell, stroke=0, fill=1)
        cv.setFillColor(CREAM)
        cv.rect(x+(cx+1)*cell, y+(cy+1)*cell, 2*cell, 2*cell, stroke=0, fill=1)


def browser_frame(cv, x, y, w, h, url):
    win_frame(cv, x, y, w, h, "")
    cv.setFillColor(PAPER2)
    cv.roundRect(x+30, y+h-14.5, w-60, 11, 5, stroke=0, fill=1)
    cv.setFillColor(MUTED); cv.setFont("Mono", 6.6)
    cv.drawString(x+36, y+h-11.5, url)
