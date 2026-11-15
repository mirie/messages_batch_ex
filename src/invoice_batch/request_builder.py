"""Builds the Messages API request for one PDF.

The same request is used synchronously (dry run) and inside batches.
"""

import base64
from pathlib import Path

from invoice_batch.config import MODEL
from invoice_batch.schema import EXTRACT_INVOICE_TOOL, TOOL_NAME

# Per the Tool use docs, these models return a 400 for forced tool_choice
# ({"type": "tool"} or {"type": "any"}), including inside batches.
NO_FORCED_TOOL_MODELS = {
    "claude-opus-5-5", "claude-sonnet-5-5",
    "claude-fable-5-1", "claude-fable-5-2", "claude-mythos-5-1", "claude-mythos-5-2",
}

MAX_TOKENS = 16000  # generous: thinking (on the auto path) also counts toward it

SYSTEM_PROMPT = """\
You are an accounts-payable data extraction assistant. You receive exactly one
document per request, usually a PDF scan of a supplier invoice, and you record
its contents by calling the extract_invoice tool exactly once.

How to fill in the tool:
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

USER_INSTRUCTION = "Extract this document by calling the extract_invoice tool."


def tool_choice_for(model: str) -> dict:
    """Forced tool choice where the model allows it, otherwise auto."""
    if model in NO_FORCED_TOOL_MODELS:
        return {"type": "auto"}
    return {"type": "tool", "name": TOOL_NAME}


def pdf_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def build_params(pdf_path: Path, model: str = MODEL, hint: str | None = None) -> dict:
    """The complete Messages API request for one document.

    Order matters for caching: tools -> system -> messages. The tool definition
    and system prompt are identical for every request, and the cache_control
    breakpoint on the system prompt caches that whole shared prefix.
    """
    text = USER_INSTRUCTION
    if hint:
        text += f"\n\nA previous attempt at this document failed a check: {hint}"
    if model in NO_FORCED_TOOL_MODELS:
        text += "\nRespond only with the extract_invoice tool call."
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "tools": [EXTRACT_INVOICE_TOOL],
        "tool_choice": tool_choice_for(model),
        "messages": [{"role": "user", "content": [pdf_block(pdf_path), {"type": "text", "text": text}]}],
    }
