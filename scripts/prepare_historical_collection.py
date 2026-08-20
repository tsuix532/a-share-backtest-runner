from __future__ import annotations

import argparse
import json
from pathlib import Path

from public_runner.historical_collection import (
    collection_entries,
    collection_matrix,
    validate_collection_config,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    config = validate_collection_config(raw)
    entries = collection_entries(config)
    matrix = json.dumps(collection_matrix(config), separators=(",", ":"))
    with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"collection_id={config['collection_id']}\n")
        handle.write(f"entry_count={len(entries)}\n")
        handle.write(f"matrix={matrix}\n")
    print(
        f"collection={config['collection_id']} entries={len(entries)} "
        f"jobs={len(entries) * 4}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
