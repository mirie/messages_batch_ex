"""Print the invoice JSON schema that every request sends.

Run:  uv run show-schema     (no API call, no key needed)
"""

import json

from invoice_batch.schema import INVOICE_SCHEMA, OUTPUT_FORMAT


def main() -> None:
    print('=== Sent with every request as  "output_config": {"format": ...} ===\n')
    print(json.dumps(OUTPUT_FORMAT, indent=2))
    print("\n=== Fields at a glance ===\n")
    for name, spec in INVOICE_SCHEMA["properties"].items():
        types = [b["type"] for b in spec["anyOf"]] if "anyOf" in spec else [spec["type"]]
        print(f"  {name:<15} {' or '.join(types)}")
    print("\n  The API guarantees Claude's reply is JSON with exactly these fields and types")
    print("  (unless it stops early with a refusal or max_tokens).")
    print("  It arrives as a text block; parse it with schema.parse_extraction().")


if __name__ == "__main__":
    main()
