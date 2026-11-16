"""collect-results downloads once the batch has ended and writes results.jsonl."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fakes import batch_status, errored_result, fake_results_client, succeeded_result

from invoice_batch.cli import collect_results

CREATED = datetime(2026, 11, 16, 1, 12, 44, tzinfo=UTC)
ENDED = CREATED + timedelta(minutes=5, seconds=15)

GOOD = {
    "is_invoice": True,
    "invoice_no": "INV-1001",
    "vendor": "Acme",
    "customer_email": "a@b.test",
    "issue_date": "2026-01-02",
    "due_date": "2026-02-01",
    "currency": "USD",
    "line_items": [{"description": "Widget", "quantity": 2, "unit_price": 5.0}],
    "total": 10.0,
    "issues": [],
}
ITEMS = [
    errored_result("21_corrupt", message="The PDF specified could not be processed"),
    succeeded_result(
        "01_clean",
        [
            {"type": "thinking", "thinking": "Sum checks out."},
            {"type": "text", "text": json.dumps(GOOD)},
        ],
    ),
]


@pytest.fixture
def run(tmp_path, monkeypatch):
    run = tmp_path / "runs" / "20261116-011243"
    run.mkdir(parents=True)
    record = {"batch_id": "msgbatch_real", "custom_ids": ["01_clean", "21_corrupt"]}
    (run / "batch.json").write_text(json.dumps(record))
    monkeypatch.setattr(collect_results, "RUNS_DIR", tmp_path / "runs")
    return run


def _use(monkeypatch, status):
    client = fake_results_client(ITEMS, status)
    monkeypatch.setattr(collect_results, "make_client", lambda: client)
    return client


def test_it_refuses_to_download_before_the_batch_has_ended(run, monkeypatch, capsys):
    client = _use(monkeypatch, batch_status("in_progress", processing=2, created_at=CREATED))
    collect_results.main([])
    assert client.messages.batches.results_for == []
    assert not (run / "results.jsonl").exists()
    assert "check-batch" in capsys.readouterr().out


def test_it_writes_results_jsonl_and_prints_each_result_cost_and_wait(run, monkeypatch, capsys):
    status = batch_status("ended", succeeded=1, errored=1, created_at=CREATED, ended_at=ENDED)
    _use(monkeypatch, status)
    collect_results.main([])
    out = capsys.readouterr().out

    lines = (run / "results.jsonl").read_text().splitlines()
    assert [json.loads(line)["custom_id"] for line in lines] == ["01_clean", "21_corrupt"]
    assert json.loads(lines[0])["thinking"] == "Sum checks out."

    assert "01_clean" in out and "end_turn" in out and "INV-1001" in out
    assert "invalid_request_error" in out
    assert "5m 15s" in out  # created_at -> ended_at
    assert "$" in out  # total cost


def test_an_unpriced_model_still_saves_results_and_warns(run, monkeypatch, capsys):
    items = [
        succeeded_result(
            "01_clean", [{"type": "text", "text": json.dumps(GOOD)}], model="claude-unpriced-9"
        )
    ]
    status = batch_status("ended", succeeded=1, created_at=CREATED, ended_at=ENDED)
    monkeypatch.setattr(collect_results, "make_client", lambda: fake_results_client(items, status))
    collect_results.main([])
    out = capsys.readouterr().out
    assert (run / "results.jsonl").exists()
    assert "$?" in out
    assert "COST UNKNOWN" in out and "claude-unpriced-9" in out
