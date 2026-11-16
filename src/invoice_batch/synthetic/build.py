"""Builds the 23-document test set and its ground truth.

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
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from invoice_batch.synthetic.data import items_total, make_invoice, truth_of
from invoice_batch.synthetic.layouts import (
    draw_letter,
    layout_classic,
    layout_cluttered,
    layout_compact,
    layout_modern,
)

LAYOUTS = {"classic": layout_classic, "modern": layout_modern, "compact": layout_compact}
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def _save_pdf(invoices_dir: Path, name: str, draw) -> None:
    # invariant: no creation timestamp or random document ID, so bytes are reproducible
    c = canvas.Canvas(str(invoices_dir / f"{name}.pdf"), pagesize=letter, invariant=True)
    c.setTitle(name)
    draw(c)
    c.showPage()
    c.save()


def generate(out_dir: Path, seed: int = 42) -> list[dict]:
    """Write out_dir/invoices/*.pdf and out_dir/ground_truth.json; return the docs.

    The same seed always produces the same documents.
    """
    rng = random.Random(seed)
    invoices_dir = out_dir / "invoices"
    invoices_dir.mkdir(parents=True, exist_ok=True)
    for old in invoices_dir.glob("*.pdf"):
        old.unlink()
    docs: list[dict] = []
    save = lambda name, draw: _save_pdf(invoices_dir, name, draw)  # noqa: E731

    def add(name, group, layout, expected, reason, truth, extra=None):
        docs.append(
            {
                "custom_id": name,
                "file": f"invoices/{name}.pdf",
                "group": group,
                "layout": layout,
                "expected_outcome": expected,
                "expected_reason": reason,
                "truth": truth,
                **(extra or {}),
            }
        )

    # 01-16 clean invoices, cycling through 3 layouts; 06 has no due date at all
    names = list(LAYOUTS)
    for i in range(1, 17):
        lay = names[(i - 1) % 3]
        no_due = i == 6
        inv = make_invoice(rng, i, with_due=not no_due)
        name = f"{i:02d}_clean_{lay}" + ("_no_due" if no_due else "")
        save(name, lambda c, inv=inv, lay=lay: LAYOUTS[lay](c, inv))
        add(
            name,
            "clean",
            lay,
            "VALID",
            "Clean invoice; no due date printed, so null is correct."
            if no_due
            else "Clean invoice.",
            truth_of(inv),
        )

    # 17 cluttered
    inv = make_invoice(rng, 17, currency="EUR")
    inv["line_items"] = [
        {"description": "Server rack rails (pair)", "quantity": 8, "unit_price": 186.38},
        {"description": "Patch cables Cat6 (box)", "quantity": 36, "unit_price": 18.68},
        {"description": "Fibre transceiver 10G", "quantity": 6, "unit_price": 380.83},
        {"description": "Rack install labour (h)", "quantity": 13, "unit_price": 88.50},
    ]
    inv["total"] = items_total(inv["line_items"])
    save("17_cluttered", lambda c: layout_cluttered(c, inv, rng))
    add(
        "17_cluttered",
        "hard",
        "cluttered",
        "RETRY_ESCALATE",
        "Small digits on a background of decoy digits (also in the PDF text layer); "
        "expected to fail checks, survive a hint, and need the bigger model.",
        truth_of(inv),
    )

    # 18 due date only in a tiny footer
    inv18 = make_invoice(rng, 18)
    note = (
        f"Payment terms: amount payable in full by {inv18['due_date']:%d %B %Y}. "
        "Late payments incur 1.5% monthly interest."
    )
    save("18_footer_due_date", lambda c: layout_classic(c, inv18, show_due=False, footer_note=note))
    add(
        "18_footer_due_date",
        "hard",
        "classic",
        "RETRY_WITH_HINT",
        "Due date appears only in a 5pt grey footer. Caution: a missed due date "
        "comes back as null, which the policy treats as valid; only ground truth "
        "reveals the miss.",
        truth_of(inv18),
    )

    # 19 unusual date + currency format
    inv19 = make_invoice(rng, 19, currency="CHF")
    inv19["vendor"], inv19["vendor_address"] = (
        "Alpenrand Feinmechanik",
        ["Seestrasse 41", "8002 Zürich"],
    )
    fmt = lambda d: f"{d.day}.{ROMAN[d.month - 1]}.{d.year}"  # noqa: E731
    swiss = lambda x: f"Fr. {x:,.2f}".replace(",", "'")  # noqa: E731
    save("19_unusual_format", lambda c: layout_modern(c, inv19, fmt_date=fmt, money_fmt=swiss))
    add(
        "19_unusual_format",
        "hard",
        "modern",
        "RETRY_WITH_HINT",
        "Dates like 15.III.2026 and amounts like Fr. 1'234.50 (currency should be "
        "returned as CHF).",
        truth_of(inv19),
    )

    # 20 printed total does not match the line items
    inv20 = make_invoice(rng, 20)
    printed = round(inv20["total"] + 100.00, 2)
    save("20_total_mismatch", lambda c: layout_compact(c, inv20, total_override=printed))
    t = truth_of(inv20)
    t["total"] = printed  # truth is what the page prints, even though it is wrong
    add(
        "20_total_mismatch",
        "source_error",
        "compact",
        "STABLE_ANSWER",
        "The invoice itself is wrong: printed total is 100.00 more than its line "
        "items. A hint cannot fix the source, so the retry returns the same values.",
        t,
        {"line_items_sum": inv20["total"]},
    )

    # 21 corrupt PDF
    (invoices_dir / "21_corrupt.pdf").write_bytes(rng.randbytes(4096))
    add(
        "21_corrupt",
        "not_retryable",
        None,
        "NO_RETRY",
        "Random bytes with a .pdf name; the API rejects the request (invalid_request_error).",
        None,
    )

    # 22 letter
    save("22_letter", draw_letter)
    add(
        "22_letter",
        "not_retryable",
        "letter",
        "NO_RETRY",
        "A change-of-address letter; no invoice data (is_invoice false).",
        None,
    )

    # 23 blank page
    save("23_blank", lambda c: None)
    add("23_blank", "not_retryable", "blank", "NO_RETRY", "A blank page; nothing to extract.", None)

    (out_dir / "ground_truth.json").write_text(
        json.dumps({"documents": docs}, indent=2, ensure_ascii=False)
    )
    return docs
