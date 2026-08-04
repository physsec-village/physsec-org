"""Check the client-side QR encoder against a reference implementation.

`static/pages/qr.js` is hand-written, so a subtle bug there would produce a
symbol that renders but does not scan — something no page test would catch.
These tests compare its module matrix against the `qrcode` package, which the
project uses only for development. The tests skip outside CI when node is
unavailable.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QR_JS = REPO_ROOT / "static" / "pages" / "qr.js"
PAYLOAD_JS = REPO_ROOT / "static" / "pages" / "store-menu-payload.js"
ECC_LEVELS = ("L", "M", "Q", "H")
PAYLOADS = (
    "PSV34|BYP002*1|T5",
    "PSV34|KYS016001*2|KYS028990*1|BYP014002*3|T395",
    "A",
    "PSV34|" + "|".join(f"KYS0160{n:02d}*{n % 9 + 1}" for n in range(1, 16)) + "|T740",
    "café — 1×",
)

REFERENCE_SCRIPT = """
import json, sys
import qrcode, qrcode.util
levels = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}
payload, ecc = json.loads(sys.argv[1]), sys.argv[2]
qr = qrcode.QRCode(error_correction=levels[ecc], box_size=1, border=0)
qr.add_data(qrcode.util.QRData(payload, mode=qrcode.util.MODE_8BIT_BYTE))
qr.make(fit=True)
print(json.dumps({"version": qr.version,
                  "modules": [[bool(c) for c in row] for row in qr.get_matrix()]}))
"""


class QrEncoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.python = sys.executable
        if subprocess.run(
            [cls.python, "-c", "import qrcode"], capture_output=True, timeout=30
        ).returncode:
            raise unittest.SkipTest("qrcode development dependency is unavailable")
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed")

    def run_node(self, source: str, *, expect_success: bool = True):
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", source],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if expect_success:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        return proc

    def encode_in_js(self, payload: str, ecc: str) -> dict:
        source = (
            f"import {{ qrMatrix }} from {json.dumps(QR_JS.as_uri())};\n"
            f"const out = qrMatrix({json.dumps(payload)}, "
            f"{{ ecc: {json.dumps(ecc)} }});\n"
            "console.log(JSON.stringify(out));\n"
        )
        return self.run_node(source)

    def encode_reference(self, payload: str, ecc: str) -> dict:
        proc = subprocess.run(
            [self.python, "-c", REFERENCE_SCRIPT, json.dumps(payload), ecc],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_matrices_match_the_reference_encoder(self):
        for payload in PAYLOADS:
            for ecc in ECC_LEVELS:
                with self.subTest(payload=payload[:24], ecc=ecc):
                    mine = self.encode_in_js(payload, ecc)
                    theirs = self.encode_reference(payload, ecc)
                    self.assertEqual(mine["version"], theirs["version"])
                    self.assertEqual(mine["size"], len(theirs["modules"]))
                    self.assertEqual(
                        [[bool(c) for c in row] for row in mine["modules"]],
                        theirs["modules"],
                    )

    def test_a_realistic_list_stays_low_density(self):
        """Scanning happens off a phone screen, so keep the symbol coarse."""
        payload = "PSV34|BYP002*2|KYS016001|BYP014002|KYS025003*3|T235"
        matrix = self.encode_in_js(payload, "M")
        self.assertLessEqual(matrix["size"], 41)

    def test_an_oversized_payload_raises_rather_than_truncating(self):
        source = (
            f"import {{ qrMatrix }} from {json.dumps(QR_JS.as_uri())};\n"
            f"qrMatrix({json.dumps('x' * 5000)}, {{ ecc: \"H\" }});\n"
        )
        proc = self.run_node(source, expect_success=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Data does not fit", proc.stderr)

    def make_payloads_in_js(self, tokens: list[str], total: int) -> list[str]:
        source = (
            f"import {{ payloads }} from {json.dumps(PAYLOAD_JS.as_uri())};\n"
            f"console.log(JSON.stringify(payloads({json.dumps(tokens)}, {total})));\n"
        )
        return self.run_node(source)

    def test_single_payload_has_page_identity(self):
        pages = self.make_payloads_in_js(["BYP002*2", "KYS016001"], 45)
        self.assertEqual(pages, ["PSV34|Q1/1|BYP002*2|KYS016001|T45"])

    def test_large_list_is_split_on_item_boundaries(self):
        tokens = [f"KYS{i:08d}*99" for i in range(100)]
        pages = self.make_payloads_in_js(tokens, 12345)

        self.assertGreater(len(pages), 1)
        recovered = []
        for index, page in enumerate(pages, 1):
            with self.subTest(index=index):
                parts = page.split("|")
                self.assertEqual(parts[:2], ["PSV34", f"Q{index}/{len(pages)}"])
                self.assertEqual(parts[-1], "T12345")
                recovered.extend(parts[2:-1])
                matrix = self.encode_in_js(page, "M")
                self.assertLessEqual(matrix["version"], 6)
                self.assertLessEqual(matrix["size"], 41)
        self.assertEqual(recovered, tokens)
