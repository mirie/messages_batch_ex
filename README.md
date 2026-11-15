# Invoice Extraction with the Claude Message Batches API

A small Python learning project that extracts fields from fake PDF invoices with Claude, first one request at a time and then through the Message Batches API.

This is a self-directed experiment. It uses 23 generated invoices, some clean and some deliberately broken, to show what the Batches API does with tool calls, timing, cost, retries, and failures.

Status: stages 1–3 are built (test data, tool schema, synchronous dry run). Batch stages are added one at a time.

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

`.env` is excluded from Git. Scripts that call the API exit with a message if the key is missing, and never print it.

Models are constants in `common.py` and can be overridden in `.env`:

| Variable | Default | Used for |
| --- | --- | --- |
| `MODEL` | `claude-haiku-5-5` | attempts 1 and 2 |
| `ESCALATION_MODEL` | `claude-sonnet-5-5` | the last attempt for documents that keep failing |

## Run

| Stage | Command | Calls the API? |
| --- | --- | --- |
| 1 | `uv run generate_invoices.py` | No. Writes `data/invoices/*.pdf` and `data/ground_truth.json` |
| 2 | `uv run schema.py` | No. Prints the tool definition |
| 3 | `uv run dry_run.py` | Yes, 4 synchronous requests (well under $0.01) |

## How it works

### The test documents

`generate_invoices.py` uses a fixed random seed, so it produces the same 23 files every time. `data/` is git-ignored; re-run the script to recreate it.

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

### The tool is the answer

```mermaid
sequenceDiagram
    participant Code as Your code
    participant API as Messages API
    Code->>API: PDF + extract_invoice tool + tool_choice {"type":"tool"}
    API-->>Code: stop_reason "tool_use", content = [tool_use {input: {...fields}}]
    Note over Code: Nothing to run. Read block.input and you're done.
```

`extract_invoice` (`schema.py`) is a form with nullable fields, `is_invoice`, and an `issues` list. Forcing the tool makes Claude's whole reply a single `tool_use` block whose `input` is the extracted data. No tool result has to be sent back, so this works in a batch, where every request is exactly one turn.

`strict: true` makes the API guarantee the input matches the schema (keys, types, no extras). Nullable fields (`["string", "null"]`) let Claude report "not printed" instead of inventing a value.

### One request

```
system  (cache_control, 1h)  ─┐  identical for every document,
tools   [extract_invoice]     ─┘  so this prefix can be cached
messages[0] user:
    document  (base64 PDF)
    text      "Extract this document by calling the extract_invoice tool."
              (+ a hint on retries)
```

### Forced vs. auto tool choice

The docs (Tool use → Forcing tool use) say Claude Sonnet 5.5, Opus 5.5, and the Fable/Mythos 5.1–5.2 models return a 400 for `tool_choice` `tool` **or** `any`, inside batches too. Haiku 5.5 accepts it.

| Model | `tool_choice` used | What guarantees the result |
| --- | --- | --- |
| `claude-haiku-5-5` | `{"type":"tool","name":"extract_invoice"}` | The API forces the call; `strict` forces the shape |
| `claude-sonnet-5-5` | `{"type":"auto"}` | The prompt asks for the tool; `strict` forces the shape *if* it calls it |

`common.tool_choice_for()` picks the right one per model. If an `auto` reply has no `tool_use` block, triage counts it as a failed check.

## Code organization

- `generate_invoices.py`: the three layouts (`layout_classic`, `layout_modern`, `layout_compact`), the special cases, and the ground truth file.
- `schema.py`: `EXTRACT_INVOICE_TOOL` (sent to the API) and the matching Pydantic `InvoiceExtraction` (used to validate what comes back).
- `common.py`: model constants, the key check, `build_params()` (the full request for one PDF), the system prompt, prices, and `cost_usd()`.
- `dry_run.py`: sends 4 documents synchronously and prints the raw `tool_use` block, `stop_reason`, usage, and any error.

## Project files

| File | Purpose |
| --- | --- |
| `generate_invoices.py` | Creates the 23 test PDFs and `ground_truth.json` |
| `schema.py` | The `extract_invoice` tool definition |
| `common.py` | Shared settings, request builder, pricing |
| `dry_run.py` | Synchronous extraction of 4 documents |
| `.env.example` | Environment configuration template |

After editing dependencies in `pyproject.toml`, run `uv sync`. You can also use `uv add package-name` or `uv remove package-name`.
