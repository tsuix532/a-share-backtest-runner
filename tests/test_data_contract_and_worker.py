from __future__ import annotations

import copy
import unittest

from public_runner.contract import ContractError
from public_runner.data_contract import validate_data_request
from public_runner.data_worker import run_data_group


JOB_ID = "2" * 32


def market_request() -> dict:
    return {
        "schema_version": 1,
        "job_id": JOB_ID,
        "task": "daily_market_snapshot_v1",
        "batch_only": True,
        "group_count": 4,
        "provider": "zzshare-0.4.9",
        "start_date": "2026-01-05",
        "end_date": "2026-01-08",
        "venues": ["SH", "SZ"],
    }


def financial_request() -> dict:
    return {
        "schema_version": 1,
        "job_id": JOB_ID,
        "task": "pit_financial_events_v1",
        "batch_only": True,
        "group_count": 4,
        "provider": "zzshare-0.4.9",
        "table": "indicator",
        "periods": ["2025q3", "2025q4"],
    }


class FakeProvider:
    def trade_days(self, **_: object) -> list[dict[str, object]]:
        return [
            {"cal_date": "20260105", "is_open": 1},
            {"cal_date": "20260106", "is_open": 1},
            {"cal_date": "20260107", "is_open": 1},
            {"cal_date": "20260108", "is_open": 1},
        ]

    def daily(self, *, trade_date: str, **_: object) -> list[dict[str, object]]:
        return [
            {
                "ts_code": "600000.SH",
                "trade_date": trade_date,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "prev_close": 10,
                "volume": 10000,
                "turnover": 105000,
                "turnover_rate": 1.2,
                "factor": 1.0,
                "high_limit": 11,
                "low_limit": 9,
                "is_paused": 0,
                "is_st": 0,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": trade_date,
                "open": 8,
                "high": 8.5,
                "low": 7.5,
                "close": 8.2,
                "volume": 0,
                "is_paused": 1,
                "is_st": 1,
                "high_limit": 0,
                "low_limit": 0,
            },
        ]

    def finance_pit(self, **_: object) -> list[dict[str, object]]:
        return [
            {"code": "600000", "market_cap": 1000, "name": "浦发银行"},
            {"code": "000001", "market_cap": 900, "name": "测试ST"},
        ]

    def finance_indicator(self, period: str) -> list[dict[str, object]]:
        return [
            {
                "code": "600000",
                "statDate": "2025-12-31" if period == "2025q4" else "2025-09-30",
                "pubDate": "2026-03-20" if period == "2025q4" else "2025-10-30",
                "roe": 7.5,
                "inc_revenue_year_on_year": 3.2,
            }
        ]


class DataContractAndWorkerTests(unittest.TestCase):
    def test_market_contract_is_bounded(self) -> None:
        value = market_request()
        value["end_date"] = "2026-03-01"
        with self.assertRaises(ContractError):
            validate_data_request(value, JOB_ID)

        value = market_request()
        value["venues"] = ["SZ", "SH"]
        with self.assertRaises(ContractError):
            validate_data_request(value, JOB_ID)

    def test_market_group_fetches_only_its_sessions(self) -> None:
        request = validate_data_request(market_request(), JOB_ID)
        result = run_data_group(
            request, 1, provider=FakeProvider(), sleep=lambda _: None
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sessions"], ["2026-01-06"])
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["rows"][0]["total_market_cap"], 900.0)
        self.assertFalse(result["rows"][0]["tradable"])
        self.assertTrue(result["rows"][0]["is_st"])
        self.assertIsNone(result["rows"][0]["limit_up"])
        self.assertIsNone(result["rows"][0]["limit_down"])
        self.assertEqual(result["rows"][1]["pre_close"], 10.0)

    def test_calendar_accepts_a_plain_date_list(self) -> None:
        class ListCalendarProvider(FakeProvider):
            def trade_days(self, **_: object) -> list[str]:
                return ["20260105", "20260106"]

        request = validate_data_request(market_request(), JOB_ID)
        result = run_data_group(
            request, 0, provider=ListCalendarProvider(), sleep=lambda _: None
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sessions"], ["2026-01-05"])

    def test_financial_events_preserve_publication_date(self) -> None:
        request = validate_data_request(financial_request(), JOB_ID)
        result = run_data_group(
            request, 0, provider=FakeProvider(), sleep=lambda _: None
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["periods"], ["2025q3"])
        self.assertEqual(result["rows"][0]["publication_date"], "2025-10-30")
        self.assertEqual(result["rows"][0]["fields"]["roe"], 7.5)

    def test_unknown_data_field_is_rejected(self) -> None:
        value = copy.deepcopy(financial_request())
        value["strategy"] = "must-remain-private"
        with self.assertRaises(ContractError):
            validate_data_request(value, JOB_ID)


if __name__ == "__main__":
    unittest.main()
