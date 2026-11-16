"""Builds the Messages API request for one PDF.

The same request is used synchronously (dry run) and inside batches.
"""

import base64
from pathlib import Path

from invoice_batch.config import MODEL
from invoice_batch.schema import OUTPUT_FORMAT

MAX_TOKENS = 16000  # generous: Haiku/Sonnet 5.5 think by default, and thinking counts

SYSTEM_PROMPT = """\
You are an accounts-payable data extraction assistant. You receive exactly one
document per request, usually a PDF scan of a supplier invoice, and you reply
with its contents as JSON.

What to put in each field:
- is_invoice: true only for an invoice or bill that requests payment. Letters,
  statements, quotes, blank pages and unreadable files are not invoices; for
  those set is_invoice to false, leave every other field null or empty, and
  explain briefly in issues.
- Copy values exactly as printed. Never invent, guess, or compute a value that
  is not on the page. If a field is genuinely absent, use null. A missing due
  date is common and null is the correct answer in that case.
- Dates: convert whatever format is printed into YYYY-MM-DD. If the day and
  month order is ambiguous, prefer the convention implied by the vendor's
  country and mention the ambiguity in issues.
- currency: always the ISO 4217 three-letter code (USD, EUR, GBP, CHF, ...),
  never a symbol or local abbreviation. Infer it from symbols, abbreviations or
  the vendor's country when the code itself is not printed.
- Amounts: plain numbers with a dot as decimal separator and no thousands
  separators or currency symbols (for example 1234.5, not "1,234.50").
- line_items: one entry per billed line, in document order. quantity and
  unit_price as printed. Do not include subtotal, tax or total rows.
- total: the final amount due exactly as printed on the document, even if it
  disagrees with the line items. Do not correct the document.
- issues: short factual notes about anything you could not read clearly,
  values you are unsure of, decoy or overlapping text, or inconsistencies such
  as a total that does not equal the sum of the line items. Leave the list
  empty when everything is clear.

Small print matters: payment terms, due dates and currency are sometimes
printed only in a footer, a stamp, or the margins, so read the whole page.
"""

USER_INSTRUCTION = "Extract the data from this document."


def pdf_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": data},
    }


def build_params(pdf_path: Path, model: str = MODEL, hint: str | None = None) -> dict:
    """The complete Messages API request for one document.

    The system prompt is identical for every request, and its cache_control
    breakpoint lets every request after the first read it from the cache.
    output_config.format makes the reply JSON matching INVOICE_SCHEMA; every
    model gets exactly the same request apart from "model".
    """
    text = USER_INSTRUCTION
    if hint:
        text += f"\n\nA previous attempt at this document failed a check: {hint}"
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ],
        # Adaptive: the model decides whether a document is worth thinking about
        # (non-invoices usually get none). Summarized: return a readable summary
        # instead of an empty thinking block. Billing is the same either way.
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"format": OUTPUT_FORMAT},
        "messages": [
            {"role": "user", "content": [pdf_block(pdf_path), {"type": "text", "text": text}]}
        ],
    }
