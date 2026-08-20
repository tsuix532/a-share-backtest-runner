from __future__ import annotations

import hashlib
from typing import Any

from .data_contract import validate_data_request
from .sealed_protocol import (
    canonical_json,
    compress_payload,
    encode_transport,
    request_aad,
    seal_bytes,
)


CONFIG_KEYS = {"schema_version", "provider", "market", "financial"}
MARKET_CONFIG_KEYS = {"start_date", "end_date", "venues"}
FINANCIAL_CONFIG_KEYS = {"table", "periods"}


def smoke_job_id(run_id: str, task: str) -> str:
    if not run_id.isdigit() or task not in {"market", "financial"}:
        raise ValueError("provider-smoke identity is invalid")
    material = f"provider-smoke-v1:{run_id}:{task}".encode("ascii")
    return hashlib.sha256(material).hexdigest()[:32]


def build_smoke_request(
    config: dict[str, Any],
    *,
    run_id: str,
    task: str,
) -> tuple[str, dict[str, Any]]:
    if set(config) != CONFIG_KEYS or config.get("schema_version") != 1:
        raise ValueError("provider-smoke config is invalid")
    if config.get("provider") != "zzshare-0.4.9":
        raise ValueError("provider-smoke version is not pinned")
    market = config.get("market")
    financial = config.get("financial")
    if (
        not isinstance(market, dict)
        or set(market) != MARKET_CONFIG_KEYS
        or not isinstance(financial, dict)
        or set(financial) != FINANCIAL_CONFIG_KEYS
    ):
        raise ValueError("provider-smoke scopes are invalid")

    job_id = smoke_job_id(run_id, task)
    if task == "market":
        request = {
            "schema_version": 1,
            "job_id": job_id,
            "task": "daily_market_snapshot_v1",
            "batch_only": True,
            "group_count": 4,
            "provider": config["provider"],
            "start_date": market["start_date"],
            "end_date": market["end_date"],
            "venues": market["venues"],
        }
    else:
        request = {
            "schema_version": 1,
            "job_id": job_id,
            "task": "pit_financial_events_v1",
            "batch_only": True,
            "group_count": 4,
            "provider": config["provider"],
            "table": financial["table"],
            "periods": financial["periods"],
        }
    validate_data_request(request, job_id)
    return job_id, request


def seal_smoke_request(
    config: dict[str, Any],
    *,
    run_id: str,
    task: str,
    key: bytes,
) -> tuple[str, str, str]:
    job_id, request = build_smoke_request(config, run_id=run_id, task=task)
    blob = seal_bytes(
        compress_payload(canonical_json(request)),
        key,
        request_aad(job_id),
    )
    return job_id, encode_transport(blob), hashlib.sha256(blob).hexdigest()
