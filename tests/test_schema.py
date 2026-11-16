"""The API schema is generated from the Pydantic model and must satisfy the
structured-outputs rules; parse_extraction() reads Claude's reply."""

import json
from types import SimpleNamespace

import pytest
from fakes import GOOD_EXTRACTION
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from invoice_batch.schema import (
    INVOICE_SCHEMA,
    api_schema,
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


# --- api_schema(): Pydantic's spelling -> the spelling we send ---------------


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class Toy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(description="Maybe a note.")
    parts: list[Part]


def test_api_schema_writes_nullable_as_a_type_list_and_keeps_the_description():
    assert api_schema(Toy)["properties"]["note"] == {
        "type": ["string", "null"],
        "description": "Maybe a note.",
    }


def test_api_schema_inlines_nested_models_and_drops_titles_and_defs():
    schema = api_schema(Toy)
    assert schema["properties"]["parts"]["items"] == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and '"title"' not in text


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
    assert "null" in SCHEMA["properties"][field]["type"]


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
