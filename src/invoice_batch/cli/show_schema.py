"""Stage 2: print the extract_invoice tool definition.

Run:  uv run show-schema     (no API call, no key needed)
"""

import json

from invoice_batch.config import ESCALATION_MODEL, MODEL
from invoice_batch.request_builder import tool_choice_for
from invoice_batch.schema import EXTRACT_INVOICE_TOOL


def main() -> None:
    print("=== The tool definition sent with every request ===\n")
    print(json.dumps(EXTRACT_INVOICE_TOOL, indent=2))
    print("\n=== Fields at a glance ===\n")
    for name, spec in EXTRACT_INVOICE_TOOL["input_schema"]["properties"].items():
        t = spec["type"]
        t = " or ".join(t) if isinstance(t, list) else t
        print(f"  {name:<15} {t}")
    print("\n=== tool_choice per model ===\n")
    for m in (MODEL, ESCALATION_MODEL):
        print(f"  {m:<20} {json.dumps(tool_choice_for(m))}")
    print("\n  Forced ({'type': 'tool'}) means the reply can only be this tool call.")
    print("  'auto' is used where the model rejects forced tool use (400 error);")
    print("  the prompt then asks for the tool, and strict: true still guarantees the shape.")


if __name__ == "__main__":
    main()
