"""Stage 5: ask the API how a batch is doing.

batches.retrieve() is free and idempotent, so it is safe to call as often as
you like. Two things worth knowing from the docs:

- request_counts.succeeded / errored / canceled / expired stay at 0 until the
  WHOLE batch ends. While it runs, every request counts as "processing", so
  you can't watch results trickle in one by one.
- ended_at and results_url are null until processing_status is "ended".
"""

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

COUNT_FIELDS = ("processing", "succeeded", "errored", "canceled", "expired")


def resolve_batch(arg: str | None, runs_dir: Path) -> tuple[str, Path | None]:
    """Turn the command-line argument into (batch_id, run folder or None).

    None            -> the newest runs/*/batch.json (folders are timestamps)
    a folder path   -> that folder's batch.json
    a batch id      -> the run folder that recorded it, if there is one
    """
    records = sorted(runs_dir.glob("*/batch.json"))
    if arg is None:
        if not records:
            raise SystemExit(f"No runs found in {runs_dir}. Submit one first: uv run submit-batch")
        return _read_id(records[-1]), records[-1].parent

    folder = Path(arg)
    if (folder / "batch.json").is_file():
        return _read_id(folder / "batch.json"), folder

    for record in records:
        if _read_id(record) == arg:
            return arg, record.parent
    return arg, None


def _read_id(record: Path) -> str:
    return json.loads(record.read_text())["batch_id"]


def elapsed_text(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    return f"{minutes}m {seconds:02d}s"


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
):
    """Poll until processing_status is "ended"; one timestamped line per poll."""
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        out(poll_line(batch, now()))
        if batch.processing_status == "ended":
            return batch
        sleep(interval)
