"""dry-run sends the default 4 documents, or the custom_ids given on the command line."""

import json
from types import SimpleNamespace

import pytest
from fakes import FAKE_PDF, GOOD_EXTRACTION

from invoice_batch.cli import dry_run


class FakeMessages:
    """Stand in for client.messages and record the model of each request."""

    def __init__(self):
        self.created_for = []

    def create(self, **params):
        self.created_for.append(params["model"])
        return SimpleNamespace(
            model=params["model"],
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(GOOD_EXTRACTION))],
            usage=SimpleNamespace(
                model_dump=lambda: {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                }
            ),
        )


@pytest.fixture
def invoices_dir(tmp_path, monkeypatch):
    """Point dry-run at a folder of fake PDFs and record which ones it reads."""
    for custom_id in [*dry_run.DOCS, "24_degraded_scan"]:
        (tmp_path / f"{custom_id}.pdf").write_bytes(FAKE_PDF)
    monkeypatch.setattr(dry_run, "pdf_path_for", lambda custom_id: tmp_path / f"{custom_id}.pdf")
    return tmp_path


@pytest.fixture
def client(monkeypatch):
    fake = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(dry_run, "make_client", lambda: fake)
    return fake


def test_no_arguments_runs_the_default_four_documents(invoices_dir, client, capsys):
    dry_run.main([])
    output = capsys.readouterr().out
    assert len(client.messages.created_for) == 4
    for custom_id in dry_run.DOCS:
        assert custom_id in output


def test_given_custom_ids_run_only_those_documents(invoices_dir, client, capsys):
    dry_run.main(["24_degraded_scan"])
    output = capsys.readouterr().out
    assert len(client.messages.created_for) == 1
    assert "24_degraded_scan" in output
    assert "01_clean_classic" not in output


def test_unknown_custom_id_exits_before_any_request(invoices_dir, client):
    with pytest.raises(SystemExit) as exit_info:
        dry_run.main(["99_missing"])
    assert "99_missing" in str(exit_info.value)
    assert "generate-invoices" in str(exit_info.value)
    assert client.messages.created_for == []
