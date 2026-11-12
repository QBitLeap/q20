"""Immutable, height-dependent rules: changing a profile requires a new index."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path


@dataclass(frozen=True)
class Rules:
    value: dict

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path else Path(__file__).with_name("rules") / "mainnet.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        required = {"bind", "bind2", "bind3", "gate", "bind5", "buyTicket", "fastGate",
                    "feeTicket", "threeTick", "addressMints"}
        if set(value["heights"]) != required or any(type(x) is not int or x < 0 for x in value["heights"].values()):
            raise ValueError("Explicit activation height required for each rule")
        if value.get("network") not in {"mainnet", "testnet4", "signet", "regtest"}:
            raise ValueError("Unknown network")
        if value.get("listingsV5Rule") != 2:
            raise ValueError("Only the corrected version 5 release rule is supported")
        if len(bytes.fromhex(value["genesis"])) != 32:
            raise ValueError("Explicit genesis required")
        return cls(value)

    @property
    def fingerprint(self):
        return sha256(json.dumps(self.value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def network(self):
        return self.value["network"]

    def active(self, feature, height):
        return height >= self.value["heights"][feature]
