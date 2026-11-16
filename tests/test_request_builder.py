"""build_params() must produce the exact request shape from the docs."""

import base64

import pytest

from invoice_batch.request_builder import build_params
from invoice_batch.schema import OUTPUT_FORMAT

FAKE_PDF = b"%PDF-1.4 not a real pdf, build_params does not parse it\n" * 40


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(FAKE_PDF)
    return path


def user_content(params):
    (message,) = params["messages"]
    assert message["role"] == "user"
    return message["content"]


def test_document_block_comes_before_the_text(pdf):
    assert [b["type"] for b in user_content(build_params(pdf, "claude-haiku-5-5"))] == [
        "document",
        "text",
    ]


def test_pdf_is_base64_without_newlines_and_round_trips(pdf):
    source = user_content(build_params(pdf, "claude-haiku-5-5"))[0]["source"]
    assert source["type"] == "base64"
    assert source["media_type"] == "application/pdf"
    assert "\n" not in source["data"]
    assert base64.standard_b64decode(source["data"]) == FAKE_PDF


def test_system_prompt_is_cached_for_one_hour(pdf):
    (system_block,) = build_params(pdf, "claude-haiku-5-5")["system"]
    assert system_block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_reply_is_constrained_to_the_invoice_json_schema(pdf):
    assert build_params(pdf, "claude-haiku-5-5")["output_config"] == {"format": OUTPUT_FORMAT}


def test_no_tools_are_sent(pdf):
    params = build_params(pdf, "claude-haiku-5-5")
    assert "tools" not in params
    assert "tool_choice" not in params


def test_every_model_gets_the_same_request_apart_from_the_model_name(pdf):
    haiku = build_params(pdf, "claude-haiku-5-5")
    sonnet = build_params(pdf, "claude-sonnet-5-5")
    assert sonnet["model"] == "claude-sonnet-5-5"
    assert {**sonnet, "model": "claude-haiku-5-5"} == haiku


def test_hint_is_appended_to_the_user_text(pdf):
    text = user_content(build_params(pdf, "claude-haiku-5-5", hint="total mismatch"))[1]["text"]
    assert "total mismatch" in text


def test_no_hint_means_the_plain_instruction(pdf):
    text = user_content(build_params(pdf, "claude-haiku-5-5"))[1]["text"]
    assert "previous attempt" not in text


def test_thinking_is_adaptive_with_a_readable_summary(pdf):
    # adaptive: the model decides whether to think; summarized: we can read
    # what it thought about (display changes visibility only, not billing).
    assert build_params(pdf, "claude-haiku-5-5")["thinking"] == {
        "type": "adaptive",
        "display": "summarized",
    }
