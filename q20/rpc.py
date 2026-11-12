"""Method-restricted Core reader. Neither cookie nor gateway permits RPC passthrough."""

import base64
from decimal import Decimal
import json
import os
from pathlib import Path
import stat
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .messages import Incomplete
from .wire import hash_id

READS = {"getblockchaininfo", "getindexinfo", "getblockhash", "getblock", "getrawtransaction", "gettxout"}
MAX_RESPONSE = 64 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Incomplete("Core redirects are refused")


class Core:
    def __init__(self, url, cookie=None, gateway_token=None):
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment):
            raise ValueError("RPC URL must have an explicit HTTP(S) host without embedded credentials")
        if bool(cookie) == bool(gateway_token):
            raise ValueError("Choose a local cookie or a Core read-gateway credential")
        if cookie is not None and (parts.hostname not in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("A full Core cookie is only sent to loopback; use a read gateway for another host")
        self.url, self.cookie, self.token = url, Path(cookie) if cookie else None, gateway_token
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, method, params):
        if method not in READS:
            raise ValueError("q20 does not support signing, wallet writes, or publication RPC")
        try:
            if self.cookie:
                info = self.cookie.lstat()
                if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600):
                    raise Incomplete("Core cookie must be a private regular file")
                credential = self.cookie.read_bytes().strip()
                if not 1 <= len(credential) <= 512 or b":" not in credential:
                    raise Incomplete("Core cookie is unavailable")
            else:
                credential = ("reader:" + self.token).encode()
            request = Request(self.url, method="POST", headers={"Content-Type": "application/json",
                "Authorization": "Basic " + base64.b64encode(credential).decode()}, data=json.dumps(
                    {"jsonrpc": "2.0", "id": "q20", "method": method, "params": params}).encode())
            try:
                response = self.opener.open(request, timeout=30)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise Incomplete("Core block exceeds the configured read budget")
            value = json.loads(raw, parse_float=Decimal)
            if (response.status != 200 or not isinstance(value, dict) or value.get("error") is not None
                    or "result" not in value):
                raise Incomplete("Core read failed; the index has not advanced")
            return value["result"]
        except Incomplete:
            raise
        except Exception:
            raise Incomplete("Core read unavailable; check the selected node and read credentials") from None

    def identity(self, rules):
        info = self.call("getblockchaininfo", [])
        if (not isinstance(info, dict) or info.get("chain") != rules.value["coreChain"]
                or self.call("getblockhash", [0]) != rules.value["genesis"]):
            raise Incomplete("Selected Core network/genesis does not match this index")
        return info

    def prevout(self, txid, vout):
        tx = self.call("getrawtransaction", [hash_id(txid), True])
        if not isinstance(tx, dict) or tx.get("txid") != txid:
            raise Incomplete("Core returned the wrong previous transaction")
        try:
            return tx["vout"][vout]
        except (KeyError, IndexError, TypeError):
            raise Incomplete("Core prevout is unavailable; enable its transaction index") from None
