from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from .contract import ContractError, JOB_ID_RE


PROVIDER = "zzshare-0.4.9"
GROUP_COUNT = 4
MAX_MARKET_CALENDAR_DAYS = 35
MAX_FINANCIAL_PERIODS = 8
PERIOD_RE = re.compile(r"^(20(?:0[5-9]|[12][0-9]|3[0-5]))q[1-4]$")
MARKET_ROOT_KEYS = {
    "schema_version",
    "job_id",
    "task",
    "batch_only",
    "group_count",
    "provider",
    "start_date",
    "end_date",
    "venues",
}
FINANCIAL_ROOT_KEYS = {
    "schema_version",
    "job_id",
    "task",
    "batch_only",
    "group_count",
    "provider",
    "table",
    "periods",
}
ALLOWED_VENUES = frozenset({"SH", "SZ", "BJ"})
ALLOWED_FINANCIAL_TABLES = frozenset(
    {"indicator", "income", "balance", "cash_flow"}
)


@dataclass(frozen=True)
class DailyMarketDataRequest:
    job_id: str
    group_count: int
    provider: str
    start_date: str
    end_date: str
    venues: tuple[str, ...]


@dataclass(frozen=True)
class FinancialEventsRequest:
    job_id: str
    group_count: int
    provider: str
    table: str
    periods: tuple[str, ...]


DataRequest = DailyMarketDataRequest | FinancialEventsRequest


def _request_header(value: dict[str, Any], expected_job_id: str) -> None:
    if value.get("schema_version") != 1 or value.get("batch_only") is not True:
        raise ContractError("data request protocol is unsupported")
    job_id = value.get("job_id")
    if (
        not isinstance(job_id, str)
        or not JOB_ID_RE.fullmatch(job_id)
        or job_id != expected_job_id
    ):
        raise ContractError("job id is invalid")
    if value.get("group_count") != GROUP_COUNT:
        raise ContractError("group_count must match the fixed workflow")
    if value.get("provider") != PROVIDER:
        raise ContractError("data provider version is not pinned")


def _iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO date") from exc
    if not date(2005, 1, 1) <= parsed <= date(2035, 12, 31):
        raise ContractError(f"{label} is outside the allowed range")
    return parsed


def validate_data_request(value: Any, expected_job_id: str) -> DataRequest:
    if not isinstance(value, dict):
        raise ContractError("data request must be an object")
    task = value.get("task")
    if task == "daily_market_snapshot_v1":
        if set(value) != MARKET_ROOT_KEYS:
            raise ContractError("market-data request fields do not match the contract")
        _request_header(value, expected_job_id)
        start = _iso_date(value.get("start_date"), "start_date")
        end = _iso_date(value.get("end_date"), "end_date")
        if end < start:
            raise ContractError("market-data date range is inverted")
        if (end - start).days + 1 > MAX_MARKET_CALENDAR_DAYS:
            raise ContractError("market-data date range exceeds one bounded batch")
        raw_venues = value.get("venues")
        if (
            not isinstance(raw_venues, list)
            or not raw_venues
            or any(not isinstance(item, str) for item in raw_venues)
        ):
            raise ContractError("venues must be a non-empty list")
        venues = tuple(raw_venues)
        if (
            len(venues) != len(set(venues))
            or tuple(sorted(venues)) != venues
            or not set(venues).issubset(ALLOWED_VENUES)
        ):
            raise ContractError("venues are invalid, duplicated or unsorted")
        return DailyMarketDataRequest(
            job_id=expected_job_id,
            group_count=GROUP_COUNT,
            provider=PROVIDER,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            venues=venues,
        )

    if task == "pit_financial_events_v1":
        if set(value) != FINANCIAL_ROOT_KEYS:
            raise ContractError("financial-data request fields do not match the contract")
        _request_header(value, expected_job_id)
        table = value.get("table")
        if table not in ALLOWED_FINANCIAL_TABLES:
            raise ContractError("financial table is unsupported")
        raw_periods = value.get("periods")
        if (
            not isinstance(raw_periods, list)
            or not 1 <= len(raw_periods) <= MAX_FINANCIAL_PERIODS
            or any(not isinstance(item, str) for item in raw_periods)
        ):
            raise ContractError("financial periods are missing or exceed the batch limit")
        periods = tuple(raw_periods)
        if (
            len(periods) != len(set(periods))
            or tuple(sorted(periods)) != periods
            or any(not PERIOD_RE.fullmatch(item) for item in periods)
        ):
            raise ContractError("financial periods are invalid, duplicated or unsorted")
        return FinancialEventsRequest(
            job_id=expected_job_id,
            group_count=GROUP_COUNT,
            provider=PROVIDER,
            table=str(table),
            periods=periods,
        )

    raise ContractError("data request task is unsupported")
