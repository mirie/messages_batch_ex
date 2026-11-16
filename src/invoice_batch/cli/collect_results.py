"""Stage 6: download a finished batch's results and save one record per document.

Run:  uv run collect-results                       newest run in runs/
      uv run collect-results runs/20261116-011243  a specific run folder

Downloading results is free. It only works once processing_status is "ended";
before that there is nothing to download. Writes results.jsonl next to
batch.json, sorted by custom_id (the API returns results in any order).
"""

import argparse
import json

from invoice_batch.config import RUNS_DIR, make_client
from invoice_batch.results import collect, total_cost, write_results_jsonl
from invoice_batch.status import display_path, elapsed_text, resolve_batch, utc_text


def _usage_text(usage: dict) -> str:
    return (
        f"in {usage.get('input_tokens', 0):>5}  out {usage.get('output_tokens', 0):>4}  "
        f"cache read {usage.get('cache_read_input_tokens') or 0:>4} "
        f"write {usage.get('cache_creation_input_tokens') or 0:>4}"
    )


def _extraction_text(ex: dict) -> str:
    if not ex["is_invoice"]:
        return f"is_invoice false | issues: {'; '.join(ex['issues']) or 'none'}"
    return (
        f"{ex['invoice_no']} | {ex['vendor']} | total {ex['total']} {ex['currency']} | "
        f"issued {ex['issue_date']} due {ex['due_date']} | {len(ex['line_items'])} items | "
        f"issues: {'; '.join(ex['issues']) or 'none'}"
    )


def _cost_text(rec: dict) -> str:
    return "$?" if rec["cost_usd"] is None else f"${rec['cost_usd']:.6f}"


def print_record(rec: dict) -> None:
    cid, kind = rec["custom_id"], rec["result_type"]
    if kind == "succeeded":
        print(
            f"{cid:<26} succeeded  {rec['stop_reason']:<10} "
            f"{_usage_text(rec['usage'])}  {_cost_text(rec)}"
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
    parser.add_argument("batch", nargs="?", help="run folder or batch id (default: newest run)")
    args = parser.parse_args(argv)

    batch_id, run_dir = resolve_batch(args.batch, RUNS_DIR)
    if run_dir is None:
        raise SystemExit(f"No run folder records {batch_id}; results.jsonl needs one.")
    expected = json.loads((run_dir / "batch.json").read_text()).get("custom_ids", [])

    client = make_client()
    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        print(f"Batch {batch_id} is {batch.processing_status}; no results yet.")
        print("Wait for it with: uv run check-batch --watch")
        return

    raws = (item.model_dump(mode="json") for item in client.messages.batches.results(batch_id))
    records, missing = collect(raws, expected_ids=expected)
    path = write_results_jsonl(run_dir, records)

    print(f"Results for {batch_id}  ({len(records)} results, in custom_id order)\n")
    for rec in records:
        print_record(rec)

    billed = [r for r in records if r["result_type"] == "succeeded"]
    failed = [r for r in billed if not r["parse_ok"]]
    cache_reads = sum(1 for r in billed if (r["usage"].get("cache_read_input_tokens") or 0) > 0)
    print()
    if missing:
        print(f"MISSING results for: {', '.join(missing)}")
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
