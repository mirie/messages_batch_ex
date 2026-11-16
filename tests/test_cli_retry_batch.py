"""retry-batch submits only the retryable documents, as round N+1 of a run."""

import json

import pytest
from fakes import FAKE_PDF, fake_client, make_run

from invoice_batch.cli import retry_batch

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
PARENT = "20261116-040415"

TRIAGE = {
    "batch_id": "msgbatch_parent",
    "round": 1,
    "documents": [
        {"custom_id": "01_ok", "class": "VALID", "reason": "", "problems": [], "attempt": 1},
        {
            "custom_id": "20_total_mismatch",
            "class": "RETRY_WITH_HINT",
            "reason": "",
            "problems": ["line items sum to 1178.88 but the total is 1278.88"],
            "attempt": 1,
        },
        {
            "custom_id": "21_corrupt",
            "class": "NO_RETRY",
            "reason": "",
            "problems": [],
            "attempt": 1,
        },
    ],
}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "invoices"
    pdf_dir.mkdir()
    for name in ["01_ok", "20_total_mismatch", "21_corrupt"]:
        (pdf_dir / f"{name}.pdf").write_bytes(FAKE_PDF)
    runs = tmp_path / "runs"
    parent = make_run(
        runs,
        PARENT,
        batch_id="msgbatch_parent",
        custom_ids=["01_ok", "20_total_mismatch", "21_corrupt"],
        models=dict.fromkeys(["01_ok", "20_total_mismatch", "21_corrupt"], HAIKU),
    )
    (parent / "triage.json").write_text(json.dumps(TRIAGE))
    client = fake_client()
    calls = []

    def make_client():
        calls.append(1)
        return client

    monkeypatch.setattr(retry_batch, "INVOICES_DIR", pdf_dir)
    monkeypatch.setattr(retry_batch, "RUNS_DIR", runs)
    monkeypatch.setattr(retry_batch, "MODEL", HAIKU)
    monkeypatch.setattr(retry_batch, "ESCALATION_MODEL", SONNET)
    monkeypatch.setattr(retry_batch, "make_client", make_client)
    return runs, parent, client, calls


def _child(runs):
    (child,) = [p for p in runs.iterdir() if p.name != PARENT]
    return child


def test_without_yes_it_only_prints_the_plan(setup, capsys):
    runs, parent, client, calls = setup
    retry_batch.main([])
    out = capsys.readouterr().out
    assert calls == []
    assert [p.name for p in runs.iterdir()] == [PARENT]
    assert "round 2" in out
    assert "20_total_mismatch" in out
    assert "RETRY_WITH_HINT" in out
    assert "01_ok" not in out  # VALID documents are not retried
    assert "--yes" in out
    assert "worst case" in out


def test_with_yes_it_submits_only_the_retryable_documents_with_their_hint(setup):
    runs, parent, client, calls = setup
    retry_batch.main(["--yes"])
    (request,) = client.messages.batches.sent
    assert request["custom_id"] == "20_total_mismatch"
    assert request["params"]["model"] == HAIKU
    text = request["params"]["messages"][0]["content"][1]["text"]
    assert "line items sum to 1178.88 but the total is 1278.88" in text


def test_the_new_batch_json_links_back_to_the_parent_run(setup):
    runs, parent, client, calls = setup
    retry_batch.main(["--yes"])
    record = json.loads((_child(runs) / "batch.json").read_text())
    assert record["batch_id"] == "msgbatch_fake123"
    assert record["round"] == 2
    assert record["parent_run"] == PARENT
    assert record["parent_batch_id"] == "msgbatch_parent"
    assert record["custom_ids"] == ["20_total_mismatch"]
    assert record["hints"] == {
        "20_total_mismatch": "line items sum to 1178.88 but the total is 1278.88."
    }


def test_it_points_at_where_to_write_predictions(setup, capsys):
    runs, parent, client, calls = setup
    retry_batch.main(["--yes"])
    out = capsys.readouterr().out
    assert str(_child(runs).name) in out
    assert "predictions.json" in out


def test_it_refuses_to_retry_the_same_run_twice(setup, capsys):
    # A second retry of the same triage would pay twice for the same round.
    runs, parent, client, calls = setup
    retry_batch.main(["--yes"])
    with pytest.raises(SystemExit, match="already retried"):
        retry_batch.main(["--yes", PARENT])
    assert len(calls) == 1


def test_it_needs_triage_json_first(setup):
    runs, parent, client, calls = setup
    (parent / "triage.json").unlink()
    with pytest.raises(SystemExit, match="uv run triage"):
        retry_batch.main([])


def test_nothing_retryable_means_nothing_submitted(setup, capsys):
    runs, parent, client, calls = setup
    done = {**TRIAGE, "documents": [TRIAGE["documents"][0]]}
    (parent / "triage.json").write_text(json.dumps(done))
    retry_batch.main(["--yes"])
    assert calls == []
    assert "Nothing to retry" in capsys.readouterr().out
