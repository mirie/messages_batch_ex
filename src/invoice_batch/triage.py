"""Apply the failure policy, putting every document in exactly one class.

    result missing / expired / canceled / errored (not invalid_request) -> RETRY_SAME
    errored with invalid_request_error                                -> NO_RETRY
    succeeded, is_invoice false or an empty document                  -> NO_RETRY
    succeeded, passes the checks                                      -> VALID
    succeeded, fails the checks (or its reply couldn't be parsed):
        same values as the previous attempt                           -> STABLE_ANSWER
        this was attempt 3                                            -> MAX_ATTEMPTS
        this was attempt 2 (the hint attempt)                         -> RETRY_ESCALATE
        this was attempt 1                                            -> RETRY_WITH_HINT

The checks look only at the extraction, never at ground truth: a real pipeline
has no answer key. So a wrong but self-consistent answer (a misread total that
still matches misread line items) passes, and only the ground-truth comparison
in the triage command can catch it.

`history` is the list of earlier results.jsonl records for one document,
oldest first. On round 1 it is empty, so STABLE_ANSWER, MAX_ATTEMPTS and
RETRY_ESCALATE can't happen yet; retry-batch and run-pipeline pass real history in.
"""

import re
from collections.abc import Sequence
from datetime import date

VALID = "VALID"
RETRY_SAME = "RETRY_SAME"
RETRY_WITH_HINT = "RETRY_WITH_HINT"
RETRY_ESCALATE = "RETRY_ESCALATE"
NO_RETRY = "NO_RETRY"
STABLE_ANSWER = "STABLE_ANSWER"
MAX_ATTEMPTS = "MAX_ATTEMPTS"

CLASSES = (
    VALID,
    RETRY_SAME,
    RETRY_WITH_HINT,
    RETRY_ESCALATE,
    NO_RETRY,
    STABLE_ANSWER,
    MAX_ATTEMPTS,
)
RETRY_CLASSES = (RETRY_SAME, RETRY_WITH_HINT, RETRY_ESCALATE)
REVIEW_CLASSES = (NO_RETRY, STABLE_ANSWER, MAX_ATTEMPTS)

ATTEMPT_LIMIT = 3
SUM_TOLERANCE = 0.01
REQUIRED_FIELDS = ("invoice_no", "vendor", "customer_email", "issue_date", "currency", "total")
DATE_FIELDS = ("issue_date", "due_date")  # due_date may be null, but not malformed
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_extraction(ex: dict) -> list[str]:
    """Return what's wrong with a parsed invoice, one sentence per problem, worded
    so a retry can use it as the hint."""
    problems = [f"required field {f} is missing" for f in REQUIRED_FIELDS if ex.get(f) is None]

    for field in DATE_FIELDS:
        value = ex.get(field)
        if value is not None and not _is_iso_date(value):
            problems.append(f"{field} {value!r} is not a YYYY-MM-DD date")

    items = ex.get("line_items") or []
    unreadable = [
        f"line item {number} ({item['description']}) has no {field}"
        for number, item in enumerate(items, start=1)
        for field in ("quantity", "unit_price")
        if item.get(field) is None
    ]
    problems.extend(unreadable)
    if not items:
        problems.append("no line items were extracted")
    elif not unreadable and ex.get("total") is not None:
        # The sum can only be checked once every quantity and unit price is known.
        items_sum = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)
        if abs(items_sum - ex["total"]) > SUM_TOLERANCE:
            problems.append(f"line items sum to {items_sum:.2f} but the total is {ex['total']:.2f}")
    return problems


def _is_iso_date(value: str) -> bool:
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_empty(ex: dict) -> bool:
    fields = (*REQUIRED_FIELDS, "due_date")
    return all(ex.get(f) is None for f in fields) and not ex.get("line_items")


def same_values(a: dict | None, b: dict | None) -> bool:
    """True if two extractions match on every field except the free-text issues list."""
    if a is None or b is None:
        return False
    strip = lambda ex: {k: v for k, v in ex.items() if k != "issues"}  # noqa: E731
    return strip(a) == strip(b)


def _decision(cls: str, reason: str, attempt: int, problems: list[str] | None = None) -> dict:
    return {"class": cls, "reason": reason, "problems": problems or [], "attempt": attempt}


def triage_one(record: dict | None, history: Sequence[dict] = ()) -> dict:
    """Classify one document's latest result. Returns {class, reason, problems, attempt}."""
    attempt = len(history) + 1
    out_of_attempts = attempt >= ATTEMPT_LIMIT

    if record is None:
        return _retry_same("no result came back (treated like expired)", attempt)

    kind = record.get("result_type")
    if kind == "errored":
        error = f"{record.get('error_type')}: {record.get('error_message')}"
        if record.get("error_type") == "invalid_request_error":
            return _decision(NO_RETRY, f"the API rejected the request ({error})", attempt)
        return _retry_same(f"errored ({error})", attempt)
    if kind != "succeeded":
        return _retry_same(f"{kind} (not billed)", attempt)

    if not record.get("parse_ok"):
        problems = [record.get("parse_problem") or "the reply could not be parsed"]
    else:
        ex = record["extraction"]
        if not ex.get("is_invoice"):
            return _decision(NO_RETRY, "not an invoice (is_invoice false)", attempt)
        if _is_empty(ex):
            return _decision(NO_RETRY, "empty document: nothing was extracted", attempt)
        problems = check_extraction(ex)
        if not problems:
            return _decision(VALID, "all checks passed", attempt)

    failing = "; ".join(problems)
    previous = history[-1] if history else None
    if (
        previous
        and record.get("parse_ok")
        and same_values(previous.get("extraction"), record.get("extraction"))
    ):
        return _decision(
            STABLE_ANSWER, f"retry returned the same values, still: {failing}", attempt, problems
        )
    if out_of_attempts:
        return _decision(
            MAX_ATTEMPTS, f"{attempt} attempts used, still: {failing}", attempt, problems
        )
    if attempt == ATTEMPT_LIMIT - 1:
        return _decision(
            RETRY_ESCALATE, f"still failing after the hint: {failing}", attempt, problems
        )
    return _decision(RETRY_WITH_HINT, f"fails checks: {failing}", attempt, problems)


def _retry_same(reason: str, attempt: int) -> dict:
    if attempt >= ATTEMPT_LIMIT:
        return _decision(MAX_ATTEMPTS, f"{attempt} attempts used, last one {reason}", attempt)
    return _decision(RETRY_SAME, reason, attempt)


def triage_run(
    custom_ids: list[str], records: list[dict], histories: dict[str, list[dict]] | None = None
) -> list[dict]:
    """One decision per batch.json custom_id, in that order.

    A custom_id with no record is triaged like expired; a record whose id
    isn't in custom_ids is ignored (see "Triage input rules" in SPEC.md).
    """
    by_id = {r["custom_id"]: r for r in records}
    histories = histories or {}
    return [
        {"custom_id": cid, **triage_one(by_id.get(cid), histories.get(cid, []))}
        for cid in custom_ids
    ]
