"""Stage 5: describing a batch's status, polling it, and saving it to batch.json."""

import json
from datetime import timedelta

import pytest
from fakes import CREATED, FakeClock, batch_status, fake_status_client

from invoice_batch.status import (
    describe,
    elapsed_text,
    update_batch_record,
    watch,
)

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


class FlakyNetwork(Exception):
    pass


def test_watch_rides_out_a_transient_error_and_keeps_polling():
    statuses = [
        batch_status("in_progress", processing=23, created_at=CREATED),
        FlakyNetwork("connection reset"),
        batch_status("ended", succeeded=23, created_at=CREATED, ended_at=CREATED),
    ]
    clock = FakeClock(CREATED)
    lines = []
    final = watch(
        fake_status_client(statuses),
        "msgbatch_x",
        interval=60,
        now=clock.now,
        sleep=clock.sleep,
        out=lines.append,
        transient=(FlakyNetwork,),
    )
    assert final.processing_status == "ended"
    assert clock.slept == [60, 60]
    assert "connection reset" in lines[1] and "trying again" in lines[1]


def test_watch_gives_up_after_too_many_errors_in_a_row():
    statuses = [FlakyNetwork("down")] * 3
    clock = FakeClock(CREATED)
    with pytest.raises(FlakyNetwork):
        watch(
            fake_status_client(statuses),
            "msgbatch_x",
            interval=60,
            now=clock.now,
            sleep=clock.sleep,
            out=lambda _: None,
            transient=(FlakyNetwork,),
            max_errors=3,
        )
    assert clock.slept == [60, 60]  # no sleep before giving up


def test_watch_does_not_retry_errors_that_are_not_transient():
    clock = FakeClock(CREATED)
    with pytest.raises(KeyError):
        watch(
            fake_status_client([KeyError("bug")]),
            "msgbatch_x",
            now=clock.now,
            sleep=clock.sleep,
            out=lambda _: None,
            transient=(FlakyNetwork,),
        )


# --- update_batch_record: keep batch.json in step with the API --------------------


def test_update_batch_record_writes_the_latest_status_and_keeps_everything_else(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    original = {
        "batch_id": "msgbatch_x",
        "custom_ids": ["01_a"],
        "processing_status": "in_progress",
    }
    (run / "batch.json").write_text(json.dumps(original))
    ended = CREATED + timedelta(minutes=5, seconds=15)
    batch = batch_status("ended", succeeded=1, created_at=CREATED, ended_at=ended)

    update_batch_record(run, batch, checked_at=ended)

    saved = json.loads((run / "batch.json").read_text())
    assert saved["batch_id"] == "msgbatch_x"
    assert saved["custom_ids"] == ["01_a"]
    assert saved["processing_status"] == "ended"
    assert saved["request_counts"]["succeeded"] == 1
    assert saved["ended_at"] == ended.isoformat()
    assert saved["last_checked_at"] == ended.isoformat()


def test_update_batch_record_leaves_ended_at_null_while_running(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "batch.json").write_text(json.dumps({"batch_id": "msgbatch_x"}))
    update_batch_record(run, batch_status("in_progress", processing=1, created_at=CREATED), CREATED)
    saved = json.loads((run / "batch.json").read_text())
    assert saved["processing_status"] == "in_progress"
    assert saved["ended_at"] is None
