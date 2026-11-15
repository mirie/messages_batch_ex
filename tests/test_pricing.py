"""Cost estimates: batch is half price, and cache tokens have their own rates."""

import pytest

from invoice_batch.pricing import cost_usd

M = 1_000_000
HAIKU = "claude-haiku-5-5"


def test_batch_input_tokens_cost_half_the_standard_rate():
    assert cost_usd({"input_tokens": M}, HAIKU, batch=True) == pytest.approx(0.05)


def test_batch_output_tokens_cost_half_the_standard_rate():
    assert cost_usd({"output_tokens": M}, HAIKU, batch=True) == pytest.approx(0.25)


def test_standard_price_is_double_the_batch_price():
    usage = {"input_tokens": 3000, "output_tokens": 400}
    assert cost_usd(usage, HAIKU, batch=False) == pytest.approx(2 * cost_usd(usage, HAIKU, batch=True))


def test_cache_writes_and_reads_use_their_own_rates():
    usage = {"cache_creation_input_tokens": M, "cache_read_input_tokens": M}
    assert cost_usd(usage, HAIKU, batch=False) == pytest.approx(0.20 + 0.01)


def test_missing_or_null_cache_fields_count_as_zero():
    usage = {"input_tokens": M, "cache_creation_input_tokens": None}
    assert cost_usd(usage, HAIKU, batch=False) == pytest.approx(0.10)


def test_unknown_model_raises_instead_of_reporting_zero_cost():
    with pytest.raises(ValueError, match="claude-unknown-9"):
        cost_usd({"input_tokens": M}, "claude-unknown-9")
