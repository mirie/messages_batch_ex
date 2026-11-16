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
