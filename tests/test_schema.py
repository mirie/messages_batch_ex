"""The extract_invoice tool must satisfy strict tool use rules, and the
Pydantic model must mirror it so our code can validate what comes back."""

import copy

import pytest
from pydantic import ValidationError

from invoice_batch.schema import EXTRACT_INVOICE_TOOL, InvoiceExtraction

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


def shape(node: dict, defs: dict) -> dict:
    """Boil a JSON schema down to what matters for parity: the allowed JSON
    types, and for objects/arrays the shape of what's inside.

    Ignores descriptions and titles, and treats the two spellings of
    "nullable" as equal: {"type": ["string", "null"]} (our dict) and
    {"anyOf": [{"type": "string"}, {"type": "null"}]} (what Pydantic emits).
    It also follows Pydantic's {"$ref": "#/$defs/LineItem"} links.
    """
    if "$ref" in node:
        node = defs[node["$ref"].split("/")[-1]]
    if "anyOf" in node:
        types: set[str] = set()
        inner: dict = {}
        for branch in node["anyOf"]:
            branch_shape = shape(branch, defs)
            types |= branch_shape.pop("types")
            inner.update(branch_shape)
        return {"types": types, **inner}
    raw = node["type"]
    result: dict = {"types": {raw} if isinstance(raw, str) else set(raw)}
    if "properties" in node:
        result["properties"] = {k: shape(v, defs) for k, v in node["properties"].items()}
        result["required"] = set(node.get("required", []))
    if "items" in node:
        result["items"] = shape(node["items"], defs)
    return result


def pydantic_shape() -> dict:
    schema = InvoiceExtraction.model_json_schema()
    return shape(schema, schema.get("$defs", {}))


def test_pydantic_model_matches_the_tool_schema_field_by_field():
    # Same field names, same JSON types, same nullability, same required
    # fields, all the way down into line_items.
    assert shape(SCHEMA, {}) == pydantic_shape()


def test_parity_check_catches_a_changed_type():
    drifted = copy.deepcopy(SCHEMA)
    drifted["properties"]["total"]["type"] = ["string", "null"]  # Pydantic says float
    assert shape(drifted, {}) != pydantic_shape()


def test_parity_check_catches_a_dropped_null():
    drifted = copy.deepcopy(SCHEMA)
    drifted["properties"]["due_date"]["type"] = "string"  # Pydantic allows None
    assert shape(drifted, {}) != pydantic_shape()


def test_parity_check_looks_inside_line_items():
    drifted = copy.deepcopy(SCHEMA)
    drifted["properties"]["line_items"]["items"]["properties"]["quantity"]["type"] = "integer"
    assert shape(drifted, {}) != pydantic_shape()


def test_pydantic_model_accepts_a_null_due_date():
    assert InvoiceExtraction.model_validate(valid_input()).due_date is None


def test_pydantic_model_rejects_a_missing_field():
    data = valid_input()
    del data["total"]
    with pytest.raises(ValidationError):
        InvoiceExtraction.model_validate(data)
