"""Turn PDFs into one Message Batch and record what was submitted.

A batch is just a list of {"custom_id", "params"} pairs, where params is
exactly the body you would send to messages.create(). The API answers each
request independently and in any order, so custom_id is how we match results
back to documents later.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from invoice_batch.config import INVOICES_DIR, MODEL
from invoice_batch.pricing import cost_usd
from invoice_batch.request_builder import build_params
from invoice_batch.runs import BATCH_RECORD, iso, write_json_atomic

CUSTOM_ID_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")
MAX_REQUESTS = 100_000
MAX_BATCH_BYTES = 256 * 1024 * 1024

# Measured in the dry run on Haiku 5.5 (per document), and confirmed by
# the first real batch (runs/20261116-011243): input ~1,800, output 300-500,
# prefix 1,608.
DRY_RUN_INPUT_TOKENS = 2000  # uncached part: the PDF + the user text
DRY_RUN_OUTPUT_TOKENS = 500  # the JSON reply, thinking tokens included
DRY_RUN_PREFIX_TOKENS = 1612  # everything up to the system prompt breakpoint (cached)


def build_requests(
    custom_ids: list[str],
    model: str = MODEL,
    hints: dict[str, str] | None = None,
    pdf_dir: Path = INVOICES_DIR,
) -> list[dict]:
    """Build one request per document. `hints` maps a custom_id to its retry hint;
    other documents get the plain prompt."""
    hints = hints or {}
    seen: set[str] = set()
    requests = []
    for cid in custom_ids:
        if not CUSTOM_ID_RE.fullmatch(cid):
            raise ValueError(f"invalid custom_id {cid!r}: must match ^[a-zA-Z0-9_-]{{1,64}}$")
        if cid in seen:
            raise ValueError(f"duplicate custom_id {cid!r}")
        seen.add(cid)
        params = build_params(pdf_dir / f"{cid}.pdf", model, hint=hints.get(cid))
        requests.append({"custom_id": cid, "params": params})
    return requests


def batch_size_bytes(requests: list[dict]) -> int:
    return len(json.dumps({"requests": requests}).encode("utf-8"))


def check_limits(requests: list[dict]) -> None:
    """Fail before submitting rather than have the API reject the batch."""
    if not requests:
        raise ValueError("batch is empty: nothing to submit")
    if len(requests) > MAX_REQUESTS:
        raise ValueError(f"{len(requests)} requests exceeds the {MAX_REQUESTS:,} limit")
    size = batch_size_bytes(requests)
    if size > MAX_BATCH_BYTES:
        raise ValueError(f"batch is {size:,} bytes, over the 256 MB limit")


def submit(client, requests: list[dict]):
    """Returns as soon as the batch is queued; the requests are processed later."""
    return client.messages.batches.create(requests=requests)


def write_batch_record(run_dir: Path, batch, requests: list[dict], submitted_at: datetime) -> Path:
    """Save what check-batch and collect-results need: the batch id, the times,
    and each document's id and model.

    The request bodies are left out: the base64 PDFs are large and can be
    rebuilt from data/.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "batch_id": batch.id,
        "submitted_at": submitted_at.isoformat(),
        "created_at": iso(batch.created_at),
        "expires_at": iso(batch.expires_at),
        "processing_status": batch.processing_status,
        "custom_ids": [r["custom_id"] for r in requests],
        "models": {r["custom_id"]: r["params"]["model"] for r in requests},
    }
    path = run_dir / BATCH_RECORD
    write_json_atomic(path, record)
    return path


def estimate_batch_cost(
    n_requests: int,
    model: str,
    input_tokens: int = DRY_RUN_INPUT_TOKENS,
    output_tokens: int = DRY_RUN_OUTPUT_TOKENS,
    prefix_tokens: int = DRY_RUN_PREFIX_TOKENS,
) -> dict[str, float]:
    """Estimate the batch-price cost of n similar requests.

    typical: the first request writes the shared prefix to the cache and the
             rest read it.
    worst:   every request misses the cache. Cache hits inside a batch are
             best-effort, so this can really happen.
    """
    base = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    write = cost_usd({**base, "cache_creation_input_tokens": prefix_tokens}, model, batch=True)
    read = cost_usd({**base, "cache_read_input_tokens": prefix_tokens}, model, batch=True)
    return {
        "typical": write + max(n_requests - 1, 0) * read,
        "worst": n_requests * write,
    }


def estimate_worst_rounds(
    n_requests: int, model: str, escalation_model: str, rounds: int = 3
) -> float:
    """Upper bound for a full retry run, assuming every document fails every round.

    All rounds except the last run on `model` (the first plain, the next with
    a hint); the last runs on `escalation_model`. Every round uses the
    cache-miss cost, so the bound doesn't depend on cache hits.
    """
    normal = estimate_batch_cost(n_requests, model)["worst"]
    escalated = estimate_batch_cost(n_requests, escalation_model)["worst"]
    return (rounds - 1) * normal + escalated
