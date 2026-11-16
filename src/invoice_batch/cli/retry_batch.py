"""Submit a retry round with only the documents that triage marked for retry.

Run:  uv run retry-batch                         plan for the newest run (free)
      uv run retry-batch 20261116-040415         plan for a specific run folder
      uv run retry-batch --yes                   actually submit (costs money)

It reads the run's triage.json and sends each document in a RETRY class:

- RETRY_WITH_HINT goes to the normal model, with a hint that names the problems.
- RETRY_SAME is sent again exactly as before.
- RETRY_ESCALATE goes to the escalation model, with the same kind of hint.

The new batch gets its own run folder. Its batch.json records the round number
and the run it retries, so triage can find the earlier attempts later.
"""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime

from invoice_batch.batch import (
    batch_size_bytes,
    build_requests,
    check_limits,
    estimate_batch_cost,
    submit,
    write_batch_record,
)
from invoice_batch.config import ESCALATION_MODEL, INVOICES_DIR, MODEL, RUNS_DIR, make_client
from invoice_batch.retry import child_runs, plan_retries
from invoice_batch.runs import add_batch_argument, display_path, load_batch_record, resolve_batch
from invoice_batch.triage import ATTEMPT_LIMIT


def _estimate(plan: list[dict]) -> dict[str, float]:
    """Return the typical and worst-case cost of this round.

    Each model has its own cache, so the estimate is made per model and then added up.
    """
    per_model = Counter(retry["model"] for retry in plan)
    totals = {"typical": 0.0, "worst": 0.0}
    for model, n in per_model.items():
        est = estimate_batch_cost(n, model)
        totals["typical"] += est["typical"]
        totals["worst"] += est["worst"]
    return totals


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="retry-batch", description="Submit the retryable documents of a run as a new batch."
    )
    add_batch_argument(parser)
    parser.add_argument("--yes", action="store_true", help="really submit (costs money)")
    args = parser.parse_args(argv)

    _, run_dir = resolve_batch(args.batch, RUNS_DIR)
    if run_dir is None:
        raise SystemExit("retry-batch needs a run folder with a triage.json.")
    triage_path = run_dir / "triage.json"
    if not triage_path.is_file():
        raise SystemExit(f"No triage.json in {run_dir.name}. Run first: uv run triage")
    triage = json.loads(triage_path.read_text())
    parent_record = load_batch_record(run_dir)

    already = child_runs(run_dir, RUNS_DIR)
    if already:
        raise SystemExit(
            f"{run_dir.name} was already retried in {already[0].name}. "
            f"Continue from there: uv run triage {already[0].name}"
        )

    round_no = triage.get("round", 1) + 1
    plan = plan_retries(triage, parent_record, MODEL, ESCALATION_MODEL)
    if not plan:
        print(f"Nothing to retry in {run_dir.name}: no RETRY_* documents in triage.json.")
        return

    ids = [retry["custom_id"] for retry in plan]
    requests = build_requests(
        ids,
        models={retry["custom_id"]: retry["model"] for retry in plan},
        hints={retry["custom_id"]: retry["hint"] for retry in plan if retry["hint"]},
        pdf_dir=INVOICES_DIR,
    )
    check_limits(requests)

    print(f"Retry plan: round {round_no}, retrying {run_dir.name} ({len(plan)} documents)\n")
    for retry in plan:
        print(f"{retry['custom_id']:<26} {retry['class']:<16} {retry['model']}")
        print(f"{'':<26} hint: {retry['hint'] or '(none, same request as before)'}")

    est = _estimate(plan)
    rounds_left = ATTEMPT_LIMIT - round_no
    worst = est["worst"] + rounds_left * estimate_batch_cost(len(plan), ESCALATION_MODEL)["worst"]
    print(f"\n  size: {batch_size_bytes(requests) / 1024:,.0f} KB")
    print(
        f"  estimated cost at batch price: ~${est['typical']:.4f} typical, "
        f"${est['worst']:.4f} if every request misses the cache"
    )
    print(
        f"  worst case through round {ATTEMPT_LIMIT} (these documents fail again and "
        f"{'go to ' + ESCALATION_MODEL if rounds_left else 'this is the last round'}): "
        f"${worst:.4f}"
    )

    if not args.yes:
        print("\nNothing submitted. Re-run with --yes to submit.")
        return

    client = make_client()
    submitted_at = datetime.now(UTC)
    batch = submit(client, requests)
    print(f"\nSubmitted batch {batch.id}", flush=True)
    new_dir = RUNS_DIR / submitted_at.strftime("%Y%m%d-%H%M%S")
    extra = {
        "round": round_no,
        "parent_run": run_dir.name,
        "parent_batch_id": parent_record.get("batch_id"),
        "hints": {retry["custom_id"]: retry["hint"] for retry in plan if retry["hint"]},
    }
    path = write_batch_record(new_dir, batch, requests, submitted_at, extra=extra)

    print(f"  processing_status: {batch.processing_status}")
    print(f"  saved: {display_path(path, RUNS_DIR.parent)}")
    template = json.dumps(dict.fromkeys(ids, "succeed | retry | review"))
    print(f"\nBefore triage, write your predictions to runs/{new_dir.name}/predictions.json:")
    print(f"  {template}")
    print("Next: uv run check-batch --watch")


if __name__ == "__main__":
    main()
