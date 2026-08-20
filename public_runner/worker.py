from __future__ import annotations

from typing import Any

from .contract import Request
from .engine import run_case


def run_group(request: Request, group: int) -> dict[str, Any]:
    if not 0 <= group < request.group_count:
        raise ValueError("group is outside the workflow range")
    results = [run_case(case) for case in request.cases_for_group(group)]
    return {
        "schema_version": 1,
        "job_id": request.job_id,
        "task": "daily_order_replay_v1",
        "group": group,
        "group_count": request.group_count,
        "case_count": len(results),
        "cases": results,
        "status": "PASS",
    }

