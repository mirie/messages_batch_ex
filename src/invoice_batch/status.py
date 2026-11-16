"""Stage 5: ask the API how a batch is doing.

batches.retrieve() is free and idempotent, so it is safe to call as often as
you like. Two things worth knowing from the docs:

- request_counts.succeeded / errored / canceled / expired stay at 0 until the
  WHOLE batch ends. While it runs, every request counts as "processing", so
  you can't watch results trickle in one by one.
- ended_at and results_url are null until processing_status is "ended".
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anthropic

from invoice_batch.runs import BATCH_RECORD, iso, load_batch_record, write_json_atomic

COUNT_FIELDS = ("processing", "succeeded", "errored", "canceled", "expired")

# Worth waiting out during a long --watch (the SDK has already retried a few
# times by the time one of these reaches us). Anything else is a real problem.
TRANSIENT_ERRORS = (
    anthropic.APIConnectionError,  # includes timeouts
    anthropic.InternalServerError,  # any 5xx, including 529 overloaded
    anthropic.RateLimitError,
)


def elapsed_text(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    return f"{minutes}m {seconds:02d}s"


def update_batch_record(run_dir: Path, batch, checked_at: datetime) -> None:
    """Write the latest status into batch.json so the file never goes stale.

    batch.json starts as a snapshot from submit time; everything else in it
    (ids, models, submit time) is kept as-is.
    """
    record = load_batch_record(run_dir)
    record["processing_status"] = batch.processing_status
    record["request_counts"] = {name: getattr(batch.request_counts, name) for name in COUNT_FIELDS}
    record["ended_at"] = iso(batch.ended_at)
    record["last_checked_at"] = iso(checked_at)
    write_json_atomic(run_dir / BATCH_RECORD, record)


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def counts_text(batch) -> str:
    counts = batch.request_counts
    return "  ".join(f"{name} {getattr(counts, name)}" for name in COUNT_FIELDS)


def describe(batch, now: datetime) -> str:
    """A few readable lines about one retrieved batch."""
    lines = [
        f"processing_status: {batch.processing_status}",
        f"request_counts:    {counts_text(batch)}",
        f"created_at:        {utc_text(batch.created_at)}",
        f"now:               {utc_text(now)}",
    ]
    if batch.ended_at is not None:
        lines.append(f"ended_at:          {utc_text(batch.ended_at)}")
        lines.append(f"total wait:        {elapsed_text(batch.ended_at - batch.created_at)}")
        lines.append(f"results_url:       {batch.results_url}")
    else:
        lines.append(f"elapsed:           {elapsed_text(now - batch.created_at)}")
    return "\n".join(lines)


def poll_line(batch, now: datetime) -> str:
    return (
        f"[{now.astimezone(UTC):%H:%M:%S}] {batch.processing_status:<11} "
        f"{counts_text(batch)}  (elapsed {elapsed_text(now - batch.created_at)})"
    )


def watch(
    client,
    batch_id: str,
    interval: float = 60,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
    transient: tuple[type[Exception], ...] = TRANSIENT_ERRORS,
    max_errors: int = 5,
):
    """Poll until processing_status is "ended"; one timestamped line per poll.

    A transient error prints a line and the next poll tries again; after
    max_errors in a row it gives up and re-raises.
    """
    errors_in_a_row = 0
    while True:
        try:
            batch = client.messages.batches.retrieve(batch_id)
        except transient as e:
            errors_in_a_row += 1
            if errors_in_a_row >= max_errors:
                raise
            out(
                f"[{now().astimezone(UTC):%H:%M:%S}] retrieve failed ({type(e).__name__}: {e}); "
                f"trying again in {interval:g}s ({errors_in_a_row}/{max_errors})"
            )
            sleep(interval)
            continue
        errors_in_a_row = 0
        out(poll_line(batch, now()))
        if batch.processing_status == "ended":
            return batch
        sleep(interval)
