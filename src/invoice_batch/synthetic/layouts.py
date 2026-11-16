"""The PDF page layouts, drawn with reportlab.

Each function draws one page onto a reportlab canvas.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter

from invoice_batch.synthetic.data import money

PAGE_W, PAGE_H = letter


def right(c, x, y, text):
    c.drawRightString(x, y, text)


def layout_classic(
    c,
    inv,
    *,
    fmt_date=lambda d: d.isoformat(),
    show_due=True,
    footer_note=None,
    total_override=None,
):
    """Plain black-and-white invoice with a ruled table."""
    cur = inv["currency"]
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 740, inv["vendor"])
    c.setFont("Helvetica", 9)
    for i, line in enumerate(inv["vendor_address"]):
        c.drawString(50, 725 - i * 11, line)
    c.setFont("Helvetica-Bold", 26)
    right(c, 562, 738, "INVOICE")

    c.setFont("Helvetica", 10)
    meta = [("Invoice No.", inv["invoice_no"]), ("Issue Date", fmt_date(inv["issue_date"]))]
    if show_due and inv["due_date"]:
        meta.append(("Due Date", fmt_date(inv["due_date"])))
    for i, (k, v) in enumerate(meta):
        c.drawString(380, 700 - i * 14, f"{k}:")
        right(c, 562, 700 - i * 14, v)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 660, "Bill To")
    c.setFont("Helvetica", 10)
    c.drawString(50, 646, inv["customer_name"])
    c.drawString(50, 632, inv["customer_email"])

    y = 590
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Description")
    right(c, 380, y, "Qty")
    right(c, 470, y, "Unit Price")
    right(c, 562, y, "Amount")
    c.line(50, y - 5, 562, y - 5)
    c.setFont("Helvetica", 10)
    for it in inv["line_items"]:
        y -= 20
        c.drawString(50, y, it["description"])
        right(c, 380, y, str(it["quantity"]))
        right(c, 470, y, money(it["unit_price"], cur))
        right(c, 562, y, money(it["quantity"] * it["unit_price"], cur))
    c.line(50, y - 8, 562, y - 8)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(380, y - 28, "Total")
    right(c, 562, y - 28, money(total_override or inv["total"], cur))

    c.setFont("Helvetica", 8)
    c.drawString(50, 60, "Thank you for your business.")
    if footer_note:
        c.setFont("Helvetica", 5)
        c.setFillColor(colors.Color(0.55, 0.55, 0.55))
        c.drawString(50, 30, footer_note)
        c.setFillColor(colors.black)


def layout_modern(
    c, inv, *, fmt_date=lambda d: f"{d:%B} {d.day}, {d.year}", money_fmt=None, show_due=True
):
    """Colored header band, two-column details, zebra-striped items."""
    cur = inv["currency"]
    money_fmt = money_fmt or (lambda x: money(x, cur))
    c.setFillColor(colors.HexColor("#1f6f78"))
    c.rect(0, 700, PAGE_W, 92, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(40, 750, inv["vendor"])
    c.setFont("Helvetica", 9)
    c.drawString(40, 734, "  ·  ".join(inv["vendor_address"]))
    c.setFont("Helvetica", 28)
    right(c, 572, 745, "Invoice")
    c.setFillColor(colors.black)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, 670, "BILLED TO")
    c.drawString(330, 670, "DETAILS")
    c.setFont("Helvetica", 10)
    c.drawString(40, 654, inv["customer_name"])
    c.drawString(40, 640, inv["customer_email"])
    rows = [("Invoice #", inv["invoice_no"]), ("Date issued", fmt_date(inv["issue_date"]))]
    if show_due and inv["due_date"]:
        rows.append(("Payment due", fmt_date(inv["due_date"])))
    for i, (k, v) in enumerate(rows):
        c.drawString(330, 654 - i * 14, k)
        right(c, 572, 654 - i * 14, v)

    y = 580
    c.setFillColor(colors.HexColor("#e8f1f2"))
    c.rect(40, y - 6, 532, 20, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(48, y, "ITEM")
    right(c, 390, y, "QTY")
    right(c, 480, y, "PRICE")
    right(c, 565, y, "LINE TOTAL")
    c.setFont("Helvetica", 10)
    for n, it in enumerate(inv["line_items"]):
        y -= 22
        if n % 2:
            c.setFillColor(colors.HexColor("#f6f6f6"))
            c.rect(40, y - 6, 532, 20, stroke=0, fill=1)
            c.setFillColor(colors.black)
        c.drawString(48, y, it["description"])
        right(c, 390, y, str(it["quantity"]))
        right(c, 480, y, money_fmt(it["unit_price"]))
        right(c, 565, y, money_fmt(it["quantity"] * it["unit_price"]))

    c.setFillColor(colors.HexColor("#1f6f78"))
    c.rect(372, y - 52, 200, 30, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(382, y - 42, "AMOUNT DUE")
    right(c, 565, y - 42, money_fmt(inv["total"]))
    c.setFillColor(colors.black)


def layout_compact(c, inv, *, show_due=True, total_override=None):
    """Narrow, receipt-like, monospaced."""
    cur = inv["currency"]
    x0, x1 = 170, 442
    y = 740
    c.setFont("Courier-Bold", 13)
    c.drawCentredString(PAGE_W / 2, y, inv["vendor"].upper())
    c.setFont("Courier", 9)
    for line in inv["vendor_address"]:
        y -= 12
        c.drawCentredString(PAGE_W / 2, y, line)
    dash = "-" * 45

    def kv(k, v):
        nonlocal y
        y -= 13
        c.drawString(x0, y, k)
        right(c, x1, y, v)

    y -= 16
    c.drawString(x0, y, dash)
    kv("INVOICE #", inv["invoice_no"])
    kv("DATE", f"{inv['issue_date']:%d %b %Y}")
    if show_due and inv["due_date"]:
        kv("DUE", f"{inv['due_date']:%d %b %Y}")
    kv("CUSTOMER", inv["customer_name"])
    kv("EMAIL", inv["customer_email"])
    y -= 13
    c.drawString(x0, y, dash)
    for it in inv["line_items"]:
        y -= 13
        c.drawString(x0, y, it["description"][:40])
        kv(
            f"  {it['quantity']} x {it['unit_price']:,.2f}",
            f"{it['quantity'] * it['unit_price']:,.2f}",
        )
    y -= 13
    c.drawString(x0, y, dash)
    c.setFont("Courier-Bold", 11)
    kv("TOTAL", f"{cur} {(total_override or inv['total']):,.2f}")
    c.setFont("Courier", 9)
    y -= 26
    c.drawCentredString(PAGE_W / 2, y, "*** THANK YOU ***")


def layout_cluttered(c, inv, rng):
    """Busy layout: small, tightly packed numbers on a background of decoy digits.

    The decoys are in the PDF's text layer too, not just in the image.
    """
    cur = inv["currency"]
    # 1) decoy digit pattern across the whole page (drawn first, so it is also
    #    the first thing in the PDF's extracted text)
    c.setFont("Helvetica", 6)
    c.setFillColor(colors.Color(0.80, 0.80, 0.80))
    for yy in range(30, 780, 8):
        c.drawString(
            20,
            yy,
            " ".join(f"{rng.randint(0, 9999):04d}.{rng.randint(0, 99):02d}" for _ in range(19)),
        )
    c.setFillColor(colors.black)

    # 2) the real content, small and cramped
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, 750, inv["vendor"] + "  —  TAX INVOICE / COPY 3 OF 3")
    c.setFont("Helvetica", 6.5)
    c.drawString(
        40, 740, " / ".join(inv["vendor_address"]) + "   VAT 80 336 6086 98   Reg 0068 3389"
    )
    c.drawString(
        40,
        728,
        f"Inv {inv['invoice_no']}  Iss {inv['issue_date']:%d/%m/%y}  "
        f"Due {inv['due_date']:%d/%m/%y}  PO 8803-6608  Acct 3868-0838",
    )
    c.drawString(40, 718, f"To {inv['customer_name']} <{inv['customer_email']}>")

    y = 700
    c.setFont("Helvetica-Bold", 6.5)
    for x, h in [
        (40, "Ref"),
        (85, "Description"),
        (300, "Qty"),
        (340, "Unit"),
        (400, "Disc"),
        (450, "Net"),
        (520, "Line"),
    ]:
        c.drawString(x, y, h)
    c.setFont("Helvetica", 6.5)
    for it in inv["line_items"]:
        y -= 9
        c.drawString(40, y, f"{rng.randint(1000, 9999)}-{rng.randint(10, 99)}")
        c.drawString(85, y, it["description"])
        c.drawString(300, y, str(it["quantity"]))
        c.drawString(340, y, f"{it['unit_price']:,.2f}")
        c.drawString(400, y, "0.00")
        c.drawString(450, y, f"{it['unit_price']:,.2f}")
        c.drawString(520, y, f"{it['quantity'] * it['unit_price']:,.2f}")
    y -= 14
    c.setFont("Helvetica-Bold", 7)
    c.drawString(400, y, f"Subtotal {cur}")
    c.drawString(520, y, f"{inv['total']:,.2f}")
    c.drawString(400, y - 9, "Tax (0.00%)")
    c.drawString(520, y - 9, "0.00")
    c.drawString(400, y - 18, f"TOTAL {cur}")
    c.drawString(520, y - 18, f"{inv['total']:,.2f}")

    # 3) a rotated "received" stamp over the totals
    c.saveState()
    c.translate(430, y - 20)
    c.rotate(14)
    c.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.45))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(0, 0, "RECEIVED 06/08 8368")
    c.restoreState()


def draw_letter(c):
    """A change-of-address letter: realistic business text, no invoice data."""
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60, 730, "Tidewater Print Studio")
    c.setFont("Helvetica", 10)
    lines = [
        "55 Harbor Way, Norfolk, VA 23510",
        "",
        "June 2, 2026",
        "",
        "Dear Ms. Sato,",
        "",
        "Thank you for another wonderful year working together. We are writing to let",
        "you know that our studio is moving to a larger space this summer. From",
        "August 1 our new address will be 210 Lighthouse Road, Norfolk, VA 23511.",
        "",
        "Nothing about your account changes, and your contact at the studio remains",
        "the same. We look forward to showing you the new print room.",
        "",
        "Warm regards,",
        "",
        "Jamie Ortega",
        "Studio Manager",
    ]
    for i, line in enumerate(lines):
        c.drawString(60, 705 - i * 15, line)
