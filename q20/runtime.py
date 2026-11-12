"""Single-writer synchronization. At tip, check once per minute and do no rescans."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import threading
import time

from . import __version__
from .index import Index
from .messages import Incomplete
from .wire import hash_id


@contextmanager
def writer_lock(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Use an independent real directory for q20 data")
    path = directory / ".q20-writer.lock"
    if path.is_symlink():
        raise ValueError("Linked writer lock refused")
    stream = path.open("a+b")
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise ValueError("Another q20 process already owns this index") from exc
    try:
        yield
    finally:
        stream.close()


class Runtime:
    def __init__(self, directory, rules, core, verify=None):
        self.directory, self.rules, self.core, self.verify = Path(directory), rules, core, verify
        self.path = self.directory / "q20.sqlite"
        self.stop = threading.Event()
        self.mutex = threading.RLock()
        self.observed = {"available": False, "observedSynchronized": False, "message": "Connecting to Core"}

    def checkpoint(self):
        with self.mutex:
            return dict(self.observed)

    def reader(self):
        if not self.path.is_file():
            raise Incomplete("q20 index is initializing")
        # Reading must never create, migrate, repair or write to an index.
        import sqlite3
        result = object.__new__(Index)
        result.rules, result.verify, result.height = self.rules, None, None
        result.db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        result.db.execute("PRAGMA query_only=ON")
        expected = result.db.execute("SELECT value FROM identity WHERE singleton=1").fetchone()
        if expected is None or json.loads(expected[0])["fingerprint"] != self.rules.fingerprint:
            result.close()
            raise Incomplete("Index identity mismatch")
        return result

    def proof(self, index, info=None):
        info = self.core.identity(self.rules) if info is None else info
        height, tip_hash = index.tip
        ready = (height >= 0 and info.get("blocks") == info.get("headers") == height
                 and info.get("initialblockdownload") is False
                 and self.core.call("getblockhash", [height]) == tip_hash)
        return info, ready

    def status(self, index, info):
        height, tip_hash = index.tip
        _, ready = self.proof(index, info)
        counters = index.get("stats", "events", {"messages": 0, "validOperations": 0})
        tokens = index.db.execute("SELECT count(*) FROM state WHERE kind='token'").fetchone()[0]
        bound = index.db.execute("SELECT count(*) FROM state WHERE kind='bound'").fetchone()[0]
        return {"app": "q20", "version": __version__, "protocol": "qbit-20", "network": self.rules.network,
                "rules": self.rules.value["id"], "rulesFingerprint": self.rules.fingerprint,
                "indexHeight": height, "indexHash": tip_hash, "nodeHeight": info.get("blocks"),
                "headers": info.get("headers"), **counters,
                "tokens": tokens, "boundOutputs": bound, "available": True,
                "observedSynchronized": ready, "observedAt": int(time.time()),
                "message": "Index is synchronized" if ready else "Index is catching up"}

    def sweep(self, index):
        info = self.core.identity(self.rules)
        node_height = info.get("blocks")
        if type(node_height) is not int or node_height < 0:
            raise Incomplete("Core tip is unavailable")
        while index.tip[0] >= 0:
            height, block_hash = index.tip
            if height <= node_height and self.core.call("getblockhash", [height]) == block_hash:
                break
            index.rollback()
        target = node_height
        last_report = 0
        next_hash = None
        while index.tip[0] < target and not self.stop.is_set():
            height = index.tip[0] + 1
            block_hash = hash_id(next_hash or self.core.call("getblockhash", [height]))
            block = self.core.call("getblock", [block_hash, 3])
            if not isinstance(block, dict) or block.get("hash") != block_hash or block.get("height") != height:
                raise Incomplete("Core returned the wrong block")
            index.apply(block, self.core.prevout)
            next_hash = block.get("nextblockhash")
            if time.monotonic() - last_report >= 5:
                with self.mutex:
                    self.observed = {"app": "q20", "network": self.rules.network, "version": __version__,
                                     "available": True, "observedSynchronized": False,
                                     "indexHeight": height, "nodeHeight": target, "message": "Index is catching up"}
                last_report = time.monotonic()
        info = self.core.identity(self.rules)
        state = self.status(index, info)
        with self.mutex:
            self.observed = state
        return state

    def run(self):
        with writer_lock(self.directory):
            if self.path.is_symlink():
                raise ValueError("Linked index refused")
            index = Index(self.path, self.rules, self.verify)
            try:
                while not self.stop.is_set():
                    try:
                        state = self.sweep(index)
                        print(json.dumps({"event": "q20-checkpoint", **state}), flush=True)
                        # Continue catch-up immediately. A quiet tip sleeps a full minute.
                        if state["indexHeight"] < state["nodeHeight"]:
                            continue
                        self.stop.wait(60)
                    except Incomplete as exc:
                        with self.mutex:
                            self.observed = {"app": "q20", "version": __version__, "network": self.rules.network,
                                             "available": False, "observedSynchronized": False,
                                             "indexHeight": index.tip[0], "message": str(exc)}
                        print(json.dumps({"event": "q20-waiting", **self.checkpoint()}), flush=True)
                        self.stop.wait(60)
            finally:
                index.close()

    def protection(self, coins):
        index = self.reader()
        try:
            index.db.execute("BEGIN")
            info, ready = self.proof(index)
            if not ready:
                raise Incomplete("Token protection unavailable while q20 is behind the verified Core tip")
            values = index.protection(coins)
            for coin, item in zip(coins, values):
                current = self.core.call("gettxout", [coin["txid"], coin["vout"], True])
                if not isinstance(current, dict) or current.get("confirmations", 0) <= 0:
                    item.update(protected=True, reason="unconfirmed-or-spent-output")
            if not self.proof(index)[1]:
                raise Incomplete("Chain changed during token protection check")
            return {"available": True, "network": self.rules.network, "rulesFingerprint": self.rules.fingerprint,
                    "indexHeight": index.tip[0], "indexHash": index.tip[1], "coins": values,
                    "scope": "QBIT-20 bound outputs only; combine with LEAP/PINS/qord protection"}
        finally:
            index.close()
