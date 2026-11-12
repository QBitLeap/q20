import json
import random
import unittest
from unittest.mock import patch

from q20.json_data import Number, amount, amount_text, loads
from q20.messages import decode, integer
from q20.rules import Rules


class JsonDataTests(unittest.TestCase):
    def test_differential_scalar_and_container_grammar(self):
        rng = random.Random(20)

        def value(depth=0):
            basic = [None, True, False, rng.randrange(-10000, 10000), "escaped\n\t\"\\雪"]
            if depth < 4:
                basic += [[value(depth+1) for _ in range(rng.randrange(3))],
                          {"k"+str(i): value(depth+1) for i in range(rng.randrange(3))}]
            return rng.choice(basic)

        for _ in range(100):
            raw = json.dumps(value(), ensure_ascii=bool(rng.randrange(2)))
            expected = json.loads(raw, parse_int=Number, parse_float=Number)
            self.assertEqual(loads(raw), (expected, False))
        for raw in ('{"a":1,}', '[1,]', '[,]', '{a:1}', '{}{}', '01', '+1', '1.', '.1',
                    '1e', '[true false]', '{"a" 1}', 'NaN', 'Infinity', '"bad\nstring"', ''):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                loads(raw)

    def test_deep_unknown_fields_and_large_ignored_numbers_are_valid_json(self):
        raw = '{"p":"qbit-20","op":"mint","tick":"TEST","amt":"1","unknown":' + '['*5000 + '1e99999999999999999999' + ']'*5000 + '}'
        self.assertEqual(decode(raw.encode(), Rules.load(), 180000).classification, "record")
        self.assertEqual(decode(('['*5000+'0'+']'*5000).encode(), Rules.load(), 180000).classification, "other-json")

    def test_duplicate_escaped_keys_in_arrays(self):
        value, duplicate = loads('{"a":[{"x":0,"\\u0078":1}]}')
        self.assertTrue(duplicate)
        self.assertEqual(value["a"][0]["x"], Number("1"))

    def test_decimal_amounts_exceed_python_digit_limit_without_losing_precision(self):
        value = "9"*5000
        n = integer(value)
        self.assertEqual(amount_text(n), value)
        self.assertEqual(amount_text(n+1), "1"+"0"*5000)
        self.assertIsNone(integer(Number("8")))
        self.assertEqual(decode(b'{"p":"qbit-20","op":"deploy","tick":"TEST","max":"1","lim":"1","dec":8}', Rules.load(), 180000).reason, "bad-dec")

    def test_http_bind_never_requires_reverse_dns(self):
        from q20.http import Server
        from http.server import BaseHTTPRequestHandler
        with patch("socket.getfqdn", side_effect=AssertionError("No reverse DNS on app startup")):
            server = Server(("127.0.0.1", 0), BaseHTTPRequestHandler)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
