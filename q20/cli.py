"""q20 desktop/Umbrel entry point; one portable engine on all platforms."""

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import threading

from . import __version__
from .http import Server, handler
from .messages import decode
from .rpc import Core
from .rules import Rules
from .runtime import Runtime
from .tickets import native_verifier


def data_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "q20/mainnet"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/q20/mainnet"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "q20/mainnet"


def main(argv=None):
    parser = argparse.ArgumentParser(description="q20 — independent QBIT-20 indexer and protected-output API")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Classify a UTF-8 JSON message without changing a ledger")
    inspect.add_argument("file", type=Path)
    inspect.add_argument("--height", type=int, required=True)
    inspect.add_argument("--rules", type=Path)
    serve = commands.add_parser("start", help="Index automatically and serve the local dashboard")
    serve.add_argument("--rpc-url", default=os.environ.get("Q20_CORE_READ_URL"), required=not bool(os.environ.get("Q20_CORE_READ_URL")))
    serve.add_argument("--cookie", type=Path)
    serve.add_argument("--data", type=Path, default=data_directory())
    serve.add_argument("--rules", type=Path)
    serve.add_argument("--port", type=int, default=8790)
    serve.add_argument("--listen", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    serve.add_argument("--pqc-library", type=Path)
    args = parser.parse_args(argv)
    rules = Rules.load(args.rules)
    if args.command == "inspect":
        if args.height < 0:
            parser.error("Height cannot be negative")
        m = decode(args.file.read_bytes(), rules, args.height)
        print(json.dumps({"classification": m.classification, "reason": m.reason,
                          "duplicateKeys": m.duplicates, "network": rules.network,
                          "rulesFingerprint": rules.fingerprint,
                          "ledgerValidity": "requires confirmed block-order evaluation"}, indent=2))
        return 0
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    if rules.network != "mainnet" and args.data == data_directory():
        parser.error("A non-mainnet profile requires a separate explicit --data directory")
    args.data.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = os.environ.get("Q20_API_TOKEN")
    if token is None:
        token_file = args.data / "read-api.token"
        if token_file.is_symlink():
            parser.error("Linked API credential refused")
        if not token_file.exists():
            with token_file.open("x", encoding="ascii") as stream:
                if os.name != "nt":
                    os.chmod(token_file, 0o600)
                stream.write(secrets.token_hex(32))
        token = token_file.read_text(encoding="ascii").strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        parser.error("A private per-installation 32-byte API token is required")
    if args.listen == "0.0.0.0" and not os.environ.get("Q20_ALLOWED_HOSTS"):
        parser.error("An external interface requires explicit Q20_ALLOWED_HOSTS")
    suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
    bundled = Path(__file__).with_name("_native") / ("q20pqc" + suffix)
    library = args.pqc_library or bundled
    verify = native_verifier(str(library.resolve()))
    core = Core(args.rpc_url, args.cookie, os.environ.get("Q20_CORE_READ_TOKEN"))
    runtime = Runtime(args.data, rules, core, verify)
    hosts = {"localhost", "127.0.0.1"} | {x.strip().lower() for x in os.environ.get("Q20_ALLOWED_HOSTS", "").split(",") if x.strip()}
    server = Server((args.listen, args.port), handler(runtime, token, hosts))
    http_thread = threading.Thread(target=server.serve_forever, name="q20-dashboard", daemon=True)
    http_thread.start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: runtime.stop.set())
    print(json.dumps({"event": "q20-start", "version": __version__, "network": rules.network,
                      "dashboard": f"http://127.0.0.1:{args.port}", "keysHeld": False}), flush=True)
    try:
        runtime.run()
    finally:
        runtime.stop.set()
        server.shutdown()
        server.server_close()
        http_thread.join(5)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as exc:
        print(f"q20: {exc}", file=sys.stderr)
        sys.exit(1)
