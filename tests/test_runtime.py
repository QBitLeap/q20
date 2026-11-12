import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

urlopen = build_opener(ProxyHandler({})).open

from q20.http import Server, handler
from q20.index import Index
from q20.messages import Incomplete
from q20.rpc import Core
from q20.runtime import Runtime, writer_lock
from test_index import coin, fixture_rules, point, record, transaction


class FakeCore:
    def __init__(self, rules):
        self.rules = rules
        self.calls = []
        self.blocks = [{"height": 0, "hash": rules.value["genesis"], "tx": [transaction(1, record())]}]

    def identity(self, rules):
        return {"chain": "main", "blocks": len(self.blocks) - 1, "headers": len(self.blocks) - 1,
                "initialblockdownload": False}

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "getblockhash":
            return self.blocks[params[0]]["hash"]
        if method == "getblock":
            return next(b for b in self.blocks if b["hash"] == params[0])
        if method == "gettxout":
            return {"confirmations": 1}
        raise AssertionError(method)

    def prevout(self, *args):
        raise AssertionError("Unexpected prevout read")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rules = fixture_rules()
        self.core = FakeCore(self.rules)
        self.runtime = Runtime(self.tmp.name, self.rules, self.core)
        self.index = Index(self.runtime.path, self.rules)

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def test_idle_check_does_not_fetch_blocks_or_write_database(self):
        self.runtime.sweep(self.index)
        self.core.calls.clear()
        before = self.index.db.total_changes
        state = self.runtime.sweep(self.index)
        self.assertTrue(state["observedSynchronized"])
        self.assertEqual(self.index.db.total_changes, before)
        self.assertFalse(any(method in {"getblock", "getrawtransaction"} for method, _ in self.core.calls))

    def test_reorg_rolls_back_and_replays(self):
        block = {"height": 1, "hash": point(500), "previousblockhash": self.core.blocks[0]["hash"],
                 "tx": [transaction(2, record(tick="OTHR"))]}
        self.core.blocks.append(block)
        self.runtime.sweep(self.index)
        self.assertIsNotNone(self.index.get("token", "OTHR"))
        self.core.blocks[1] = {**block, "hash": point(501), "tx": [transaction(3)]}
        self.runtime.sweep(self.index)
        self.assertIsNone(self.index.get("token", "OTHR"))
        self.assertEqual(self.index.tip, (1, point(501)))

    def test_protection_requires_fresh_tip_proof_and_confirmed_unspent_coin(self):
        self.runtime.sweep(self.index)
        coins = [{"txid": point(1), "vout": 1}]
        self.assertFalse(self.runtime.protection(coins)["coins"][0]["protected"])
        self.core.blocks.append({"height": 1, "hash": point(500)})
        with self.assertRaises(Incomplete):
            self.runtime.protection(coins)
        self.core.blocks.pop()
        old_call = self.core.call
        self.core.call = lambda method, params: None if method == "gettxout" else old_call(method, params)
        self.assertTrue(self.runtime.protection(coins)["coins"][0]["protected"])

    def test_duplicate_writer_is_refused(self):
        with writer_lock(self.tmp.name):
            with self.assertRaises(ValueError):
                with writer_lock(self.tmp.name):
                    pass

    def test_no_signing_or_cookie_forwarding_to_an_external_host(self):
        with self.assertRaises(ValueError):
            Core("http://example.com", cookie="private.cookie")
        core = Core("http://127.0.0.1:1", gateway_token="x" * 64)
        for name in ("sendrawtransaction", "signrawtransactionwithwallet", "walletpassphrase", "stop"):
            with self.assertRaises(ValueError):
                core.call(name, [])

    def test_authenticated_api_rejects_bad_origins_and_stale_protection(self):
        self.runtime.sweep(self.index)
        token = "1" * 64
        server = Server(("127.0.0.1", 0), handler(self.runtime, token, {"127.0.0.1"}))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_port)
        auth = "Basic " + base64.b64encode(("reader:" + token).encode()).decode()
        try:
            with urlopen(base + "/status") as response:
                self.assertTrue(json.load(response)["observedSynchronized"])
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/v1/tokens")
            self.assertEqual(error.exception.code, 401)
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/status", headers={"Host": "evil.example"}))
            self.assertEqual(error.exception.code, 403)
            request = Request(base + "/v1/protection", method="POST", headers={"Authorization": auth},
                              data=json.dumps({"coins": [{"txid": point(1), "vout": 1}]}).encode())
            with urlopen(request) as response:
                self.assertTrue(json.load(response)["available"])
            self.core.blocks.append({"height": 1, "hash": point(500)})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 503)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == "__main__":
    unittest.main()
