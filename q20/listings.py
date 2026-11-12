"""Published listing versions 1/2/3/5, including the v5 shape/leaf distinction."""

from hashlib import sha256
import re

from .messages import integer
from .wire import (ANCHOR, MAX_MONEY, Output, address, address_script, branch, ctv,
                   leaf, p2mr, template, witness)

SINK_SCRIPT = b"\x52\x20" + leaf(bytes.fromhex("6a0c716269742d32302073696e6b"))


def terms(message, seller, rules, height):
    r = message.record
    if (message.duplicates or len(message.payload) > 512 or r.get("bind") != "1"
            or not isinstance(r.get("list"), dict)):
        return None
    value = r["list"]
    version = value.get("v")
    if type(version) is not str:
        return None
    feature = {"1": "bind", "2": "bind2", "3": "bind3", "5": "bind5"}.get(version)
    if feature is None or not rules.active(feature, height):
        return None
    price, expiry = integer(value.get("price")), integer(value.get("exp"))
    salt = value.get("salt")
    if (price is None or price < 3000 or expiry is None or not 1 <= expiry < 500000000
            or type(salt) is not str or re.fullmatch(r"[0-9a-f]{32}", salt) is None):
        return None
    fee = None
    if "fee" in value or "feeAddress" in value:
        fee = integer(value.get("fee"))
        try:
            address_script(value.get("feeAddress"), rules.value["hrp"])
        except ValueError:
            return None
        if fee is None or fee < 3000:
            return None
    lots, anchor = 1, version in ("1", "2")
    if version == "5":
        lots = integer(value.get("lots"))
        if lots is None or not 1 <= lots <= 100 or ("anchor" in value and value["anchor"] != "1"):
            return None
        anchor = "anchor" in value
        if any(x % lots for x in (integer(r["amt"]), price, fee or 0)):
            return None
        if price // lots < 3000 or fee is not None and fee // lots < 3000:
            return None
    if price + (fee or 0) + (330 if anchor else 0) > MAX_MONEY:
        return None
    keys = {"v", "price", "fee", "feeAddress", "salt", "exp"} | ({"lots", "anchor"} if version == "5" else set())
    return {"version": version, "tick": r["tick"], "amount": r["amt"], "seller": seller,
            "price": str(price), "fee": str(fee) if fee is not None else None,
            "feeAddress": value.get("feeAddress") if fee is not None else None,
            "salt": salt, "exp": expiry, "lots": lots, "anchor": anchor,
            "list": {k: v for k, v in value.items() if k in keys}}


def buy_outputs(terms, rules, lots=1, remaining=None):
    count = terms["lots"]
    result = [Output(int(terms["price"]) // count * lots,
                     address_script(terms["seller"], rules.value["hrp"]))]
    if terms["fee"] is not None:
        result.append(Output(int(terms["fee"]) // count * lots,
                             address_script(terms["feeAddress"], rules.value["hrp"])))
    if remaining is not None:
        result.append(Output(5000, remaining))
    if terms["anchor"]:
        result.append(Output(330, ANCHOR))
    return result


def refund_outputs(terms, rules):
    return [Output(3000, address_script(terms["seller"], rules.value["hrp"])), Output(330, ANCHOR)]


def refund_leaf(terms, rules):
    tx, outputs = template(refund_outputs(terms, rules), terms["exp"], 1, 0xFFFFFFFE)
    return leaf(b"\x20" + ctv(tx, outputs) + b"\xbb")


def salt_branch(terms, rules, lots=None):
    amt = int(terms["amount"])
    if lots is not None:
        amt = amt // terms["lots"] * lots
    salt = sha256(f'{terms["tick"]}|{amt}|{terms["salt"]}'.encode()).digest()[:16]
    salt_hash = leaf(b"\x6a\x10" + salt)
    seller = address_script(terms["seller"], rules.value["hrp"])[2:]
    return branch(salt_hash, seller) if terms["version"] != "1" else salt_hash


def listing_script(terms, rules):
    """v1-3 validation only; v5 binds deliberately do not reconstruct this tree."""
    tx, outputs = template(buy_outputs(terms, rules))
    buy = leaf(b"\x20" + ctv(tx, outputs) + b"\xbb")
    root = branch(branch(buy, refund_leaf(terms, rules)), salt_branch(terms, rules))
    return b"\x52\x20" + root


def bind(message, seller, outputs, rules, height):
    first = next((i for i, o in enumerate(outputs) if o.script[:1] != b"\x6a"), None)
    if first is None:
        return None, False
    sink = rules.active("bind5", height) and outputs[first].script == SINK_SCRIPT
    parsed = terms(message, seller, rules, height)
    if parsed is None:
        return None, sink
    if sink:
        rest = next((i for i in range(first + 1, len(outputs)) if outputs[i].script[:1] != b"\x6a"), None)
        if (parsed["version"] != "5" or rest is None or outputs[rest].bits < 5000
                or not p2mr(outputs[rest].script)):
            return None, True
        return (rest, parsed), True
    if parsed["version"] == "5":
        return None, False
    if outputs[first].bits >= 5000 and outputs[first].script == listing_script(parsed, rules):
        return (first, parsed), False
    return None, False


def buyer(tx, prevouts, origin, rules, height):
    if len(prevouts) < 2 or not p2mr(prevouts[1].script):
        return origin
    payer = address(prevouts[1].script, rules.value["hrp"])
    if not rules.active("buyTicket", height):
        return payer
    stack = witness(tx["vin"][1])
    if len(stack) != 3:
        return payer
    script, cb = stack[1:]
    if (len(cb) < 1 or (len(cb) - 1) % 32 or cb[0] != 0xC1 or len(script) != 103
            or script[:1] != b"\x20" or script[33:35] != b"\x75\x20"
            or script[67:70] != b"\xbb\x75\x20" or script[-1:] != b"\xb3"):
        return payer
    return address(b"\x52\x20" + script[1:33], rules.value["hrp"])


def release(coin, input_index, tx, outputs, prevouts, rules, height):
    """Return sold lots, recipient, rebind output, classification. No mutations."""
    t = coin["terms"]
    count = coin["lots"]
    if t["version"] == "5":
        # These fields and witness are mandatory even for a refund/cancellation.
        digest = ctv(tx, outputs)
        stack = witness(tx["vin"][input_index])
        sold, remaining_output = 0, None
        if input_index == 0 and len(prevouts) == 2 and outputs:
            unit_price = int(t["price"]) // t["lots"]
            j, rem = divmod(outputs[0].bits, unit_price)
            rest_index = 1 + (t["fee"] is not None)
            rest = outputs[rest_index].script if len(outputs) > rest_index else None
            if (not rem and 1 <= j <= count and (j == count or rest is not None and p2mr(rest))
                    and outputs == buy_outputs(t, rules, j, rest if j < count else None)):
                sold = j
                if j < count and len(stack) == 2:
                    script, cb = stack
                    if (script == b"\x20" + digest + b"\xbb" and len(cb) >= 65
                            and (len(cb) - 1) % 32 == 0 and cb[0] == 0xC1
                            and cb[-64:-32] == refund_leaf(t, rules)
                            and cb[-32:] == salt_branch(t, rules, count)):
                        remaining_output = rest_index
        if sold:
            return sold, buyer(tx, prevouts, t["seller"], rules, height), remaining_output, "buy"
    else:
        sale = input_index == 0 and len(prevouts) == 2 and outputs == buy_outputs(t, rules)
        if t["version"] == "1":
            # v1 recipient deliberately uses the broad input shape, independent of via.
            credited = (buyer(tx, prevouts, t["seller"], rules, height)
                        if input_index == 0 and len(prevouts) >= 2 else t["seller"])
            via = "buy" if sale else "refund" if len(prevouts) == 1 and outputs == refund_outputs(t, rules) else "seller"
            return count, credited, None, via
        if sale:
            return count, buyer(tx, prevouts, t["seller"], rules, height), None, "buy"
    via = "refund" if input_index == 0 and len(prevouts) == 1 and outputs == refund_outputs(t, rules) else "seller"
    return count, t["seller"], None, via
