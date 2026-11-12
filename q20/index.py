"""Transactional block-order ledger with durable per-row undo and message evidence."""

from contextlib import contextmanager
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from . import listings, tickets
from .json_data import amount as number, amount_text
from .messages import Incomplete, discover
from .wire import address, hash_id, output, p2mr, witness


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=lambda x: str(x) if isinstance(x, Decimal) else _unsupported(x))


def _unsupported(value):
    raise TypeError(type(value).__name__)


class Index:
    def __init__(self, path, rules, verify=None):
        self.rules, self.verify = rules, verify
        existing = str(path) != ":memory:" and Path(path).is_file() and Path(path).stat().st_size > 0
        self.db = sqlite3.connect(str(path), timeout=10)
        if existing:
            marked = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='identity'").fetchone()
            if not marked:
                self.db.close()
                raise ValueError("Existing unmarked database refused; use a new q20 data directory")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS blocks (height INTEGER PRIMARY KEY, hash TEXT UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS state (kind TEXT, key TEXT, value TEXT NOT NULL, PRIMARY KEY(kind,key));
          CREATE TABLE IF NOT EXISTS undo (height INTEGER, kind TEXT, key TEXT, before TEXT,
                                         PRIMARY KEY(height,kind,key));
          CREATE TABLE IF NOT EXISTS events (height INTEGER, position INTEGER, txid TEXT, seq INTEGER,
                                           value TEXT NOT NULL, PRIMARY KEY(height,position,seq));
          CREATE INDEX IF NOT EXISTS events_txid ON events(txid);
        """)
        expected = encode({"format": 1, "protocol": "qbit-20", "rules": rules.value,
                           "fingerprint": rules.fingerprint})
        row = self.db.execute("SELECT value FROM identity WHERE singleton=1").fetchone()
        if row is not None and row[0] != expected:
            self.db.close()
            raise ValueError("Index belongs to another network/rules profile; use a separate data directory")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO identity VALUES (1,?)", (expected,))
        self.height = None

    def close(self):
        self.db.close()

    @property
    def tip(self):
        return self.db.execute("SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1").fetchone() or (-1, None)

    def get(self, kind, key, default=None):
        row = self.db.execute("SELECT value FROM state WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, kind, key, value):
        if self.height is None:
            raise RuntimeError("State changes require a block transaction")
        old = self.db.execute("SELECT value FROM state WHERE kind=? AND key=?", (kind, key)).fetchone()
        self.db.execute("INSERT OR IGNORE INTO undo VALUES (?,?,?,?)",
                        (self.height, kind, key, old[0] if old else None))
        if value is None:
            self.db.execute("DELETE FROM state WHERE kind=? AND key=?", (kind, key))
        else:
            self.db.execute("INSERT INTO state VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET value=excluded.value",
                            (kind, key, encode(value)))

    def rows(self, kind):
        return [(k, json.loads(v)) for k, v in self.db.execute(
            "SELECT key,value FROM state WHERE kind=? ORDER BY key", (kind,))]

    def balance(self, owner, tick):
        return number(self.get("balance", owner + ":" + tick, "0"))

    def credit(self, owner, tick, amount):
        updated = self.balance(owner, tick) + amount
        if updated < 0:
            raise Incomplete("Ledger attempted a negative balance")
        self.put("balance", owner + ":" + tick, amount_text(updated) if updated else None)

    def state_digest(self):
        # q20's own digest format; not the marketplace's undocumented digest serialization.
        digest = sha256()
        for row in self.db.execute("SELECT kind,key,value FROM state ORDER BY kind,key"):
            digest.update((encode(row) + "\n").encode())
        return digest.hexdigest()

    def rollback(self):
        height, old_hash = self.tip
        if height < 0:
            return
        with self.db:
            for kind, key, before in self.db.execute("SELECT kind,key,before FROM undo WHERE height=?", (height,)).fetchall():
                if before is None:
                    self.db.execute("DELETE FROM state WHERE kind=? AND key=?", (kind, key))
                else:
                    self.db.execute("INSERT INTO state VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET value=excluded.value",
                                    (kind, key, before))
            self.db.execute("DELETE FROM undo WHERE height=?", (height,))
            self.db.execute("DELETE FROM events WHERE height=?", (height,))
            self.db.execute("DELETE FROM blocks WHERE height=?", (height,))

    def apply(self, block, resolve=None):
        """Apply a full, Core-validated block; missing evidence rolls the entire block back."""
        height, block_hash = block.get("height"), hash_id(block.get("hash"))
        tip_height, tip_hash = self.tip
        if type(height) is not int or height != tip_height + 1:
            raise Incomplete("Blocks must be contiguous from genesis")
        if height == 0:
            if block_hash != self.rules.value["genesis"]:
                raise Incomplete("Wrong-chain genesis")
        elif block.get("previousblockhash") != tip_hash:
            raise Incomplete("Previous block differs; rollback to the common ancestor first")
        transactions = block.get("tx")
        if not isinstance(transactions, list) or not transactions or any(not isinstance(t, dict) for t in transactions):
            raise Incomplete("Full decoded transactions required")
        same_block, ticket_sensitive, v5_sensitive = {}, set(), set()
        seen_txids, minted_addresses, tick_mints = set(), set(), {}
        self.height = height
        try:
            with self.db:
                counters = self.get("stats", "events", {"messages": 0, "validOperations": 0})
                changed_counters = False
                for position, tx in enumerate(transactions):
                    txid = hash_id(tx.get("txid"))
                    if txid in seen_txids:
                        raise Incomplete("Duplicate transaction in block")
                    seen_txids.add(txid)
                    inputs, values = tx.get("vin"), tx.get("vout")
                    if not isinstance(inputs, list) or not inputs or not isinstance(values, list) or not values:
                        raise Incomplete("Complete transaction inputs and outputs required")
                    outputs = [output(x) for x in values]
                    data_index, message = discover(outputs, self.rules, height)
                    points = []
                    for vin in inputs:
                        if "coinbase" in vin:
                            points.append(None)
                        else:
                            prev_tx = hash_id(vin.get("txid"))
                            vout = vin.get("vout")
                            if type(vout) is not int or vout < 0:
                                raise Incomplete("Missing prevout index")
                            points.append(f"{prev_tx}:{vout}")
                    bound = [self.get("bound", p) if p else None for p in points]
                    cache = {}

                    def previous(i):
                        if i >= len(inputs) or points[i] is None:
                            return None
                        if i in cache:
                            return cache[i]
                        point = points[i]
                        if point in same_block:
                            value = same_block[point]
                        elif isinstance(inputs[i].get("prevout"), dict):
                            value = output(inputs[i]["prevout"])
                        elif resolve is not None:
                            value = output(resolve(inputs[i]["txid"], inputs[i]["vout"]))
                        else:
                            raise Incomplete("Prevout evidence missing; cannot infer sender/buyer")
                        cache[i] = value
                        return value

                    if (self.rules.active("buyTicket", height) and len(inputs) > 1
                            and (bound[0] is not None or points[0] in ticket_sensitive)):
                        if p2mr(previous(1).script):
                            witness(inputs[1])
                    if (self.rules.active("bind5", height) and
                            (any(c is not None and c["terms"]["version"] == "5" for c in bound)
                             or any(p in v5_sensitive for p in points if p))):
                        from .wire import ctv
                        ctv(tx, outputs)
                        for i, (vin, point) in enumerate(zip(inputs, points)):
                            if point is not None and ((bound[i] is not None and bound[i]["terms"]["version"] == "5")
                                                      or point in v5_sensitive and p2mr(previous(i).script)):
                                witness(vin)
                    sequence = 0

                    def event(value):
                        nonlocal sequence, changed_counters
                        value.update(height=height, blockHash=block_hash, transactionIndex=position, txid=txid)
                        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (height, position, txid, sequence, encode(value)))
                        sequence += 1
                        counters["messages"] += value["op"] not in {"release", "rebind"}
                        counters["validOperations"] += value.get("valid") is True
                        changed_counters = True

                    for input_index, coin in enumerate(bound):
                        if coin is None:
                            continue
                        prevouts = [previous(i) if i < 2 else None for i in range(len(inputs))]
                        sold, recipient, rest, via = listings.release(
                            coin, input_index, tx, outputs, prevouts, self.rules, height)
                        t = coin["terms"]
                        per_lot = number(t["amount"]) // t["lots"]
                        self.credit(recipient, t["tick"], sold * per_lot)
                        self.put("bound", points[input_index], None)
                        extra = {}
                        if len(inputs) > 1 and prevouts[1] is not None:
                            payer = address(prevouts[1].script, self.rules.value["hrp"])
                            if payer is not None and payer != recipient:
                                extra["payer"] = payer
                        leftover = coin["lots"] - sold
                        if leftover and rest is None:
                            self.credit(t["seller"], t["tick"], leftover * per_lot)
                            extra["back"] = leftover
                        event({"op": "release", "valid": True, "sender": coin["address"], "receiver": recipient,
                               "tick": t["tick"], "amt": amount_text(sold * per_lot), "lots": sold, "via": via,
                               "outpoint": points[input_index], **extra})
                        if leftover and rest is not None:
                            point = f"{txid}:{rest}"
                            updated = {**coin, "lots": leftover, "height": height,
                                       "address": address(outputs[rest].script, self.rules.value["hrp"])}
                            self.put("bound", point, updated)
                            event({"op": "rebind", "valid": True, "outpoint": point, "lots": leftover,
                                   "tick": t["tick"], "amt": amount_text(leftover * per_lot)})

                    if data_index is not None:
                        result = {"op": "message", "classification": message.classification,
                                  "reason": message.reason, "valid": False,
                                  "dataOutput": data_index, "payloadBytes": len(message.payload),
                                  "payloadSha256": sha256(message.payload).hexdigest(),
                                  "scriptSha256": sha256(outputs[data_index].script).hexdigest(),
                                  "duplicateKeys": message.duplicates}
                        # q20 is not another artwork cache. Preserve recognized QBIT-20
                        # evidence in full; unrelated binary/JSON has size/hash + chain identity.
                        if message.record is not None:
                            result.update(payloadHex=message.payload.hex(), scriptHex=outputs[data_index].script.hex())
                        if message.classification == "record":
                            first = previous(0)
                            sender = address(first.script, self.rules.value["hrp"]) if first is not None else None
                            result.update(op=message.record["op"], tick=message.record["tick"], sender=sender)
                            if sender is None:
                                result["reason"] = "non-p2mr-sender"
                            else:
                                result.update(self.record(message, sender, outputs, txid, height,
                                                          minted_addresses, tick_mints))
                        event(result)
                    carries = data_index is not None and message.classification != "invalid-carrier"
                    may_v5 = isinstance(message.record, dict) and isinstance(message.record.get("list"), dict) and message.record["list"].get("v") == "5"
                    for i, value in enumerate(outputs):
                        point = f"{txid}:{i}"
                        same_block[point] = value
                        if carries or any(bound):
                            ticket_sensitive.add(point)
                        if may_v5 or any(c is not None and c["terms"]["version"] == "5" for c in bound):
                            v5_sensitive.add(point)
                if changed_counters:
                    self.put("stats", "events", counters)
                self.db.execute("INSERT INTO blocks VALUES (?,?)", (height, block_hash))
        finally:
            self.height = None

    def record(self, message, sender, outputs, txid, height, minted_addresses, tick_mints):
        r, rules = message.record, self.rules
        tick, op = r["tick"], r["op"]
        token = self.get("token", tick)
        if op == "deploy":
            if token is not None:
                return {"reason": "tick-taken"}
            gate = r.get("gate") if rules.active("gate", height) else None
            delay = 1 if gate and rules.active("fastGate", height) else 60
            value = {"max": r["max"], "lim": r["lim"], "minted": "0", "dec": "8",
                     "height": height, "txid": txid, "open": height + delay,
                     "addr_mints": int(r["addr_mints"]) if rules.active("addressMints", height) and "addr_mints" in r else 100,
                     "gate": gate, "gate_end": int(r["gate_end"]) if gate else None,
                     "feeTicket": bool(gate and rules.active("feeTicket", height))}
            self.put("token", tick, value)
            return {"valid": True, "reason": "", "mintOpen": value["open"]}
        if token is None:
            return {"reason": "not-deployed"}
        amount = number(r["amt"])
        if op == "mint":
            if height < token["open"]:
                return {"reason": "mint-not-open"}
            left = number(token["max"]) - number(token["minted"])
            if left <= 0:
                return {"reason": "mint-finished"}
            if amount != min(left, number(token["lim"])):
                return {"reason": "wrong-mint-amount"}
            ticket = None
            if token["gate"] and height < token["open"] + token["gate_end"]:
                if type(r.get("tkt")) is not str:
                    return {"reason": "no-mint-ticket"}
                ticket = tickets.parse(r["tkt"], token["feeTicket"], rules)
                if ticket is None:
                    return {"reason": "bad-mint-ticket"}
                if not height <= ticket["exp"] <= height + 100:
                    return {"reason": "mint-ticket-expired"}
                used = self.get("nonce", tick + ":" + ticket["nonce"], -1)
                if used >= height:
                    return {"reason": "mint-ticket-used"}
                if "fee" in ticket and sum(o.bits for o in outputs if o.script == ticket["script"]) < ticket["fee"]:
                    return {"reason": "mint-fee-unpaid"}
            count_key = tick + ":" + sender
            count = self.get("mintCount", count_key, 0)
            if sender in minted_addresses:
                return {"reason": "address-block-cap"}
            if count >= token["addr_mints"]:
                return {"reason": "address-lifetime-cap"}
            if tick_mints.get(tick, 0) >= 20:
                return {"reason": "tick-block-cap"}
            if ticket is not None:
                if self.verify is None:
                    raise Incomplete("Mint ticket requires the Qbit bounded30 signature verifier")
                valid = self.verify(bytes.fromhex(token["gate"]), tickets.digest(ticket, rules, tick, sender), ticket["signature"])
                if type(valid) is not bool:
                    raise Incomplete("Signature verifier did not return a boolean")
                if not valid:
                    return {"reason": "bad-mint-ticket"}
                self.put("nonce", tick + ":" + ticket["nonce"], ticket["exp"])
            self.credit(sender, tick, amount)
            self.put("token", tick, {**token, "minted": amount_text(number(token["minted"]) + amount)})
            self.put("mintCount", count_key, count + 1)
            minted_addresses.add(sender)
            tick_mints[tick] = tick_mints.get(tick, 0) + 1
            return {"valid": True, "reason": "", "amt": r["amt"], "receiver": sender}
        first = next((o for o in outputs if o.script[:1] != b"\x6a"), None)
        receiver = address(first.script, rules.value["hrp"]) if first is not None else None
        if receiver is None:
            return {"reason": "non-p2mr-receiver"}
        if self.balance(sender, tick) < amount:
            return {"reason": "insufficient-balance"}
        binding, sink = listings.bind(message, sender, outputs, rules, height)
        if sink and binding is None:
            return {"reason": "sink-not-bound"}
        self.credit(sender, tick, -amount)
        if binding is None:
            self.credit(receiver, tick, amount)
            return {"valid": True, "reason": "", "receiver": receiver, "amt": r["amt"]}
        vout, parsed = binding
        point = f"{txid}:{vout}"
        coin = {"terms": parsed, "address": address(outputs[vout].script, rules.value["hrp"]),
                "lots": parsed["lots"], "root": point, "listed": height, "height": height}
        self.put("bound", point, coin)
        return {"valid": True, "reason": "", "bound": point, "amt": r["amt"], "receiver": None}

    def history(self, limit=100, offset=0):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT value FROM events ORDER BY height DESC,position DESC,seq DESC LIMIT ? OFFSET ?", (limit, offset))]

    def protection(self, coins):
        """A caller must independently establish current node/index identity before using this."""
        result = []
        for coin in coins:
            point = f'{hash_id(coin["txid"])}:{coin["vout"]}'
            bound = self.get("bound", point)
            result.append({"outpoint": point, "protected": bound is not None,
                           "reason": "qbit20-bound-listing" if bound is not None else None,
                           "tick": bound["terms"]["tick"] if bound is not None else None})
        return result
