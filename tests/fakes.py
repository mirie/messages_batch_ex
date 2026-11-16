"""Test doubles shared by several test files. Nothing here calls the API."""

from datetime import UTC, datetime
from types import SimpleNamespace

FAKE_PDF = b"%PDF-1.4 fake\n" * 20


class FakeBatches:
    """Stands in for client.messages.batches; records what was sent."""

    def __init__(self):
        self.sent = None

    def create(self, requests):
        self.sent = requests
        return SimpleNamespace(
            id="msgbatch_fake123",
            processing_status="in_progress",
            created_at=datetime(2026, 11, 15, 10, 0, tzinfo=UTC),
            expires_at=datetime(2026, 11, 16, 10, 0, tzinfo=UTC),
            request_counts=SimpleNamespace(processing=len(requests)),
        )


def fake_client():
    return SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches()))


def batch_status(
    processing_status,
    *,
    processing=0,
    succeeded=0,
    errored=0,
    canceled=0,
    expired=0,
    created_at=None,
    ended_at=None,
    results_url=None,
):
    """A MessageBatch as batches.retrieve() returns it (only the fields we read)."""
    return SimpleNamespace(
        id="msgbatch_x",
        processing_status=processing_status,
        request_counts=SimpleNamespace(
            processing=processing,
            succeeded=succeeded,
            errored=errored,
            canceled=canceled,
            expired=expired,
        ),
        created_at=created_at,
        ended_at=ended_at,
        expires_at=None,
        results_url=results_url,
    )


class FakeStatusBatches:
    """client.messages.batches whose retrieve() replays a list of statuses."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.retrieved = []

    def retrieve(self, batch_id):
        self.retrieved.append(batch_id)
        return self._statuses.pop(0)


def fake_status_client(statuses):
    return SimpleNamespace(messages=SimpleNamespace(batches=FakeStatusBatches(statuses)))


class FakeClock:
    """now() and sleep() for polling tests: sleeping just moves the clock."""

    def __init__(self, start):
        self.current = start
        self.slept = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.slept.append(seconds)
        from datetime import timedelta

        self.current += timedelta(seconds=seconds)
