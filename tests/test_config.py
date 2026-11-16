"""The API key check exits with setup instructions when the key is missing."""

import pytest

from invoice_batch.config import require_api_key


def test_missing_key_exits_with_setup_instructions(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        require_api_key()
    assert ".env" in str(exc.value)


def test_placeholder_key_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your-anthropic-api-key-here")
    with pytest.raises(SystemExit):
        require_api_key()
