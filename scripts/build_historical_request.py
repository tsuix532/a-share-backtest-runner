from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from public_runner.historical_collection import seal_collection_request
from public_runner.sealed_protocol import decode_key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--entry-id", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("historical collection config root must be an object")
    key = decode_key(os.environ["SEALED_JOB_KEY_B64"])
    job_id, sealed_b64, digest = seal_collection_request(
        raw, args.entry_id, key=key
    )
    with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"job_id={job_id}\n")
        handle.write(f"sealed_job_b64={sealed_b64}\n")
        handle.write(f"sealed_job_sha256={digest}\n")
    print(f"entry={args.entry_id} job_id={job_id} request=sealed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
