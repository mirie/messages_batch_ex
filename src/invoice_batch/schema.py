"""The invoice model: one Pydantic definition, from which the API schema is generated.

No field has a default, so every field is required: a value that isn't on the
page comes back as null rather than as a missing key, which also gives Claude a
way out instead of inventing a value. The API does allow optional fields, but
each one makes the output grammar more complex and is moved after the required
ones in the reply.

INVOICE_SCHEMA comes from the SDK's transform_schema(), the same conversion
client.messages.parse() uses. The API guarantees the reply matches it, except
after a refusal or max_tokens stop, so replies are still validated with
InvoiceExtraction (where extra="forbid" rejects unknown keys).
"""

from anthropic import transform_schema
from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class LineItem(BaseModel):
    model_config = _STRICT

    description: str
    quantity: float
    unit_price: float = Field(description="Price per unit as a plain number.")


class InvoiceExtraction(BaseModel):
    model_config = _STRICT

    is_invoice: bool = Field(
        description="true only if the document is an invoice or bill requesting payment."
    )
    invoice_no: str | None = Field(description="Invoice number exactly as printed.")
    vendor: str | None = Field(description="Name of the business that issued the invoice.")
    customer_email: str | None = Field(description="Email address of the customer being billed.")
    issue_date: str | None = Field(description="Issue date as YYYY-MM-DD.")
    due_date: str | None = Field(
        description="Payment due date as YYYY-MM-DD, or null if none is printed."
    )
    currency: str | None = Field(
        description="ISO 4217 three-letter currency code, e.g. USD, EUR, GBP, CHF."
    )
    line_items: list[LineItem] = Field(
        description="One entry per billed line, in document order. Empty if none."
    )
    total: float | None = Field(
        description="The total amount due exactly as printed, as a plain number."
    )
    issues: list[str] = Field(
        description=(
            "Short notes on anything unreadable, ambiguous or suspicious, e.g. "
            "'printed total does not equal sum of line items'. Empty if none."
        )
    )


INVOICE_SCHEMA = transform_schema(InvoiceExtraction)

# What goes in the request:  "output_config": {"format": OUTPUT_FORMAT}
OUTPUT_FORMAT = {"type": "json_schema", "schema": INVOICE_SCHEMA}


def parse_extraction(content: list) -> InvoiceExtraction:
    """Validate the JSON-outputs reply as an InvoiceExtraction.

    Searches for the text block because a thinking block usually comes first.
    Takes SDK blocks (dry-run) or plain dicts (results.jsonl).
    """
    blocks = [
        b if isinstance(b, dict) else {"type": b.type, "text": getattr(b, "text", None)}
        for b in content
    ]
    text = next((b["text"] for b in blocks if b["type"] == "text"), None)
    if text is None:
        raise ValueError(f"reply has no text block (got {[b['type'] for b in blocks]})")
    return InvoiceExtraction.model_validate_json(text)
