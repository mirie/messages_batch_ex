"""collect-results downloads once the batch has ended and writes results.jsonl."""

import json
from datetime import timedelta

import pytest
from fakes import (
    CREATED,
    GOOD_EXTRACTION,
    batch_status,
    errored_result,
    fake_results_client,
    make_run,
    succeeded_result,
)

from invoice_batch.cli import collect_results

ENDED = CREATED + timedelta(minutes=5, seconds=15)
GOOD_TEXT = {"type": "text", "text": json.dumps(GOOD_EXTRACTION)}
ITEMS = [
    errored_result("21_corrupt", message="The PDF specified could not be processed"),
    succeeded_result("01_clean", [{"type": "thinking", "thinking": "Sum checks out."}, GOOD_TEXT]),
]


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_results, "RUNS_DIR", tmp_path / "runs")
    return make_run(tmp_path / "runs", custom_ids=["01_clean", "21_corrupt"])


def _use(monkeypatch, status, items=ITEMS):
    client = fake_results_client(items, status)
    monkeypatch.setattr(collect_results, "make_client", lambda: client)
    return client


def _ended(**counts):
    return batch_status("ended", created_at=CREATED, ended_at=ENDED, **counts)


def test_it_refuses_to_download_before_the_batch_has_ended(run, monkeypatch, capsys):
    client = _use(monkeypatch, batch_status("in_progress", processing=2, created_at=CREATED))
    collect_results.main([])
    assert client.messages.batches.results_for == []
    assert not (run / "results.jsonl").exists()
    assert "check-batch" in capsys.readouterr().out


def test_it_writes_results_jsonl_and_prints_each_result_cost_and_wait(run, monkeypatch, capsys):
    _use(monkeypatch, _ended(succeeded=1, errored=1))
    collect_results.main([])
    out = capsys.readouterr().out

    records = [json.loads(line) for line in (run / "results.jsonl").read_text().splitlines()]
    assert [r["custom_id"] for r in records] == ["01_clean", "21_corrupt"]
    assert records[0]["thinking"] == "Sum checks out."

    assert "01_clean" in out and "end_turn" in out and "INV-1001" in out
    assert "invalid_request_error" in out
    assert "5m 15s" in out  # created_at -> ended_at
    assert f"actual cost:   ${records[0]['cost_usd']:.6f}" in out  # only succeeded is billed


def test_a_document_with_no_result_is_reported_as_missing(run, monkeypatch, capsys):
    _use(monkeypatch, _ended(errored=1), items=[ITEMS[0]])
    collect_results.main([])
    assert "MISSING results for: 01_clean" in capsys.readouterr().out


def test_an_unpriced_model_still_saves_results_and_warns(run, monkeypatch, capsys):
    items = [succeeded_result("01_clean", [GOOD_TEXT], model="claude-unpriced-9")]
    _use(monkeypatch, _ended(succeeded=1), items=items)
    collect_results.main([])
    out = capsys.readouterr().out
    assert (run / "results.jsonl").exists()
    assert "$?" in out
    assert "COST UNKNOWN" in out and "claude-unpriced-9" in out


def test_print_record_copes_with_missing_fields(capsys):
    rec = {
        "custom_id": "01_x",
        "result_type": "succeeded",
        "stop_reason": None,
        "usage": {},
        "cost_usd": 0.0,
        "parse_ok": True,
        "extraction": {"is_invoice": True, "total": 5.0},  # most keys missing
    }
    collect_results.print_record(rec)
    out = capsys.readouterr().out
    assert "01_x" in out and "total 5.0" in out
