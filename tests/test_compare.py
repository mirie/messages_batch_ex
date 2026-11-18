"""compare.py checks triage against ground truth and against my predictions."""

import copy

from fakes import GOOD_EXTRACTION

from invoice_batch.compare import expected_verdict, prediction_verdict, truth_diffs

TRUTH = {k: v for k, v in GOOD_EXTRACTION.items() if k not in ("is_invoice", "issues")}


def ex(**changes):
    return copy.deepcopy(GOOD_EXTRACTION) | changes


# --- truth_diffs: extracted values vs. the answer key ------------------------


def test_matching_values_have_no_diffs():
    assert truth_diffs(ex(), TRUTH) == []


def test_vendor_and_descriptions_ignore_case_and_spacing():
    upper = ex(
        vendor="  ACME ", line_items=[{"description": "WIDGET", "quantity": 2, "unit_price": 5.0}]
    )
    assert truth_diffs(upper, TRUTH) == []


def test_a_missed_due_date_shows_up_even_though_null_is_valid_to_the_policy():
    diffs = truth_diffs(ex(due_date=None), TRUTH)
    assert diffs == ["due_date: got None, truth '2026-02-01'"]


def test_a_misread_total_and_line_item_show_up():
    misread = ex(
        total=12.0, line_items=[{"description": "Widget", "quantity": 2, "unit_price": 6.0}]
    )
    diffs = truth_diffs(misread, TRUTH)
    assert any(d.startswith("total:") for d in diffs)
    assert any(d.startswith("line_items[0].unit_price:") for d in diffs)


def test_a_null_unit_price_shows_up_as_a_diff():
    unreadable = ex(line_items=[{"description": "Widget", "quantity": 2, "unit_price": None}])
    assert truth_diffs(unreadable, TRUTH) == ["line_items[0].unit_price: got None, truth 5.0"]


def test_a_different_number_of_line_items_is_one_diff():
    diffs = truth_diffs(ex(line_items=[]), TRUTH)
    assert diffs == ["line_items: got 0 items, truth 1"]


def test_no_truth_means_the_document_is_not_an_invoice():
    assert truth_diffs(ex(is_invoice=False), None) == []
    assert truth_diffs(ex(), None) == ["is_invoice: got True, truth: not an invoice"]


def test_no_extraction_has_nothing_to_compare():
    assert truth_diffs(None, TRUTH) is None


# --- expected_verdict: ground truth's expected_outcome vs. round-1 triage ----


def test_same_class_matches():
    assert expected_verdict("VALID", "VALID", round_no=1) == "match"
    assert expected_verdict("NO_RETRY", "NO_RETRY", round_no=1) == "match"


def test_later_round_outcomes_on_their_way_are_not_reachable_yet():
    assert expected_verdict("STABLE_ANSWER", "RETRY_WITH_HINT", round_no=1) == "not reachable yet"
    assert expected_verdict("RETRY_ESCALATE", "RETRY_WITH_HINT", round_no=1) == (
        "not reachable yet"
    )


def test_a_document_that_left_the_loop_early_is_a_mismatch():
    # 17_cluttered was meant to need escalation; if it passes on round 1, that differs.
    assert expected_verdict("RETRY_ESCALATE", "VALID", round_no=1) == "MISMATCH"
    assert expected_verdict("RETRY_WITH_HINT", "VALID", round_no=1) == "MISMATCH"


def test_on_later_rounds_nothing_is_excused():
    assert expected_verdict("STABLE_ANSWER", "RETRY_WITH_HINT", round_no=3) == "MISMATCH"


# --- prediction_verdict: my succeed / retry / review guess -------------------


def test_predictions_map_onto_classes():
    assert prediction_verdict("succeed", "VALID") == "match"
    assert prediction_verdict("retry", "RETRY_WITH_HINT") == "match"
    assert prediction_verdict("retry", "RETRY_SAME") == "match"
    assert prediction_verdict("review", "NO_RETRY") == "match"
    assert prediction_verdict("review", "STABLE_ANSWER") == "match"
    assert prediction_verdict("retry", "VALID") == "MISMATCH"
    assert prediction_verdict(None, "VALID") == "-"
