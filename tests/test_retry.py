"""retry.py: which documents go into the next round, on which model, with which hint."""

import json

import pytest
from fakes import make_run

from invoice_batch.retry import child_runs, hint_for, load_histories, plan_retries

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"


def _doc(cid, cls, problems=(), attempt=1):
    return {
        "custom_id": cid,
        "class": cls,
        "reason": "r",
        "problems": list(problems),
        "attempt": attempt,
    }


TRIAGE = {
    "batch_id": "msgbatch_parent",
    "round": 1,
    "documents": [
        _doc("01_ok", "VALID"),
        _doc("17_hint", "RETRY_WITH_HINT", ["line items sum to 1 but the total is 2"]),
        _doc("18_same", "RETRY_SAME"),
        _doc("19_up", "RETRY_ESCALATE", ["issue_date is not a real date", "total is missing"]),
        _doc("21_bad", "NO_RETRY"),
        _doc("22_stable", "STABLE_ANSWER", ["x"]),
        _doc("23_max", "MAX_ATTEMPTS", ["x"]),
    ],
}
PARENT = {
    "batch_id": "msgbatch_parent",
    "models": {"17_hint": HAIKU, "18_same": SONNET, "19_up": HAIKU},
    "hints": {"18_same": "earlier hint"},
}


def _plan():
    return {p["custom_id"]: p for p in plan_retries(TRIAGE, PARENT, HAIKU, SONNET)}


def test_only_the_three_retry_classes_are_planned():
    assert list(_plan()) == ["17_hint", "18_same", "19_up"]


def test_retry_with_hint_goes_to_the_normal_model_with_a_hint_from_problems():
    p = _plan()["17_hint"]
    assert p["class"] == "RETRY_WITH_HINT"
    assert p["model"] == HAIKU
    assert p["hint"] == "line items sum to 1 but the total is 2."


def test_retry_same_repeats_the_previous_request_exactly():
    # Same model and same hint as last time: "resubmit unchanged".
    p = _plan()["18_same"]
    assert (p["model"], p["hint"]) == (SONNET, "earlier hint")


def test_retry_same_without_a_previous_hint_has_none():
    parent = {"models": {"18_same": HAIKU}}
    (p,) = [x for x in plan_retries(TRIAGE, parent, HAIKU, SONNET) if x["class"] == "RETRY_SAME"]
    assert (p["model"], p["hint"]) == (HAIKU, None)


def test_retry_escalate_goes_to_the_escalation_model_and_keeps_the_hint():
    p = _plan()["19_up"]
    assert p["model"] == SONNET
    assert p["hint"] == "issue_date is not a real date; total is missing."


def test_hint_for_joins_problems_into_one_sentence():
    assert hint_for(["a", "b"]) == "a; b."
    assert hint_for([]) is None


def test_nothing_to_retry_gives_an_empty_plan():
    triage = {"documents": [_doc("01_ok", "VALID")]}
    assert plan_retries(triage, {}, HAIKU, SONNET) == []


# --- history across run folders --------------------------------------------


def _write_results(folder, records):
    (folder / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def test_round_one_has_no_history(tmp_path):
    run = make_run(tmp_path, "r1", custom_ids=["a"])
    assert load_histories(run, tmp_path) == {}


def test_history_follows_parent_runs_oldest_first(tmp_path):
    r1 = make_run(tmp_path, "r1", custom_ids=["a", "b"])
    _write_results(r1, [{"custom_id": "a", "n": 1}, {"custom_id": "b", "n": 1}])
    r2 = make_run(tmp_path, "r2", custom_ids=["a"], round=2, parent_run="r1")
    _write_results(r2, [{"custom_id": "a", "n": 2}])
    r3 = make_run(tmp_path, "r3", custom_ids=["a"], round=3, parent_run="r2")

    histories = load_histories(r3, tmp_path)

    # Only this run's documents, and only earlier attempts (not r3's own result).
    assert histories == {"a": [{"custom_id": "a", "n": 1}, {"custom_id": "a", "n": 2}]}


def test_a_missing_parent_run_stops_with_a_clear_message(tmp_path):
    r2 = make_run(tmp_path, "r2", custom_ids=["a"], round=2, parent_run="gone")
    with pytest.raises(SystemExit, match="gone"):
        load_histories(r2, tmp_path)


def test_a_parent_without_results_stops_with_a_clear_message(tmp_path):
    make_run(tmp_path, "r1", custom_ids=["a"])
    r2 = make_run(tmp_path, "r2", custom_ids=["a"], round=2, parent_run="r1")
    with pytest.raises(SystemExit, match="results.jsonl"):
        load_histories(r2, tmp_path)


def test_child_runs_finds_retries_already_submitted_from_a_run(tmp_path):
    r1 = make_run(tmp_path, "r1")
    make_run(tmp_path, "r2", batch_id="b2", parent_run="r1")
    make_run(tmp_path, "r3", batch_id="b3")
    assert [p.name for p in child_runs(r1, tmp_path)] == ["r2"]
