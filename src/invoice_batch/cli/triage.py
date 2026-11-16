"""Put every document of a collected batch in exactly one failure-policy class.

Run:  uv run triage                       newest run in runs/
      uv run triage 20261116-011243       a specific run folder (or runs/...)

Free and offline: reads batch.json and results.jsonl, writes triage.json next
to them. In a retry round, earlier attempts come from the parent runs'
results.jsonl. Then, for learning, prints a comparison with my predictions
(predictions.json in the run folder, optional) and with ground truth
(data/ground_truth.json, optional). Ground truth never changes a class.
"""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from invoice_batch.compare import expected_verdict, prediction_verdict, truth_diffs
from invoice_batch.config import GROUND_TRUTH, RUNS_DIR
from invoice_batch.results import read_results_jsonl
from invoice_batch.retry import load_histories
from invoice_batch.runs import (
    add_batch_argument,
    display_path,
    load_batch_record,
    resolve_batch,
    write_json_atomic,
)
from invoice_batch.triage import CLASSES, triage_run


def _read_optional_json(path: Path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"Can't read {path}: {e}") from e


def print_triage(decisions: list[dict]) -> None:
    print("Triage (policy checks only, no ground truth)\n")
    for d in decisions:
        print(f"{d['custom_id']:<26} {d['class']:<16} {d['reason']}")
    counts = Counter(d["class"] for d in decisions)
    print("\n" + "  ".join(f"{c} {counts[c]}" for c in CLASSES if counts[c]))


def print_comparison(decisions, predictions, truth_docs, round_no) -> None:
    print("\nPredicted vs actual\n")
    header = (
        f"{'document':<26} {'you predicted':<14} {'expected (truth)':<17} "
        f"{'actual triage':<16} {'you':<9} expected"
    )
    print(header)
    print("-" * len(header))
    for d in decisions:
        cid, actual = d["custom_id"], d["class"]
        guess = (predictions or {}).get(cid)
        expected = (truth_docs.get(cid) or {}).get("expected_outcome")
        exp_verdict = expected_verdict(expected, actual, round_no) if expected else "-"
        print(
            f"{cid:<26} {guess or '-':<14} {expected or '-':<17} {actual:<16} "
            f"{prediction_verdict(guess, actual):<9} {exp_verdict}"
        )


def print_value_check(decisions, records_by_id, truth_docs) -> None:
    print("\nExtracted values vs ground truth (catches wrong answers the policy can't see)\n")
    all_match = []
    for d in decisions:
        cid = d["custom_id"]
        doc = truth_docs.get(cid)
        rec = records_by_id.get(cid) or {}
        diffs = truth_diffs(rec.get("extraction"), doc["truth"] if doc else None)
        if diffs is None:
            print(f"{cid:<26} (no extraction to compare)")
        elif diffs:
            print(f"{cid:<26} {d['class']:<16} {len(diffs)} wrong:")
            for diff in diffs:
                print(f"{'':<44}{diff}")
        else:
            all_match.append(cid)
    print(f"\nall fields match ground truth: {len(all_match)} documents")
    print("(vendor, email and descriptions are compared ignoring case and spacing)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="triage", description="Apply the failure policy to a collected batch (free)."
    )
    add_batch_argument(parser)
    args = parser.parse_args(argv)

    batch_id, run_dir = resolve_batch(args.batch, RUNS_DIR)
    if run_dir is None:
        raise SystemExit(f"No run folder records {batch_id}; triage needs one.")
    record = load_batch_record(run_dir)
    results_path = run_dir / "results.jsonl"
    if not results_path.is_file():
        raise SystemExit(f"No results.jsonl in {run_dir}. Run first: uv run collect-results")

    records = read_results_jsonl(results_path)
    round_no = record.get("round", 1)
    decisions = triage_run(
        record.get("custom_ids", []), records, histories=load_histories(run_dir, RUNS_DIR)
    )
    counts = Counter(d["class"] for d in decisions)

    path = run_dir / "triage.json"
    write_json_atomic(
        path,
        {
            "batch_id": batch_id,
            "round": round_no,
            "triaged_at": datetime.now(UTC).isoformat(),
            "counts": {c: counts[c] for c in CLASSES if counts[c]},
            "documents": decisions,
        },
    )

    print_triage(decisions)

    predictions = _read_optional_json(run_dir / "predictions.json")
    ground_truth = _read_optional_json(GROUND_TRUTH)
    truth_docs = {d["custom_id"]: d for d in (ground_truth or {}).get("documents", [])}
    if predictions is None:
        print("\n(no predictions.json in the run folder, so the 'you predicted' column is empty)")
    if ground_truth is None:
        print(f"\n(no ground truth at {GROUND_TRUTH}; regenerate it: uv run generate-invoices)")
    print_comparison(decisions, predictions, truth_docs, round_no)
    if ground_truth is not None:
        print_value_check(decisions, {r["custom_id"]: r for r in records}, truth_docs)

    print(f"\nsaved: {display_path(path, RUNS_DIR.parent)}")
    print("Next: uv run retry-batch")


if __name__ == "__main__":
    main()
