"""Compile pinned Qbit bounded30 sources into the platform's verification library."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build():
    vendor = ROOT / "third_party/libbitcoinpqc"
    manifest = json.loads((ROOT / "third_party/source-manifest.json").read_text())
    actual = {p.relative_to(vendor).as_posix() for p in vendor.rglob("*") if p.is_file()}
    if actual != set(manifest["sha256"]) or any(p.is_symlink() for p in vendor.rglob("*")):
        raise ValueError("Vendored source inventory differs from its verified manifest")
    for relative, digest in manifest["sha256"].items():
        path = vendor / relative
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Vendored crypto source changed: " + relative)
    system = platform.system()
    suffix = {"Darwin": ".dylib", "Linux": ".so", "Windows": ".dll"}[system]
    destination = ROOT / "q20/_native"
    destination.mkdir(exist_ok=True)
    target = destination / ("q20pqc" + suffix)
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise ValueError("A native C compiler is required")
    ref = vendor / "sphincsplus/ref"
    sources = list((vendor / "src").rglob("*.c")) + list(ref.glob("*.c"))
    args = [compiler, "-O2", "-std=c11", "-DPARAMS=sphincs-sha2-128s-bounded30",
            "-DCUSTOM_RANDOMBYTES", "-DSPX_PRODUCTION_BUILD", "-I" + str(vendor / "include"), "-I" + str(ref)]
    if system == "Darwin":
        args += ["-dynamiclib", "-fPIC"]
    elif system == "Linux":
        args += ["-shared", "-fPIC"]
    else:
        # clang/LLD's automatic DLL exports make the upstream C API visible to ctypes.
        args += ["-shared", "-Wl,/EXPORT:bitcoin_pqc_verify"]
    subprocess.run([*args, *map(str, sources), "-o", str(target)], check=True)
    print(json.dumps({"library": target.name, "sha256": sha256(target.read_bytes()).hexdigest(),
                      "algorithm": manifest["source"]["algorithm"], "publicVerificationOnly": True}))
    return target


if __name__ == "__main__":
    build()
