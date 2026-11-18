# Invoice Extraction with the Claude Message Batches API

A small Python learning project that extracts fields from fake PDF invoices with Claude, first one request at a time and then through the Message Batches API.

This is a self-directed experiment. It uses 26 generated invoices, some clean and some deliberately broken, to show what the Batches API does with tool calls, timing, cost, retries, and failures.

Status: stages 1–8 are built (test data, JSON schema, synchronous dry run, batch submit, status, results, triage, one retry round). Batch stages are added one at a time.

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
| 3 | `uv run dry-run [custom_id ...]` | Yes, 4 synchronous requests by default, or only the documents named (well under $0.01 on Haiku, about $0.02 per document on Sonnet) |
| 4 | `uv run submit-batch` | Only with `--yes`. Without it, prints the plan and a cost estimate |
| 5 | `uv run check-batch [--watch]` | Yes, but free (status only). Updates `batch.json` |
| 6 | `uv run collect-results` | Yes, but free (downloads results). Writes `results.jsonl` |
| 7 | `uv run triage` | No. Writes `triage.json` and prints predicted vs. actual |
| 8 | `uv run retry-batch` | Only with `--yes`. Submits the retryable documents as the next round, in a new run folder |

`check-batch`, `collect-results`, `triage` and `retry-batch` use the newest run by default. You can also pass a run folder (`runs/20261116-011243` or just `20261116-011243`) or a batch id.

## Test

```bash
uv run pytest
uv run ruff format .     # format
uv run ruff check .      # lint
```

The tests never call the API. They cover the invoice JSON schema (generated from the Pydantic model, checked against the structured-output rules), the request builder, batch building and submitting (with a fake client), pricing, the API key check, and the generated test set (counts, totals, reproducibility). New behavior is added test-first: write a failing test, then the code that makes it pass.

## How it works

### The stages

```mermaid
flowchart TB
    subgraph prepare["Prepare the test set"]
        G["1 · generate-invoices<br/>26 PDFs + ground_truth.json"]
        S["2 · show-schema<br/>print the invoice JSON schema"]
        D["3 · dry-run<br/>a few documents, one request at a time"]
    end
    subgraph round["One round = one run folder in runs/"]
        SUB["4 · submit-batch<br/>one batch, one request per document"]
        CHK["5 · check-batch<br/>poll until the batch has ended"]
        COL["6 · collect-results<br/>download and match by custom_id"]
        TRI["7 · triage<br/>our checks give every document a class"]
    end
    RET["8 · retry-batch<br/>only the RETRY_* documents, with hints"]
    DONE(["VALID: saved"])
    REVIEW(["NO_RETRY, STABLE_ANSWER, MAX_ATTEMPTS:<br/>human review"])

    G --> D
    G --> SUB
    SUB -- batch.json --> CHK
    CHK --> COL
    COL -- results.jsonl --> TRI
    TRI -- triage.json --> RET
    RET -- "new run folder, linked by parent_run" --> CHK
    TRI --> DONE
    TRI --> REVIEW
```

| # | Stage | What happens | Writes |
| --- | --- | --- | --- |
| 1 | `generate-invoices` | Builds the 26 test PDFs from a fixed random seed, and records the true values and the expected outcome of each one. | `data/invoices/*.pdf`, `data/ground_truth.json` |
| 2 | `show-schema` | Prints the JSON schema that every request sends, so you can see exactly what Claude is asked to return. | nothing |
| 3 | `dry-run` | Sends a few documents through the normal Messages API, one at a time, and prints each reply immediately. Use it to try a document before batching it. | nothing |
| 4 | `submit-batch` | Builds one request per PDF and sends them all as **one** batch. Without `--yes` it only prints the plan and the cost estimate. | `runs/<time>/batch.json` |
| 5 | `check-batch` | Asks the API how the batch is doing. `--watch` keeps asking until it has ended (usually minutes, at most 24 hours). | updates `batch.json` |
| 6 | `collect-results` | Downloads the results, which arrive in any order, and matches each one to its document by `custom_id`. Prints tokens, cost and the real wait time. | `results.jsonl` |
| 7 | `triage` | Runs our own checks on each reply (required fields, real dates, line items present, sum equals total) and gives every document exactly one class. Then prints a table comparing the result with ground truth and with your predictions. | `triage.json` |
| 8 | `retry-batch` | Sends only the documents in a `RETRY_*` class as a new batch, each with a hint built from its failed checks. Then stages 5–7 run again on the new run folder. | a new `runs/<time>/` |

The checks in stage 7 are Python code in `triage.py`. They never trust the model to check itself, and they never look at ground truth.

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
| `24_degraded_scan` | Image-only, blurry, tilted scan. Line items use the easily confused digits 3/8, 1/7, 5/6, and the total is large and clear. In dry-runs both Haiku and Sonnet misread 38.83 | `MAX_ATTEMPTS` |
| `25_handwritten_correction` | Image-only scan. A quantity is crossed out and rewritten by hand, and the total uses the new value. A control: Haiku reads it correctly | `VALID` |
| `26_fax_scan` | Image-only black-and-white fax scan with a stain over a price; the price can be worked out from the total | `RETRY_ESCALATE` |

`ground_truth.json` stores the true field values and the expected outcome for each document, so predictions can be compared with what actually happens.

Claude receives each PDF page as an image **and** as its extracted text. Small grey print is therefore still easy to read through the text layer. That is why `17_cluttered` puts its decoy digits into the text layer as well, not just into the picture.

Documents 24–26 have **no text layer at all**: each page is a single picture (drawn with Pillow, then shrunk, tilted, blurred and speckled like a cheap scan). Claude has only the image to read. Each source invoice adds up, so a misread line item breaks the sum check, which triage can see. Their expected outcomes are design goals, adjusted after dry-runs. Try one at a time with `uv run dry-run 24_degraded_scan`, and tune them in `SCAN_SETTINGS` in `synthetic/build.py`. Each scan has its own random seed, so tuning one never changes another.

```text
draw page sharply  -->  make it look scanned               -->  PDF with one image
(Pillow, 200 dpi)       (shrink, tilt, blur, grain, fax)        (no text for Claude)
```

### Program flow

```mermaid
%%{init: {"sequence": {"mirrorActors": false}}}%%
sequenceDiagram
    participant Code as Data extraction code
    participant API as Messages API
    Code->>API: PDF + output_config.format (invoice JSON schema)
    API-->>Code: stop_reason "end_turn", content = [text '{"vendor": ...}']
    Note over Code,API: json-parse the text block with parse_extraction() and you're done.
```

`INVOICE_SCHEMA` (`schema.py`, generated from the `InvoiceExtraction` Pydantic model) describes the reply: nullable fields, `is_invoice`, and an `issues` list. Sending it as `output_config.format` makes the API guarantee that Claude's reply is JSON matching the schema (keys, types, no extras). Nullable fields (`str | None`, sent as `anyOf: [string, null]`) let Claude report "not printed" instead of inventing a value. Every model gets the same request, so the Haiku attempts and the Sonnet escalation look identical.

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

### How a document gets its class, round by round

A document gets at most 3 attempts: the first batch and up to two retries. Each attempt is one round, and after each round `triage` gives the document a class. The class decides whether it is finished or goes into the next round, and how.

```mermaid
flowchart LR
    R1["Round 1<br/>attempt 1<br/>MODEL, no hint"] --> T1{triage}
    T1 -- passes the checks --> V1(["VALID"])
    T1 -- "bad request, not an invoice,<br/>or empty" --> N1(["NO_RETRY"])
    T1 -- fails a check --> H["RETRY_WITH_HINT"]
    T1 -- "server error or expired" --> S1["RETRY_SAME"]

    H --> R2["Round 2<br/>attempt 2<br/>MODEL + hint"]
    S1 -- "same request again" --> R2
    R2 --> T2{triage}
    T2 -- passes the checks --> V2(["VALID"])
    T2 -- "fails with the same<br/>values as round 1" --> SA2(["STABLE_ANSWER"])
    T2 -- "fails with<br/>different values" --> E["RETRY_ESCALATE"]

    E --> R3["Round 3<br/>attempt 3<br/>ESCALATION_MODEL + hint"]
    R3 --> T3{triage}
    T3 -- passes the checks --> V3(["VALID"])
    T3 -- "fails with the same<br/>values as round 2" --> SA3(["STABLE_ANSWER"])
    T3 -- "fails, or errors again" --> M(["MAX_ATTEMPTS"])

    classDef done fill:#d8f3dc,stroke:#2d6a4f,color:#1b4332
    classDef retry fill:#fff3bf,stroke:#b08900,color:#5c4400
    classDef review fill:#ffe3e3,stroke:#c92a2a,color:#7d1a1a
    class V1,V2,V3 done
    class H,S1,E retry
    class N1,SA2,SA3,M review
```

Green means finished, yellow means another round, and red means sent to a person for review.

- **What changes between rounds:** round 2 adds a hint that names the failed checks, for example "line items sum to 543.66 but the total is 568.26". Round 3 keeps the hint and switches to the bigger model.
- **Why "same values" stops early:** if a retry returns exactly what the previous attempt returned, another try is unlikely to help. `20_total_mismatch` ends this way, because the invoice itself is wrong.
- **Rarer paths left out of the diagram:** a `RETRY_SAME` in round 2 sends the same request again in round 3. A document can also become `NO_RETRY` in any round. An error in round 3 ends as `MAX_ATTEMPTS`.

Some designed paths, from `ground_truth.json` (these are design goals, not results):

```text
25_handwritten_correction   round 1 VALID
20_total_mismatch           round 1 RETRY_WITH_HINT -> round 2 STABLE_ANSWER
26_fax_scan                 round 1 RETRY_WITH_HINT -> round 2 RETRY_ESCALATE -> round 3 VALID
24_degraded_scan            round 1 RETRY_WITH_HINT -> round 2 RETRY_ESCALATE -> round 3 MAX_ATTEMPTS
```

### Retry rounds

`retry-batch` reads the newest `triage.json` and submits only the documents in a `RETRY_*` class, as a new batch in a new run folder. The new `batch.json` records `round` and `parent_run`, so `triage` in that folder can follow the link back and see the earlier attempts.

```
runs/20261116-040415/   round 1   23 docs   triage: 20_total_mismatch RETRY_WITH_HINT
        ▲ parent_run
runs/<new stamp>/       round 2    1 doc    triage (with round-1 history): same values -> STABLE_ANSWER
```

| Class | Next round's model | Hint |
| --- | --- | --- |
| `RETRY_WITH_HINT` | `MODEL` | the failed checks from `triage.json` |
| `RETRY_SAME` | same as last time | same as last time (the request is unchanged) |
| `RETRY_ESCALATE` | `ESCALATION_MODEL` | the failed checks from `triage.json` |

A run that already has a retry round can't be retried again, so the same round isn't paid for twice.

## Code organization

The code is a package in `src/invoice_batch/`. Library modules hold the logic and are covered by tests; `cli/` holds thin commands that call them and print results.

```
src/invoice_batch/
├── config.py            paths, MODEL / ESCALATION_MODEL, API key check, client
├── schema.py            InvoiceExtraction (single source), INVOICE_SCHEMA, OUTPUT_FORMAT, parse_extraction()
├── request_builder.py   system prompt, build_params()
├── batch.py             build_requests(), check_limits(), submit(), estimate_batch_cost()
├── pricing.py           PRICES, cost_usd() (standard vs. batch)
├── runs.py              run folders: resolve_batch(), batch.json, atomic file writes
├── status.py            describe(), watch(), update_batch_record()
├── results.py           record_from_result(), collect(), results.jsonl
├── triage.py            the failure policy: check_extraction(), triage_one(), triage_run()
├── retry.py             plan_retries(), load_histories() (follows parent_run links)
├── compare.py           learning only: truth_diffs(), expected/prediction verdicts
├── synthetic/           the fake test set
│   ├── data.py          vendors, customers, make_invoice(), truth_of()
│   ├── layouts.py       classic, modern, compact, cluttered, letter pages
│   ├── scan.py          image-only scanned pages: ScanPage, make_scanned(), save_image_pdf()
│   └── build.py         generate(): all 26 documents + ground_truth.json
└── cli/                 one module per command
    ├── generate_invoices.py
    ├── show_schema.py
    ├── dry_run.py
    ├── submit_batch.py
    ├── check_batch.py
    ├── collect_results.py
    ├── triage.py
    └── retry_batch.py
tests/                   pytest, one file per library module
```

- `schema.py`: the `InvoiceExtraction` Pydantic model is the only definition of the fields; the SDK's `transform_schema()` generates `INVOICE_SCHEMA` from it. `OUTPUT_FORMAT` is sent to the API; `parse_extraction()` reads the reply's text block into an `InvoiceExtraction`.
- `request_builder.py`: `build_params()` returns the full request for one PDF. The dry run and the batch stages use the same function.
- `synthetic/build.py`: `generate(out_dir, seed=42)` writes the PDFs and ground truth. It takes the output folder as an argument, so tests can write to a temporary folder.
- `cli/dry_run.py`: sends 4 documents synchronously and prints the raw JSON text block, the parsed result, `stop_reason`, usage, and any error.
- `batch.py` / `cli/submit_batch.py`: builds one request per PDF, checks the batch limits, prints a cost estimate, and only submits with `--yes`. Saves `runs/<timestamp>/batch.json`.

## Project files

| File | Purpose |
| --- | --- |
| `architecture.md` | How the code is organized: layers, modules, files and design rules |
| `src/invoice_batch/` | The package (see above) |
| `tests/` | pytest suite; runs offline |
| `pyproject.toml` | Dependencies, the stage commands, pytest settings |
| `.env.example` | Environment configuration template |
| `data/` | Generated test set (git-ignored) |
| `runs/` | Batch run outputs, added in later stages (git-ignored) |

After editing dependencies in `pyproject.toml`, run `uv sync`. You can also use `uv add package-name` or `uv remove package-name`.
