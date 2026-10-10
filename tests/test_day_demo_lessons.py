"""勤務日・占有日・完全休日を公開検証と別の日付集計で確認する。"""

import copy
import json
from datetime import datetime, timedelta

import pytest

from shift_schedula import solve, verify
from tests.test_playground_scenarios import SAMPLES, scenario_requests

LESSONS = [
    x for x in json.loads((SAMPLES / "lessons.json").read_text()) if x.get("module") == "days"
]


def independent_counts(request, solution):
    known = request["continuity"]["employees"][0]
    facts = (
        known["actual_shifts"]
        + known["committed_shifts"]
        + [s for s in solution["shifts"] if "committed_shift_id" not in s]
    )
    start, end = (
        datetime.fromisoformat(request["constraints"][0]["interval"][k]) for k in ("start", "end")
    )
    work = {
        datetime.fromisoformat(s["segments"][0]["interval"]["start"]).date()
        for s in facts
        if start <= datetime.fromisoformat(s["segments"][0]["interval"]["start"]) < end
    }
    occupied, day = set(), start
    while day < end:
        if any(
            datetime.fromisoformat(t["interval"]["start"]) < day + timedelta(days=1)
            and day < datetime.fromisoformat(t["interval"]["end"])
            for s in facts
            for t in s["segments"]
        ):
            occupied.add(day.date())
        day += timedelta(days=1)
    return {
        "employee_id": "a",
        "work_days": len(work),
        "occupied_days": len(occupied),
        "days_off": (end - start).days - len(occupied),
    }


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x["id"])
def test_day_lesson_counts_and_public_verification(lesson):
    baseline = json.loads((SAMPLES / lesson["request_file"]).read_text())
    saved = copy.deepcopy(baseline)
    for step, request in scenario_requests(lesson, baseline):
        before = copy.deepcopy(request)
        result = solve(request, num_workers=1)
        assert request == before
        assert request["demand"] == baseline["demand"]
        assert request["continuity"] == baseline["continuity"]
        expected = step["expected"]
        assert result["status"] == expected["status"]
        if not result["solution"]:
            assert result["shortage_summary"] is None and result["day_count_summary"] is None
            if step["id"] == "future":
                assert "INVALID_DAY_COUNT_INTERVAL" in {d["code"] for d in result["diagnostics"]}
            continue
        checked = verify(request, result["solution"])
        assert checked["verification"]["valid"]
        assert not checked["shortage_summary"]["proven_minimal"]
        assert result["shortage_summary"]["proven_minimal"]
        assert (
            result["shortage_summary"]["total_person_minutes"] == expected["total_person_minutes"]
        )
        counts = independent_counts(request, result["solution"])
        assert counts == expected["day_counts"]
        assert result["day_count_summary"][0]["employees"][0] == counts
        assert checked["day_count_summary"] == result["day_count_summary"]
        rule = request["constraints"][0]
        actual = counts["work_days" if lesson["id"] == "work_days" else "days_off"]
        assert rule["min_days"] <= actual <= rule["max_days"]
        if step["id"] == "last_day":
            assert counts["work_days"] == counts["occupied_days"] == 0
        if step["id"] == "restored":
            assert request == baseline
    assert baseline == saved


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x["id"])
def test_day_bounds_and_history_remain_trust_boundaries(lesson):
    request = json.loads((SAMPLES / lesson["request_file"]).read_text())
    request["constraints"][0].update(min_days=3, max_days=2)
    result = solve(request)
    assert result["status"] == "INVALID_INPUT" and result["solution"] is None
    request["constraints"][0].update(min_days=0, max_days=5)
    request["constraints"][0]["interval"]["start"] = "2026-10-04T00:00:00+09:00"
    request["continuity"]["employees"][0]["past_complete"] = False
    result = solve(request)
    assert result["status"] == "INVALID_INPUT" and result["solution"] is None
    assert "INCOMPLETE_HISTORY" in {d["code"] for d in result["diagnostics"]}
