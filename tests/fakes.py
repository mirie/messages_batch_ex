"""Test doubles shared by several test files. Nothing here calls the API."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

FAKE_PDF = b"%PDF-1.4 fake\n" * 20
CREATED = datetime(2026, 11, 16, 1, 12, 44, tzinfo=UTC)

# A valid extraction, as InvoiceExtraction.model_dump() would give it.
GOOD_EXTRACTION = {
    "is_invoice": True,
    "invoice_no": "INV-1001",
    "vendor": "Acme",
    "customer_email": "a@b.test",
    "issue_date": "2026-01-02",
    "due_date": "2026-02-01",
    "currency": "USD",
    "line_items": [{"description": "Widget", "quantity": 2, "unit_price": 5.0}],
    "total": 10.0,
    "issues": [],
}


def make_run(runs_dir, name="20261116-011243", batch_id="msgbatch_real", **record):
    """A run folder holding a batch.json with batch_id plus any extra fields."""
    run = runs_dir / name
    run.mkdir(parents=True)
    (run / "batch.json").write_text(json.dumps({"batch_id": batch_id, **record}))
    return run


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
    """client.messages.batches whose retrieve() replays a list of statuses.

    An Exception in the list is raised instead of returned.
    """

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.retrieved = []

    def retrieve(self, batch_id):
        self.retrieved.append(batch_id)
        status = self._statuses.pop(0)
        if isinstance(status, Exception):  # simulate a failed API call
            raise status
        return status


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
        self.current += timedelta(seconds=seconds)


# --- Batch results ------------------------------------------------------
# Each helper returns the dict that SDK_result.model_dump(mode="json") would give.

HAIKU = "claude-haiku-5-5"
USAGE = {
    "input_tokens": 2000,
    "output_tokens": 400,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 1612,
}


def succeeded_result(custom_id, content, stop_reason="end_turn", usage=None, model=HAIKU):
    return {
        "custom_id": custom_id,
        "result": {
            "type": "succeeded",
            "message": {
                "id": f"msg_{custom_id}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": content,
                "stop_reason": stop_reason,
                "stop_details": None,
                "usage": usage or dict(USAGE),
            },
        },
    }


def errored_result(custom_id, error_type="invalid_request_error", message="bad document"):
    return {
        "custom_id": custom_id,
        "result": {
            "type": "errored",
            "error": {
                "type": "error",
                "error": {"type": error_type, "message": message},
                "request_id": "req_x",
            },
        },
    }


def bare_result(custom_id, result_type):
    """canceled / expired results carry nothing but their type."""
    return {"custom_id": custom_id, "result": {"type": result_type}}


class FakeSdkItem:
    """Looks like an SDK result object: only model_dump() is used."""

    def __init__(self, data):
        self._data = data

    def model_dump(self, mode="python"):
        return self._data


class FakeResultsBatches:
    def __init__(self, items, status):
        self._items = items
        self._status = status
        self.results_for = []

    def results(self, batch_id):
        self.results_for.append(batch_id)
        return iter(FakeSdkItem(d) for d in self._items)

    def retrieve(self, batch_id):
        return self._status


def fake_results_client(items, status):
    return SimpleNamespace(messages=SimpleNamespace(batches=FakeResultsBatches(items, status)))
