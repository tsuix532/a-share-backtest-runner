from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import re
from typing import Any


JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
CASE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SYMBOL_RE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
ROOT_KEYS = {"schema_version", "job_id", "task", "batch_only", "group_count", "cases"}
CASE_KEYS = {"case_id", "partition", "initial_cash", "cost_bps", "bars", "intents"}
BAR_KEYS = {"date", "symbol", "open", "high", "low", "close", "tradable", "limit_up", "limit_down"}
INTENT_KEYS = {
    "intent_id", "decision_date", "execution_date", "symbol", "side",
    "execution", "quantity", "limit_price", "reason_code"
}


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class Bar:
    session: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    tradable: bool
    limit_up: float | None
    limit_down: float | None


@dataclass(frozen=True)
class Intent:
    intent_id: str
    decision_date: str
    execution_date: str
    symbol: str
    side: str
    execution: str
    quantity: int
    limit_price: float | None
    reason_code: str


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    partition: int
    initial_cash: float
    cost_bps: float
    bars: tuple[Bar, ...]
    intents: tuple[Intent, ...]


@dataclass(frozen=True)
class Request:
    job_id: str
    group_count: int
    cases: tuple[ReplayCase, ...]

    def cases_for_group(self, group: int) -> tuple[ReplayCase, ...]:
        return tuple(case for case in self.cases if case.partition % self.group_count == group)


def _iso_date(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO date") from exc
    if not date(2000, 1, 1) <= parsed <= date(2035, 12, 31):
        raise ContractError(f"{label} is outside the allowed range")
    return parsed.isoformat()


def _number(value: Any, label: str, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or (positive and normalized <= 0):
        raise ContractError(f"{label} is invalid")
    return normalized


def validate_request(value: Any, expected_job_id: str) -> Request:
    if not isinstance(value, dict) or set(value) != ROOT_KEYS:
        raise ContractError("request fields do not match the batch contract")
    if value.get("schema_version") != 1 or value.get("task") != "daily_order_replay_v1":
        raise ContractError("request protocol is unsupported")
    if value.get("batch_only") is not True:
        raise ContractError("request must declare the batch-only boundary")
    job_id = value.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id) or job_id != expected_job_id:
        raise ContractError("job id is invalid")
    group_count = value.get("group_count")
    if group_count != 4:
        raise ContractError("group_count must match the fixed workflow")
    raw_cases = value.get("cases")
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 128:
        raise ContractError("cases must contain between 1 and 128 items")

    cases: list[ReplayCase] = []
    seen_cases: set[str] = set()
    for case_index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict) or set(raw_case) != CASE_KEYS:
            raise ContractError("case fields do not match the contract")
        case_id = raw_case.get("case_id")
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id) or case_id in seen_cases:
            raise ContractError("case id is invalid or duplicated")
        partition = raw_case.get("partition")
        if not isinstance(partition, int) or not 0 <= partition <= 255:
            raise ContractError("partition is invalid")
        initial_cash = _number(raw_case.get("initial_cash"), "initial_cash")
        cost_bps = _number(raw_case.get("cost_bps"), "cost_bps", positive=False)
        if not 0 <= cost_bps <= 500:
            raise ContractError("cost_bps is outside the allowed range")

        bars: list[Bar] = []
        seen_bars: set[tuple[str, str]] = set()
        raw_bars = raw_case.get("bars")
        if not isinstance(raw_bars, list) or not 1 <= len(raw_bars) <= 500000:
            raise ContractError("bars are missing or exceed the safety limit")
        for raw_bar in raw_bars:
            if not isinstance(raw_bar, dict) or set(raw_bar) != BAR_KEYS:
                raise ContractError("bar fields do not match the contract")
            session = _iso_date(raw_bar.get("date"), "bar.date")
            symbol = raw_bar.get("symbol")
            if not isinstance(symbol, str) or not SYMBOL_RE.fullmatch(symbol):
                raise ContractError("bar symbol is invalid")
            key = (session, symbol)
            if key in seen_bars:
                raise ContractError("bar is duplicated")
            prices = [_number(raw_bar.get(name), f"bar.{name}") for name in ("open", "high", "low", "close")]
            if prices[2] > prices[1] or not prices[2] <= prices[0] <= prices[1] or not prices[2] <= prices[3] <= prices[1]:
                raise ContractError("bar OHLC values are inconsistent")
            tradable = raw_bar.get("tradable")
            if not isinstance(tradable, bool):
                raise ContractError("bar.tradable must be boolean")
            limit_up = raw_bar.get("limit_up")
            limit_down = raw_bar.get("limit_down")
            normalized_up = None if limit_up is None else _number(limit_up, "bar.limit_up")
            normalized_down = None if limit_down is None else _number(limit_down, "bar.limit_down")
            bars.append(Bar(session, symbol, *prices, tradable, normalized_up, normalized_down))
            seen_bars.add(key)

        intents: list[Intent] = []
        seen_intents: set[str] = set()
        raw_intents = raw_case.get("intents")
        if not isinstance(raw_intents, list) or len(raw_intents) > 500000:
            raise ContractError("intents exceed the safety limit")
        for raw_intent in raw_intents:
            if not isinstance(raw_intent, dict) or set(raw_intent) != INTENT_KEYS:
                raise ContractError("intent fields do not match the contract")
            intent_id = raw_intent.get("intent_id")
            if not isinstance(intent_id, str) or not CASE_ID_RE.fullmatch(intent_id) or intent_id in seen_intents:
                raise ContractError("intent id is invalid or duplicated")
            decision_date = _iso_date(raw_intent.get("decision_date"), "intent.decision_date")
            execution_date = _iso_date(raw_intent.get("execution_date"), "intent.execution_date")
            if decision_date > execution_date:
                raise ContractError("intent executes before its decision")
            symbol = raw_intent.get("symbol")
            if not isinstance(symbol, str) or not SYMBOL_RE.fullmatch(symbol):
                raise ContractError("intent symbol is invalid")
            side = raw_intent.get("side")
            execution = raw_intent.get("execution")
            if side not in {"BUY", "SELL"} or execution not in {"MARKET_OPEN", "MARKET_CLOSE", "LIMIT"}:
                raise ContractError("intent side or execution is unsupported")
            quantity = raw_intent.get("quantity")
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                raise ContractError("intent quantity must be positive integer")
            limit_price = raw_intent.get("limit_price")
            if execution == "LIMIT":
                normalized_limit = _number(limit_price, "intent.limit_price")
            elif limit_price is not None:
                raise ContractError("non-limit intent cannot carry limit_price")
            else:
                normalized_limit = None
            reason_code = raw_intent.get("reason_code")
            if not isinstance(reason_code, str) or not CASE_ID_RE.fullmatch(reason_code):
                raise ContractError("reason_code must be opaque and bounded")
            intents.append(Intent(intent_id, decision_date, execution_date, symbol, side, execution, quantity, normalized_limit, reason_code))
            seen_intents.add(intent_id)

        cases.append(ReplayCase(case_id, partition, initial_cash, cost_bps, tuple(bars), tuple(intents)))
        seen_cases.add(case_id)
    return Request(job_id, group_count, tuple(cases))

