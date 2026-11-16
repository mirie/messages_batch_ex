"""The invoice JSON schema: the shape of the data extracted from invoice PDF files.

Nullable fields ("type": ["string", "null"]) let Claude say "not on the page"
instead of inventing a value. Sent as output_config.format, it makes the API
guarantee Claude's reply is JSON matching this schema exactly (right keys,
right types).
"""

from pydantic import BaseModel


def _nullable(type_: str, description: str) -> dict:
    return {"type": [type_, "null"], "description": description}


INVOICE_SCHEMA = {
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
        "due_date": _nullable(
            "string", "Payment due date as YYYY-MM-DD, or null if none is printed."
        ),
        "currency": _nullable(
            "string", "ISO 4217 three-letter currency code, e.g. USD, EUR, GBP, CHF."
        ),
        "line_items": {
            "type": "array",
            "description": "One entry per billed line, in document order. Empty if none.",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {
                        "type": "number",
                        "description": "Price per unit as a plain number.",
                    },
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
        "is_invoice",
        "invoice_no",
        "vendor",
        "customer_email",
        "issue_date",
        "due_date",
        "currency",
        "line_items",
        "total",
        "issues",
    ],
    "additionalProperties": False,
}

# What goes in the request:  "output_config": {"format": OUTPUT_FORMAT}
OUTPUT_FORMAT = {"type": "json_schema", "schema": INVOICE_SCHEMA}


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


def parse_extraction(content: list) -> InvoiceExtraction:
    """Read Claude's reply: the JSON is in the text block.

    The content may start with thinking blocks (Haiku and Sonnet 5.5 think by
    default), so look for the text block rather than taking content[0].
    """
    text = next((b.text for b in content if b.type == "text"), None)
    if text is None:
        raise ValueError(f"reply has no text block (got {[b.type for b in content]})")
    return InvoiceExtraction.model_validate_json(text)
