"""Exact integer transaction values, bech32m P2MR addresses and CTV templates."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
import struct

from .messages import Incomplete

ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
ANCHOR = bytes.fromhex("51024e73")
MAX_MONEY = 21000000000000000


def compact(n):
    if n < 253:
        return bytes([n])
    if n <= 65535:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def tagged(tag, value):
    h = sha256(tag.encode("ascii")).digest()
    return sha256(h + h + value).digest()


def leaf(script):
    return tagged("P2MRLeaf", b"\xc0" + compact(len(script)) + script)


def branch(a, b):
    return tagged("P2MRBranch", b"".join(sorted((a, b))))


def p2mr(script):
    return len(script) == 34 and script[:2] == b"\x52\x20"


def polymod(values):
    value = 1
    for item in values:
        top = value >> 25
        value = (value & 0x1FFFFFF) << 5 ^ item
        for i, generator in enumerate((0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)):
            if top >> i & 1:
                value ^= generator
    return value


def expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def convert(values, source, target, pad):
    acc = bits = 0
    result = []
    for value in values:
        if value < 0 or value >> source:
            raise ValueError("Invalid bech32 value")
        acc = ((acc << source) | value) & ((1 << (source + target - 1)) - 1)
        bits += source
        while bits >= target:
            bits -= target
            result.append(acc >> bits & ((1 << target) - 1))
    if pad and bits:
        result.append(acc << (target - bits) & ((1 << target) - 1))
    elif not pad and (bits >= source or acc << (target - bits) & ((1 << target) - 1)):
        raise ValueError("Noncanonical bech32 padding")
    return result


def address(script, hrp):
    if not p2mr(script):
        return None
    data = [2] + convert(script[2:], 8, 5, True)
    checksum = polymod(expand(hrp) + data + [0] * 6) ^ 0x2BC830A3
    return hrp + "1" + "".join(ALPHABET[x] for x in data + [(checksum >> 5 * (5 - i)) & 31 for i in range(6)])


def address_script(value, hrp):
    if (type(value) is not str or len(value) > 90 or
            not (value.islower() or value.isupper())):
        raise ValueError("Invalid P2MR address case")
    value = value.lower()
    pos = value.rfind("1")
    if value[:pos] != hrp or pos < 1:
        raise ValueError("Wrong-network address")
    try:
        data = [ALPHABET.index(x) for x in value[pos + 1:]]
    except ValueError as exc:
        raise ValueError("Invalid bech32 alphabet") from exc
    if len(data) < 7 or data[0] != 2 or polymod(expand(hrp) + data) != 0x2BC830A3:
        raise ValueError("Invalid P2MR bech32m checksum/version")
    program = bytes(convert(data[1:-6], 5, 8, False))
    if len(program) != 32:
        raise ValueError("Invalid P2MR program")
    return b"\x52\x20" + program


def hex_bytes(value):
    if type(value) is not str or len(value) % 2 or re.fullmatch(r"[0-9a-fA-F]*", value) is None:
        raise Incomplete("Missing or malformed transaction hex field")
    return bytes.fromhex(value)


def hash_id(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise Incomplete("Missing or malformed transaction/block hash")
    return value


@dataclass(frozen=True)
class Output:
    bits: int
    script: bytes

    def serialize(self):
        return struct.pack("<Q", self.bits) + compact(len(self.script)) + self.script


def output(value):
    if "value_bits" in value:
        bits = value["value_bits"]
        if type(bits) is not int:
            raise Incomplete("Output value_bits must be an integer")
    else:
        try:
            amount = Decimal(str(value["value"])) * 100000000
            if not amount.is_finite() or amount != amount.to_integral_value():
                raise ValueError("Fractional bit value")
            bits = int(amount)
        except (ValueError, KeyError, InvalidOperation) as exc:
            raise Incomplete("Missing/exact output value required") from exc
    if not 0 <= bits <= MAX_MONEY:
        raise Incomplete("Output value out of range")
    script = value.get("scriptPubKey")
    if not isinstance(script, dict):
        raise Incomplete("Decoded scriptPubKey required")
    return Output(bits, hex_bytes(script.get("hex")))


def witness(vin):
    items = vin.get("txinwitness")
    if not isinstance(items, list) or not items:
        raise Incomplete("Required witness missing; cannot determine token recipient/rebind")
    result = [hex_bytes(x) for x in items]
    if len(result) >= 2 and result[-1][:1] == b"\x50":
        result.pop()
    return result


def ctv(tx, outputs, index=0):
    try:
        inputs = tx["vin"]
        version, locktime = tx["version"], tx["locktime"]
        if type(version) is not int or type(locktime) is not int:
            raise KeyError("version/locktime")
        scripts = [hex_bytes(x["scriptSig"]["hex"]) for x in inputs]
        seq = [x["sequence"] for x in inputs]
        if any(type(x) is not int or not 0 <= x <= 0xFFFFFFFF for x in seq):
            raise KeyError("sequence")
        data = struct.pack("<II", version & 0xFFFFFFFF, locktime)
        if any(scripts):
            data += sha256(b"".join(compact(len(x)) + x for x in scripts)).digest()
        data += struct.pack("<I", len(inputs))
        data += sha256(b"".join(struct.pack("<I", x) for x in seq)).digest()
        data += struct.pack("<I", len(outputs))
        data += sha256(b"".join(x.serialize() for x in outputs)).digest()
        return sha256(data + struct.pack("<I", index)).digest()
    except (KeyError, TypeError, struct.error) as exc:
        raise Incomplete("Complete version/locktime/scriptSigs/sequences required") from exc


def template(outputs, locktime=0, inputs=2, sequence=0xFFFFFFFD):
    return {"version": 2, "locktime": locktime,
            "vin": [{"scriptSig": {"hex": ""}, "sequence": sequence} for _ in range(inputs)]}, outputs
