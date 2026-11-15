"""Stage 2: the extract_invoice tool, the "blank form" Claude fills in.

Run:  uv run schema.py     (prints the definition; no API call, no key needed)

Why a tool? With tool_choice forcing this tool, Claude's whole answer IS the
tool call. Nothing has to run on our side, so it works inside a batch even
though a batch request is only ONE turn.

Nullable fields ("type": ["string", "null"]) let Claude say "not on the page"
instead of inventing a value. strict: true makes the API guarantee the tool
input matches this schema exactly (right keys, right types).
"""

import json

from pydantic import BaseModel

TOOL_NAME = "extract_invoice"


def _nullable(type_: str, description: str) -> dict:
    return {"type": [type_, "null"], "description": description}


EXTRACT_INVOICE_TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Record the data extracted from one document. Call this exactly once per "
        "document. Use null for any field that is not printed on the document; "
        "never guess or compute a value that is not shown."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "is_invoice": {
                "type": "boolean",
                "description": "true only if the document is an invoice or bill requesting payment.",
            },
            "invoice_no": _nullable("string", "Invoice number exactly as printed."),
            "vendor": _nullable("string", "Name of the business that issued the invoice."),
            "customer_email": _nullable("string", "Email address of the customer being billed."),
            "issue_date": _nullable("string", "Issue date as YYYY-MM-DD."),
            "due_date": _nullable("string", "Payment due date as YYYY-MM-DD, or null if none is printed."),
            "currency": _nullable("string", "ISO 4217 three-letter currency code, e.g. USD, EUR, GBP, CHF."),
            "line_items": {
                "type": "array",
                "description": "One entry per billed line, in document order. Empty if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit_price": {"type": "number", "description": "Price per unit as a plain number."},
                    },
                    "required": ["description", "quantity", "unit_price"],
                    "additionalProperties": False,
                },
            },
            "total": _nullable("number", "The total amount due exactly as printed, as a plain number."),
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Short notes on anything unreadable, ambiguous or suspicious, e.g. "
                    "'printed total does not equal sum of line items'. Empty if none."
                ),
            },
        },
        "required": [
            "is_invoice", "invoice_no", "vendor", "customer_email", "issue_date",
            "due_date", "currency", "line_items", "total", "issues",
        ],
        "additionalProperties": False,
    },
}


# The same shape as a Pydantic model, so our code can validate what comes back.
class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float


class InvoiceExtraction(BaseModel):
    is_invoice: bool
    invoice_no: str | None
    vendor: str | None
    customer_email: str | None
    issue_date: str | None
    due_date: str | None
    currency: str | None
    line_items: list[LineItem]
    total: float | None
    issues: list[str]


if __name__ == "__main__":
    from common import ESCALATION_MODEL, MODEL, tool_choice_for

    print("=== The tool definition sent with every request ===\n")
    print(json.dumps(EXTRACT_INVOICE_TOOL, indent=2))
    print("\n=== Fields at a glance ===\n")
    props = EXTRACT_INVOICE_TOOL["input_schema"]["properties"]
    for name, spec in props.items():
        t = spec["type"]
        t = " or ".join(t) if isinstance(t, list) else t
        print(f"  {name:<15} {t}")
    print("\n=== tool_choice per model ===\n")
    for m in (MODEL, ESCALATION_MODEL):
        print(f"  {m:<20} {json.dumps(tool_choice_for(m))}")
    print("\n  Forced ({'type': 'tool'}) means the reply can only be this tool call.")
    print("  'auto' is used where the model rejects forced tool use (400 error);")
    print("  the prompt then asks for the tool, and strict: true still guarantees the shape.")
