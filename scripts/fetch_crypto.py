"""Fetch only pinned, hash-verified public PQC source/fixtures. No npm hooks."""

import base64
from hashlib import sha512, sha256
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch():
    lock = json.loads((ROOT / "dependencies.lock.json").read_text())["pqc"]
    with urlopen(lock["url"], timeout=30) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024 or "sha512-" + base64.b64encode(sha512(raw).digest()).decode() != lock["integrity"]:
        raise ValueError("PQC package checksum/budget mismatch")
    destination = ROOT / "third_party/libbitcoinpqc"
    destination.mkdir(parents=True, exist_ok=True)
    prefix = "package/vendor/libbitcoinpqc-qbit/"
    manifest = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            if member.name.startswith(prefix) and member.isfile():
                relative = PurePosixPath(member.name[len(prefix):])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe upstream member")
                value = archive.extractfile(member).read()
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
                manifest[str(relative)] = sha256(value).hexdigest()
        for source, target in (("package/fixtures/qbit-core-signature-vectors.json", ROOT / "tests/fixtures/pqc-vectors.json"),
                               ("package/LICENSE", ROOT / "third_party/PQC-PACKAGE-LICENSE"),
                               ("package/THIRD_PARTY_NOTICES", ROOT / "third_party/PQC-THIRD-PARTY-NOTICES")):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(source).read())
    (ROOT / "third_party/source-manifest.json").write_text(json.dumps({"source": lock, "sha256": manifest}, indent=2) + "\n")
    print(f"Verified and retained {len(manifest)} pinned public crypto source files")


if __name__ == "__main__":
    fetch()
