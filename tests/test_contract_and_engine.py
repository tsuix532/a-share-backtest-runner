from __future__ import annotations

import copy
import unittest

from public_runner.contract import ContractError, validate_request
from public_runner.engine import run_case


JOB_ID = "1" * 32


def sample_request() -> dict:
    bars = []
    for session, prices in [
        ("2026-01-05", (10.0, 10.5, 9.8, 10.2)),
        ("2026-01-06", (10.3, 10.8, 10.1, 10.6)),
    ]:
        bars.append({
            "date": session, "symbol": "600000.SH", "open": prices[0],
            "high": prices[1], "low": prices[2], "close": prices[3],
            "tradable": True, "limit_up": 11.0, "limit_down": 9.0,
        })
    return {
        "schema_version": 1,
        "job_id": JOB_ID,
        "task": "daily_order_replay_v1",
        "batch_only": True,
        "group_count": 4,
        "cases": [{
            "case_id": "smoke-20bps",
            "partition": 0,
            "initial_cash": 100000.0,
            "cost_bps": 20,
            "bars": bars,
            "intents": [
                {
                    "intent_id": "buy-1", "decision_date": "2026-01-04",
                    "execution_date": "2026-01-05", "symbol": "600000.SH",
                    "side": "BUY", "execution": "MARKET_OPEN", "quantity": 100,
                    "limit_price": None, "reason_code": "OPAQUE_ENTRY",
                },
                {
                    "intent_id": "sell-same-day", "decision_date": "2026-01-05",
                    "execution_date": "2026-01-05", "symbol": "600000.SH",
                    "side": "SELL", "execution": "MARKET_CLOSE", "quantity": 100,
                    "limit_price": None, "reason_code": "OPAQUE_EXIT_A",
                },
                {
                    "intent_id": "sell-next-day", "decision_date": "2026-01-05",
                    "execution_date": "2026-01-06", "symbol": "600000.SH",
                    "side": "SELL", "execution": "MARKET_OPEN", "quantity": 100,
                    "limit_price": None, "reason_code": "OPAQUE_EXIT_B",
                },
            ],
        }],
    }


class ContractAndEngineTests(unittest.TestCase):
    def test_valid_case_enforces_t_plus_one(self) -> None:
        request = validate_request(sample_request(), JOB_ID)
        result = run_case(request.cases[0])
        self.assertEqual(result["trade_count"], 2)
        self.assertEqual(result["rejected_count"], 1)
        self.assertEqual(result["rejected"][0]["reason"], "T_PLUS_ONE_OR_POSITION")
        self.assertGreater(result["final_equity"], 100000.0)

    def test_unknown_root_field_is_rejected(self) -> None:
        value = sample_request()
        value["strategy"] = "private"
        with self.assertRaises(ContractError):
            validate_request(value, JOB_ID)

    def test_duplicate_case_is_rejected(self) -> None:
        value = sample_request()
        value["cases"].append(copy.deepcopy(value["cases"][0]))
        with self.assertRaises(ContractError):
            validate_request(value, JOB_ID)


if __name__ == "__main__":
    unittest.main()

