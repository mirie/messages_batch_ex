"""Fake invoice data: vendors, customers, line items, and the ground truth form."""

import random
from datetime import date, timedelta

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
