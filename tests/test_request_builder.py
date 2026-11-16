"""build_params() must produce the exact request shape from the docs."""

import base64

import pytest

from invoice_batch.request_builder import build_params, tool_choice_for
from invoice_batch.schema import TOOL_NAME

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


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "claude-sonnet-5"])
def test_models_that_allow_it_get_a_forced_tool_choice(model):
    assert tool_choice_for(model) == {"type": "tool", "name": TOOL_NAME}


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2"])
def test_models_that_reject_forcing_get_auto(model):
    assert tool_choice_for(model) == {"type": "auto"}


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


def test_request_sends_only_the_extract_invoice_tool(pdf):
    assert [t["name"] for t in build_params(pdf, "claude-haiku-5-5")["tools"]] == [TOOL_NAME]


def test_hint_is_appended_to_the_user_text(pdf):
    text = user_content(build_params(pdf, "claude-haiku-5-5", hint="total mismatch"))[1]["text"]
    assert "total mismatch" in text


def test_no_hint_means_the_plain_instruction(pdf):
    text = user_content(build_params(pdf, "claude-haiku-5-5"))[1]["text"]
    assert "previous attempt" not in text


def test_auto_models_are_told_to_respond_with_the_tool(pdf):
    text = user_content(build_params(pdf, "claude-sonnet-5-5"))[1]["text"]
    assert "Respond only with the extract_invoice tool call" in text


def test_model_and_tool_choice_travel_together(pdf):
    params = build_params(pdf, "claude-sonnet-5-5")
    assert params["model"] == "claude-sonnet-5-5"
    assert params["tool_choice"] == {"type": "auto"}
