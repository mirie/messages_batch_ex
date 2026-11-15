"""Stage 1: create 23 fake test PDFs and data/ground_truth.json.

Run:  uv run generate_invoices.py

Everything is generated from a fixed random seed, so you get the same files
every time. data/ is git-ignored; just re-run this script to recreate it.

Documents (custom_id = filename stem):
  01-16  clean invoices in 3 layouts (06 genuinely has no due date)
  17     cluttered layout with decoy digits mixed into the text layer
  18     due date printed only in a tiny footer
  19     unusual date format (Roman-numeral months) and Swiss currency "Fr."
  20     printed total does not match its own line items (source error)
  21     corrupt PDF: random bytes with a .pdf name
  22     a business letter (not an invoice)
  23     a blank page
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
INVOICES_DIR = DATA_DIR / "invoices"
GROUND_TRUTH = DATA_DIR / "ground_truth.json"

PAGE_W, PAGE_H = letter
rng = random.Random(42)

VENDORS = [
    ("Bluefin Office Supply", ["118 Market Row", "Portland, OR 97204"]),
    ("Cedar & Pine Woodworks", ["44 Mill Lane", "Asheville, NC 28801"]),
    ("Lumen Data Services", ["900 Cobalt Ave, Suite 12", "Austin, TX 78701"]),
    ("Quillbrook Stationers", ["7 Paper Street", "Leeds LS1 4AP, UK"]),
    ("Orbital Coffee Roasters", ["301 Bean Blvd", "Seattle, WA 98101"]),
    ("Mosswell Landscaping", ["2 Fern Court", "Dublin D02, Ireland"]),
    ("Tidewater Print Studio", ["55 Harbor Way", "Norfolk, VA 23510"]),
    ("Kestrel IT Consulting", ["Rue des Alpes 18", "Lyon 69002, France"]),
]
CUSTOMERS = [
    ("Dana Whitfield", "dana.whitfield@example.com"),
    ("Arjun Mehta", "accounts@mehta-design.example.org"),
    ("Sofia Lindqvist", "sofia.l@example.net"),
    ("Marcus Obi", "billing@obi-studio.example.com"),
    ("Hana Sato", "hana.sato@example.org"),
    ("Theo Brandt", "ap@brandt-logistics.example.net"),
]
PRODUCTS = [
    "A4 copy paper (box of 5 reams)", "Ergonomic desk chair", "Toner cartridge, black",
    "Network audit (hours)", "Oak bookshelf, 5-tier", "Whole-bean coffee, 1 kg",
    "Business cards (500)", "Hedge trimming (hours)", "Cloud backup, monthly plan",
    "Walnut cutting board", "Poster print A2", "On-site support (hours)",
    "Mulch delivery (cubic yard)", "Espresso blend, 250 g", "Spiral notebooks (10-pack)",
]
CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "Fr."}


# ---------------------------------------------------------------- data helpers
def make_line_items(n: int) -> list[dict]:
    items = []
    for desc in rng.sample(PRODUCTS, n):
        items.append({
            "description": desc,
            "quantity": rng.choice([1, 1, 2, 3, 4, 5, 10, 12]),
            "unit_price": round(rng.uniform(4, 450), 2),
        })
    return items


def items_total(items: list[dict]) -> float:
    return round(sum(i["quantity"] * i["unit_price"] for i in items), 2)


def make_invoice(n: int, currency: str | None = None, with_due: bool = True) -> dict:
    vendor, address = VENDORS[n % len(VENDORS)]
    cust_name, cust_email = CUSTOMERS[n % len(CUSTOMERS)]
    issue = date(2026, 1, 5) + timedelta(days=rng.randint(0, 240))
    items = make_line_items(rng.randint(2, 5))
    return {
        "invoice_no": f"INV-2026-{rng.randint(1000, 9999)}",
        "vendor": vendor,
        "vendor_address": address,
        "customer_name": cust_name,
        "customer_email": cust_email,
        "issue_date": issue,
        "due_date": issue + timedelta(days=rng.choice([14, 30, 45])) if with_due else None,
        "currency": currency or rng.choice(["USD", "USD", "EUR", "GBP"]),
        "line_items": items,
        "total": items_total(items),
    }


def money(x: float, currency: str) -> str:
    return f"{CURRENCY_SYMBOL[currency]}{x:,.2f}"


def truth_of(inv: dict) -> dict:
    """The values a perfect extraction should return (dates as ISO strings)."""
    return {
        "invoice_no": inv["invoice_no"],
        "vendor": inv["vendor"],
        "customer_email": inv["customer_email"],
        "issue_date": inv["issue_date"].isoformat(),
        "due_date": inv["due_date"].isoformat() if inv["due_date"] else None,
        "currency": inv["currency"],
        "line_items": inv["line_items"],
        "total": inv["total"],
    }


# ---------------------------------------------------------------- layouts
def right(c, x, y, text):
    c.drawRightString(x, y, text)


def layout_classic(c, inv, *, fmt_date=lambda d: d.isoformat(), show_due=True,
                   footer_note=None, total_override=None):
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


def layout_modern(c, inv, *, fmt_date=lambda d: f"{d:%B} {d.day}, {d.year}",
                  money_fmt=None, show_due=True):
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
        kv(f"  {it['quantity']} x {it['unit_price']:,.2f}",
           f"{it['quantity'] * it['unit_price']:,.2f}")
    y -= 13
    c.drawString(x0, y, dash)
    c.setFont("Courier-Bold", 11)
    kv("TOTAL", f"{cur} {(total_override or inv['total']):,.2f}")
    c.setFont("Courier", 9)
    y -= 26
    c.drawCentredString(PAGE_W / 2, y, "*** THANK YOU ***")


def layout_cluttered(c, inv):
    """Busy layout: a security pattern of decoy digits sits behind (and in the
    text layer alongside) small, tightly packed numbers."""
    cur = inv["currency"]
    # 1) decoy digit pattern across the whole page (drawn first, so it is also
    #    the first thing in the PDF's extracted text)
    c.setFont("Helvetica", 6)
    c.setFillColor(colors.Color(0.80, 0.80, 0.80))
    for yy in range(30, 780, 8):
        c.drawString(20, yy, " ".join(
            f"{rng.randint(0, 9999):04d}.{rng.randint(0, 99):02d}" for _ in range(19)))
    c.setFillColor(colors.black)

    # 2) the real content, small and cramped
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, 750, inv["vendor"] + "  —  TAX INVOICE / COPY 3 OF 3")
    c.setFont("Helvetica", 6.5)
    c.drawString(40, 740, " / ".join(inv["vendor_address"]) + "   VAT 80 336 6086 98   Reg 0068 3389")
    c.drawString(40, 728, f"Inv {inv['invoice_no']}  Iss {inv['issue_date']:%d/%m/%y}  "
                          f"Due {inv['due_date']:%d/%m/%y}  PO 8803-6608  Acct 3868-0838")
    c.drawString(40, 718, f"To {inv['customer_name']} <{inv['customer_email']}>")

    y = 700
    c.setFont("Helvetica-Bold", 6.5)
    for x, h in [(40, "Ref"), (85, "Description"), (300, "Qty"), (340, "Unit"),
                 (400, "Disc"), (450, "Net"), (520, "Line")]:
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


# ---------------------------------------------------------------- non-invoices
def draw_letter(c):
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60, 730, "Tidewater Print Studio")
    c.setFont("Helvetica", 10)
    lines = [
        "55 Harbor Way, Norfolk, VA 23510", "", "June 2, 2026", "",
        "Dear Ms. Sato,", "",
        "Thank you for another wonderful year working together. We are writing to let",
        "you know that our studio is moving to a larger space this summer. From",
        "August 1 our new address will be 210 Lighthouse Road, Norfolk, VA 23511.",
        "",
        "Nothing about your account changes, and your contact at the studio remains",
        "the same. We look forward to showing you the new print room.",
        "", "Warm regards,", "", "Jamie Ortega", "Studio Manager",
    ]
    for i, line in enumerate(lines):
        c.drawString(60, 705 - i * 15, line)


# ---------------------------------------------------------------- build
def save_pdf(name: str, draw) -> None:
    c = canvas.Canvas(str(INVOICES_DIR / f"{name}.pdf"), pagesize=letter)
    c.setTitle(name)
    draw(c)
    c.showPage()
    c.save()


def main() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    for old in INVOICES_DIR.glob("*.pdf"):
        old.unlink()
    docs = []

    def add(name, group, layout, expected, reason, truth, extra=None):
        docs.append({"custom_id": name, "file": f"invoices/{name}.pdf", "group": group,
                     "layout": layout, "expected_outcome": expected,
                     "expected_reason": reason, "truth": truth, **(extra or {})})

    # 01-16 clean invoices, cycling through 3 layouts; 06 has no due date at all
    layouts = {"classic": layout_classic, "modern": layout_modern, "compact": layout_compact}
    names = list(layouts)
    for i in range(1, 17):
        lay = names[(i - 1) % 3]
        no_due = i == 6
        inv = make_invoice(i, with_due=not no_due)
        name = f"{i:02d}_clean_{lay}" + ("_no_due" if no_due else "")
        save_pdf(name, lambda c, inv=inv, lay=lay: layouts[lay](c, inv))
        add(name, "clean", lay, "VALID",
            "Clean invoice; no due date printed, so null is correct." if no_due
            else "Clean invoice.", truth_of(inv))

    # 17 cluttered
    inv = make_invoice(17, currency="EUR")
    inv["line_items"] = [
        {"description": "Server rack rails (pair)", "quantity": 8, "unit_price": 186.38},
        {"description": "Patch cables Cat6 (box)", "quantity": 36, "unit_price": 18.68},
        {"description": "Fibre transceiver 10G", "quantity": 6, "unit_price": 380.83},
        {"description": "Rack install labour (h)", "quantity": 13, "unit_price": 88.50},
    ]
    inv["total"] = items_total(inv["line_items"])
    save_pdf("17_cluttered", lambda c: layout_cluttered(c, inv))
    add("17_cluttered", "hard", "cluttered", "RETRY_ESCALATE",
        "Small digits on a background of decoy digits (also in the PDF text layer); "
        "expected to fail checks, survive a hint, and need the bigger model.", truth_of(inv))

    # 18 due date only in a tiny footer
    inv = make_invoice(18)
    note = (f"Payment terms: amount payable in full by {inv['due_date']:%d %B %Y}. "
            "Late payments incur 1.5% monthly interest.")
    save_pdf("18_footer_due_date", lambda c: layout_classic(c, inv, show_due=False, footer_note=note))
    add("18_footer_due_date", "hard", "classic", "RETRY_WITH_HINT",
        "Due date appears only in a 5pt grey footer. Caution: a missed due date "
        "comes back as null, which the policy treats as valid; only ground truth "
        "reveals the miss.", truth_of(inv))

    # 19 unusual date + currency format
    inv = make_invoice(19, currency="CHF")
    inv["vendor"], inv["vendor_address"] = "Alpenrand Feinmechanik", ["Seestrasse 41", "8002 Zürich"]
    roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
    fmt = lambda d: f"{d.day}.{roman[d.month - 1]}.{d.year}"
    swiss = lambda x: f"Fr. {x:,.2f}".replace(",", "'")
    save_pdf("19_unusual_format", lambda c: layout_modern(c, inv, fmt_date=fmt, money_fmt=swiss))
    add("19_unusual_format", "hard", "modern", "RETRY_WITH_HINT",
        "Dates like 15.III.2026 and amounts like Fr. 1'234.50 (currency should be "
        "returned as CHF).", truth_of(inv))

    # 20 printed total does not match the line items
    inv = make_invoice(20)
    printed = round(inv["total"] + 100.00, 2)
    save_pdf("20_total_mismatch", lambda c: layout_compact(c, inv, total_override=printed))
    t = truth_of(inv)
    t["total"] = printed  # the document really says this
    add("20_total_mismatch", "source_error", "compact", "STABLE_ANSWER",
        "The invoice itself is wrong: printed total is 100.00 more than its line "
        "items. A hint cannot fix the source, so the retry returns the same values.",
        t, {"line_items_sum": inv["total"]})

    # 21 corrupt PDF
    (INVOICES_DIR / "21_corrupt.pdf").write_bytes(rng.randbytes(4096))
    add("21_corrupt", "not_retryable", None, "NO_RETRY",
        "Random bytes with a .pdf name; the API rejects the request (invalid_request_error).", None)

    # 22 letter
    save_pdf("22_letter", draw_letter)
    add("22_letter", "not_retryable", "letter", "NO_RETRY",
        "A change-of-address letter; no invoice data (is_invoice false).", None)

    # 23 blank page
    save_pdf("23_blank", lambda c: None)
    add("23_blank", "not_retryable", "blank", "NO_RETRY", "A blank page; nothing to extract.", None)

    GROUND_TRUTH.write_text(json.dumps({"documents": docs}, indent=2, ensure_ascii=False))

    # ---- summary
    print(f"Wrote {len(docs)} documents to {INVOICES_DIR.relative_to(ROOT)}/ "
          f"and {GROUND_TRUTH.relative_to(ROOT)}\n")
    print(f"{'custom_id':<26} {'group':<14} {'expected_outcome':<16} {'size':>7}")
    print("-" * 66)
    for d in docs:
        size = (DATA_DIR / d["file"]).stat().st_size
        print(f"{d['custom_id']:<26} {d['group']:<14} {d['expected_outcome']:<16} {size:>6}B")
    counts: dict[str, int] = {}
    for d in docs:
        counts[d["expected_outcome"]] = counts.get(d["expected_outcome"], 0) + 1
    print("\nExpected outcomes:", ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
