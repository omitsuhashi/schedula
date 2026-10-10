"""担当時間・勤務量・休息の教材を公開検証と独立した分数計算で確認する。"""

import copy
import json
from datetime import datetime

import pytest

from shift_schedula import solve, verify
from tests.test_playground_scenarios import SAMPLES, scenario_requests

LESSONS = [
    x for x in json.loads((SAMPLES / "lessons.json").read_text()) if x.get("module") == "conditions"
]


def minutes(interval, window=None):
    start, end = (datetime.fromisoformat(interval[k]) for k in ("start", "end"))
    if window:
        start = max(start, datetime.fromisoformat(window["start"]))
        end = min(end, datetime.fromisoformat(window["end"]))
    return max(0, (end - start).total_seconds() / 60)


def work(shifts, window=None):
    return sum(
        minutes(s["interval"], window) - sum(minutes(b, window) for b in s["breaks"])
        for shift in shifts
        for s in shift["segments"]
    )


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x["id"])
def test_condition_lesson_meaning_and_public_verification(lesson):
    baseline = json.loads((SAMPLES / lesson["request_file"]).read_text())
    saved = copy.deepcopy(baseline)
    for step, request in scenario_requests(lesson, baseline):
        before = copy.deepcopy(request)
        result = solve(request, num_workers=1)
        expected = step["expected"]
        assert request == before
        assert result["status"] == expected["status"]
        assert request["demand"] == baseline["demand"]
        if result["status"] == "INFEASIBLE":
            assert result["solution"] is None
            assert result["shortage_summary"] is None
            assert request["constraints"][0]["min_minutes"] == 270
            assert work(request["shift_candidates"][:2]) == 180
            continue
        checked = verify(request, result["solution"])
        assert checked["verification"]["valid"]
        assert checked["status"] == ("PARTIAL" if expected["total_person_minutes"] else "VALID")
        assert not checked["shortage_summary"]["proven_minimal"]
        assert result["shortage_summary"]["proven_minimal"]
        assert (
            result["shortage_summary"]["total_person_minutes"] == expected["total_person_minutes"]
        )
        assignments, shifts = result["solution"]["assignments"], result["solution"]["shifts"]
        assert sum(minutes(a["interval"]) for a in assignments) == expected["assigned_minutes"]
        assert work(shifts) == expected["original_work_minutes"]
        rule = request["constraints"][0]
        subject = [s for s in shifts if s["employee_id"] == "a"]
        if lesson["id"] == "assigned_limit":
            actual = sum(minutes(a["interval"]) for a in assignments if a["employee_id"] == "a")
            assert actual <= rule["limit_minutes"]
        elif lesson["id"] == "scheduled_limit":
            assert work(subject) <= rule["limit_minutes"]
            if step["id"] != "lower":
                assert work(subject) == 240
                assert work(shifts) - sum(minutes(a["interval"]) for a in assignments) == 60
        elif lesson["id"] == "scheduled_bounds":
            known = request["continuity"]["employees"][0]
            actual = work(
                subject + known["actual_shifts"] + known["committed_shifts"], rule["interval"]
            )
            assert rule["min_minutes"] <= actual <= rule["max_minutes"]
            if step["id"] == "month":
                assert actual == 300
                assert not subject
            if step["id"] == "minimum":
                assert actual == 180
        else:
            ordered = sorted(subject, key=lambda s: s["segments"][0]["interval"]["start"])
            for first, next_shift in zip(ordered, ordered[1:], strict=False):
                gap = minutes(
                    {
                        "start": first["segments"][-1]["interval"]["end"],
                        "end": next_shift["segments"][0]["interval"]["start"],
                    }
                )
                assert gap >= rule["limit_minutes"]
            assert len(subject) == (1 if step["id"] == "longer" else 2)
        if step["id"] == "restored":
            assert request == baseline
    assert baseline == saved


def test_period_bounds_reject_inverted_limits_without_relaxing():
    request = json.loads((SAMPLES / "scheduled-bounds.json").read_text())
    request["constraints"][0].update(min_minutes=390, max_minutes=360)
    result = solve(request)
    assert result["status"] == "INVALID_INPUT"
    assert result["solution"] is None
    assert request["constraints"][0]["min_minutes"] == 390
