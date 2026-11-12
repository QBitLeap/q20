"""Verify locked-mint tickets with Qbit's bounded30 library, never FIPS SLH-DSA."""

import base64
import ctypes
from functools import lru_cache
from hashlib import sha256
import re

from .messages import Incomplete, integer
from .wire import address_script


@lru_cache(maxsize=1)
def native_verifier(path):
    try:
        library = ctypes.CDLL(path)
        function = library.bitcoin_pqc_verify
        function.argtypes = [ctypes.c_void_p, ctypes.c_size_t] * 3
        function.restype = ctypes.c_int
    except (OSError, AttributeError) as exc:
        raise Incomplete("Install the Qbit bounded30 verification library to validate mint tickets") from exc

    def verify(key, digest, signature):
        return function(key, len(key), digest, len(digest), signature, len(signature)) == 0

    verify.library = library
    return verify


def parse(value, paid, rules):
    if type(value) is not str:
        return None
    fields = value.split(".")
    if len(fields) != (5 if paid else 3):
        return None
    exp, nonce, signature = fields[0], fields[1], fields[-1]
    if (re.fullmatch(r"[1-9][0-9]{0,9}", exp) is None
            or re.fullmatch(r"[0-9a-f]{16}", nonce) is None
            or re.fullmatch(r"[A-Za-z0-9_-]{4907}", signature) is None):
        return None
    decoded = base64.urlsafe_b64decode(signature + "=")
    if len(decoded) != 3680 or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != signature:
        return None
    result = {"exp": int(exp), "nonce": nonce, "signature": decoded}
    if paid:
        fee, address = fields[2:4]
        if (len(fee) > 16 or integer(fee) is None or address != address.lower()
                or len(address) > 100):
            return None
        try:
            script = address_script(address, rules.value["hrp"])
        except ValueError:
            return None
        result.update(fee=int(fee), address=address, script=script)
    return result


def digest(ticket, rules, tick, minter):
    paid = "fee" in ticket
    fields = ["qbit-20 mint ticket v2" if paid else "qbit-20 mint ticket v1",
              rules.network, tick, minter, str(ticket["exp"]), ticket["nonce"]]
    if paid:
        fields.extend((str(ticket["fee"]), ticket["address"]))
    return sha256("|".join(fields).encode()).digest()
