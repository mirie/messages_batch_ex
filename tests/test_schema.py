"""The API schema is generated from the Pydantic model and must satisfy the
structured-outputs rules; parse_extraction() reads Claude's reply."""

import json
from types import SimpleNamespace

import pytest
from anthropic import transform_schema
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


def all_nodes(node):
    """Yield every dict in a JSON schema, including nested ones."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from all_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from all_nodes(value)


def all_object_schemas(node):
    return [n for n in all_nodes(node) if n.get("type") == "object"]


def valid_input(**overrides) -> dict:
    return {**GOOD_EXTRACTION, **overrides}


# --- the structured-outputs rules, checked on the generated schema -----------


def test_every_top_level_property_is_required():
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])


def test_every_object_forbids_additional_properties():
    objects = all_object_schemas(SCHEMA)
    assert len(objects) == 2  # the invoice and a line item
    assert all(obj["additionalProperties"] is False for obj in objects)
    assert all(set(obj["required"]) == set(obj["properties"]) for obj in objects)


@pytest.mark.parametrize("field", NULLABLE_FIELDS)
def test_optional_fields_accept_null(field):
    branches = SCHEMA["properties"][field]["anyOf"]
    assert {"type": "null"} in branches


def test_the_schema_is_the_sdk_transform_of_the_model():
    assert SCHEMA == transform_schema(InvoiceExtraction)


def test_every_top_level_field_tells_claude_what_it_is():
    missing = [k for k, v in SCHEMA["properties"].items() if not v.get("description")]
    assert missing == []


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
