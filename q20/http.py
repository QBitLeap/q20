"""Small bounded dashboard and authenticated read/protection API. No RPC forwarding."""

import base64
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from socketserver import TCPServer, ThreadingMixIn
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from .index import encode
from .messages import Incomplete
from .wire import address_script, hash_id

STATIC = Path(__file__).with_name("static")


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def server_bind(self):
        # HTTPServer's reverse lookup can block local startup on DNS configuration.
        # No q20 operation needs a PTR record for its explicit listening address.
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def handler(runtime, token, allowed_hosts):
    class Handler(BaseHTTPRequestHandler):
        server_version = "q20"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def send(self, code, value, mime="application/json; charset=utf-8"):
            body = value if isinstance(value, bytes) else encode(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def admitted(self, api=False):
            try:
                host = urlsplit("http://" + self.headers.get("Host", "")).hostname
            except ValueError:
                host = None
            if host not in allowed_hosts and "*" not in allowed_hosts:
                self.send(403, {"error": "Unknown app host"})
                return False
            if api:
                expected = "Basic " + base64.b64encode(("reader:" + token).encode()).decode()
                value = self.headers.get("Authorization", "")
                if not hmac.compare_digest(value.encode(), expected.encode()):
                    self.send(401, {"error": "Read API authentication required"})
                    return False
            return True

        def do_GET(self):
            path = urlsplit(self.path)
            if not self.admitted(path.path.startswith("/v1/")):
                return
            if path.path in ("/", "/app.js", "/style.css", "/icon.svg"):
                name = {"/": "index.html"}.get(path.path, path.path[1:])
                mime = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                        "style.css": "text/css; charset=utf-8", "icon.svg": "image/svg+xml"}[name]
                return self.send(200, (STATIC / name).read_bytes(), mime)
            if path.path in ("/status", "/v1/status", "/healthz"):
                return self.send(200, runtime.checkpoint())
            index = None
            try:
                index = runtime.reader()
                index.db.execute("BEGIN")
                params = parse_qs(path.query)
                limit = int(params.get("limit", ["100"])[0])
                offset = int(params.get("offset", ["0"])[0])
                if not 1 <= limit <= 500 or not 0 <= offset <= 10000000:
                    raise ValueError("Invalid pagination")
                if path.path == "/v1/messages":
                    data = index.history(limit, offset)
                elif path.path == "/v1/tokens":
                    data = [{"tick": k, **json.loads(v)} for k, v in index.db.execute(
                        "SELECT key,value FROM state WHERE kind='token' ORDER BY key LIMIT ? OFFSET ?", (limit, offset))]
                elif path.path == "/v1/bound":
                    data = [{"outpoint": k, **json.loads(v)} for k, v in index.db.execute(
                        "SELECT key,value FROM state WHERE kind='bound' ORDER BY key LIMIT ? OFFSET ?", (limit, offset))]
                elif path.path.startswith("/v1/balances/"):
                    owner = unquote(path.path.removeprefix("/v1/balances/"))
                    canonical = address_script(owner, runtime.rules.value["hrp"])
                    from .wire import address
                    owner = address(canonical, runtime.rules.value["hrp"])
                    prefix = owner + ":"
                    data = [{"tick": k[len(prefix):], "available": json.loads(v)} for k, v in index.db.execute(
                        "SELECT key,value FROM state WHERE kind='balance' AND key>=? AND key<? ORDER BY key LIMIT ? OFFSET ?",
                        (prefix, owner + ";", limit, offset))]
                else:
                    return self.send(404, {"error": "Unknown route"})
                return self.send(200, {"network": runtime.rules.network, "indexHeight": index.tip[0],
                                       "indexHash": index.tip[1], "rulesFingerprint": runtime.rules.fingerprint, "items": data})
            except ValueError:
                return self.send(400, {"error": "Invalid read parameters"})
            except Exception:
                return self.send(503, {"available": False, "error": "Committed index snapshot unavailable"})
            finally:
                if index:
                    index.close()

        def do_POST(self):
            if not self.admitted(api=True):
                return
            if urlsplit(self.path).path != "/v1/protection":
                return self.send(404, {"error": "Unknown route"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 65536 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Body budget")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict) or set(value) != {"coins"}:
                    raise ValueError("Expected coins")
                coins = value["coins"]
                if not isinstance(coins, list) or not 1 <= len(coins) <= 128:
                    raise ValueError("Input budget")
                for coin in coins:
                    if not isinstance(coin, dict) or set(coin) != {"txid", "vout"}:
                        raise ValueError("Bad input")
                    hash_id(coin["txid"])
                    if type(coin["vout"]) is not int or not 0 <= coin["vout"] <= 0xFFFFFFFF:
                        raise ValueError("Bad vout")
                return self.send(200, runtime.protection(coins))
            except (ValueError, KeyError):
                return self.send(400, {"error": "Invalid protection request"})
            except Incomplete:
                return self.send(503, {"available": False, "error": "Current token protection cannot be established; do not use these inputs"})
            except Exception:
                return self.send(503, {"available": False, "error": "Protection check unavailable"})

    return Handler
