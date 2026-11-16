"""Stage 6: turning raw batch results into one record per document."""

import json

import pytest
from fakes import HAIKU, bare_result, errored_result, succeeded_result

from invoice_batch.pricing import cost_usd
from invoice_batch.results import (
    collect,
    read_results_jsonl,
    record_from_result,
    total_cost,
    write_results_jsonl,
)

GOOD = {
    "is_invoice": True,
    "invoice_no": "INV-1001",
    "vendor": "Acme",
    "customer_email": "a@b.test",
    "issue_date": "2026-01-02",
    "due_date": None,
    "currency": "USD",
    "line_items": [{"description": "Widget", "quantity": 2, "unit_price": 5.0}],
    "total": 10.0,
    "issues": [],
}


def text(obj) -> dict:
    return {"type": "text", "text": json.dumps(obj)}


def thinking(summary) -> dict:
    return {"type": "thinking", "thinking": summary, "signature": "sig"}


# --- succeeded ---------------------------------------------------------------------


def test_a_good_result_keeps_the_extraction_thinking_usage_and_cost():
    raw = succeeded_result("01_a", [thinking("Checked the sum."), text(GOOD)])
    rec = record_from_result(raw)
    assert rec["custom_id"] == "01_a"
    assert rec["result_type"] == "succeeded"
    assert rec["stop_reason"] == "end_turn"
    assert rec["model"] == HAIKU
    assert rec["extraction"] == GOOD
    assert rec["parse_ok"] is True
    assert rec["parse_problem"] is None
    assert rec["thinking"] == "Checked the sum."
    assert rec["usage"]["cache_read_input_tokens"] == 1612
    assert rec["cost_usd"] == pytest.approx(cost_usd(rec["usage"], HAIKU, batch=True))


def test_no_thinking_block_means_thinking_is_none():
    rec = record_from_result(succeeded_result("22_letter", [text(GOOD)]))
    assert rec["thinking"] is None
    assert rec["parse_ok"] is True


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_a_stop_reason_that_breaks_the_schema_guarantee_fails_the_check(stop_reason):
    rec = record_from_result(succeeded_result("01_a", [text(GOOD)], stop_reason=stop_reason))
    assert rec["parse_ok"] is False
    assert stop_reason in rec["parse_problem"]
    assert rec["extraction"] is None
    assert rec["cost_usd"] > 0  # it still ran, so it is still billed


def test_a_missing_text_block_fails_the_check():
    rec = record_from_result(succeeded_result("01_a", [thinking("hmm")]))
    assert rec["parse_ok"] is False
    assert "no text block" in rec["parse_problem"]


def test_json_that_fails_validation_fails_the_check():
    broken = {k: v for k, v in GOOD.items() if k != "total"}
    rec = record_from_result(succeeded_result("01_a", [text(broken)]))
    assert rec["parse_ok"] is False
    assert "validation" in rec["parse_problem"]
    assert "total" in rec["parse_problem"]


@pytest.mark.parametrize("model", ["claude-unpriced-9", None])
def test_an_unpriced_or_missing_model_records_no_cost_instead_of_crashing(model):
    rec = record_from_result(succeeded_result("01_a", [text(GOOD)], model=model))
    assert rec["cost_usd"] is None
    assert "price" in rec["cost_problem"] or "model" in rec["cost_problem"]
    assert rec["parse_ok"] is True  # the extraction is still kept


def test_a_priced_result_has_no_cost_problem():
    rec = record_from_result(succeeded_result("01_a", [text(GOOD)]))
    assert rec["cost_problem"] is None


def test_total_cost_skips_results_with_no_known_cost():
    records, *_ = collect(
        [
            succeeded_result("01_a", [text(GOOD)]),
            succeeded_result("02_b", [text(GOOD)], model="claude-unpriced-9"),
        ],
        expected_ids=["01_a", "02_b"],
    )
    assert total_cost(records) == pytest.approx(records[0]["cost_usd"])


# --- errored / canceled / expired ----------------------------------------------------


def test_an_errored_result_records_the_error_type_and_is_not_billed():
    rec = record_from_result(errored_result("21_corrupt", message="Could not process PDF"))
    assert rec["result_type"] == "errored"
    assert rec["error_type"] == "invalid_request_error"
    assert rec["error_message"] == "Could not process PDF"
    assert rec["cost_usd"] == 0
    assert rec["extraction"] is None


@pytest.mark.parametrize("result_type", ["canceled", "expired"])
def test_canceled_and_expired_are_recorded_and_not_billed(result_type):
    rec = record_from_result(bare_result("05_x", result_type))
    assert rec["result_type"] == result_type
    assert rec["cost_usd"] == 0
    assert rec["parse_ok"] is False


# --- the whole batch ------------------------------------------------------------------


def test_collect_matches_by_custom_id_not_order_and_flags_missing_ones():
    raws = [
        succeeded_result("02_b", [text(GOOD)]),
        errored_result("03_c"),
        succeeded_result("01_a", [text(GOOD)]),
    ]
    records, missing = collect(raws, expected_ids=["01_a", "02_b", "03_c", "04_d"])
    assert [r["custom_id"] for r in records] == ["01_a", "02_b", "03_c"]
    assert missing == ["04_d"]


def test_total_cost_adds_up_only_billed_results():
    records, _ = collect(
        [succeeded_result("01_a", [text(GOOD)]), errored_result("02_b")],
        expected_ids=["01_a", "02_b"],
    )
    assert total_cost(records) == pytest.approx(records[0]["cost_usd"])


def test_results_jsonl_round_trips(tmp_path):
    records, _ = collect([succeeded_result("01_a", [text(GOOD)])], expected_ids=["01_a"])
    path = write_results_jsonl(tmp_path, records)
    assert path.name == "results.jsonl"
    assert read_results_jsonl(path) == records
