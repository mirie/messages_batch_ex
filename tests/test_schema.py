"""The invoice JSON schema must satisfy the structured-outputs rules, and the
Pydantic model must mirror it so our code can validate what comes back."""

import copy
import json
from types import SimpleNamespace

import pytest
from fakes import GOOD_EXTRACTION
from pydantic import ValidationError

from invoice_batch.schema import (
    INVOICE_SCHEMA,
    InvoiceExtraction,
    parse_extraction,
)

SCHEMA = INVOICE_SCHEMA
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
    return {**GOOD_EXTRACTION, **overrides}


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


# --- reading Claude's reply ------------------------------------------------


def block(type_, **fields):
    return SimpleNamespace(type=type_, **fields)


def test_reply_is_read_from_the_text_block():
    content = [block("text", text=json.dumps(valid_input()))]
    assert parse_extraction(content).invoice_no == "INV-1001"


def test_thinking_blocks_before_the_reply_are_skipped():
    content = [block("thinking", thinking=""), block("text", text=json.dumps(valid_input()))]
    assert parse_extraction(content).vendor == "Acme"


def test_a_reply_without_a_text_block_is_an_error():
    with pytest.raises(ValueError, match="no text block"):
        parse_extraction([block("thinking", thinking="")])


def test_a_reply_that_does_not_match_the_model_is_an_error():
    with pytest.raises(ValidationError):
        parse_extraction([block("text", text='{"is_invoice": true}')])


def test_blocks_can_also_be_plain_dicts_as_saved_from_batch_results():
    content = [
        {"type": "thinking", "thinking": "ok"},
        {"type": "text", "text": json.dumps(valid_input())},
    ]
    assert parse_extraction(content).invoice_no == "INV-1001"
