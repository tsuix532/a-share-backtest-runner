from __future__ import annotations

import unittest

from public_runner.sealed_protocol import ProtocolError, request_aad, seal_bytes, unseal_bytes


class ProtocolTests(unittest.TestCase):
    def test_round_trip_and_context_binding(self) -> None:
        key = bytes(range(32))
        blob = seal_bytes(b"private", key, request_aad("1" * 32))
        self.assertEqual(unseal_bytes(blob, key, request_aad("1" * 32)), b"private")
        with self.assertRaises(ProtocolError):
            unseal_bytes(blob, key, request_aad("2" * 32))

    def test_tamper_is_rejected(self) -> None:
        key = bytes(range(32))
        blob = bytearray(seal_bytes(b"private", key, request_aad("1" * 32)))
        blob[-1] ^= 1
        with self.assertRaises(ProtocolError):
            unseal_bytes(bytes(blob), key, request_aad("1" * 32))


if __name__ == "__main__":
    unittest.main()

