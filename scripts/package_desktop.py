"""Build, extract and smoke-test a self-contained native q20 archive."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from q20 import __version__
from build_crypto import build
sys.path.insert(0, str(ROOT / "checks"))
from smoke_process import smoke


def package(output):
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}[platform.system()]
    architecture = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}[platform.machine().lower()]
    library = build()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="q20-package-") as folder:
        work = Path(folder)
        icon = ROOT / "assets/platform-icons" / (system + ".png")
        options = []
        if system == "windows":
            png = icon.read_bytes()
            ico = work / "q20.ico"
            ico.write_bytes(struct.pack("<HHHBBBBHHII", 0, 1, 1, 0, 0, 0, 0, 1, 32, len(png), 22) + png)
            options = ["--icon", str(ico)]
        environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(work / "cache"))
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--name", "q20",
            "--paths", str(ROOT), "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
            "--specpath", str(work), "--add-data", f"{ROOT / 'q20/static'}:q20/static",
            "--add-data", f"{ROOT / 'q20/rules'}:q20/rules", "--add-binary", f"{library}:q20/_native",
            *options, str(ROOT / "scripts/desktop_entry.py")], check=True, cwd=ROOT, env=environment)
        bundle = work / "dist/q20"
        for name in ("README.md", "LICENSE", "NOTICE", "dependencies.lock.json"):
            shutil.copyfile(ROOT / name, bundle / name)
        shutil.copytree(ROOT / "third_party", bundle / "third_party-licenses",
                        ignore=shutil.ignore_patterns("*.c", "*.h", "MANIFEST", "UPSTREAM.md", "source-manifest.json"))
        shutil.copyfile(icon, bundle / "icon.png")
        shutil.copyfile(ROOT / "assets/platform-icons" / (system + "-testnet4.png"), bundle / "icon-testnet4.png")
        shutil.copyfile(ROOT / "assets/icon-overlays/NOTICE.md", bundle / "ICON-NOTICE.md")
        archive = Path(shutil.make_archive(str(output / f"q20-{__version__}-{system}-{architecture}"),
                        "zip" if system == "windows" else "gztar", root_dir=bundle.parent, base_dir="q20"))
        extracted = work / "extracted"
        shutil.unpack_archive(archive, extracted)
        executable = extracted / "q20" / ("q20.exe" if system == "windows" else "q20")
        subprocess.run([executable, "--version"], check=True, cwd=work)
        fixture = work / "mint.json"
        fixture.write_text('{"p":"qbit-20","op":"mint","tick":"TEST","amt":"1"}')
        value = json.loads(subprocess.check_output([executable, "inspect", fixture, "--height", "180000"], cwd=work))
        if value["classification"] != "record":
            raise ValueError("Packaged parser failed its smoke check")
        process_receipt = smoke([str(executable)])
        receipt = {"version": __version__, "os": system, "architecture": architecture,
                   "archive": archive.name, "sha256": sha256(archive.read_bytes()).hexdigest(),
                   "nativePackagingSmokePassed": True, "liveChainParityAccepted": False,
                   "testnet4RulesAccepted": False, "coreStarted": False, "transactionsBroadcast": False}
        receipt.update(process_receipt)
        archive.with_suffix(archive.suffix + ".json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt))
        return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.output.resolve())
