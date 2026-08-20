from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import re
from typing import Any

from .data_contract import (
    ALLOWED_FINANCIAL_TABLES,
    ALLOWED_VENUES,
    MAX_FINANCIAL_PERIODS,
    MAX_MARKET_CALENDAR_DAYS,
    PERIOD_RE,
    PROVIDER,
    validate_data_request,
)


COLLECTION_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,63}$")
CONFIG_KEYS = {
    "schema_version",
    "collection_id",
    "status",
    "provider",
    "group_count",
    "market",
    "financial",
}
MARKET_KEYS = {
    "start_date",
    "end_date",
    "venues",
    "max_calendar_days_per_entry",
}
FINANCIAL_KEYS = {"tables", "periods", "max_periods_per_entry"}
MAX_COLLECTION_ENTRIES = 64


def _day(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc
    if not date(2005, 1, 1) <= parsed <= date(2035, 12, 31):
        raise ValueError(f"{label} is outside the supported range")
    return parsed


def validate_collection_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS:
        raise ValueError("historical collection config fields are invalid")
    if (
        value.get("schema_version") != 1
        or value.get("status") not in {"PILOT_ONLY", "FROZEN_COHORT"}
        or value.get("provider") != PROVIDER
        or value.get("group_count") != 4
        or not isinstance(value.get("collection_id"), str)
        or not COLLECTION_ID_RE.fullmatch(value["collection_id"])
    ):
        raise ValueError("historical collection header is invalid")

    market = value.get("market")
    financial = value.get("financial")
    if (
        not isinstance(market, dict)
        or set(market) != MARKET_KEYS
        or not isinstance(financial, dict)
        or set(financial) != FINANCIAL_KEYS
    ):
        raise ValueError("historical collection scopes are invalid")
    start = _day(market.get("start_date"), "market.start_date")
    end = _day(market.get("end_date"), "market.end_date")
    if end < start:
        raise ValueError("historical market range is inverted")
    if market.get("max_calendar_days_per_entry") != MAX_MARKET_CALENDAR_DAYS:
        raise ValueError("historical market entry limit is not frozen")
    venues = market.get("venues")
    if (
        not isinstance(venues, list)
        or not venues
        or any(not isinstance(item, str) for item in venues)
        or venues != sorted(set(venues))
        or not set(venues).issubset(ALLOWED_VENUES)
    ):
        raise ValueError("historical market venues are invalid")

    tables = financial.get("tables")
    periods = financial.get("periods")
    if (
        financial.get("max_periods_per_entry") != MAX_FINANCIAL_PERIODS
        or not isinstance(tables, list)
        or not tables
        or any(not isinstance(item, str) for item in tables)
        or tables != sorted(set(tables))
        or not set(tables).issubset(ALLOWED_FINANCIAL_TABLES)
        or not isinstance(periods, list)
        or not periods
        or any(not isinstance(item, str) for item in periods)
        or periods != sorted(set(periods))
        or any(not PERIOD_RE.fullmatch(item) for item in periods)
    ):
        raise ValueError("historical financial scope is invalid")
    return value


def collection_entries(config: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    value = validate_collection_config(config)
    market = value["market"]
    start = date.fromisoformat(market["start_date"])
    end = date.fromisoformat(market["end_date"])
    entries: list[dict[str, Any]] = []
    cursor = start
    index = 0
    while cursor <= end:
        window_end = min(
            end, cursor + timedelta(days=MAX_MARKET_CALENDAR_DAYS - 1)
        )
        entries.append(
            {
                "entry_id": f"market-w{index:03d}",
                "task": "market",
                "start_date": cursor.isoformat(),
                "end_date": window_end.isoformat(),
                "venues": list(market["venues"]),
            }
        )
        cursor = window_end + timedelta(days=1)
        index += 1

    financial = value["financial"]
    periods = list(financial["periods"])
    for table in financial["tables"]:
        for batch_index, offset in enumerate(
            range(0, len(periods), MAX_FINANCIAL_PERIODS)
        ):
            entries.append(
                {
                    "entry_id": f"financial-{table}-b{batch_index:03d}",
                    "task": "financial",
                    "table": table,
                    "periods": periods[offset : offset + MAX_FINANCIAL_PERIODS],
                }
            )
    if len(entries) > MAX_COLLECTION_ENTRIES:
        raise ValueError("historical collection exceeds one bounded workflow run")
    return tuple(entries)


def collection_matrix(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "include": [
            {
                "entry_id": entry["entry_id"],
                "task": entry["task"],
                "group": group,
            }
            for entry in collection_entries(config)
            for group in range(4)
        ]
    }


def collection_job_id(config: dict[str, Any], entry_id: str) -> str:
    value = validate_collection_config(config)
    entry_ids = {entry["entry_id"] for entry in collection_entries(value)}
    if entry_id not in entry_ids:
        raise ValueError("historical collection entry is unknown")
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    material = hashlib.sha256(encoded).hexdigest() + ":" + entry_id
    return hashlib.sha256(material.encode("ascii")).hexdigest()[:32]


def build_collection_request(
    config: dict[str, Any],
    entry_id: str,
) -> tuple[str, dict[str, Any]]:
    value = validate_collection_config(config)
    entries = {entry["entry_id"]: entry for entry in collection_entries(value)}
    if entry_id not in entries:
        raise ValueError("historical collection entry is unknown")
    entry = entries[entry_id]
    job_id = collection_job_id(value, entry_id)
    if entry["task"] == "market":
        request = {
            "schema_version": 1,
            "job_id": job_id,
            "task": "daily_market_snapshot_v1",
            "batch_only": True,
            "group_count": 4,
            "provider": PROVIDER,
            "start_date": entry["start_date"],
            "end_date": entry["end_date"],
            "venues": entry["venues"],
        }
    else:
        request = {
            "schema_version": 1,
            "job_id": job_id,
            "task": "pit_financial_events_v1",
            "batch_only": True,
            "group_count": 4,
            "provider": PROVIDER,
            "table": entry["table"],
            "periods": entry["periods"],
        }
    validate_data_request(request, job_id)
    return job_id, request


def seal_collection_request(
    config: dict[str, Any],
    entry_id: str,
    *,
    key: bytes,
) -> tuple[str, str, str]:
    from .sealed_protocol import (
        canonical_json,
        compress_payload,
        encode_transport,
        request_aad,
        seal_bytes,
    )

    job_id, request = build_collection_request(config, entry_id)
    blob = seal_bytes(
        compress_payload(canonical_json(request)),
        key,
        request_aad(job_id),
    )
    return job_id, encode_transport(blob), hashlib.sha256(blob).hexdigest()
