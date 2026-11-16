"""Stage 4: building, sizing, submitting and recording a batch (no API calls)."""

import json
from datetime import UTC, datetime

import pytest
from fakes import FAKE_PDF, HAIKU, fake_client

from invoice_batch.batch import (
    build_requests,
    check_limits,
    estimate_batch_cost,
    estimate_worst_rounds,
    submit,
    write_batch_record,
)
from invoice_batch.pricing import cost_usd
from invoice_batch.request_builder import build_params

SONNET = "claude-sonnet-5-5"


@pytest.fixture
def pdf_dir(tmp_path):
    for name in ["01_a", "02_b", "03_c"]:
        (tmp_path / f"{name}.pdf").write_bytes(FAKE_PDF)
    return tmp_path


# --- build_requests -------------------------------------------------------


def test_one_request_per_document_keyed_by_custom_id(pdf_dir):
    reqs = build_requests(["01_a", "02_b", "03_c"], pdf_dir=pdf_dir)
    assert [r["custom_id"] for r in reqs] == ["01_a", "02_b", "03_c"]


def test_params_are_exactly_what_build_params_makes(pdf_dir):
    (req,) = build_requests(["01_a"], model=HAIKU, pdf_dir=pdf_dir)
    assert req["params"] == build_params(pdf_dir / "01_a.pdf", HAIKU)


def test_hints_go_only_to_their_own_document(pdf_dir):
    reqs = build_requests(["01_a", "02_b"], pdf_dir=pdf_dir, hints={"02_b": "total mismatch"})
    texts = {r["custom_id"]: r["params"]["messages"][0]["content"][1]["text"] for r in reqs}
    assert "total mismatch" in texts["02_b"]
    assert "total mismatch" not in texts["01_a"]


def test_every_request_shares_the_same_cached_prefix(pdf_dir):
    reqs = build_requests(["01_a", "02_b", "03_c"], pdf_dir=pdf_dir)
    prefixes = {json.dumps([r["params"]["system"], r["params"]["output_config"]]) for r in reqs}
    assert len(prefixes) == 1  # identical bytes, so the cache can be shared


@pytest.mark.parametrize("bad_id", ["has space", "a.pdf", "x" * 65, ""])
def test_invalid_custom_ids_are_rejected_before_submitting(pdf_dir, bad_id):
    with pytest.raises(ValueError, match="custom_id"):
        build_requests([bad_id], pdf_dir=pdf_dir)


def test_duplicate_custom_ids_are_rejected(pdf_dir):
    with pytest.raises(ValueError, match="duplicate"):
        build_requests(["01_a", "01_a"], pdf_dir=pdf_dir)


def test_missing_pdf_fails_loudly(pdf_dir):
    with pytest.raises(FileNotFoundError):
        build_requests(["99_missing"], pdf_dir=pdf_dir)


# --- limits ---------------------------------------------------------------


def test_small_batch_is_within_limits(pdf_dir):
    check_limits(build_requests(["01_a", "02_b"], pdf_dir=pdf_dir))  # no exception


def test_empty_batch_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        check_limits([])


def test_oversized_batch_is_rejected(monkeypatch, pdf_dir):
    monkeypatch.setattr("invoice_batch.batch.MAX_BATCH_BYTES", 100)
    with pytest.raises(ValueError, match="256 MB"):
        check_limits(build_requests(["01_a"], pdf_dir=pdf_dir))


# --- submit + record ------------------------------------------------------


def test_submit_sends_the_requests_unchanged(pdf_dir):
    client = fake_client()
    reqs = build_requests(["01_a", "02_b"], pdf_dir=pdf_dir)
    batch = submit(client, reqs)
    assert client.messages.batches.sent == reqs
    assert batch.id == "msgbatch_fake123"


def test_batch_record_has_what_later_stages_need(tmp_path, pdf_dir):
    reqs = build_requests(["01_a", "02_b"], model=HAIKU, pdf_dir=pdf_dir)
    batch = submit(fake_client(), reqs)
    submitted_at = datetime(2026, 11, 15, 10, 0, 1, tzinfo=UTC)

    path = write_batch_record(tmp_path / "run1", batch, reqs, submitted_at)

    assert path == tmp_path / "run1" / "batch.json"
    record = json.loads(path.read_text())
    assert record["batch_id"] == "msgbatch_fake123"
    assert record["submitted_at"] == "2026-11-15T10:00:01+00:00"
    assert record["created_at"] == "2026-11-15T10:00:00+00:00"
    assert record["expires_at"] == "2026-11-16T10:00:00+00:00"
    assert record["processing_status"] == "in_progress"
    assert record["custom_ids"] == ["01_a", "02_b"]
    assert record["models"] == {"01_a": HAIKU, "02_b": HAIKU}


def test_batch_record_never_contains_the_pdf_bytes(tmp_path, pdf_dir):
    reqs = build_requests(["01_a"], pdf_dir=pdf_dir)
    path = write_batch_record(tmp_path, submit(fake_client(), reqs), reqs, datetime.now(UTC))
    assert reqs[0]["params"]["messages"][0]["content"][0]["source"]["data"] not in path.read_text()


# --- cost estimate --------------------------------------------------------


def test_estimate_typical_is_one_cache_write_then_reads():
    est = estimate_batch_cost(3, HAIKU, input_tokens=2000, output_tokens=500, prefix_tokens=1600)
    base = {"input_tokens": 2000, "output_tokens": 500}
    expected = cost_usd({**base, "cache_creation_input_tokens": 1600}, HAIKU) + 2 * cost_usd(
        {**base, "cache_read_input_tokens": 1600}, HAIKU
    )
    assert est["typical"] == pytest.approx(expected)


def test_estimate_worst_case_is_every_request_missing_the_cache():
    est = estimate_batch_cost(3, HAIKU, input_tokens=2000, output_tokens=500, prefix_tokens=1600)
    one = cost_usd(
        {"input_tokens": 2000, "output_tokens": 500, "cache_creation_input_tokens": 1600}, HAIKU
    )
    assert est["worst"] == pytest.approx(3 * one)


def test_estimate_uses_batch_prices():
    est = estimate_batch_cost(1, SONNET, input_tokens=1_000_000, output_tokens=0, prefix_tokens=0)
    assert est["worst"] == pytest.approx(1.00)  # $2/M standard, halved


def test_worst_rounds_is_every_doc_failing_every_round_with_the_last_on_escalation():
    haiku = estimate_batch_cost(23, "claude-haiku-5-5")["worst"]
    sonnet = estimate_batch_cost(23, "claude-sonnet-5-5")["worst"]
    worst = estimate_worst_rounds(23, "claude-haiku-5-5", "claude-sonnet-5-5", rounds=3)
    assert worst == pytest.approx(haiku + haiku + sonnet)
