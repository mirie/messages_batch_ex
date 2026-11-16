"""Download a finished batch's results and save one record per document.

Run:  uv run collect-results                       newest run in runs/
      uv run collect-results 20261116-011243       a specific run folder (or runs/...)

Downloading results is free. It only works once processing_status is "ended";
before that there is nothing to download. Writes results.jsonl next to
batch.json, sorted by custom_id (the API returns results in any order).
"""

import argparse

from invoice_batch.config import RUNS_DIR, make_client
from invoice_batch.results import collect, total_cost, write_results_jsonl
from invoice_batch.runs import add_batch_argument, display_path, load_batch_record, resolve_batch
from invoice_batch.status import elapsed_text, utc_text


def _usage_text(usage: dict) -> str:
    return (
        f"in {usage.get('input_tokens', 0):>5}  out {usage.get('output_tokens', 0):>4}  "
        f"cache read {usage.get('cache_read_input_tokens') or 0:>4} "
        f"write {usage.get('cache_creation_input_tokens') or 0:>4}"
    )


def _extraction_text(ex: dict) -> str:
    issues = "; ".join(ex.get("issues") or []) or "none"
    if not ex.get("is_invoice"):
        return f"is_invoice false | issues: {issues}"
    return (
        f"{ex.get('invoice_no')} | {ex.get('vendor')} | "
        f"total {ex.get('total')} {ex.get('currency')} | "
        f"issued {ex.get('issue_date')} due {ex.get('due_date')} | "
        f"{len(ex.get('line_items') or [])} items | issues: {issues}"
    )


def _cost_text(rec: dict) -> str:
    return "$?" if rec["cost_usd"] is None else f"${rec['cost_usd']:.6f}"


def print_record(rec: dict) -> None:
    cid, kind = rec["custom_id"], rec["result_type"]
    if kind == "succeeded":
        print(
            f"{cid:<26} succeeded  {rec.get('stop_reason') or '-':<10} "
            f"{_usage_text(rec.get('usage') or {})}  {_cost_text(rec)}"
        )
        if rec["parse_ok"]:
            print(f"{'':<26} {_extraction_text(rec['extraction'])}")
        else:
            print(f"{'':<26} CHECK FAILED: {rec['parse_problem']}")
    elif kind == "errored":
        print(f"{cid:<26} errored    {rec['error_type']}: {rec['error_message']}  (not billed)")
    else:
        print(f"{cid:<26} {kind:<10} (not billed)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="collect-results", description="Download a finished batch's results (free)."
    )
    add_batch_argument(parser)
    args = parser.parse_args(argv)

    batch_id, run_dir = resolve_batch(args.batch, RUNS_DIR)
    if run_dir is None:
        raise SystemExit(f"No run folder records {batch_id}; results.jsonl needs one.")
    expected = load_batch_record(run_dir).get("custom_ids", [])

    client = make_client()
    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        print(f"Batch {batch_id} is {batch.processing_status}; no results yet.")
        print("Wait for it with: uv run check-batch --watch")
        return

    raws = (item.model_dump(mode="json") for item in client.messages.batches.results(batch_id))
    records, missing, warnings = collect(raws, expected_ids=expected)
    path = write_results_jsonl(run_dir, records)

    print(f"Results for {batch_id}  ({len(records)} results, in custom_id order)\n")
    for rec in records:
        print_record(rec)

    billed = [r for r in records if r["result_type"] == "succeeded"]
    failed = [r for r in billed if not r["parse_ok"]]
    cache_reads = sum(
        1 for r in billed if ((r["usage"] or {}).get("cache_read_input_tokens") or 0) > 0
    )
    print()
    if missing:
        print(f"MISSING results for: {', '.join(missing)}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    counts = {}
    for r in records:
        counts[r["result_type"]] = counts.get(r["result_type"], 0) + 1
    print("result types:  " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"check failed:  {len(failed)} of {len(billed)} succeeded results")
    print(f"cache hits:    {cache_reads} of {len(billed)} billed requests read the cached prefix")
    print(f"actual cost:   ${total_cost(records):.6f} at batch price (only succeeded is billed)")
    unknown = [r for r in billed if r["cost_usd"] is None]
    if unknown:
        print(f"COST UNKNOWN for {len(unknown)} results: {unknown[0]['cost_problem']}")
    print(f"created_at:    {utc_text(batch.created_at)}")
    print(f"ended_at:      {utc_text(batch.ended_at)}")
    print(f"real wait:     {elapsed_text(batch.ended_at - batch.created_at)}")
    print(f"\nsaved: {display_path(path, RUNS_DIR.parent)}")
    print("Next: uv run triage")


if __name__ == "__main__":
    main()
