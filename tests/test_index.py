import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from q20.index import Index
from q20 import listings, tickets
from q20.messages import Incomplete, decode, discover, op_return, single_push
from q20.rules import Rules
from q20.wire import Output, address, address_script, ctv, template


def point(n):
    return f"{n:064x}"


def owner(n):
    return b"\x52\x20" + bytes([n]) * 32


def coin(script=None, bits=10000):
    return {"value_bits": bits, "scriptPubKey": {"hex": (script or owner(1)).hex()}}


def record(op="deploy", tick="TEST", **fields):
    r = {"p": "qbit-20", "op": op, "tick": tick}
    r.update({"max": "1000", "lim": "100", "dec": "8"} if op == "deploy" else {"amt": "100"})
    r.update(fields)
    return r


def transaction(n, r=None, sender=1, destination=2, inputs=None, outputs=None, raw=None):
    vin = inputs or [{"txid": point(100000 + n), "vout": 0, "prevout": coin(owner(sender)),
                      "scriptSig": {"hex": ""}, "sequence": 0xFFFFFFFD,
                      "txinwitness": ["00", "20" + "01" * 32 + "b3", "c1"]}]
    outs = outputs if outputs is not None else [coin(owner(destination))]
    if r is not None or raw is not None:
        payload = raw if raw is not None else json.dumps(r, separators=(",", ":")).encode()
        outs = [coin(op_return(payload), 0)] + outs
    return {"txid": point(n), "vin": vin, "vout": outs, "version": 2, "locktime": 0}


def fixture_rules():
    value = deepcopy(Rules.load().value)
    value["id"] = "synthetic-unit-fixtures-not-a-network-profile"
    value["heights"] = {k: 0 for k in value["heights"]}
    return Rules(value)


class MessageTests(unittest.TestCase):
    def setUp(self):
        self.rules = Rules.load()

    def parse(self, value, height=180000):
        return decode(value if isinstance(value, bytes) else json.dumps(value).encode(), self.rules, height)

    def test_three_validation_levels(self):
        self.assertEqual(self.parse(b'{"p":').classification, "invalid-json")
        self.assertEqual(self.parse({"p": "brc-20"}).classification, "other-protocol")
        self.assertEqual(self.parse(record(amt=1, op="mint")).reason, "bad-amount")
        self.assertEqual(self.parse(record()).classification, "record")

    def test_utf8_and_json_not_javascript(self):
        for raw in (b"\xff", b'{"p":"qbit-20","op":NaN}', b'{"p":"qbit-20",}', b"// comment\n{}", b"\xef\xbb\xbf{}"):
            self.assertIn(self.parse(raw).classification, {"invalid-utf8", "invalid-json"})
        for value in ([], None, "qbit-20", 2, True):
            self.assertEqual(self.parse(value).classification, "other-json")

    def test_decimal_strings(self):
        for value in (1, True, None, "", "01", "-1", "+1", "1.0", "1e2", " 1", "١", "1\n"):
            with self.subTest(value=value):
                self.assertEqual(self.parse(record("mint", amt=value)).reason, "bad-amount")
        self.assertEqual(self.parse(record("mint", amt="0")).reason, "zero-amount")
        self.assertEqual(self.parse(record(max="9" * 100, lim="1")).classification, "record")

    def test_duplicates_last_wins_including_escaped_names(self):
        raw = b'{"p":"x","p":"qbit-20","op":"mint","tick":"TEST","amt":"0","a\\u006dt":"100"}'
        m = self.parse(raw)
        self.assertTrue(m.duplicates)
        self.assertEqual(m.record["amt"], "100")
        self.assertEqual(m.classification, "record")

    def test_activations_do_not_rewrite_history(self):
        self.assertEqual(self.parse(record(tick="ABC"), 166999).reason, "bad-tick")
        self.assertEqual(self.parse(record(tick="ABC"), 167000).classification, "record")
        self.assertEqual(self.parse(record(addr_mints="bad"), 172499).classification, "record")
        self.assertEqual(self.parse(record(addr_mints="bad"), 172500).reason, "bad-addr-mints")
        self.assertEqual(self.parse(record(gate="bad"), 160499).classification, "record")
        self.assertEqual(self.parse(record(gate="bad"), 160500).reason, "bad-mint-gate")
        self.assertEqual(self.parse(record(gate=None, addr_mints="bad")).reason, "bad-mint-gate")

    def test_only_first_op_return(self):
        outputs = [Output(0, b"\x6a"), Output(0, op_return(json.dumps(record()).encode()))]
        index, m = discover(outputs, self.rules, 180000)
        self.assertEqual(index, 0)
        self.assertEqual(m.classification, "invalid-carrier")

    def test_push_encodings_and_trailing_data(self):
        for payload in (b"x", b"x" * 76, b"x" * 256, b"x" * 65536):
            self.assertEqual(single_push(op_return(payload)), payload)
            self.assertIsNone(single_push(op_return(payload) + b"\x00"))
        self.assertEqual(single_push(b"\x6a\x4c\x01x"), b"x")
        for raw in (b"", b"\x6a\x00", b"\x6a\x51", b"\x6a\x4d\xff"):
            self.assertIsNone(single_push(raw))

    def test_addresses_match_published_sink(self):
        self.assertEqual(address(listings.SINK_SCRIPT, "qb"),
                         "qb1zyd2trtw796tar75xyhqd7eyjqhur6hpdakaw7j7gqfmes44t6rvstqx22t")
        for hrp in ("qb", "tq", "qbrt"):
            value = address(owner(1), hrp)
            self.assertEqual(address_script(value, hrp), owner(1))
            self.assertEqual(address_script(value.upper(), hrp), owner(1))
            with self.assertRaises(ValueError):
                address_script(value[:3].upper() + value[3:], hrp)
            with self.assertRaises(ValueError):
                address_script(value, "wrong")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "index.sqlite"
        self.rules = fixture_rules()
        self.index = Index(self.path, self.rules)
        self.n = 0

    def tearDown(self):
        self.index.close()
        self.tmp.cleanup()

    def add(self, *txs):
        h, old = self.index.tip
        h += 1
        self.index.apply({"height": h, "hash": self.rules.value["genesis"] if h == 0 else point(900000 + h),
                          "previousblockhash": old, "tx": list(txs) or [transaction(800000 + h)]})

    def event(self, txid):
        return next(e for e in self.index.history(100) if e["txid"] == point(txid) and e["op"] != "release")

    def opened(self, **fields):
        self.add(transaction(1, record(**fields)))
        for _ in range(59):
            self.add()

    def funded(self):
        self.opened()
        self.add(transaction(2, record("mint")))

    def listing(self, version="3", lots=1):
        r = record("transfer", bind="1", list={"v": version, "price": "9000", "salt": "00" * 16, "exp": "200"})
        if version == "5":
            r["list"]["lots"] = str(lots)
        m = decode(json.dumps(r).encode(), self.rules, self.index.tip[0] + 1)
        parsed = listings.terms(m, address(owner(1), "qb"), self.rules, self.index.tip[0] + 1)
        script = owner(5) if version == "5" else listings.listing_script(parsed, self.rules)
        outputs = ([coin(listings.SINK_SCRIPT, 3000)] if version == "5" else []) + [coin(script, 5000)]
        tx = transaction(3, r, outputs=outputs)
        return tx, parsed, script

    def test_mint_open_and_remainder(self):
        self.opened(max="150")
        self.add(transaction(2, record("mint")), transaction(3, record("mint")))
        self.assertTrue(self.event(2)["valid"])
        self.assertEqual(self.event(3)["reason"], "wrong-mint-amount")
        self.add(transaction(4, record("mint", amt="50")))
        self.assertEqual(self.index.balance(address(owner(1), "qb"), "TEST"), 150)
        self.add(transaction(5, record("mint", amt="1")))
        self.assertEqual(self.event(5)["reason"], "mint-finished")

    def test_too_early_first_deploy_and_unknown_fields(self):
        self.add(transaction(1, record(unknown="safe")), transaction(2, record()), transaction(3, record("mint")))
        self.assertEqual(self.event(2)["reason"], "tick-taken")
        self.assertEqual(self.event(3)["reason"], "mint-not-open")

    def test_invalid_does_not_consume_mint_cap(self):
        self.opened()
        self.add(transaction(2, record("mint", amt="1")), transaction(3, record("mint")), transaction(4, record("mint")))
        self.assertTrue(self.event(3)["valid"])
        self.assertEqual(self.event(4)["reason"], "address-block-cap")

    def test_twenty_valid_mints_per_tick(self):
        self.opened(max="10000")
        self.add(*(transaction(10 + i, record("mint"), sender=i + 1) for i in range(21)))
        self.assertEqual(self.event(30)["reason"], "tick-block-cap")
        self.assertEqual(self.index.get("token", "TEST")["minted"], "2000")

    def test_address_cap_across_ticks_and_lifetime(self):
        self.add(transaction(1, record(addr_mints="1")), transaction(2, record(tick="OTHR")))
        for _ in range(59):
            self.add()
        self.add(transaction(3, record("mint")), transaction(4, record("mint", tick="OTHR")))
        self.assertEqual(self.event(4)["reason"], "address-block-cap")
        self.add(transaction(5, record("mint")))
        self.assertEqual(self.event(5)["reason"], "address-lifetime-cap")

    def test_transfer_and_reorg_replay(self):
        self.funded()
        digest = self.index.state_digest()
        self.add(transaction(4, record("transfer")))
        self.assertEqual(self.index.balance(address(owner(2), "qb"), "TEST"), 100)
        self.index.rollback()
        self.assertEqual(self.index.state_digest(), digest)
        self.assertEqual(self.index.balance(address(owner(2), "qb"), "TEST"), 0)
        self.add(transaction(5, record("transfer"), destination=3))
        self.assertEqual(self.index.balance(address(owner(3), "qb"), "TEST"), 100)

    def test_record_lookalike_and_insufficient_balance_are_not_valid(self):
        self.opened()
        self.add(transaction(2, record("transfer")), transaction(3, raw=b'{"p":"QBIT-20"}'))
        self.assertEqual(self.event(2)["reason"], "insufficient-balance")
        self.assertEqual(self.event(3)["classification"], "other-protocol")

    def test_missing_prevout_rolls_back_whole_block(self):
        self.opened()
        tx = transaction(3, record("mint"), inputs=[{"txid": point(111), "vout": 0}])
        tip, digest = self.index.tip, self.index.state_digest()
        with self.assertRaises(Incomplete):
            self.add(transaction(2, record("mint")), tx)
        self.assertEqual(self.index.tip, tip)
        self.assertEqual(self.index.state_digest(), digest)

    def test_network_profile_is_immutable_on_reopen(self):
        self.index.close()
        value = deepcopy(self.rules.value)
        value["heights"]["bind"] = 12
        with self.assertRaises(ValueError):
            Index(self.path, Rules(value))
        self.index = Index(self.path, self.rules)

    def test_real_bound_coin_is_protected_and_ordinary_balance_is_not(self):
        self.funded()
        tx, terms, script = self.listing()
        self.add(tx)
        self.assertTrue(self.index.protection([{"txid": point(3), "vout": 1}])[0]["protected"])
        self.assertFalse(self.index.protection([{"txid": point(2), "vout": 1}])[0]["protected"])
        self.assertEqual(self.index.balance(address(owner(1), "qb"), "TEST"), 0)
        buy = transaction(4, inputs=[{"txid": point(3), "vout": 1, "txinwitness": ["00"]},
                                   transaction(600, sender=2)["vin"][0]],
                          outputs=[{"value_bits": o.bits, "scriptPubKey": {"hex": o.script.hex()}}
                                   for o in listings.buy_outputs(terms, self.rules)])
        buy["vin"][0]["prevout"] = coin(script, 5000)
        self.add(buy)
        self.assertEqual(self.index.balance(address(owner(2), "qb"), "TEST"), 100)
        self.assertFalse(self.index.protection([{"txid": point(3), "vout": 1}])[0]["protected"])
        self.index.rollback()
        self.assertIsNotNone(self.index.get("bound", point(3) + ":1"))

    def test_duplicate_keys_disqualify_bind_but_transfer_still_counts(self):
        self.funded()
        tx, parsed, script = self.listing()
        raw = json.dumps(record("transfer", bind="1", list=parsed["list"])).replace('"bind": "1"', '"bind":"0","bind":"1"').encode()
        self.add(transaction(3, raw=raw, outputs=[coin(script, 5000)]))
        self.assertIsNone(self.index.get("bound", point(3) + ":1"))
        self.assertEqual(self.index.balance(address(script, "qb"), "TEST"), 100)

    def test_sink_ignores_invalid_bind_without_debit(self):
        self.funded()
        self.add(transaction(3, record("transfer"), outputs=[coin(listings.SINK_SCRIPT, 3000)]))
        self.assertEqual(self.event(3)["reason"], "sink-not-bound")
        self.assertEqual(self.index.balance(address(owner(1), "qb"), "TEST"), 100)

    def test_v5_partial_sale_through_seller_sells_but_returns_rest(self):
        self.funded()
        tx, terms, script = self.listing("5", 2)
        self.add(tx)
        self.assertIsNotNone(self.index.get("bound", point(3) + ":2"))
        vin = [{"txid": point(3), "vout": 2, "prevout": coin(script, 5000),
                "scriptSig": {"hex": ""}, "sequence": 0xFFFFFFFD, "txinwitness": ["00", "01", "c1"]},
               transaction(600, sender=2)["vin"][0]]
        outs = listings.buy_outputs(terms, self.rules, 1, owner(6))
        buy = transaction(4, inputs=vin, outputs=[coin(o.script, o.bits) for o in outs])
        self.add(buy)
        self.assertEqual(self.index.balance(address(owner(2), "qb"), "TEST"), 50)
        self.assertEqual(self.index.balance(address(owner(1), "qb"), "TEST"), 50)
        self.assertIsNone(self.index.get("bound", point(4) + ":1"))

    def test_v5_buy_leaf_rebinds_rest_and_same_block_spend(self):
        self.funded()
        tx, terms, script = self.listing("5", 2)
        self.add(tx)
        vin = [{"txid": point(3), "vout": 2, "prevout": coin(script, 5000),
                "scriptSig": {"hex": ""}, "sequence": 0xFFFFFFFD}, transaction(600, sender=2)["vin"][0]]
        outs = listings.buy_outputs(terms, self.rules, 1, owner(6))
        buy = transaction(4, inputs=vin, outputs=[coin(o.script, o.bits) for o in outs])
        digest = ctv(buy, outs)
        buy["vin"][0]["txinwitness"] = [(b"\x20" + digest + b"\xbb").hex(),
            (b"\xc1" + listings.refund_leaf(terms, self.rules) + listings.salt_branch(terms, self.rules, 2)).hex()]
        self.add(buy)
        rest = self.index.get("bound", point(4) + ":1")
        self.assertEqual(rest["lots"], 1)
        self.assertEqual(rest["root"], point(3) + ":2")
        self.assertEqual(self.index.balance(address(owner(1), "qb"), "TEST"), 0)

    def test_buy_ticket_recipient_and_missing_witness_fail_closed(self):
        self.funded()
        tx, terms, script = self.listing()
        self.add(tx)
        payer = transaction(600, sender=2)["vin"][0]
        ticket_script = b"\x20" + bytes([7]) * 32 + b"\x75\x20" + b"x" * 32 + b"\xbb\x75\x20" + b"k" * 32 + b"\xb3"
        payer["txinwitness"] = ["00", ticket_script.hex(), "c1", "50abcd"]
        vin = [{"txid": point(3), "vout": 1, "prevout": coin(script, 5000)}, payer]
        buy = transaction(4, inputs=vin, outputs=[coin(o.script, o.bits) for o in listings.buy_outputs(terms, self.rules)])
        self.add(buy)
        self.assertEqual(self.index.balance(address(owner(7), "qb"), "TEST"), 100)
        self.index.rollback()
        payer.pop("txinwitness")
        tip = self.index.tip
        with self.assertRaises(Incomplete):
            self.add(buy)
        self.assertEqual(self.index.tip, tip)

    def test_locked_mint_verifier_is_required_not_treated_as_invalid(self):
        self.add(transaction(1, record(gate="11" * 32, gate_end="10")))
        signature = base64.urlsafe_b64encode(bytes(3680)).decode().rstrip("=")
        payee = address(owner(3), "qb")
        ticket = f"10.{'01' * 8}.0.{payee}.{signature}"
        tx = transaction(2, record("mint", tkt=ticket))
        tip = self.index.tip
        with self.assertRaises(Incomplete):
            self.add(tx)
        self.assertEqual(self.index.tip, tip)
        self.index.verify = lambda *args: False
        self.add(tx)
        self.assertEqual(self.event(2)["reason"], "bad-mint-ticket")
        self.index.verify = lambda *args: True
        self.add(transaction(3, record("mint", tkt=ticket)))
        self.assertEqual(self.index.balance(address(owner(1), "qb"), "TEST"), 100)
        self.assertEqual(self.index.get("nonce", "TEST:" + "01" * 8), 10)
        self.index.rollback()
        self.assertIsNone(self.index.get("nonce", "TEST:" + "01" * 8))

    def test_malformed_listing_fields_fall_back_without_crashing(self):
        self.funded()
        for n, invalid in enumerate(({}, [], None, 2, True, "unknown"), 10):
            tx = transaction(n, record("transfer", bind="1", list={"v": invalid}), destination=1)
            self.add(tx)
            self.assertTrue(self.event(n)["valid"])
            self.assertEqual(self.index.balance(address(owner(1), "qb"), "TEST"), 100)

    def test_mint_conservation_through_transfers_and_rollback(self):
        import random
        self.funded()
        rng = random.Random(20)
        for n in range(100, 150):
            sender, recipient = rng.randrange(1, 6), rng.randrange(1, 6)
            amount = str(rng.randrange(1, 101))
            before = self.index.state_digest()
            self.add(transaction(n, record("transfer", amt=amount), sender=sender, destination=recipient))
            balances = sum(int(value) for _, value in self.index.rows("balance"))
            self.assertEqual(balances, 100)
            if n % 7 == 0:
                self.index.rollback()
                self.assertEqual(self.index.state_digest(), before)

    def test_late_bind_is_still_bound(self):
        self.funded()
        r = record("transfer", bind="1", list={"v":"3", "price":"9000", "salt":"00"*16, "exp":"1"})
        m = decode(json.dumps(r).encode(), self.rules, self.index.tip[0]+1)
        t = listings.terms(m, address(owner(1), "qb"), self.rules, self.index.tip[0]+1)
        script = listings.listing_script(t, self.rules)
        self.add(transaction(3, r, outputs=[coin(script, 50000)]))
        self.assertIsNotNone(self.index.get("bound", point(3)+":1"))

    def test_nonce_and_fee_failures_do_not_occupy_mint_slots(self):
        self.add(transaction(1, record(gate="11"*32, gate_end="10")))
        signature = base64.urlsafe_b64encode(bytes(3680)).decode().rstrip("=")
        payee = address(owner(3), "qb")
        ticket = f"10.{'01'*8}.3000.{payee}.{signature}"
        self.index.verify = lambda *args: True
        self.add(transaction(2, record("mint", tkt=ticket)),
                 transaction(3, record("mint", tkt=ticket), outputs=[coin(owner(3), 3000)]))
        self.assertEqual(self.event(2)["reason"], "mint-fee-unpaid")
        self.assertTrue(self.event(3)["valid"])
        self.add(transaction(4, record("mint", tkt=ticket), outputs=[coin(owner(3), 3000)]))
        self.assertEqual(self.event(4)["reason"], "mint-ticket-used")

    def test_large_token_balances_survive_mint_transfer_and_undo(self):
        value = "9"*5000
        self.opened(max=value, lim=value)
        self.add(transaction(2, record("mint", amt=value)))
        self.assertEqual(self.index.get("token", "TEST")["minted"], value)
        before = self.index.state_digest()
        self.add(transaction(3, record("transfer", amt=value)))
        self.assertEqual(self.index.get("balance", address(owner(2), "qb")+":TEST"), value)
        self.index.rollback()
        self.assertEqual(self.index.state_digest(), before)

    def test_unrelated_artwork_is_not_duplicated_in_token_index(self):
        self.add(transaction(1, raw=b"\xff"*100000))
        event = self.event(1)
        self.assertEqual(event["classification"], "invalid-utf8")
        self.assertEqual(event["payloadBytes"], 100000)
        self.assertNotIn("payloadHex", event)
        self.assertEqual(len(event["payloadSha256"]), 64)


if __name__ == "__main__":
    unittest.main()
