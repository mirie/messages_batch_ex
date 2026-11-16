"""Create the 26 test PDFs and data/ground_truth.json.

Run:  uv run generate-invoices     (no API call)
"""

from collections import Counter

from invoice_batch.config import DATA_DIR, PROJECT_ROOT
from invoice_batch.synthetic.build import generate


def main() -> None:
    docs = generate(DATA_DIR)
    print(
        f"Wrote {len(docs)} documents to {(DATA_DIR / 'invoices').relative_to(PROJECT_ROOT)}/ "
        f"and {(DATA_DIR / 'ground_truth.json').relative_to(PROJECT_ROOT)}\n"
    )
    print(f"{'custom_id':<26} {'group':<14} {'expected_outcome':<16} {'size':>7}")
    print("-" * 66)
    for d in docs:
        size = (DATA_DIR / d["file"]).stat().st_size
        print(f"{d['custom_id']:<26} {d['group']:<14} {d['expected_outcome']:<16} {size:>6}B")
    counts = Counter(d["expected_outcome"] for d in docs)
    print("\nExpected outcomes:", ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
