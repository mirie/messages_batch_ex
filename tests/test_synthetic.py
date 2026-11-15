"""The generated test set must match the experiment design in the README."""

import json
import re
from collections import Counter

import pytest

from invoice_batch.synthetic.build import generate
from invoice_batch.synthetic.data import items_total


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    generate(out)
    return out


@pytest.fixture(scope="module")
def docs(out_dir):
    return {d["custom_id"]: d for d in json.loads((out_dir / "ground_truth.json").read_text())["documents"]}


def test_writes_23_pdfs(out_dir):
    assert len(list((out_dir / "invoices").glob("*.pdf"))) == 23


def test_every_ground_truth_entry_points_at_an_existing_file(out_dir, docs):
    assert len(docs) == 23
    assert all((out_dir / d["file"]).exists() for d in docs.values())


def test_custom_ids_are_valid_for_the_batch_api(docs):
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", cid) for cid in docs)


def test_expected_outcome_counts_match_the_design(docs):
    assert Counter(d["expected_outcome"] for d in docs.values()) == {
        "VALID": 16, "RETRY_ESCALATE": 1, "RETRY_WITH_HINT": 2,
        "STABLE_ANSWER": 1, "NO_RETRY": 3,
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


def test_real_pdfs_start_with_the_pdf_header(out_dir):
    assert (out_dir / "invoices" / "01_clean_classic.pdf").read_bytes().startswith(b"%PDF")
