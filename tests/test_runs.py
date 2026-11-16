"""Run folders: finding the right one, reading batch.json, and writing files safely."""

import json

import pytest
from fakes import make_run

from invoice_batch import runs
from invoice_batch.runs import (
    display_path,
    load_batch_record,
    resolve_batch,
    write_json_atomic,
    write_text_atomic,
)

# --- resolve_batch: which batch are we talking about? ---------------------------


def test_default_is_the_newest_run_folder(tmp_path):
    make_run(tmp_path, "20261115-090000", "msgbatch_old")
    newest = make_run(tmp_path, "20261116-011243", "msgbatch_new")
    assert resolve_batch(None, tmp_path) == ("msgbatch_new", newest)


def test_a_run_folder_path_uses_that_folder(tmp_path):
    old = make_run(tmp_path, "20261115-090000", "msgbatch_old")
    make_run(tmp_path, "20261116-011243", "msgbatch_new")
    assert resolve_batch(str(old), tmp_path) == ("msgbatch_old", old)


def test_a_bare_run_folder_name_is_looked_up_in_runs_dir(tmp_path, monkeypatch):
    run = make_run(tmp_path / "runs", "20261116-011243", "msgbatch_new")
    monkeypatch.chdir(tmp_path)  # "20261116-011243" is not a folder here
    assert resolve_batch("20261116-011243", tmp_path / "runs") == ("msgbatch_new", run.resolve())


def test_a_batch_id_finds_its_run_folder(tmp_path):
    old = make_run(tmp_path, "20261115-090000", "msgbatch_old")
    make_run(tmp_path, "20261116-011243", "msgbatch_new")
    assert resolve_batch("msgbatch_old", tmp_path) == ("msgbatch_old", old)


def test_an_unknown_batch_id_is_returned_without_a_folder(tmp_path):
    assert resolve_batch("msgbatch_elsewhere", tmp_path) == ("msgbatch_elsewhere", None)


def test_a_relative_run_folder_comes_back_absolute(tmp_path, monkeypatch):
    run = make_run(tmp_path / "runs", "20261116-011243", "msgbatch_new")
    monkeypatch.chdir(tmp_path)
    batch_id, folder = resolve_batch("runs/20261116-011243", tmp_path / "runs")
    assert batch_id == "msgbatch_new"
    assert folder == run.resolve()


@pytest.mark.parametrize("arg", ["runs/2026111-011243", "runs/20261116-011243/"])
def test_a_path_without_batch_json_is_a_clear_error_not_a_batch_id(tmp_path, monkeypatch, arg):
    (tmp_path / "runs" / "20261116-011243").mkdir(parents=True)  # exists, but no batch.json
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="batch.json"):
        resolve_batch(arg, tmp_path / "runs")


def test_no_runs_at_all_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match="submit-batch"):
        resolve_batch(None, tmp_path)


def test_one_unreadable_batch_json_does_not_hide_the_others(tmp_path):
    old = make_run(tmp_path, "20261115-090000", "msgbatch_old")
    broken = tmp_path / "20261116-011243"
    broken.mkdir()
    (broken / "batch.json").write_text('{"batch_id": "msgb')  # cut off mid-write
    assert resolve_batch("msgbatch_old", tmp_path) == ("msgbatch_old", old)


def test_an_unreadable_newest_run_is_a_clear_error_naming_the_file(tmp_path):
    make_run(tmp_path, "20261115-090000", "msgbatch_old")
    broken = tmp_path / "20261116-011243"
    broken.mkdir()
    (broken / "batch.json").write_text("{")
    with pytest.raises(SystemExit, match="20261116-011243"):
        resolve_batch(None, tmp_path)


# --- load_batch_record ---------------------------------------------------------


def test_load_batch_record_returns_the_saved_fields(tmp_path):
    run = make_run(tmp_path, custom_ids=["01_a"])
    assert load_batch_record(run) == {"batch_id": "msgbatch_real", "custom_ids": ["01_a"]}


# --- atomic writes ---------------------------------------------------------------


def test_write_json_atomic_writes_indented_json_with_a_newline(tmp_path):
    path = tmp_path / "x.json"
    write_json_atomic(path, {"a": 1})
    assert path.read_text() == '{\n  "a": 1\n}\n'
    assert json.loads(path.read_text()) == {"a": 1}


def test_a_failed_write_leaves_the_old_file_and_no_temp_files(tmp_path, monkeypatch):
    path = tmp_path / "batch.json"
    path.write_text("old contents")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(runs.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        write_text_atomic(path, "new contents")
    assert path.read_text() == "old contents"
    assert [p.name for p in tmp_path.iterdir()] == ["batch.json"]


# --- display_path ----------------------------------------------------------------


def test_display_path_is_relative_to_the_project_when_it_can_be(tmp_path):
    assert display_path(tmp_path / "runs" / "x", tmp_path) == "runs/x"
    assert display_path(tmp_path / "x", tmp_path / "elsewhere") == str(tmp_path / "x")
