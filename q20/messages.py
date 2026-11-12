"""Decode data, never execute it. JSON syntax, schema and ledger validity differ."""

from dataclasses import dataclass
import re

from .json_data import loads, amount


class Incomplete(RuntimeError):
    """Input/source/verification is unavailable; never call this a bad token record."""


def integer(value):
    if type(value) is not str or re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is None:
        return None
    return amount(value)


def single_push(script):
    if len(script) < 2 or script[0] != 0x6A:
        return None
    op = script[1]
    if 1 <= op <= 75:
        start, length = 2, op
    elif op in (0x4C, 0x4D, 0x4E):
        size = {0x4C: 1, 0x4D: 2, 0x4E: 4}[op]
        if len(script) < 2 + size:
            return None
        start, length = 2 + size, int.from_bytes(script[2:2 + size], "little")
    else:
        return None
    return script[start:] if start + length == len(script) else None


def op_return(payload):
    length = len(payload)
    if 1 <= length <= 75:
        push = bytes([length])
    elif length <= 255:
        push = b"\x4c" + bytes([length])
    elif length <= 65535:
        push = b"\x4d" + length.to_bytes(2, "little")
    else:
        push = b"\x4e" + length.to_bytes(4, "little")
    return b"\x6a" + push + payload


@dataclass
class Message:
    classification: str
    reason: str = ""
    record: dict | None = None
    duplicates: bool = False
    payload: bytes = b""


def decode(payload, rules, height):
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return Message("invalid-utf8", payload=payload)
    try:
        record, duplicates = loads(text)
    except ValueError:
        return Message("invalid-json", payload=payload)
    result = Message("other-json", record=None, duplicates=duplicates, payload=payload)
    if not isinstance(record, dict):
        return result
    if record.get("p") != "qbit-20":
        result.classification = "other-protocol"
        return result
    result.record = record
    result.classification = "invalid-record"

    def bad(reason):
        result.reason = reason
        return result

    pattern = r"[A-Z0-9]{3,4}" if rules.active("threeTick", height) else r"[A-Z0-9]{4}"
    if type(record.get("tick")) is not str or not re.fullmatch(pattern, record["tick"]):
        return bad("bad-tick")
    op = record.get("op")
    if op == "deploy":
        maximum, limit = integer(record.get("max")), integer(record.get("lim"))
        if maximum is None or limit is None:
            return bad("bad-amount")
        if record.get("dec") != "8":
            return bad("bad-dec")
        if not maximum or not limit:
            return bad("zero-supply-or-limit")
        if rules.active("gate", height) and ("gate" in record or "gate_end" in record):
            gate, end = record.get("gate"), record.get("gate_end")
            if (type(gate) is not str or re.fullmatch(r"[0-9a-f]{64}", gate) is None
                    or (integer(end) or 0) not in range(1, 43201)):
                return bad("bad-mint-gate")
        if rules.active("addressMints", height) and "addr_mints" in record:
            if (integer(record["addr_mints"]) or 0) not in range(1, 101):
                return bad("bad-addr-mints")
    elif op in ("mint", "transfer"):
        amount = integer(record.get("amt"))
        if amount is None:
            return bad("bad-amount")
        if not amount:
            return bad("zero-amount")
    else:
        return bad("unknown-op")
    result.classification = "record"
    return result


def discover(outputs, rules, height):
    for index, output in enumerate(outputs):
        script = output.script
        if script[:1] != b"\x6a":
            continue
        payload = single_push(script)
        message = (Message("invalid-carrier", reason="not-exactly-one-data-push") if payload is None
                   else decode(payload, rules, height))
        return index, message
    return None, Message("no-message")
