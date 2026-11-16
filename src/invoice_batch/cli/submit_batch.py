"""Submit every PDF in data/invoices/ as ONE Message Batch.

Run:  uv run submit-batch          show the plan and the cost estimate (free)
      uv run submit-batch --yes    actually submit (costs money)

Submitting returns in about a second with a batch id; the work itself happens
later, somewhere in the next minutes to 24 hours. The id and the submit time
are saved to runs/<timestamp>/batch.json for check-batch and collect-results.
"""

import argparse
from datetime import UTC, datetime

from invoice_batch.batch import (
    batch_size_bytes,
    build_requests,
    check_limits,
    estimate_batch_cost,
    estimate_worst_rounds,
    submit,
    write_batch_record,
)
from invoice_batch.config import ESCALATION_MODEL, INVOICES_DIR, MODEL, RUNS_DIR, make_client
from invoice_batch.runs import display_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="submit-batch", description="Submit every PDF in data/invoices/ as ONE Message Batch."
    )
    parser.add_argument("--yes", action="store_true", help="really submit (costs money)")
    args = parser.parse_args(argv)

    custom_ids = sorted(p.stem for p in INVOICES_DIR.glob("*.pdf"))
    if not custom_ids:
        raise SystemExit(f"No PDFs in {INVOICES_DIR}. Run: uv run generate-invoices")

    requests = build_requests(custom_ids, model=MODEL, pdf_dir=INVOICES_DIR)
    check_limits(requests)
    est = estimate_batch_cost(len(requests), MODEL)

    print(f"Batch plan: {len(requests)} requests, model {MODEL}")
    print(f"  size: {batch_size_bytes(requests) / 1024:,.0f} KB (limit 256 MB)")
    print(f"  custom_ids: {custom_ids[0]} ... {custom_ids[-1]}")
    print("  reply format: output_config.format (invoice JSON schema)")
    print(
        f"  estimated cost at batch price: ~${est['typical']:.4f} typical, "
        f"${est['worst']:.4f} if every request misses the cache"
    )
    worst_rounds = estimate_worst_rounds(len(requests), MODEL, ESCALATION_MODEL)
    print(
        f"  worst case, 3 rounds ({MODEL}, {MODEL} + hint, {ESCALATION_MODEL}; "
        f"every doc fails every time): ${worst_rounds:.4f}"
    )

    if not args.yes:
        print("\nNothing submitted. Re-run with --yes to submit.")
        return

    client = make_client()
    submitted_at = datetime.now(UTC)
    batch = submit(client, requests)
    # Print the id first: the batch is live and billable now, even if saving fails.
    print(f"\nSubmitted batch {batch.id}", flush=True)
    run_dir = RUNS_DIR / submitted_at.strftime("%Y%m%d-%H%M%S")
    path = write_batch_record(run_dir, batch, requests, submitted_at)

    print(f"  processing_status: {batch.processing_status}")
    print(f"  created_at: {batch.created_at}   expires_at: {batch.expires_at}")
    print(f"  saved: {display_path(path, RUNS_DIR.parent)}")
    print("Next: uv run check-batch")


if __name__ == "__main__":
    main()
