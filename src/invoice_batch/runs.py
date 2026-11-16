"""Run folders: runs/<timestamp>/ holds one batch's files.

batch.json is written by submit-batch and updated by check-batch; later stages
add their own files next to it (results.jsonl, triage.json, ...). Everything
that finds a run folder, reads batch.json, or writes a file into a run folder
goes through here.

Files are written atomically (temp file, then rename), so a crash mid-write
leaves the old file instead of a truncated one. batch.json matters most: it
is the only local record of a batch id you have already paid for.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

BATCH_RECORD = "batch.json"


def add_batch_argument(parser) -> None:
    """The optional positional argument every run-folder command takes."""
    parser.add_argument(
        "batch", nargs="?", help="run folder, its name, or a batch id (default: newest run)"
    )


def resolve_batch(arg: str | None, runs_dir: Path) -> tuple[str, Path | None]:
    """Turn the command-line argument into (batch_id, run folder or None).

    None              -> the newest runs/*/batch.json (folder names are timestamps)
    a folder path     -> that folder's batch.json (returned as an absolute path)
    a folder name     -> runs_dir/<name>, so "20261116-011243" works from anywhere
    a batch id        -> the run folder that recorded it, if there is one

    Batch ids never contain "/", so an argument with a "/" (or one naming an
    existing folder) is a path. A path without batch.json is an error, not a
    batch id: a typo should say "not found", not send the path to the API.
    """
    records = sorted(runs_dir.glob(f"*/{BATCH_RECORD}"))
    if arg is None:
        if not records:
            raise SystemExit(f"No runs found in {runs_dir}. Submit one first: uv run submit-batch")
        return load_batch_record(records[-1].parent)["batch_id"], records[-1].parent

    candidates = [Path(arg).resolve(), (runs_dir / arg).resolve()]
    for folder in candidates:
        if (folder / BATCH_RECORD).is_file():
            return load_batch_record(folder)["batch_id"], folder
    if "/" in arg or any(folder.is_dir() for folder in candidates):
        raise SystemExit(
            f"No {BATCH_RECORD} in {arg}. Is the run folder name right? See {runs_dir}"
        )

    for record in records:
        if _batch_id_or_none(record) == arg:
            return arg, record.parent
    return arg, None


def load_batch_record(run_dir: Path) -> dict:
    """Read the run folder's batch.json and return it as a dict.

    If the file is missing or isn't valid JSON, stop with an error that says which file.
    """
    path = run_dir / BATCH_RECORD
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"Can't read {path}: {e}") from e


def _batch_id_or_none(record: Path) -> str | None:
    """While searching for an id, one broken batch.json must not hide the rest."""
    try:
        return json.loads(record.read_text()).get("batch_id")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def write_text_atomic(path: Path, text: str) -> None:
    """Write to a temp file in the same folder, then rename it over path."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, data) -> None:
    write_text_atomic(path, json.dumps(data, indent=2) + "\n")


def iso(value) -> str | None:
    """A datetime as ISO 8601 text for a JSON file; None (or a string) unchanged."""
    return value.isoformat() if isinstance(value, datetime) else value


def display_path(path: Path, base: Path) -> str:
    """path relative to base when it is inside it, else the full path."""
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)
