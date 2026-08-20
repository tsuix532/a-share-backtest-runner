from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from public_runner.contract import ContractError, validate_request
from public_runner.data_contract import validate_data_request
from public_runner.data_worker import run_data_group
from public_runner.sealed_protocol import (
    canonical_json,
    compress_payload,
    decode_key,
    decode_transport,
    decompress_payload,
    request_aad,
    result_aad,
    seal_bytes,
    unseal_bytes,
)
from public_runner.worker import run_group


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--group", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    blob = decode_transport(os.environ["SEALED_JOB_B64"])
    expected_digest = os.environ["SEALED_JOB_SHA256"]
    if hashlib.sha256(blob).hexdigest() != expected_digest:
        raise RuntimeError("sealed request digest mismatch")
    key = decode_key(os.environ["SEALED_JOB_KEY_B64"])
    compressed = unseal_bytes(blob, key, request_aad(args.job_id))
    plaintext = decompress_payload(compressed)
    raw_request = json.loads(plaintext.decode("utf-8"))
    if not isinstance(raw_request, dict):
        raise ContractError("request root must be an object")
    if raw_request.get("task") == "daily_order_replay_v1":
        request = validate_request(raw_request, args.job_id)
        result = run_group(request, args.group)
    else:
        data_request = validate_data_request(raw_request, args.job_id)
        result = run_data_group(data_request, args.group)
    sealed = seal_bytes(
        compress_payload(canonical_json(result)),
        key,
        result_aad(args.job_id, args.group),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"result-g{args.group}.asr"
    output.write_bytes(sealed)
    unit_count = result.get("case_count", result.get("row_count", 0))
    print(f"group={args.group} units={unit_count} status={result['status']}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
