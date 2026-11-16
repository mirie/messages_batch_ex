"""Stage 3: extract 4 documents with the normal (synchronous) Messages API.

Run:  uv run dry-run

Same request shape the batch will use, but one call at a time, so you see
each answer immediately. Includes the corrupt PDF so you can see what an
invalid-request error looks like. Cost: a fraction of a cent on Haiku.
"""

import json
import time

import anthropic

from invoice_batch.config import MODEL, make_client, pdf_path_for
from invoice_batch.pricing import cost_usd
from invoice_batch.request_builder import build_params

DOCS = ["01_clean_classic", "19_unusual_format", "22_letter", "21_corrupt"]


def main() -> None:
    client = make_client()
    total = 0.0
    for custom_id in DOCS:
        print("=" * 72)
        print(f"{custom_id}   (model: {MODEL})")
        print("=" * 72)
        params = build_params(pdf_path_for(custom_id))
        start = time.perf_counter()
        try:
            msg = client.messages.create(**params)
        except anthropic.BadRequestError as e:  # 400: the request itself is bad
            print(f"ERROR  HTTP {e.status_code}  (took {time.perf_counter() - start:.1f}s)")
            print(json.dumps(e.body, indent=2))
            print("-> invalid_request_error: resubmitting this unchanged can never succeed.\n")
            continue
        except anthropic.APIStatusError as e:  # 429 / 5xx etc.: usually retryable
            print(f"ERROR  HTTP {e.status_code}: {e.body}\n")
            continue

        elapsed = time.perf_counter() - start
        usage = msg.usage.model_dump()
        cost = cost_usd(usage, msg.model, batch=False)
        total += cost
        print(f"stop_reason: {msg.stop_reason}    took {elapsed:.1f}s")
        print(f"content block types: {[b.type for b in msg.content]}")
        for block in msg.content:
            if block.type == "tool_use":
                print("raw tool_use block:")
                print(json.dumps(block.model_dump(), indent=2, ensure_ascii=False))
            elif block.type == "text":
                print(f"text: {block.text}")
        print(
            f"usage: input={usage['input_tokens']} output={usage['output_tokens']} "
            f"cache_write={usage.get('cache_creation_input_tokens')} "
            f"cache_read={usage.get('cache_read_input_tokens')}"
        )
        print(f"cost (standard price): ${cost:.5f}\n")
    print(
        f"Total dry-run cost at standard price: ${total:.5f} "
        f"(a batch would be half: ${total / 2:.5f})"
    )


if __name__ == "__main__":
    main()
