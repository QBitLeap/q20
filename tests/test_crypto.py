import json
from pathlib import Path
import sys
import unittest

from q20.tickets import native_verifier


class CryptoParityTests(unittest.TestCase):
    def test_qbit_core_bounded30_vectors_and_corruption(self):
        root = Path(__file__).resolve().parents[1]
        suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
        path = root / "q20/_native" / ("q20pqc" + suffix)
        if not path.exists():
            self.skipTest("Build the bundled verifier with scripts/build_crypto.py")
        verify = native_verifier(str(path))
        vectors = json.loads((root / "tests/fixtures/pqc-vectors.json").read_text())
        for vector in vectors["accept"]:
            key = bytes.fromhex(vectors["keys"][vector["key"]]["publicKey"])
            message, signature = bytes.fromhex(vector["message"]), bytes.fromhex(vector["signature"])
            with self.subTest(vector=vector["name"]):
                self.assertTrue(verify(key, message, signature))
                changed = bytes([signature[0] ^ 1]) + signature[1:]
                self.assertFalse(verify(key, message, changed))


if __name__ == "__main__":
    unittest.main()
