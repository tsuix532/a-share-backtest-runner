from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from public_runner.data_contract import validate_data_request
from public_runner.historical_collection import (
    build_collection_request,
    collection_entries,
    collection_job_id,
    collection_matrix,
    seal_collection_request,
)
from public_runner.sealed_protocol import (
    decode_transport,
    decompress_payload,
    request_aad,
    unseal_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads(
    (ROOT / "config" / "historical_collection_pilot_v1.json").read_text(
        encoding="utf-8"
    )
)
KEY = bytes(range(32))


class HistoricalCollectionTests(unittest.TestCase):
    def test_pilot_is_split_into_bounded_entries(self) -> None:
        entries = collection_entries(CONFIG)
        market = [entry for entry in entries if entry["task"] == "market"]
        financial = [entry for entry in entries if entry["task"] == "financial"]
        self.assertEqual(len(market), 2)
        self.assertEqual(market[0]["start_date"], "2026-06-01")
        self.assertEqual(market[0]["end_date"], "2026-07-05")
        self.assertEqual(market[1]["start_date"], "2026-07-06")
        self.assertEqual(market[1]["end_date"], "2026-07-10")
        self.assertEqual(len(financial), 1)
        self.assertEqual(len(collection_matrix(CONFIG)["include"]), 12)

    def test_every_entry_builds_a_valid_generic_request(self) -> None:
        ids: set[str] = set()
        for entry in collection_entries(CONFIG):
            job_id, request = build_collection_request(CONFIG, entry["entry_id"])
            validate_data_request(request, job_id)
            self.assertNotIn("strategy", request)
            ids.add(job_id)
        self.assertEqual(len(ids), 3)

    def test_job_id_is_stable(self) -> None:
        self.assertEqual(
            collection_job_id(CONFIG, "market-w000"),
            collection_job_id(CONFIG, "market-w000"),
        )
        with self.assertRaises(ValueError):
            collection_job_id(CONFIG, "missing")

    def test_sealed_entry_round_trip(self) -> None:
        job_id, encoded, digest = seal_collection_request(
            CONFIG, "financial-indicator-b000", key=KEY
        )
        blob = decode_transport(encoded)
        self.assertEqual(len(digest), 64)
        request = json.loads(
            decompress_payload(
                unseal_bytes(blob, KEY, request_aad(job_id))
            ).decode("utf-8")
        )
        self.assertEqual(request["periods"], ["2025q3", "2025q4"])

    def test_collection_workflow_is_bounded_and_ciphertext_only(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "historical-collection.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("max-parallel: 2", workflow)
        self.assertIn("retention-days: 1", workflow)
        self.assertIn("path: sealed-output/*.asr", workflow)
        self.assertNotIn("upload-artifact@v", workflow)

    def test_collection_entry_points_resolve_the_package(self) -> None:
        for module in (
            "scripts.prepare_historical_collection",
            "scripts.build_historical_request",
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
