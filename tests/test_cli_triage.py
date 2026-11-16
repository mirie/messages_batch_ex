"""triage reads a run folder, writes triage.json and prints the comparison table."""

import json

import pytest
from fakes import GOOD_EXTRACTION, make_run

from invoice_batch.cli import triage

IDS = ["01_clean", "20_total_mismatch", "21_corrupt"]
TRUTH = {k: v for k, v in GOOD_EXTRACTION.items() if k not in ("is_invoice", "issues")}


def _record(cid, **extraction_changes):
    return {
        "custom_id": cid,
        "result_type": "succeeded",
        "parse_ok": True,
        "parse_problem": None,
        "extraction": GOOD_EXTRACTION | extraction_changes,
        "error_type": None,
        "error_message": None,
    }


RECORDS = [
    _record("01_clean", due_date=None),  # passes the policy, but truth has a due date
    _record("20_total_mismatch", total=110.0),
    {
        "custom_id": "21_corrupt",
        "result_type": "errored",
        "error_type": "invalid_request_error",
        "error_message": "The PDF specified was not valid.",
    },
]
GROUND_TRUTH = {
    "documents": [
        {"custom_id": "01_clean", "expected_outcome": "VALID", "truth": TRUTH},
        {
            "custom_id": "20_total_mismatch",
            "expected_outcome": "STABLE_ANSWER",
            "truth": TRUTH | {"total": 110.0},
        },
        {"custom_id": "21_corrupt", "expected_outcome": "NO_RETRY", "truth": None},
    ]
}


@pytest.fixture
def run(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    gt = tmp_path / "ground_truth.json"
    gt.write_text(json.dumps(GROUND_TRUTH))
    monkeypatch.setattr(triage, "RUNS_DIR", runs)
    monkeypatch.setattr(triage, "GROUND_TRUTH", gt)
    folder = make_run(runs, custom_ids=IDS)
    (folder / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in RECORDS))
    return folder


def test_it_needs_results_jsonl_first(run):
    (run / "results.jsonl").unlink()
    with pytest.raises(SystemExit, match="collect-results"):
        triage.main([])


def test_it_writes_one_class_and_reason_per_document(run):
    triage.main([])
    saved = json.loads((run / "triage.json").read_text())
    assert saved["batch_id"] == "msgbatch_real"
    assert saved["round"] == 1
    docs = {d["custom_id"]: d for d in saved["documents"]}
    assert list(docs) == IDS
    assert docs["01_clean"]["class"] == "VALID"
    assert docs["20_total_mismatch"]["class"] == "RETRY_WITH_HINT"
    assert docs["21_corrupt"]["class"] == "NO_RETRY"
    assert all(d["reason"] for d in docs.values())
    assert saved["counts"] == {"VALID": 1, "RETRY_WITH_HINT": 1, "NO_RETRY": 1}


def test_it_prints_predicted_expected_and_actual(run, capsys):
    (run / "predictions.json").write_text(
        json.dumps({"01_clean": "succeed", "20_total_mismatch": "review", "21_corrupt": "review"})
    )
    triage.main([])
    out = capsys.readouterr().out
    table = out.split("Predicted vs actual")[1]
    row_20 = next(line for line in table.splitlines() if line.startswith("20_total_mismatch"))
    assert "review" in row_20 and "STABLE_ANSWER" in row_20 and "RETRY_WITH_HINT" in row_20
    assert "not reachable yet" in row_20


def test_it_shows_wrong_values_that_passed_the_policy(run, capsys):
    triage.main([])
    out = capsys.readouterr().out
    assert "due_date: got None, truth '2026-02-01'" in out


def test_it_works_without_predictions_or_ground_truth(run, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(triage, "GROUND_TRUTH", tmp_path / "missing.json")
    triage.main([])
    out = capsys.readouterr().out
    assert "no predictions.json" in out
    assert "no ground truth" in out
    assert (run / "triage.json").exists()


def test_a_retry_round_uses_the_parent_runs_results_as_history(tmp_path, monkeypatch):
    # Round 2 returned the same wrong total as round 1, so retrying again
    # can't help: STABLE_ANSWER, attempt 2.
    runs = tmp_path / "runs"
    monkeypatch.setattr(triage, "RUNS_DIR", runs)
    monkeypatch.setattr(triage, "GROUND_TRUTH", tmp_path / "none.json")
    same = _record("20_total_mismatch", total=110.0)
    r1 = make_run(runs, "r1", batch_id="b1", custom_ids=IDS)
    (r1 / "results.jsonl").write_text(json.dumps(same) + "\n")
    r2 = make_run(
        runs, "r2", batch_id="b2", custom_ids=["20_total_mismatch"], round=2, parent_run="r1"
    )
    (r2 / "results.jsonl").write_text(json.dumps(same) + "\n")

    triage.main(["r2"])

    saved = json.loads((r2 / "triage.json").read_text())
    (doc,) = saved["documents"]
    assert (doc["class"], doc["attempt"]) == ("STABLE_ANSWER", 2)
    assert saved["round"] == 2


def test_it_suggests_retry_batch_when_something_can_be_retried(run, capsys):
    triage.main([])  # 20_total_mismatch is RETRY_WITH_HINT on round 1
    assert "Next: uv run retry-batch" in capsys.readouterr().out


def test_it_says_nothing_is_left_to_retry_when_no_retry_class_remains(
    tmp_path, monkeypatch, capsys
):
    runs = tmp_path / "runs"
    monkeypatch.setattr(triage, "RUNS_DIR", runs)
    monkeypatch.setattr(triage, "GROUND_TRUTH", tmp_path / "none.json")
    folder = make_run(runs, custom_ids=["01_clean"])
    (folder / "results.jsonl").write_text(json.dumps(_record("01_clean")) + "\n")

    triage.main([])

    out = capsys.readouterr().out
    assert "retry-batch" not in out
    assert "Nothing left to retry" in out
