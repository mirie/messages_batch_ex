"""triage.py puts every document in exactly one failure-policy class."""

import copy

from fakes import GOOD_EXTRACTION

from invoice_batch.triage import (
    MAX_ATTEMPTS,
    NO_RETRY,
    RETRY_ESCALATE,
    RETRY_SAME,
    RETRY_WITH_HINT,
    STABLE_ANSWER,
    VALID,
    check_extraction,
    triage_one,
    triage_run,
)


def ok_record(cid="01_clean", **changes):
    """A succeeded, parsed results.jsonl record; changes edit its extraction."""
    ex = copy.deepcopy(GOOD_EXTRACTION) | changes
    return {
        "custom_id": cid,
        "result_type": "succeeded",
        "parse_ok": True,
        "parse_problem": None,
        "extraction": ex,
        "error_type": None,
    }


def bad_total(cid="01_clean", **changes):
    return ok_record(cid, total=99.0, **changes)


# --- check_extraction: the policy checks for a parsed invoice ---------------


def test_a_good_extraction_has_no_problems():
    assert check_extraction(GOOD_EXTRACTION) == []


def test_a_null_due_date_is_valid():
    assert check_extraction(GOOD_EXTRACTION | {"due_date": None}) == []


def test_line_items_must_sum_to_the_total_within_a_cent():
    assert check_extraction(GOOD_EXTRACTION | {"total": 10.004}) == []
    problems = check_extraction(GOOD_EXTRACTION | {"total": 110.0})
    assert len(problems) == 1
    assert "10.00" in problems[0] and "110.00" in problems[0]


def test_dates_must_be_real_yyyy_mm_dd_dates():
    assert check_extraction(GOOD_EXTRACTION | {"issue_date": "15.III.2026"})
    assert check_extraction(GOOD_EXTRACTION | {"due_date": "2026-02-30"})


def test_a_missing_required_field_is_a_problem():
    problems = check_extraction(GOOD_EXTRACTION | {"invoice_no": None, "total": None})
    assert any("invoice_no" in p for p in problems)
    assert any("total" in p for p in problems)


def test_an_invoice_with_no_line_items_is_a_problem():
    assert check_extraction(GOOD_EXTRACTION | {"line_items": []})


def test_a_null_unit_price_is_named_in_the_problem():
    items = [
        {"description": "Widget", "quantity": 1, "unit_price": 4.0},
        {"description": "Mulch delivery", "quantity": 3, "unit_price": None},
    ]
    problems = check_extraction(GOOD_EXTRACTION | {"line_items": items})
    assert problems == ["line item 2 (Mulch delivery) has no unit_price"]


def test_a_null_quantity_is_named_in_the_problem():
    items = [{"description": "Widget", "quantity": None, "unit_price": 5.0}]
    problems = check_extraction(GOOD_EXTRACTION | {"line_items": items})
    assert problems == ["line item 1 (Widget) has no quantity"]


def test_a_null_line_item_number_triages_as_retry_with_hint():
    items = [{"description": "Widget", "quantity": 2, "unit_price": None}]
    decision = triage_one(ok_record(line_items=items))
    assert decision["class"] == RETRY_WITH_HINT
    assert decision["problems"] == ["line item 1 (Widget) has no unit_price"]


def test_issues_alone_are_not_a_problem():
    # Claude often notes harmless oddities (currency vs. address); that is not a failure.
    assert check_extraction(GOOD_EXTRACTION | {"issues": ["currency vs address"]}) == []


# --- triage_one: one document, first round ----------------------------------


def test_a_clean_result_is_valid():
    assert triage_one(ok_record())["class"] == VALID


def test_a_result_that_fails_checks_is_retried_with_a_hint_naming_the_problem():
    t = triage_one(bad_total())
    assert t["class"] == RETRY_WITH_HINT
    assert t["problems"] and "99.00" in t["problems"][0]
    assert "99.00" in t["reason"]


def test_an_unparseable_reply_is_retried_with_a_hint():
    rec = ok_record() | {"parse_ok": False, "parse_problem": "stop_reason max_tokens"}
    t = triage_one(rec)
    assert t["class"] == RETRY_WITH_HINT
    assert "max_tokens" in t["reason"]


def test_not_an_invoice_goes_to_review():
    t = triage_one(ok_record(is_invoice=False, invoice_no=None, line_items=[], total=None))
    assert t["class"] == NO_RETRY
    assert "not an invoice" in t["reason"]


def test_an_empty_document_goes_to_review():
    empty = {k: None for k in GOOD_EXTRACTION} | {
        "is_invoice": True,
        "line_items": [],
        "issues": [],
    }
    t = triage_one(ok_record(**empty))
    assert t["class"] == NO_RETRY
    assert "empty" in t["reason"]


def test_an_invalid_request_error_goes_to_review():
    rec = {
        "custom_id": "21",
        "result_type": "errored",
        "error_type": "invalid_request_error",
        "error_message": "The PDF specified was not valid.",
    }
    t = triage_one(rec)
    assert t["class"] == NO_RETRY
    assert "The PDF specified was not valid." in t["reason"]


def test_other_errors_expired_canceled_and_missing_results_are_resubmitted_unchanged():
    server = {
        "custom_id": "x",
        "result_type": "errored",
        "error_type": "api_error",
        "error_message": "overloaded",
    }
    assert triage_one(server)["class"] == RETRY_SAME
    assert triage_one({"custom_id": "x", "result_type": "expired"})["class"] == RETRY_SAME
    assert triage_one({"custom_id": "x", "result_type": "canceled"})["class"] == RETRY_SAME
    missing = triage_one(None)
    assert missing["class"] == RETRY_SAME and "no result" in missing["reason"]


# --- triage_one: later rounds use the attempt history ------------------------


def test_still_failing_after_the_hint_attempt_escalates():
    first = bad_total()
    second = ok_record(total=98.0)
    assert triage_one(second, history=[first])["class"] == RETRY_ESCALATE


def test_a_retry_with_the_same_values_is_a_stable_answer():
    first = bad_total(issues=["total looks wrong"])
    second = bad_total(issues=["worded differently"])  # issues text doesn't count
    t = triage_one(second, history=[first])
    assert t["class"] == STABLE_ANSWER


def test_three_failed_attempts_hit_max_attempts():
    history = [bad_total(), ok_record(total=98.0)]
    assert triage_one(ok_record(total=97.0), history=history)["class"] == MAX_ATTEMPTS
    expired = {"custom_id": "x", "result_type": "expired"}
    assert triage_one(expired, history=[expired, expired])["class"] == MAX_ATTEMPTS


def test_a_later_attempt_that_passes_is_valid():
    assert triage_one(ok_record(), history=[bad_total()])["class"] == VALID


def test_the_attempt_number_counts_the_history():
    assert triage_one(ok_record())["attempt"] == 1
    assert triage_one(ok_record(), history=[bad_total()])["attempt"] == 2


# --- triage_run: the whole batch ---------------------------------------------


def test_triage_run_covers_batch_ids_only_in_batch_order():
    records = [ok_record("b"), ok_record("stray"), bad_total("a")]
    out = triage_run(["a", "b", "c"], records)
    assert [t["custom_id"] for t in out] == ["a", "b", "c"]
    assert [t["class"] for t in out] == [RETRY_WITH_HINT, VALID, RETRY_SAME]


def test_triage_run_passes_each_documents_history():
    out = triage_run(["a"], [bad_total("a")], histories={"a": [bad_total("a")]})
    assert out[0]["class"] == STABLE_ANSWER
