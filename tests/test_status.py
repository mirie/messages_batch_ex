"""Stage 5: finding the batch to check, describing its status, and polling it."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock, batch_status, fake_status_client

from invoice_batch.status import (
    describe,
    elapsed_text,
    resolve_batch,
    watch,
)

CREATED = datetime(2026, 11, 16, 1, 12, 44, tzinfo=UTC)


def _write_run(runs_dir, name, batch_id):
    run = runs_dir / name
    run.mkdir(parents=True)
    (run / "batch.json").write_text(json.dumps({"batch_id": batch_id}))
    return run


# --- resolve_batch: which batch are we checking? -------------------------------


def test_default_is_the_newest_run_folder(tmp_path):
    _write_run(tmp_path, "20261115-090000", "msgbatch_old")
    newest = _write_run(tmp_path, "20261116-011243", "msgbatch_new")
    assert resolve_batch(None, tmp_path) == ("msgbatch_new", newest)


def test_a_run_folder_argument_uses_that_folder(tmp_path):
    old = _write_run(tmp_path, "20261115-090000", "msgbatch_old")
    _write_run(tmp_path, "20261116-011243", "msgbatch_new")
    assert resolve_batch(str(old), tmp_path) == ("msgbatch_old", old)


def test_a_batch_id_argument_finds_its_run_folder(tmp_path):
    old = _write_run(tmp_path, "20261115-090000", "msgbatch_old")
    _write_run(tmp_path, "20261116-011243", "msgbatch_new")
    assert resolve_batch("msgbatch_old", tmp_path) == ("msgbatch_old", old)


def test_an_unknown_batch_id_is_still_checked_without_a_folder(tmp_path):
    assert resolve_batch("msgbatch_elsewhere", tmp_path) == ("msgbatch_elsewhere", None)


def test_no_runs_at_all_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match="submit-batch"):
        resolve_batch(None, tmp_path)


# --- elapsed_text --------------------------------------------------------------


def test_elapsed_text_is_hours_minutes_seconds():
    assert elapsed_text(timedelta(hours=1, minutes=2, seconds=3)) == "1h 02m 03s"
    assert elapsed_text(timedelta(minutes=4, seconds=5)) == "4m 05s"


# --- describe: one batch status as readable lines -------------------------------


def test_describe_in_progress_shows_status_counts_now_and_elapsed():
    batch = batch_status("in_progress", processing=23, created_at=CREATED)
    text = describe(batch, now=CREATED + timedelta(minutes=12, seconds=30))
    assert "in_progress" in text
    assert "processing 23" in text
    assert "succeeded 0" in text
    assert "expired 0" in text
    assert "2026-11-16 01:25:14 UTC" in text  # the time now
    assert "12m 30s" in text  # elapsed since created_at


def test_describe_ended_shows_ended_at_the_total_wait_and_the_results_url():
    ended = CREATED + timedelta(minutes=7, seconds=5)
    batch = batch_status(
        "ended",
        succeeded=22,
        errored=1,
        created_at=CREATED,
        ended_at=ended,
        results_url="https://api.example/results",
    )
    text = describe(batch, now=ended + timedelta(hours=2))
    assert "succeeded 22" in text
    assert "errored 1" in text
    assert "ended_at" in text
    assert "7m 05s" in text  # created_at -> ended_at, not until now
    assert "https://api.example/results" in text


# --- watch: poll until ended, without really sleeping ---------------------------


def test_watch_polls_until_ended_and_prints_one_line_per_poll():
    statuses = [
        batch_status("in_progress", processing=23, created_at=CREATED),
        batch_status("in_progress", processing=23, created_at=CREATED),
        batch_status("ended", succeeded=22, errored=1, created_at=CREATED, ended_at=CREATED),
    ]
    client = fake_status_client(statuses)
    clock = FakeClock(CREATED)
    lines = []

    final = watch(
        client, "msgbatch_x", interval=60, now=clock.now, sleep=clock.sleep, out=lines.append
    )

    assert final.processing_status == "ended"
    assert client.messages.batches.retrieved == ["msgbatch_x"] * 3
    assert clock.slept == [60, 60]  # no sleep after the last poll
    assert len(lines) == 3
    assert lines[0].startswith("[01:12:44]")
    assert lines[1].startswith("[01:13:44]")
    assert "ended" in lines[2]
