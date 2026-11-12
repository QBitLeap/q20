"""Prepare a standalone Umbrel candidate with its own data, API and Core dependency."""

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def package(destination, image, app_id="qbitleap-q20-main", core_id="qbitleap-core-main", port=8790, *, private=False):
    for value in (app_id, core_id):
        if re.fullmatch(r"[a-z][a-z0-9-]{2,45}", value) is None:
            raise ValueError("Invalid app ID")
    if app_id == core_id or not 1024 <= port <= 65535:
        raise ValueError("Independent app/Core IDs and a valid port required")
    if re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}", image) is None:
        raise ValueError("A verified registry manifest digest is required")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Preserve the existing package; choose a new destination")
    prefix = "APP_" + app_id.upper().replace("-", "_")
    core_prefix = "APP_" + core_id.upper().replace("-", "_")
    service = {"image": image, "user": "1000:1000", "init": True, "restart": "on-failure",
               "read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
               "pids_limit": 128, "mem_limit": "2048m", "cpus": 2, "stop_grace_period": "2m",
               "environment": {"Q20_CORE_READ_URL": "${" + core_prefix + "_READ_URL}",
                               "Q20_CORE_READ_TOKEN": "${" + core_prefix + "_READ_TOKEN}",
                               "Q20_API_TOKEN": "${" + prefix + "_API_TOKEN}",
                               "Q20_ALLOWED_HOSTS": "*"},
               "volumes": ["${APP_DATA_DIR}/data/index:/data"],
               "tmpfs": ["/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777"],
               "healthcheck": {"test": ["CMD", "python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz',timeout=2).close()"],
                               "interval": "1m", "timeout": "5s", "retries": 3}}
    manifest = {"manifestVersion": 2.0, "id": app_id, "name": "q20 Indexer", "version": "0.1.1",
                "tagline": "Independent QBIT-20 messages and token indexing", "category": "finance",
                "description": "Index QBIT-20 JSON messages, balances and bound listing outputs using your Qbit Core. Starts indexing automatically. Includes a browser dashboard and authenticated read API.",
                "developer": "QBitLeap", "repo": "https://github.com/QBitLeap/q20",
                "support": "https://github.com/QBitLeap/q20/issues", "website": "https://qbitleap.com",
                "dependencies": [core_id], "storage": {"dataRoot": "data"}, "port": port,
                "path": "", "gallery": [], "submitter": "QBitLeap",
                "releaseNotes": "Initial q20 0.1.1. Native platform and isolated Core/gateway lifecycle checks passed. Starts Mainnet indexing automatically. Experimental: managed installation and real-chain replay parity are separate checks.",
                "icon": "https://raw.githubusercontent.com/QBitLeap/q20/main/icon.svg"}
    compose = {"services": {"app_proxy": {"environment": {"APP_HOST": app_id + "_q20_1", "APP_PORT": 8080}}, "q20": service}}
    if private:
        manifest['icon']='data:image/svg+xml;base64,'+base64.b64encode((ROOT/'icon.svg').read_bytes()).decode()
        manifest['repo']=manifest['support']=''
    destination.mkdir(parents=True)
    (destination / "data/index").mkdir(parents=True)
    (destination / "data/index/.gitkeep").write_text("")
    for name, value in (("docker-compose.yml", compose), ("umbrel-app.yml", manifest)):
        (destination / name).write_text(json.dumps(value, indent=2) + "\n")
    exports = (f'export {prefix}_API_URL="http://{app_id}_q20_1:8080/v1/"\n'
               f'export {prefix}_API_USER="reader"\n'
               f'export {prefix}_API_TOKEN="$(derive_entropy "app-{app_id}-seed-read-api")"\n')
    (destination / "exports.sh").write_text(exports)
    shutil.copyfile(ROOT / "icon.svg", destination / "icon.svg")
    receipt = {"app": app_id, "network": "mainnet", "image": image, "installed": False,
               "fullUmbrelInstallationAccepted": False, "testnet4RulesAccepted": False,
               "files": {p.relative_to(destination).as_posix(): sha256(p.read_bytes()).hexdigest()
                         for p in sorted(destination.rglob("*")) if p.is_file()}}
    (destination / "package-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--app-id", default="qbitleap-q20-main")
    parser.add_argument("--core-id", default="qbitleap-core-main")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    print(json.dumps(package(args.destination, args.image, args.app_id, args.core_id, args.port, private=args.private), indent=2))
