# Invoice Extraction with the Claude Message Batches API

A small Python learning project that extracts fields from fake PDF invoices with Claude, first one request at a time and then through the Message Batches API.

This is a self-directed experiment. It uses 23 generated invoices, some clean and some deliberately broken, to show what the Batches API does with tool calls, timing, cost, retries, and failures.

Status: stages 1–4 are built (test data, JSON schema, synchronous dry run, batch submit). Batch stages are added one at a time.

## Setup

You need uv, Python 3.12 or newer, and an Anthropic API key.

From the project directory, install the dependencies:

```bash
uv sync
```

Create your local environment file:

```bash
cp .env.example .env
```

Edit `.env` and replace the placeholder with your key:

```dotenv
ANTHROPIC_API_KEY=your-anthropic-api-key-here
```

Scripts that call the API exit with a message if the key is missing, and never print it.

Models are constants in `src/invoice_batch/config.py` and can be overridden in `.env`:

| Variable | Default | Used for |
| --- | --- | --- |
| `MODEL` | `claude-haiku-5-5` | attempts 1 and 2 |
| `ESCALATION_MODEL` | `claude-sonnet-5-5` | the last attempt for documents that keep failing |

## Run

Each stage is a command registered in `pyproject.toml` under `[project.scripts]`:

| Stage | Command | Calls the API? |
| --- | --- | --- |
| 1 | `uv run generate-invoices` | No. Writes `data/invoices/*.pdf` and `data/ground_truth.json` |
| 2 | `uv run show-schema` | No. Prints the invoice JSON schema |
| 3 | `uv run dry-run` | Yes, 4 synchronous requests (well under $0.01) |
| 4 | `uv run submit-batch` | Only with `--yes`. Without it, prints the plan and a cost estimate |

## Test

```bash
uv run pytest
uv run ruff format .     # format
uv run ruff check .      # lint
```

The tests never call the API. They cover the invoice JSON schema (structured-output rules, and a field-by-field match with the Pydantic model), the request builder, batch building and submitting (with a fake client), pricing, the API key check, and the generated test set (counts, totals, reproducibility). New behavior is added test-first: write a failing test, then the code that makes it pass.

## How it works

### The test documents

`generate-invoices` uses a fixed random seed and reportlab's invariant mode, so it produces byte-identical files every time. `data/` is git-ignored; re-run the command to recreate it.

| custom_id | Group | Expected outcome |
| --- | --- | --- |
| `01`–`16` `_clean_<layout>` | Clean invoices in 3 layouts (classic, modern, compact). `06` has no due date, so null is correct | `VALID` |
| `17_cluttered` | Small digits on a background of decoy digits | `RETRY_ESCALATE` |
| `18_footer_due_date` | Due date only in a 5pt grey footer | `RETRY_WITH_HINT` |
| `19_unusual_format` | Dates like `11.II.2026`, money like `Fr. 1'209.67` | `RETRY_WITH_HINT` |
| `20_total_mismatch` | Printed total is 100.00 more than the line items | `STABLE_ANSWER` |
| `21_corrupt` | Random bytes named `.pdf` | `NO_RETRY` |
| `22_letter` | A change-of-address letter | `NO_RETRY` |
| `23_blank` | A blank page | `NO_RETRY` |

`ground_truth.json` stores the true field values and the expected outcome for each document, so predictions can be compared with what actually happens.

Claude receives each PDF page as an image **and** as its extracted text. Small grey print is therefore still easy to read through the text layer. That is why `17_cluttered` puts its decoy digits into the text layer as well, not just into the picture.

### Program flow

```mermaid
sequenceDiagram
    participant Code as Data extraction code
    participant API as Messages API
    Code->>API: PDF + output_config.format (invoice JSON schema)
    API-->>Code: stop_reason "end_turn", content = [text '{"vendor": ...}']
    Note over Code: json-parse the text block with parse_extraction() and you're done.
```

`INVOICE_SCHEMA` (`schema.py`) describes the reply: nullable fields, `is_invoice`, and an `issues` list. Sending it as `output_config.format` makes the API guarantee that Claude's reply is JSON matching the schema (keys, types, no extras). Nullable fields (`["string", "null"]`) let Claude report "not printed" instead of inventing a value. Every model gets the same request, so the Haiku attempts and the Sonnet escalation look identical.

### Structured outputs: JSON outputs vs. strict tools

The API has two structured-output features. This project uses the first; stage 10 uses the second.

| Feature | Set on | Guarantees | Use when |
| --- | --- | --- | --- |
| JSON outputs | `output_config.format` | Claude's **reply** is JSON matching the schema | You just want the answer as data (this project's extraction) |
| Strict tool use | `strict: true` on a tool | A **tool call's arguments** match the tool's schema | Claude calls a tool that your code runs (stage 10's `lookup_crm`) |

Neither forces the other: JSON outputs never produce a tool call, and `strict` doesn't make Claude call a tool, it only guarantees the arguments when it does.

### One request

```
system  (cache_control, 1h)       identical for every document, so it can be cached
thinking  adaptive, summarized   the model decides whether to think; we can read a summary
output_config.format              the invoice JSON schema (same for every document)
messages[0] user:
    document  (base64 PDF)
    text      "Extract the data from this document."
              (+ a hint on retries)
```

## Code organization

The code is a package in `src/invoice_batch/`. Library modules hold the logic and are covered by tests; `cli/` holds thin commands that call them and print results.

```
src/invoice_batch/
├── config.py            paths, MODEL / ESCALATION_MODEL, API key check, client
├── schema.py            INVOICE_SCHEMA, OUTPUT_FORMAT, InvoiceExtraction, parse_extraction()
├── request_builder.py   system prompt, build_params()
├── batch.py             build_requests(), check_limits(), submit(), estimate_batch_cost()
├── pricing.py           PRICES, cost_usd() (standard vs. batch)
├── synthetic/           the fake test set
│   ├── data.py          vendors, customers, make_invoice(), truth_of()
│   ├── layouts.py       classic, modern, compact, cluttered, letter pages
│   └── build.py         generate(): all 23 documents + ground_truth.json
└── cli/                 one module per command
    ├── generate_invoices.py
    ├── show_schema.py
    ├── dry_run.py
    └── submit_batch.py
tests/                   pytest, one file per library module
```

- `schema.py`: `OUTPUT_FORMAT` is sent to the API; `parse_extraction()` reads the reply's text block into an `InvoiceExtraction`.
- `request_builder.py`: `build_params()` returns the full request for one PDF. The dry run and the batch stages use the same function.
- `synthetic/build.py`: `generate(out_dir, seed=42)` writes the PDFs and ground truth. It takes the output folder as an argument, so tests can write to a temporary folder.
- `cli/dry_run.py`: sends 4 documents synchronously and prints the raw JSON text block, the parsed result, `stop_reason`, usage, and any error.
- `batch.py` / `cli/submit_batch.py`: builds one request per PDF, checks the batch limits, prints a cost estimate, and only submits with `--yes`. Saves `runs/<timestamp>/batch.json`.

## Project files

| File | Purpose |
| --- | --- |
| `src/invoice_batch/` | The package (see above) |
| `tests/` | pytest suite; runs offline |
| `pyproject.toml` | Dependencies, the stage commands, pytest settings |
| `.env.example` | Environment configuration template |
| `data/` | Generated test set (git-ignored) |
| `runs/` | Batch run outputs, added in later stages (git-ignored) |

After editing dependencies in `pyproject.toml`, run `uv sync`. You can also use `uv add package-name` or `uv remove package-name`.
