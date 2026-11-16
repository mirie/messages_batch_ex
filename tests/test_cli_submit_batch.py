"""submit-batch only spends money with --yes, and then records the batch."""

import json

import pytest
from fakes import FAKE_PDF, fake_client

from invoice_batch.cli import submit_batch


@pytest.fixture
def setup(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "invoices"
    pdf_dir.mkdir()
    for name in ["01_a", "02_b"]:
        (pdf_dir / f"{name}.pdf").write_bytes(FAKE_PDF)
    client = fake_client()
    calls = []

    def make_client():
        calls.append(1)
        return client

    monkeypatch.setattr(submit_batch, "INVOICES_DIR", pdf_dir)
    monkeypatch.setattr(submit_batch, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(submit_batch, "make_client", make_client)
    return tmp_path, client, calls


def test_without_yes_it_only_prints_the_plan(setup, capsys):
    tmp_path, client, calls = setup
    submit_batch.main([])
    out = capsys.readouterr().out
    assert calls == []  # never even builds a client
    assert not (tmp_path / "runs").exists()
    assert "2 requests" in out
    assert "--yes" in out
    assert "worst case, 3 rounds" in out


def test_with_yes_it_submits_and_writes_batch_json(setup, capsys):
    tmp_path, client, calls = setup
    submit_batch.main(["--yes"])
    assert [r["custom_id"] for r in client.messages.batches.sent] == ["01_a", "02_b"]
    (record_path,) = (tmp_path / "runs").glob("*/batch.json")
    assert json.loads(record_path.read_text())["batch_id"] == "msgbatch_fake123"
    assert "msgbatch_fake123" in capsys.readouterr().out
