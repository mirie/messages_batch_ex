"""Plan the next round from a triage, and read a document's earlier attempts.

A retry round is a new batch in a new run folder whose batch.json points back
at the run it retries (`parent_run`). Following those links gives each
document's attempt history, which triage needs for STABLE_ANSWER,
RETRY_ESCALATE and MAX_ATTEMPTS.

    class            model                       hint
    RETRY_WITH_HINT  MODEL                       from this attempt's problems
    RETRY_SAME       same as the previous try    same as the previous try
    RETRY_ESCALATE   ESCALATION_MODEL            from this attempt's problems
"""

import json
from pathlib import Path

from invoice_batch.config import ESCALATION_MODEL, MODEL
from invoice_batch.results import read_results_jsonl
from invoice_batch.runs import BATCH_RECORD, load_batch_record
from invoice_batch.triage import RETRY_ESCALATE, RETRY_SAME, RETRY_WITH_HINT


def hint_for(problems: list[str]) -> str | None:
    """The check failures as one sentence, or None if there are none."""
    return "; ".join(problems) + "." if problems else None


def plan_retries(
    triage: dict,
    parent_record: dict,
    model: str = MODEL,
    escalation_model: str = ESCALATION_MODEL,
) -> list[dict]:
    """One {custom_id, class, model, hint} per retryable document, in triage order.

    parent_record is the batch.json of the run that was triaged; RETRY_SAME
    reads the model and hint it used.
    """
    previous_models = parent_record.get("models", {})
    previous_hints = parent_record.get("hints", {})
    plan = []
    for doc in triage.get("documents", []):
        cid, cls = doc["custom_id"], doc["class"]
        if cls == RETRY_WITH_HINT:
            chosen, hint = model, hint_for(doc.get("problems", []))
        elif cls == RETRY_ESCALATE:
            chosen, hint = escalation_model, hint_for(doc.get("problems", []))
        elif cls == RETRY_SAME:
            chosen, hint = previous_models.get(cid, model), previous_hints.get(cid)
        else:
            continue
        plan.append({"custom_id": cid, "class": cls, "model": chosen, "hint": hint})
    return plan


def load_histories(run_dir: Path, runs_dir: Path) -> dict[str, list[dict]]:
    """Earlier results.jsonl records for each of this run's documents, oldest first.

    Walks batch.json's parent_run links back to round 1. Documents with no
    earlier attempt are left out. A broken link stops with an error, because a
    missing attempt would make triage count attempts wrong.
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
        for rec in read_results_jsonl(results):
            if rec.get("custom_id") in custom_ids:
                histories.setdefault(rec["custom_id"], []).append(rec)
    return histories


def child_runs(run_dir: Path, runs_dir: Path) -> list[Path]:
    """Run folders whose batch.json names run_dir as its parent_run."""
    children = []
    for record in sorted(runs_dir.glob(f"*/{BATCH_RECORD}")):
        try:
            parent = json.loads(record.read_text()).get("parent_run")
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        if parent == run_dir.name:
            children.append(record.parent)
    return children
