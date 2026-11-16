"""check-batch reads the newest run, retrieves once (or watches), and prints."""

import json
from datetime import UTC, datetime

import pytest
from fakes import batch_status, fake_status_client

from invoice_batch.cli import check_batch

CREATED = datetime(2026, 11, 16, 1, 12, 44, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path, monkeypatch):
    run = tmp_path / "runs" / "20261116-011243"
    run.mkdir(parents=True)
    (run / "batch.json").write_text(json.dumps({"batch_id": "msgbatch_real"}))
    monkeypatch.setattr(check_batch, "RUNS_DIR", tmp_path / "runs")
    return tmp_path


def _use_client(monkeypatch, statuses):
    client = fake_status_client(statuses)
    monkeypatch.setattr(check_batch, "make_client", lambda: client)
    return client


def test_check_once_prints_the_status_of_the_newest_batch(runs, monkeypatch, capsys):
    client = _use_client(
        monkeypatch, [batch_status("in_progress", processing=23, created_at=CREATED)]
    )
    check_batch.main([])
    out = capsys.readouterr().out
    assert client.messages.batches.retrieved == ["msgbatch_real"]
    assert "msgbatch_real" in out
    assert "processing 23" in out
    assert "--watch" in out  # tells you how to keep waiting


def test_watch_polls_until_ended(runs, monkeypatch, capsys):
    client = _use_client(
        monkeypatch,
        [
            batch_status("in_progress", processing=23, created_at=CREATED),
            batch_status("ended", succeeded=23, created_at=CREATED, ended_at=CREATED),
        ],
    )
    monkeypatch.setattr(check_batch.time, "sleep", lambda s: None)
    check_batch.main(["--watch", "--interval", "5"])
    out = capsys.readouterr().out
    assert client.messages.batches.retrieved == ["msgbatch_real"] * 2
    assert "collect-results" in out  # next step once it has ended


def test_check_writes_the_latest_status_back_into_batch_json(runs, monkeypatch):
    _use_client(
        monkeypatch,
        [batch_status("ended", succeeded=23, created_at=CREATED, ended_at=CREATED)],
    )
    check_batch.main([])
    saved = json.loads((runs / "runs" / "20261116-011243" / "batch.json").read_text())
    assert saved["processing_status"] == "ended"
    assert saved["batch_id"] == "msgbatch_real"


def test_a_relative_run_folder_argument_works(runs, monkeypatch, capsys):
    _use_client(monkeypatch, [batch_status("in_progress", processing=23, created_at=CREATED)])
    monkeypatch.chdir(runs)
    check_batch.main(["runs/20261116-011243"])
    assert "msgbatch_real" in capsys.readouterr().out
