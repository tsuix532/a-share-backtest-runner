from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .contract import Bar, Intent, ReplayCase


def _fill_price(intent: Intent, bar: Bar) -> float | None:
    if not bar.tradable:
        return None
    if intent.execution == "MARKET_OPEN":
        price = bar.open
    elif intent.execution == "MARKET_CLOSE":
        price = bar.close
    else:
        assert intent.limit_price is not None
        if intent.side == "BUY":
            if bar.low > intent.limit_price:
                return None
            price = bar.open if bar.open <= intent.limit_price else intent.limit_price
        else:
            if bar.high < intent.limit_price:
                return None
            price = bar.open if bar.open >= intent.limit_price else intent.limit_price
    if intent.side == "BUY" and bar.limit_up is not None and price >= bar.limit_up:
        return None
    if intent.side == "SELL" and bar.limit_down is not None and price <= bar.limit_down:
        return None
    return price


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def run_case(case: ReplayCase) -> dict[str, Any]:
    bars = {(bar.session, bar.symbol): bar for bar in case.bars}
    sessions = sorted({bar.session for bar in case.bars})
    intents_by_session: dict[str, list[Intent]] = {}
    for intent in case.intents:
        intents_by_session.setdefault(intent.execution_date, []).append(intent)

    cash = case.initial_cash
    lots: dict[str, list[list[Any]]] = {}
    trades: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    equity_curve: list[dict[str, float | str]] = []
    turnover = 0.0

    for session in sessions:
        todays = sorted(intents_by_session.get(session, []), key=lambda item: (item.side != "SELL", item.intent_id))
        for intent in todays:
            bar = bars.get((session, intent.symbol))
            if bar is None:
                rejected.append({"intent_id": intent.intent_id, "reason": "MISSING_BAR"})
                continue
            price = _fill_price(intent, bar)
            if price is None:
                rejected.append({"intent_id": intent.intent_id, "reason": "NOT_FILLABLE"})
                continue
            notional = price * intent.quantity
            fee = notional * case.cost_bps / 10000.0
            symbol_lots = lots.setdefault(intent.symbol, [])
            if intent.side == "BUY":
                if intent.quantity % 100 != 0:
                    rejected.append({"intent_id": intent.intent_id, "reason": "BOARD_LOT"})
                    continue
                if cash + 1e-9 < notional + fee:
                    rejected.append({"intent_id": intent.intent_id, "reason": "INSUFFICIENT_CASH"})
                    continue
                cash -= notional + fee
                symbol_lots.append([session, intent.quantity])
            else:
                sellable = sum(quantity for acquired, quantity in symbol_lots if acquired < session)
                if sellable < intent.quantity:
                    rejected.append({"intent_id": intent.intent_id, "reason": "T_PLUS_ONE_OR_POSITION"})
                    continue
                remaining = intent.quantity
                for lot in symbol_lots:
                    if lot[0] >= session or remaining == 0:
                        continue
                    used = min(lot[1], remaining)
                    lot[1] -= used
                    remaining -= used
                symbol_lots[:] = [lot for lot in symbol_lots if lot[1] > 0]
                cash += notional - fee
            turnover += notional
            trades.append({
                "intent_id": intent.intent_id,
                "date": session,
                "symbol": intent.symbol,
                "side": intent.side,
                "quantity": intent.quantity,
                "price": round(price, 8),
                "fee": round(fee, 8),
                "reason_code": intent.reason_code,
            })

        holdings_value = 0.0
        for symbol, symbol_lots in lots.items():
            quantity = sum(lot[1] for lot in symbol_lots)
            if quantity == 0:
                continue
            bar = bars.get((session, symbol))
            if bar is None:
                raise RuntimeError("held symbol is missing a valuation bar")
            holdings_value += quantity * bar.close
        equity_curve.append({"date": session, "equity": round(cash + holdings_value, 8)})

    values = [float(item["equity"]) for item in equity_curve]
    final_equity = values[-1]
    return {
        "case_id": case.case_id,
        "status": "PASS",
        "initial_cash": case.initial_cash,
        "final_equity": round(final_equity, 8),
        "total_return": round(final_equity / case.initial_cash - 1.0, 12),
        "max_drawdown": round(_max_drawdown(values), 12),
        "turnover": round(turnover, 8),
        "trade_count": len(trades),
        "rejected_count": len(rejected),
        "trades": trades,
        "rejected": rejected,
        "equity_curve": equity_curve,
    }

