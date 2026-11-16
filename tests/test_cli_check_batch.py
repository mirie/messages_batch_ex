"""check-batch reads the newest run, retrieves once (or watches), and prints."""

import json
from functools import partial

import pytest
from fakes import CREATED, batch_status, fake_status_client, make_run

from invoice_batch import status
from invoice_batch.cli import check_batch


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(check_batch, "RUNS_DIR", tmp_path / "runs")
    return make_run(tmp_path / "runs")


def _use_client(monkeypatch, statuses):
    client = fake_status_client(statuses)
    monkeypatch.setattr(check_batch, "make_client", lambda: client)
    return client


def test_check_once_prints_the_status_of_the_newest_batch(run, monkeypatch, capsys):
    client = _use_client(
        monkeypatch, [batch_status("in_progress", processing=23, created_at=CREATED)]
    )
    check_batch.main([])
    out = capsys.readouterr().out
    assert client.messages.batches.retrieved == ["msgbatch_real"]
    assert "msgbatch_real" in out
    assert "processing 23" in out
    assert "--watch" in out  # tells you how to keep waiting


def test_watch_polls_until_ended(run, monkeypatch, capsys):
    client = _use_client(
        monkeypatch,
        [
            batch_status("in_progress", processing=23, created_at=CREATED),
            batch_status("ended", succeeded=23, created_at=CREATED, ended_at=CREATED),
        ],
    )
    monkeypatch.setattr(check_batch, "watch", partial(status.watch, sleep=lambda s: None))
    check_batch.main(["--watch", "--interval", "5"])
    out = capsys.readouterr().out
    assert client.messages.batches.retrieved == ["msgbatch_real"] * 2
    assert "collect-results" in out  # next step once it has ended


def test_check_writes_the_latest_status_back_into_batch_json(run, monkeypatch):
    _use_client(
        monkeypatch,
        [batch_status("ended", succeeded=23, created_at=CREATED, ended_at=CREATED)],
    )
    check_batch.main([])
    saved = json.loads((run / "batch.json").read_text())
    assert saved["processing_status"] == "ended"
    assert saved["batch_id"] == "msgbatch_real"


def test_a_batch_id_with_no_run_folder_is_checked_without_writing_anything(
    run, monkeypatch, capsys
):
    client = _use_client(
        monkeypatch, [batch_status("in_progress", processing=3, created_at=CREATED)]
    )
    before = (run / "batch.json").read_text()
    check_batch.main(["msgbatch_elsewhere"])
    assert client.messages.batches.retrieved == ["msgbatch_elsewhere"]
    assert (run / "batch.json").read_text() == before
    assert "processing 3" in capsys.readouterr().out
