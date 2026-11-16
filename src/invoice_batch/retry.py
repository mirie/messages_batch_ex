"""Decide what to send in a retry round, and find each document's earlier attempts.

Each retry round is a new batch with its own run folder. Its batch.json has a
`parent_run` field that names the run it retries. By following these links
back to round 1, we can collect every earlier attempt for a document. Triage
needs those attempts to tell whether a retry gave the same answer again.

How each retry class is sent:

    class            model                       hint
    RETRY_WITH_HINT  MODEL                       the problems triage found
    RETRY_SAME       same as the previous try    same as the previous try
    RETRY_ESCALATE   ESCALATION_MODEL            the problems triage found
"""

import json
from pathlib import Path

from invoice_batch.config import ESCALATION_MODEL, MODEL
from invoice_batch.results import read_results_jsonl
from invoice_batch.runs import BATCH_RECORD, load_batch_record
from invoice_batch.triage import RETRY_ESCALATE, RETRY_SAME, RETRY_WITH_HINT


def hint_for(problems: list[str]) -> str | None:
    """Join the problems into one sentence. Return None if there are no problems."""
    return "; ".join(problems) + "." if problems else None


def plan_retries(
    triage: dict,
    parent_record: dict,
    model: str = MODEL,
    escalation_model: str = ESCALATION_MODEL,
) -> list[dict]:
    """Return one plan entry for each document that should be retried.

    Each entry is a dict with custom_id, class, model and hint. Documents in
    other classes are skipped.

    parent_record is the batch.json of the run that was triaged. A RETRY_SAME
    document is sent again with the same model and hint it had in that run.
    """
    previous_models = parent_record.get("models", {})
    previous_hints = parent_record.get("hints", {})
    plan = []
    for doc in triage.get("documents", []):
        custom_id = doc["custom_id"]
        triage_class = doc["class"]
        if triage_class == RETRY_WITH_HINT:
            next_model = model
            hint = hint_for(doc.get("problems", []))
        elif triage_class == RETRY_ESCALATE:
            next_model = escalation_model
            hint = hint_for(doc.get("problems", []))
        elif triage_class == RETRY_SAME:
            next_model = previous_models.get(custom_id, model)
            hint = previous_hints.get(custom_id)
        else:
            continue
        plan.append(
            {"custom_id": custom_id, "class": triage_class, "model": next_model, "hint": hint}
        )
    return plan


def load_histories(run_dir: Path, runs_dir: Path) -> dict[str, list[dict]]:
    """Return the earlier attempts for each document in this run, oldest first.

    The result maps a custom_id to a list of results.jsonl records from earlier
    rounds. It finds them by following parent_run from this run back to round 1.
    A document with no earlier attempts is not in the result.

    If a parent run or its results.jsonl is missing, this stops with an error.
    Without it, triage would count the attempts wrong.
    """
    custom_ids = set(load_batch_record(run_dir).get("custom_ids", []))
    ancestors = []  # nearest parent first
    seen = {run_dir.resolve()}
    parent = load_batch_record(run_dir).get("parent_run")
    while parent:
        folder = (runs_dir / parent).resolve()
        if folder in seen:
            raise SystemExit(f"parent_run links loop back to {parent}")
        if not (folder / BATCH_RECORD).is_file():
            raise SystemExit(f"Parent run {parent} not found in {runs_dir}")
        results = folder / "results.jsonl"
        if not results.is_file():
            raise SystemExit(f"Parent run {parent} has no results.jsonl")
        seen.add(folder)
        ancestors.append(results)
        parent = load_batch_record(folder).get("parent_run")

    histories: dict[str, list[dict]] = {}
    for results in reversed(ancestors):  # oldest first
        for record in read_results_jsonl(results):
            if record.get("custom_id") in custom_ids:
                histories.setdefault(record["custom_id"], []).append(record)
    return histories


def child_runs(run_dir: Path, runs_dir: Path) -> list[Path]:
    """Return the run folders that retry run_dir (their parent_run is run_dir)."""
    children = []
    for record in sorted(runs_dir.glob(f"*/{BATCH_RECORD}")):
        try:
            parent = json.loads(record.read_text()).get("parent_run")
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        if parent == run_dir.name:
            children.append(record.parent)
    return children
