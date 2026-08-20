from __future__ import annotations

from datetime import date, datetime
import logging
import math
import os
import time
from typing import Any, Callable

from .data_contract import (
    DailyMarketDataRequest,
    DataRequest,
    FinancialEventsRequest,
)


REQUEST_PACE_SECONDS = 2.1
MAX_PROVIDER_COLUMNS = 256
MAX_PROVIDER_FIELD_NAME = 128


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("list", "data", "rows", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [dict(item) for item in nested if isinstance(item, dict)]
        return [dict(value)] if value else []
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter(orient="records")
        if isinstance(converted, list):
            return [dict(item) for item in converted if isinstance(item, dict)]
    raise TypeError("provider returned an unsupported tabular value")


def _calendar_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return [dict(item) for item in value]
        return [{"date": item} for item in value]
    if isinstance(value, dict):
        for key in (
            "list", "data", "rows", "items", "dates", "date_list", "trade_days"
        ):
            nested = value.get(key)
            if isinstance(nested, list):
                return _calendar_records(nested)
    return _records(value)


def _pick(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return bool(int(value))
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def _iso_day(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    raw = str(value).strip()
    if len(raw) == 8 and raw.isdigit():
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def _normalize_code(value: Any) -> str | None:
    raw = str(value).strip().upper()
    if not raw or raw == "NAN":
        return None
    if "." in raw:
        code, venue = raw.split(".", 1)
        if len(code) == 6 and code.isdigit() and venue in {"SH", "SZ", "BJ"}:
            return f"{code}.{venue}"
        return None
    if len(raw) != 6 or not raw.isdigit():
        return None
    if raw.startswith(("6", "5")):
        return f"{raw}.SH"
    if raw.startswith(("0", "3")):
        return f"{raw}.SZ"
    if raw.startswith(("8", "4", "2", "9")):
        return f"{raw}.BJ"
    return None


def _provider() -> Any:
    from zzshare.client import DataApi

    logging.getLogger("zzshare").setLevel(logging.CRITICAL + 1)
    token = os.environ.get("ZZSHARE_TOKEN", "").strip()
    kwargs: dict[str, Any] = {"timeout": 20}
    if token:
        kwargs["token"] = token
    return DataApi(**kwargs)


def _retry(call: Callable[[], Any], sleep: Callable[[float], None]) -> Any:
    last: Exception | None = None
    for attempt in range(1, 5):
        try:
            return call()
        except Exception as exc:  # provider failures are classified, never logged verbatim
            last = exc
            if attempt < 4:
                sleep(float(attempt * 2))
    assert last is not None
    raise last


def _trading_sessions(provider: Any, request: DailyMarketDataRequest) -> list[str]:
    raw = _calendar_records(
        provider.trade_days(day_start=request.start_date, day_end=request.end_date)
    )
    sessions: set[str] = set()
    for row in raw:
        session = _iso_day(
            _pick(row, ("cal_date", "calendar_date", "trade_date", "date"))
        )
        if session is None or not request.start_date <= session <= request.end_date:
            continue
        raw_open = _pick(row, ("is_open", "is_trading_day", "trade_status"))
        is_open = _flag(raw_open)
        if is_open is not False:
            sessions.add(session)
    return sorted(sessions)


def _market_rows(
    provider: Any,
    session: str,
    venues: tuple[str, ...],
    sleep: Callable[[float], None],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    compact = session.replace("-", "")
    daily = _records(
        _retry(
            lambda: provider.daily(
                trade_date=compact, limit=6000, fields="all"
            ),
            sleep,
        )
    )
    valuation = _records(
        _retry(
            lambda: provider.finance_pit(table="valuation", trade_date=session),
            sleep,
        )
    )
    caps: dict[str, float] = {}
    names: dict[str, str] = {}
    for row in valuation:
        symbol = _normalize_code(_pick(row, ("code", "ts_code", "stock_code")))
        cap = _finite_number(
            _pick(row, ("market_cap", "total_mv", "total_market_cap"))
        )
        if symbol is not None and cap is not None and cap > 0:
            caps[symbol] = cap
        name = _pick(row, ("name", "code_name", "stock_name"))
        if symbol is not None and name is not None:
            names[symbol] = str(name)

    normalized: dict[str, dict[str, Any]] = {}
    invalid_price_rows = 0
    st_observed_rows = 0
    duplicate_symbols = 0
    for row in daily:
        symbol = _normalize_code(_pick(row, ("ts_code", "code", "stock_code")))
        if symbol is None or symbol.rsplit(".", 1)[1] not in venues:
            continue
        open_price = _finite_number(_pick(row, ("open",)))
        high = _finite_number(_pick(row, ("high",)))
        low = _finite_number(_pick(row, ("low",)))
        close = _finite_number(_pick(row, ("close",)))
        if (
            open_price is None
            or high is None
            or low is None
            or close is None
            or min(open_price, high, low, close) <= 0
            or low > min(open_price, close)
            or high < max(open_price, close)
        ):
            invalid_price_rows += 1
            continue
        volume = _finite_number(_pick(row, ("volume", "vol")))
        paused = _flag(_pick(row, ("is_paused", "paused")))
        raw_st = _flag(_pick(row, ("is_st", "st")))
        name = str(_pick(row, ("name", "code_name")) or names.get(symbol, ""))
        if raw_st is not None or name:
            st_observed_rows += 1
        is_st = raw_st if raw_st is not None else "ST" in name.upper()
        if symbol in normalized:
            duplicate_symbols += 1
        normalized[symbol] = {
            "date": session,
            "symbol": symbol,
            "name": name,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "pre_close": _finite_number(_pick(row, ("pre_close", "preclose"))),
            "volume": volume,
            "amount": _finite_number(_pick(row, ("turnover", "amount"))),
            "turnover_rate": _finite_number(_pick(row, ("turnover_rate", "turn"))),
            "adjustment_factor": _finite_number(_pick(row, ("factor", "adjustment_factor"))),
            "tradable": paused is not True and (volume is None or volume > 0),
            "limit_up": _finite_number(_pick(row, ("high_limit", "limit_up"))),
            "limit_down": _finite_number(_pick(row, ("low_limit", "limit_down"))),
            "is_st": bool(is_st),
            "total_market_cap": caps.get(symbol),
        }
    rows = [normalized[symbol] for symbol in sorted(normalized)]
    return rows, {
        "raw_daily_rows": len(daily),
        "raw_valuation_rows": len(valuation),
        "normalized_rows": len(rows),
        "invalid_price_rows": invalid_price_rows,
        "market_cap_rows": sum(row["total_market_cap"] is not None for row in rows),
        "st_observed_rows": st_observed_rows,
        "duplicate_symbols_removed": duplicate_symbols,
    }


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _scalar(item())
        except (TypeError, ValueError):
            pass
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except (TypeError, ValueError):
            pass
    raw = str(value)
    return None if raw.lower() in {"nan", "nat", "<na>"} else raw


def _financial_rows(
    provider: Any,
    table: str,
    period: str,
    sleep: Callable[[float], None],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    method = getattr(provider, f"finance_{table}")
    raw = _records(_retry(lambda: method(period), sleep))
    normalized: dict[tuple[str, str, str], dict[str, Any]] = {}
    invalid_keys = 0
    oversized_schema_rows = 0
    for row in raw:
        if len(row) > MAX_PROVIDER_COLUMNS:
            oversized_schema_rows += 1
            continue
        symbol = _normalize_code(_pick(row, ("code", "ts_code", "stock_code")))
        statement_date = _iso_day(_pick(row, ("statDate", "stat_date", "report_date")))
        publication_date = _iso_day(_pick(row, ("pubDate", "pub_date", "publish_date")))
        if symbol is None or statement_date is None or publication_date is None:
            invalid_keys += 1
            continue
        fields: dict[str, Any] = {}
        for key, value in row.items():
            name = str(key)
            if name in {
                "code", "ts_code", "stock_code", "statDate", "stat_date",
                "report_date", "pubDate", "pub_date", "publish_date",
            }:
                continue
            if not name or len(name) > MAX_PROVIDER_FIELD_NAME:
                continue
            fields[name] = _scalar(value)
        key = (symbol, statement_date, publication_date)
        normalized[key] = {
            "symbol": symbol,
            "statement_date": statement_date,
            "publication_date": publication_date,
            "source_period": period,
            "fields": {name: fields[name] for name in sorted(fields)},
        }
    rows = [normalized[key] for key in sorted(normalized)]
    return rows, {
        "raw_rows": len(raw),
        "normalized_rows": len(rows),
        "invalid_key_rows": invalid_keys,
        "oversized_schema_rows": oversized_schema_rows,
        "duplicate_event_rows_removed": max(
            0, len(raw) - invalid_keys - oversized_schema_rows - len(rows)
        ),
    }


def _run_market_group(
    request: DailyMarketDataRequest,
    group: int,
    provider: Any,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    try:
        sessions = _trading_sessions(provider, request)
    except Exception as exc:
        sessions = []
        failures.append({"unit": "calendar", "error_type": type(exc).__name__})
    assigned = [session for index, session in enumerate(sessions) if index % 4 == group]
    rows: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    for session in assigned:
        try:
            batch, audit = _market_rows(provider, session, request.venues, sleep)
            rows.extend(batch)
            calls.append({"session": session, "ok": bool(batch), **audit})
            if not batch:
                failures.append({"unit": session, "error_type": "EmptySnapshot"})
        except Exception as exc:
            calls.append({"session": session, "ok": False})
            failures.append({"unit": session, "error_type": type(exc).__name__})
        sleep(REQUEST_PACE_SECONDS)
    rows.sort(key=lambda item: (item["date"], item["symbol"]))
    return {
        "schema_version": 1,
        "job_id": request.job_id,
        "task": "daily_market_snapshot_v1",
        "provider": request.provider,
        "group": group,
        "group_count": request.group_count,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "venues": list(request.venues),
        "session_count": len(assigned),
        "sessions": assigned,
        "row_count": len(rows),
        "rows": rows,
        "audit": {"calls": calls, "failures": failures},
        "status": "PASS" if not failures else "FAILED_RETRYABLE",
    }


def _run_financial_group(
    request: FinancialEventsRequest,
    group: int,
    provider: Any,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    assigned = [period for index, period in enumerate(request.periods) if index % 4 == group]
    rows: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for period in assigned:
        try:
            batch, audit = _financial_rows(
                provider, request.table, period, sleep
            )
            rows.extend(batch)
            calls.append({"period": period, "ok": bool(batch), **audit})
            if not batch:
                failures.append({"unit": period, "error_type": "EmptyPeriod"})
        except Exception as exc:
            calls.append({"period": period, "ok": False})
            failures.append({"unit": period, "error_type": type(exc).__name__})
        sleep(REQUEST_PACE_SECONDS)
    rows.sort(
        key=lambda item: (
            item["symbol"], item["statement_date"], item["publication_date"]
        )
    )
    return {
        "schema_version": 1,
        "job_id": request.job_id,
        "task": "pit_financial_events_v1",
        "provider": request.provider,
        "group": group,
        "group_count": request.group_count,
        "table": request.table,
        "period_count": len(assigned),
        "periods": assigned,
        "row_count": len(rows),
        "rows": rows,
        "audit": {"calls": calls, "failures": failures},
        "status": "PASS" if not failures else "FAILED_RETRYABLE",
    }


def run_data_group(
    request: DataRequest,
    group: int,
    *,
    provider: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not 0 <= group < request.group_count:
        raise ValueError("group is outside the workflow range")
    active_provider = provider if provider is not None else _provider()
    if isinstance(request, DailyMarketDataRequest):
        return _run_market_group(request, group, active_provider, sleep)
    return _run_financial_group(request, group, active_provider, sleep)
