"""The extract_invoice tool must satisfy strict tool use rules, and the
Pydantic model must mirror it so our code can validate what comes back."""

import pytest
from pydantic import ValidationError

from invoice_batch.schema import EXTRACT_INVOICE_TOOL, TOOL_NAME, InvoiceExtraction

SCHEMA = EXTRACT_INVOICE_TOOL["input_schema"]
NULLABLE_FIELDS = [
    "invoice_no",
    "vendor",
    "customer_email",
    "issue_date",
    "due_date",
    "currency",
    "total",
]


def all_object_schemas(node):
    """Yield every {"type": "object"} schema, including nested ones."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from all_object_schemas(value)
    elif isinstance(node, list):
        for value in node:
            yield from all_object_schemas(value)


def valid_input(**overrides) -> dict:
    data = {
        "is_invoice": True,
        "invoice_no": "INV-1",
        "vendor": "Acme",
        "customer_email": "a@example.com",
        "issue_date": "2026-01-02",
        "due_date": None,
        "currency": "USD",
        "line_items": [{"description": "Widget", "quantity": 2, "unit_price": 5.5}],
        "total": 11.0,
        "issues": [],
    }
    data.update(overrides)
    return data


def test_tool_name_is_extract_invoice():
    assert EXTRACT_INVOICE_TOOL["name"] == TOOL_NAME == "extract_invoice"


def test_tool_uses_strict_mode():
    assert EXTRACT_INVOICE_TOOL["strict"] is True


def test_every_top_level_property_is_required():
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])


def test_every_object_forbids_additional_properties():
    objects = list(all_object_schemas(SCHEMA))
    assert len(objects) == 2  # the invoice and a line item
    assert all(obj["additionalProperties"] is False for obj in objects)


@pytest.mark.parametrize("field", NULLABLE_FIELDS)
def test_optional_fields_accept_null(field):
    assert "null" in SCHEMA["properties"][field]["type"]


def test_is_invoice_is_a_plain_boolean():
    assert SCHEMA["properties"]["is_invoice"]["type"] == "boolean"


def test_pydantic_model_has_the_same_fields_as_the_schema():
    assert set(InvoiceExtraction.model_fields) == set(SCHEMA["properties"])


def test_pydantic_model_accepts_a_null_due_date():
    assert InvoiceExtraction.model_validate(valid_input()).due_date is None


def test_pydantic_model_rejects_a_missing_field():
    data = valid_input()
    del data["total"]
    with pytest.raises(ValidationError):
        InvoiceExtraction.model_validate(data)
