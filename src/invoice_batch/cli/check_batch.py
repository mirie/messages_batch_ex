"""Stage 5: check how a submitted batch is doing (free: retrieving costs nothing).

Run:  uv run check-batch                      newest run in runs/
      uv run check-batch 20261116-011243      a specific run folder (or runs/...)
      uv run check-batch msgbatch_...         a specific batch id
      uv run check-batch --watch              poll until it has ended
      uv run check-batch --watch --interval 30
"""

import argparse
from datetime import UTC, datetime

from invoice_batch.config import RUNS_DIR, make_client
from invoice_batch.runs import add_batch_argument, display_path, resolve_batch
from invoice_batch.status import describe, update_batch_record, watch


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="check-batch", description="Check the status of a submitted Message Batch (free)."
    )
    add_batch_argument(parser)
    parser.add_argument("--watch", action="store_true", help="poll until processing has ended")
    parser.add_argument(
        "--interval", type=float, default=60, help="seconds between polls (default 60)"
    )
    args = parser.parse_args(argv)

    batch_id, run_dir = resolve_batch(args.batch, RUNS_DIR)
    where = f"  ({display_path(run_dir, RUNS_DIR.parent)})" if run_dir else ""
    print(f"Batch {batch_id}{where}\n")

    client = make_client()
    if args.watch:
        batch = watch(client, batch_id, interval=args.interval)
        print()
    else:
        batch = client.messages.batches.retrieve(batch_id)

    now = datetime.now(UTC)
    if run_dir is not None:
        update_batch_record(run_dir, batch, checked_at=now)
    print(describe(batch, now=now))

    if batch.processing_status == "ended":
        print("\nDone. Next: uv run collect-results")
    else:
        print("\nStill running. Check again later, or: uv run check-batch --watch")


if __name__ == "__main__":
    main()
