"""The invoice model: one Pydantic definition, from which the API schema is generated.

Structured outputs require every field to be listed in `required`, so no field
has a default: a value that isn't on the page comes back as null rather than as
a missing key. That also gives Claude a way out instead of inventing a value.
`extra="forbid"` produces the required `additionalProperties: false`.

The API guarantees the reply matches the schema, except after a refusal or
max_tokens stop. So replies are still validated with InvoiceExtraction.
"""

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


def api_schema(model: type[BaseModel]) -> dict:
    """Convert model_json_schema() output to the plain style the API docs use.

    Only the spelling changes, never the meaning: nested models are inlined
    instead of "$ref" links, `anyOf: [X, null]` becomes `type: [X, "null"]`,
    and Pydantic's auto-generated titles are dropped.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def clean(node):
        if isinstance(node, list):
            return [clean(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return clean(defs[node["$ref"].split("/")[-1]])
        node = {k: v for k, v in node.items() if k != "title"}
        branches = node.get("anyOf", [])
        if len(branches) == 2 and {"type": "null"} in branches:
            (other,) = [b for b in branches if b != {"type": "null"}]
            node = {"type": [other["type"], "null"], **_without(node, "anyOf")}
        node = {"type": node["type"], **_without(node, "type")} if "type" in node else node
        return {k: (v if k == "required" else clean(v)) for k, v in node.items()}

    schema = clean(raw)
    assert isinstance(schema, dict)
    return schema


def _without(d: dict, key: str) -> dict:
    return {k: v for k, v in d.items() if k != key}


INVOICE_SCHEMA = api_schema(InvoiceExtraction)

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
