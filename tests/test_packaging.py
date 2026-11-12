import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_umbrel_is_independent_and_uses_only_read_credentials(self):
        spec = importlib.util.spec_from_file_location("q20_package_umbrel", ROOT / "scripts/package_umbrel.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "app"
            receipt = module.package(destination, "registry.example/q20@sha256:" + "1"*64)
            self.assertFalse(receipt["installed"])
            manifest = json.loads((destination / "umbrel-app.yml").read_text())
            self.assertEqual(manifest["dependencies"], ["qbitleap-core-main"])
            self.assertNotIn("defaultPassword", manifest)
            compose = json.loads((destination / "docker-compose.yml").read_text())
            service = compose["services"]["q20"]
            self.assertFalse(any("auth" in v or "core:" in v or "docker.sock" in v for v in service["volumes"]))
            self.assertNotIn("QBIT_WALLET_ENABLED", service["environment"])
            with self.assertRaises(ValueError):
                module.package(destination, "registry.example/q20:latest")

    def test_platform_marks_and_large_testnet_cones(self):
        svg = "{http://www.w3.org/2000/svg}"
        for platform in ("macos", "windows", "linux", "umbrel"):
            root = ET.parse(ROOT / "assets/platform-icons" / (platform+"-testnet4.svg")).getroot()
            cone = next(e for e in root if e.get("data-mark") == "testnet4")
            self.assertEqual(cone.get("opacity"), "0.5")
            self.assertEqual(cone.get("width"), "1024")
            self.assertEqual(cone.get("y"), "0")
            if platform != "umbrel":
                mark = next(e for e in root if e.get("data-mark") == platform)
                self.assertEqual(mark.get("opacity"), "0.5")


if __name__ == "__main__":
    unittest.main()
