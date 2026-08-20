from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from public_runner.data_contract import validate_data_request
from public_runner.provider_smoke import (
    build_smoke_request,
    seal_smoke_request,
    smoke_job_id,
)
from public_runner.sealed_protocol import (
    decode_transport,
    decompress_payload,
    request_aad,
    unseal_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads(
    (ROOT / "config" / "provider_smoke_v1.json").read_text(encoding="utf-8")
)
KEY = bytes(range(32))


class ProviderSmokeTests(unittest.TestCase):
    def test_job_identity_is_deterministic_and_task_scoped(self) -> None:
        self.assertEqual(smoke_job_id("123", "market"), smoke_job_id("123", "market"))
        self.assertNotEqual(
            smoke_job_id("123", "market"),
            smoke_job_id("123", "financial"),
        )
        with self.assertRaises(ValueError):
            smoke_job_id("not-a-run", "market")

    def test_generic_requests_validate(self) -> None:
        for task in ("market", "financial"):
            job_id, request = build_smoke_request(
                CONFIG, run_id="123", task=task
            )
            validate_data_request(request, job_id)
            self.assertNotIn("strategy", request)

    def test_transport_round_trip(self) -> None:
        job_id, encoded, digest = seal_smoke_request(
            CONFIG, run_id="123", task="market", key=KEY
        )
        blob = decode_transport(encoded)
        self.assertEqual(len(digest), 64)
        plaintext = decompress_payload(
            unseal_bytes(blob, KEY, request_aad(job_id))
        )
        request = json.loads(plaintext.decode("utf-8"))
        self.assertEqual(request["task"], "daily_market_snapshot_v1")

    def test_workflow_entry_points_resolve_the_package(self) -> None:
        for module in (
            "scripts.build_provider_smoke_request",
            "scripts.run_sealed_job",
        ):
            completed = subprocess.run(
                [sys.executable, "-m", module, "--help"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
