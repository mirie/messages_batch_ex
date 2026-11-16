"""The generated test set must match the experiment design in the README."""

import json
import re
from collections import Counter

import pytest
from pypdf import PdfReader

from invoice_batch.synthetic.build import generate
from invoice_batch.synthetic.data import items_total


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    generate(out)
    return out


@pytest.fixture(scope="module")
def docs(out_dir):
    return {
        d["custom_id"]: d
        for d in json.loads((out_dir / "ground_truth.json").read_text())["documents"]
    }


IMAGE_ONLY = ["24_degraded_scan", "25_handwritten_correction", "26_illegible_scan"]


def test_writes_26_pdfs(out_dir):
    assert len(list((out_dir / "invoices").glob("*.pdf"))) == 26


def test_every_ground_truth_entry_points_at_an_existing_file(out_dir, docs):
    assert len(docs) == 26
    assert all((out_dir / d["file"]).exists() for d in docs.values())


def test_custom_ids_are_valid_for_the_batch_api(docs):
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", cid) for cid in docs)


def test_expected_outcome_counts_match_the_design(docs):
    assert Counter(d["expected_outcome"] for d in docs.values()) == {
        "VALID": 16,
        "RETRY_ESCALATE": 2,
        "RETRY_WITH_HINT": 3,
        "STABLE_ANSWER": 1,
        "MAX_ATTEMPTS": 1,
        "NO_RETRY": 3,
    }


def test_clean_invoice_totals_equal_their_line_items(docs):
    for d in docs.values():
        if d["group"] == "clean":
            assert d["truth"]["total"] == pytest.approx(items_total(d["truth"]["line_items"]))


def test_mismatch_invoice_prints_100_more_than_its_line_items(docs):
    d = docs["20_total_mismatch"]
    assert d["truth"]["total"] == pytest.approx(items_total(d["truth"]["line_items"]) + 100)
    assert d["line_items_sum"] == pytest.approx(items_total(d["truth"]["line_items"]))


def test_only_invoice_06_has_no_due_date(docs):
    no_due = [cid for cid, d in docs.items() if d["truth"] and d["truth"]["due_date"] is None]
    assert no_due == ["06_clean_compact_no_due"]


def test_corrupt_file_is_not_a_pdf(out_dir):
    assert not (out_dir / "invoices" / "21_corrupt.pdf").read_bytes().startswith(b"%PDF")


def test_generating_twice_gives_identical_ground_truth(tmp_path):
    generate(tmp_path / "a")
    generate(tmp_path / "b")
    assert (tmp_path / "a" / "ground_truth.json").read_text() == (
        tmp_path / "b" / "ground_truth.json"
    ).read_text()


def test_generating_twice_gives_byte_identical_pdfs(tmp_path):
    generate(tmp_path / "a")
    generate(tmp_path / "b")
    for pdf in sorted((tmp_path / "a" / "invoices").glob("*.pdf")):
        assert pdf.read_bytes() == (tmp_path / "b" / "invoices" / pdf.name).read_bytes(), pdf.name


@pytest.mark.parametrize("custom_id", IMAGE_ONLY)
def test_scanned_documents_have_no_text_layer(out_dir, custom_id):
    reader = PdfReader(out_dir / "invoices" / f"{custom_id}.pdf")
    assert len(reader.pages) == 1
    assert reader.pages[0].extract_text().strip() == ""
    assert len(reader.pages[0].images) == 1


@pytest.mark.parametrize("custom_id", IMAGE_ONLY)
def test_scanned_invoice_totals_equal_their_line_items(docs, custom_id):
    """Check that the source is self-consistent, so only a misread can break the sum."""
    truth = docs[custom_id]["truth"]
    assert truth["total"] == pytest.approx(items_total(truth["line_items"]))


def test_degraded_scan_line_items_use_easily_confused_digits(docs):
    prices = [
        f"{item['unit_price']:.2f}" for item in docs["24_degraded_scan"]["truth"]["line_items"]
    ]
    confusable_pairs = [("3", "8"), ("1", "7"), ("5", "6")]
    for first, second in confusable_pairs:
        assert any(first in price or second in price for price in prices)


def test_handwritten_correction_truth_uses_the_corrected_quantity(docs):
    document = docs["25_handwritten_correction"]
    correction = document["correction"]
    corrected_item = document["truth"]["line_items"][correction["line_index"]]
    assert corrected_item["quantity"] == correction["handwritten_quantity"]
    assert correction["crossed_out_quantity"] != correction["handwritten_quantity"]


def test_handwritten_correction_breaks_the_sum_if_misread(docs):
    """Check that reading the crossed-out quantity makes the line items disagree with the total."""
    document = docs["25_handwritten_correction"]
    correction = document["correction"]
    misread_items = [dict(item) for item in document["truth"]["line_items"]]
    misread_items[correction["line_index"]]["quantity"] = correction["crossed_out_quantity"]
    assert items_total(misread_items) != pytest.approx(document["truth"]["total"])
