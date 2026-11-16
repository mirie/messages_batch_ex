"""Documents 01-23 must never change when new documents are added.

Earlier real batches were run on these exact files. The hashes below were taken
from the generator at commit 722132f. If a change to the generator moves any
random value, these tests fail.
"""

import hashlib
import json

import pytest

from invoice_batch.synthetic.build import generate

FROZEN_PDF_SHA256 = {
    "01_clean_classic": "3b6a8228603413e45f48af170effe60c18daa97ae5fc3b9de0602017b439a706",
    "02_clean_modern": "97c4192d122f73a94309337cce3306adc5e78025b72ee988f494b2de856ca11f",
    "03_clean_compact": "1eb1801e5421ad2c7cd9ab9e93b7d9f58f84b851b920a6d925063a514c49a0f9",
    "04_clean_classic": "c75c912fe2326cd8ea2a385cbf349af87499734e6e691bb098afde88e98130e0",
    "05_clean_modern": "2b946e550ddd32b5dbd463b4f7fd6129366a01ddb07a088ca9b28f9ddf68fb63",
    "06_clean_compact_no_due": "aa592b0b034eb2bb5376d436133b045227a3163b7ad57b45ea26c5f8d785c1c1",
    "07_clean_classic": "dc433b31a0ba6f90613e41c077643ec53726bae0d4b2cfc99903332f6d305d15",
    "08_clean_modern": "e22a6c9c4872637d66b88e421e2e334805033ddf93c7c0aab83bce338cd18f7f",
    "09_clean_compact": "ba6ad58909b0e94352331f82858d0602d2e5eb57473220a22ca802b1c3af336b",
    "10_clean_classic": "fca3d976474af5dd015f53ad7979002b1c0ca12c964efbe464cf1eaa1d53b9bf",
    "11_clean_modern": "42d6996268bf073fc0eeb9978e587cf32f9396561bdb43ec4dadc5c217a01668",
    "12_clean_compact": "b6dac54d9fc9ebfb3f068e075fb763e18530534dcb70cd8f2991544bead371ab",
    "13_clean_classic": "afe57ed4e755acac8dd345fa9fc1fa02d9ca71d46adc660b1ee9fcd47978e2eb",
    "14_clean_modern": "ae3fcac05486b8f1a782a1153f662f4563f71b4686c028ae353088e40eb6c3d8",
    "15_clean_compact": "b28e6345554c8a99ec26aa7a204b6ff2c85edc2e988ea53c377ca78e40dcacad",
    "16_clean_classic": "ebd376c791fb793dc6777d0cb02bd74f2fd3b7f1b82c535c4b3ab3c2e0d628e0",
    "17_cluttered": "c3a22b34f3f57973f1c7bc5eebe9128b55da9d9c8248477b00e7dc9154c90c72",
    "18_footer_due_date": "976096246e284bb3ab3d67c3c87771f211ca34a229e3cf23ab3820ceaa70bb6a",
    "19_unusual_format": "2f8f62f1ca7b47bb213ce357591206b682bc6b54bf4255d9cde32641abf07dd8",
    "20_total_mismatch": "b3dc97a22c6c130ea2515a903b55b3e6ada4df8ac222b7bbe04da53f304dc14f",
    "21_corrupt": "9e7969ddb488862d503e04924e5bdab6947d35e4386551729c6d27fa3f419260",
    "22_letter": "51ae860224a769c4e6f3e8595c164960ca2d2c6e2a6951d5ba54e3c7a01ada34",
    "23_blank": "87ca0b73aeb9516cfb95e8dd61a6cd2b91ff5cc87830aca029fce5d5fc868ee0",
}

# The SHA-256 of json.dumps(first 23 ground-truth entries, sort_keys=True).
FROZEN_GROUND_TRUTH_SHA256 = "329046b3a1d328e39793eccdfa08983da10917f5afa4a137fb3b8869363e3bc0"


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    generate(out)
    return out


@pytest.mark.parametrize("custom_id", sorted(FROZEN_PDF_SHA256))
def test_original_pdf_is_byte_identical(out_dir, custom_id):
    pdf_bytes = (out_dir / "invoices" / f"{custom_id}.pdf").read_bytes()
    assert hashlib.sha256(pdf_bytes).hexdigest() == FROZEN_PDF_SHA256[custom_id]


def test_original_ground_truth_entries_are_unchanged(out_dir):
    documents = json.loads((out_dir / "ground_truth.json").read_text())["documents"]
    first_23 = json.dumps(documents[:23], sort_keys=True).encode()
    assert hashlib.sha256(first_23).hexdigest() == FROZEN_GROUND_TRUTH_SHA256
