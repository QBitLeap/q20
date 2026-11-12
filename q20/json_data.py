"""Iterative JSON containers with the standard decoder for scalar grammar/escapes.

Unknown fields must not turn a valid record into an interpreter-recursion or
floating-point failure. Numeric values remain distinctly numeric; QBIT-20
amounts are strings, so JSON numbers never become token amounts.
"""

from dataclasses import dataclass
from decimal import Decimal
import json
import re


@dataclass(frozen=True)
class Number:
    literal: str


def loads(text):
    duplicates = False

    def bad_constant(_):
        raise ValueError("Non-JSON constant")

    decoder = json.JSONDecoder(parse_int=Number, parse_float=Number, parse_constant=bad_constant)
    whitespace = re.compile(r"[ \t\r\n]*")
    frames, result, have_result, pos = [], None, False, 0

    def accept(value):
        nonlocal result, have_result
        if not frames:
            if have_result:
                raise ValueError("Extra JSON value")
            result, have_result = value, True
        else:
            frame = frames[-1]
            if isinstance(frame[0], list):
                frame[0].append(value)
                frame[1] = 1
            else:
                frame[0][frame[2]] = value
                frame[1] = 3

    while True:
        pos = whitespace.match(text, pos).end()
        if not frames and have_result:
            if pos != len(text):
                raise ValueError("Trailing JSON data")
            return result, duplicates
        if pos >= len(text):
            raise ValueError("Truncated JSON")
        char = text[pos]
        if frames:
            frame = frames[-1]
            container, state = frame[:2]
            if isinstance(container, dict):
                if state in (0, 4):
                    if char == "}" and state == 0:
                        frames.pop()
                        pos += 1
                        continue
                    if char != '"':
                        raise ValueError("Expected JSON object key")
                    key, pos = decoder.raw_decode(text, pos)
                    duplicates |= key in container
                    frame[2], frame[1] = key, 1
                    continue
                if state == 1:
                    if char != ":":
                        raise ValueError("Expected colon")
                    frame[1] = 2
                    pos += 1
                    continue
                if state == 3:
                    if char == "}":
                        frames.pop()
                    elif char == ",":
                        frame[1] = 4
                    else:
                        raise ValueError("Expected object comma or end")
                    pos += 1
                    continue
            else:
                if state == 0 and char == "]":
                    frames.pop()
                    pos += 1
                    continue
                if state == 1:
                    if char == "]":
                        frames.pop()
                    elif char == ",":
                        frame[1] = 2
                    else:
                        raise ValueError("Expected array comma or end")
                    pos += 1
                    continue
        if char in "[{":
            container = [] if char == "[" else {}
            accept(container)
            frames.append([container, 0, None])
            pos += 1
        else:
            value, pos = decoder.raw_decode(text, pos)
            accept(value)


def amount(value):
    """Convert decimal strings without Python's int<->str digit-limit artifact."""
    return int(Decimal(value))


def amount_text(value):
    return str(Decimal(value))
