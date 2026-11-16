"""Turn raw batch results into one flat record per document.

Each result line from the API looks like:

    {"custom_id": "...", "result": {"type": "succeeded", "message": {...}}}
    {"custom_id": "...", "result": {"type": "errored",
                                    "error": {"type": "error",
                                              "error": {"type": "invalid_request_error",
                                                        "message": "..."}}}}
    {"custom_id": "...", "result": {"type": "canceled"}}
    {"custom_id": "...", "result": {"type": "expired"}}

The CLI converts each SDK object with .model_dump(mode="json") first, so
everything here works on plain dicts (and missing keys just become None).

Only "succeeded" results are billed. A succeeded result can still fail our
check: a refusal or max_tokens stop breaks the JSON-outputs guarantee, and the
text might not validate. That is recorded as parse_ok False + parse_problem;
deciding what to do about it is triage's job.

A model with no entry in PRICES gives cost_usd None + cost_problem instead of
an exception, so one unpriced result never stops results.jsonl being written.
"""

import json
from pathlib import Path

from pydantic import ValidationError

from invoice_batch.pricing import cost_usd
from invoice_batch.runs import write_text_atomic
from invoice_batch.schema import parse_extraction

BROKEN_STOP_REASONS = ("refusal", "max_tokens")


def record_from_result(raw: dict) -> dict:
    result = raw.get("result") or {}
    rec = {
        "custom_id": raw.get("custom_id"),
        "result_type": result.get("type"),
        "model": None,
        "stop_reason": None,
        "usage": None,
        "cost_usd": 0.0,
        "cost_problem": None,
        "thinking": None,
        "extraction": None,
        "parse_ok": False,
        "parse_problem": None,
        "error_type": None,
        "error_message": None,
    }

    if rec["result_type"] == "succeeded":
        _fill_succeeded(rec, result.get("message") or {})
    elif rec["result_type"] == "errored":
        inner = (result.get("error") or {}).get("error") or {}
        rec["error_type"] = inner.get("type")
        rec["error_message"] = inner.get("message")
    return rec


def _fill_succeeded(rec: dict, message: dict) -> None:
    content = message.get("content") or []
    rec["model"] = message.get("model")
    rec["stop_reason"] = message.get("stop_reason")
    rec["usage"] = message.get("usage") or {}
    rec["cost_usd"], rec["cost_problem"] = _cost(rec["usage"], rec["model"])

    summaries = [b.get("thinking") for b in content if b.get("type") == "thinking"]
    summaries = [s.strip() for s in summaries if s and s.strip()]
    rec["thinking"] = "\n\n".join(summaries) or None

    if rec["stop_reason"] in BROKEN_STOP_REASONS:
        rec["parse_problem"] = f"stop_reason {rec['stop_reason']}: JSON not guaranteed"
        return
    try:
        rec["extraction"] = parse_extraction(content).model_dump()
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in e.errors()
        )
        rec["parse_problem"] = f"JSON failed validation: {problems}"
        return
    except ValueError as e:  # no text block
        rec["parse_problem"] = str(e)
        return
    rec["parse_ok"] = True


def _cost(usage: dict, model: str | None) -> tuple[float | None, str | None]:
    if not model:
        return None, "message has no model, so its cost is unknown"
    try:
        return cost_usd(usage, model, batch=True), None
    except ValueError as e:  # no price for this model
        return None, str(e)


def collect(raws, expected_ids: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """Return (records sorted by custom_id, expected ids that got no result, warnings).

    The API promises one result per custom_id, so duplicates, ids that
    batch.json doesn't list, and results with no id should never happen.
    If they do, they are reported, not silently absorbed.
    """
    by_id: dict[str, dict] = {}
    warnings = []
    expected = set(expected_ids)
    for raw in raws:
        rec = record_from_result(raw)
        cid = rec["custom_id"]
        if not cid:
            warnings.append(f"skipped a {rec['result_type']} result with no custom_id")
            continue
        if cid in by_id:
            warnings.append(f"duplicate result for {cid} (kept the last one)")
        elif cid not in expected:
            warnings.append(f"result for {cid}, which is not in batch.json")
        by_id[cid] = rec
    missing = [cid for cid in expected_ids if cid not in by_id]
    return [by_id[cid] for cid in sorted(by_id)], missing, warnings


def total_cost(records: list[dict]) -> float:
    return sum(r["cost_usd"] for r in records if r["cost_usd"] is not None)


def write_results_jsonl(run_dir: Path, records: list[dict]) -> Path:
    path = run_dir / "results.jsonl"
    write_text_atomic(path, "".join(json.dumps(r) + "\n" for r in records))
    return path


def read_results_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
