"""Compare triage with ground truth and with my predictions.

This is for learning only. The pipeline itself never reads ground truth (a
real pipeline has no answer key), so nothing here changes a triage class.

Three questions, three functions:

    truth_diffs         were the extracted VALUES right?
    expected_verdict    did triage pick the CLASS ground truth expected?
    prediction_verdict  did my succeed / retry / review guess come true?
"""

from invoice_batch.triage import RETRY_CLASSES, RETRY_WITH_HINT, REVIEW_CLASSES, VALID

TOLERANCE = 0.01
TEXT_FIELDS = ("invoice_no", "vendor", "customer_email", "issue_date", "due_date", "currency")
CASE_INSENSITIVE = {"vendor", "customer_email", "description"}

# expected_outcome values that need more than one round to reach.
LATER_ROUND = {"RETRY_ESCALATE", "STABLE_ANSWER", "MAX_ATTEMPTS"}

PREDICTION_CLASSES = {
    "succeed": (VALID,),
    "retry": RETRY_CLASSES,
    "review": REVIEW_CLASSES,
}


def _same_text(field: str, got, truth) -> bool:
    if field in CASE_INSENSITIVE and isinstance(got, str) and isinstance(truth, str):
        return " ".join(got.split()).casefold() == " ".join(truth.split()).casefold()
    return got == truth


def _same_number(got, truth) -> bool:
    if got is None or truth is None:
        return got is truth
    return abs(got - truth) <= TOLERANCE


def truth_diffs(extraction: dict | None, truth: dict | None) -> list[str] | None:
    """Return the fields that differ from ground truth, or None if there is no
    extraction to compare.

    Non-invoices (the letter, the blank page) have no truth values, so for
    them only is_invoice is checked.
    """
    if extraction is None:
        return None
    if truth is None:
        if extraction.get("is_invoice"):
            return ["is_invoice: got True, truth: not an invoice"]
        return []
    if not extraction.get("is_invoice"):
        return ["is_invoice: got False, truth: an invoice"]

    diffs = [
        f"{f}: got {extraction.get(f)!r}, truth {truth.get(f)!r}"
        for f in TEXT_FIELDS
        if not _same_text(f, extraction.get(f), truth.get(f))
    ]
    if not _same_number(extraction.get("total"), truth.get("total")):
        diffs.append(f"total: got {extraction.get('total')}, truth {truth.get('total')}")

    got_items, true_items = extraction.get("line_items") or [], truth.get("line_items") or []
    if len(got_items) != len(true_items):
        diffs.append(f"line_items: got {len(got_items)} items, truth {len(true_items)}")
        return diffs
    for n, (got, want) in enumerate(zip(got_items, true_items, strict=True)):
        if not _same_text("description", got["description"], want["description"]):
            diffs.append(
                f"line_items[{n}].description: got {got['description']!r}, "
                f"truth {want['description']!r}"
            )
        for key in ("quantity", "unit_price"):
            if not _same_number(got[key], want[key]):
                diffs.append(f"line_items[{n}].{key}: got {got[key]}, truth {want[key]}")
    return diffs


def expected_verdict(expected: str, actual: str, round_no: int) -> str:
    """Returns match, MISMATCH, or "not reachable yet".

    expected_outcome is the FINAL outcome after all rounds. On round 1 a
    later-round outcome (escalate, stable answer, max attempts) can't happen
    yet; a document still on its way there is RETRY_WITH_HINT. One that came
    back VALID or NO_RETRY has already left the loop, so that is a mismatch.
    """
    if expected == actual:
        return "match"
    if round_no == 1 and expected in LATER_ROUND and actual == RETRY_WITH_HINT:
        return "not reachable yet"
    return "MISMATCH"


def prediction_verdict(prediction: str | None, actual: str) -> str:
    if prediction is None:
        return "-"
    return "match" if actual in PREDICTION_CLASSES.get(prediction, ()) else "MISMATCH"
