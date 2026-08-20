from __future__ import annotations

import unittest

from public_runner.sealed_protocol import (
    ProtocolError,
    compress_payload,
    decompress_payload,
    request_aad,
    seal_bytes,
    unseal_bytes,
)


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

    def test_compressed_payload_is_bounded(self) -> None:
        compressed = compress_payload(b"a" * 100)
        self.assertEqual(decompress_payload(compressed, max_bytes=100), b"a" * 100)
        with self.assertRaises(ProtocolError):
            decompress_payload(compressed, max_bytes=99)


if __name__ == "__main__":
    unittest.main()
