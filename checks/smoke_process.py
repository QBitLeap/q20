"""Exercise the actual executable against an owned, synthetic Core read fixture."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from q20.rules import Rules


def smoke(command, library=None):
    opener = build_opener(ProxyHandler({}))
    rules = Rules.load()
    genesis = rules.value["genesis"]
    tx = {"txid": "a" * 64, "version": 2, "locktime": 0, "vin": [{"coinbase": "00"}],
          "vout": [{"value_bits": 0, "scriptPubKey": {"hex": "6a"}}]}
    block = {"height": 0, "hash": genesis, "tx": [tx]}
    calls = []

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method, params = request["method"], request["params"]
            calls.append(method)
            if method == "getblockchaininfo":
                result = {"chain": "main", "blocks": 0, "headers": 0, "initialblockdownload": False}
            elif method == "getblockhash" and params == [0]:
                result = genesis
            elif method == "getblock" and params == [genesis, 3]:
                result = block
            else:
                raise AssertionError("Unexpected fixture RPC " + method)
            body = json.dumps({"id": request["id"], "result": result, "error": None}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    try:
        with tempfile.TemporaryDirectory(prefix="q20-owned-smoke-") as directory:
            environment = dict(os.environ, Q20_CORE_READ_TOKEN="2" * 64)
            args = [*command, "start", "--data", directory, "--rpc-url", f"http://127.0.0.1:{server.server_port}", "--port", str(port)]
            if library:
                args += ["--pqc-library", str(library)]
            process = subprocess.Popen(args, env=environment, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise AssertionError(process.communicate()[1].decode())
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/status", timeout=1) as response:
                            status = json.load(response)
                        if status.get("observedSynchronized"):
                            break
                    except OSError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError("Packaged index did not reach its synthetic tip; observed=" + repr(locals().get("status")) + "; calls=" + repr(calls))
                with opener.open(f"http://127.0.0.1:{port}/", timeout=2) as response:
                    assert b"YOUR QBIT-20 INDEXER" in response.read()
                with opener.open(f"http://127.0.0.1:{port}/icon.svg", timeout=2) as response:
                    assert b"<path" in response.read()
                assert calls.count("getblock") == 1
            finally:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
                    raise AssertionError("q20 did not shut down promptly")
            if os.name != "nt" and process.returncode != 0:
                raise AssertionError(stderr.decode())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    return {"isolatedProcessPassed": True, "dashboardAccepted": True, "shutdownAccepted": True,
            "nativeCoreStarted": False, "liveChainReplayAccepted": False}


if __name__ == "__main__":
    suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
    print(json.dumps(smoke([sys.executable, "-m", "q20"], ROOT / "q20/_native" / ("q20pqc" + suffix))))
