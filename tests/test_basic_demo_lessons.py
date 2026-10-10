"""基本6主題と期間別教材を実エンジン・公開の独立検証で確かめる。"""

import copy
import json
from collections import Counter
from datetime import datetime

import pytest

from shift_schedula import solve, verify
from tests.test_playground_scenarios import SAMPLES, scenario_requests

LESSONS = [
    x for x in json.loads((SAMPLES / "lessons.json").read_text()) if x.get("module") == "basic"
]


def minutes(interval):
    return (
        datetime.fromisoformat(interval["end"]) - datetime.fromisoformat(interval["start"])
    ).total_seconds() / 60


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x["id"])
def test_basic_lesson_meaning_and_public_verification(lesson):
    baseline = json.loads((SAMPLES / lesson["request_file"]).read_text())
    saved = copy.deepcopy(baseline)
    for step, request in scenario_requests(lesson, baseline):
        before = copy.deepcopy(request)
        result = solve(request, num_workers=1)
        expected = step["expected"]
        assert request == before
        assert result["status"] == expected["status"]
        assert (
            result["shortage_summary"]["total_person_minutes"] == expected["total_person_minutes"]
        )
        assert result["shortage_summary"]["proven_minimal"]
        checked = verify(request, result["solution"])
        assert checked["status"] == ("PARTIAL" if expected["total_person_minutes"] else "VALID")
        assert checked["verification"]["valid"]
        assert not checked["shortage_summary"]["proven_minimal"]
        shifts = result["solution"]["shifts"]
        assignments = result["solution"]["assignments"]
        assert sum(minutes(x["interval"]) for x in assignments) == expected["assigned_minutes"]
        assert (
            sum(
                minutes(s["interval"]) - sum(minutes(b) for b in s["breaks"])
                for shift in shifts
                for s in shift["segments"]
            )
            == expected["original_work_minutes"]
        )
        if lesson["id"] == "skills":
            required = request["roles"][0]["required_skills"][0]
            qualified = {
                e["id"]
                for e in request["employees"]
                if any(
                    s["skill_id"] == required["skill_id"] and s["level"] >= required["min_level"]
                    for s in e["skills"]
                )
            }
            assert len(qualified) == (
                0 if step["id"] == "lower" else 2 if step["id"] == "requirement" else 1
            )
            assert {a["employee_id"] for a in assignments} <= qualified
        if lesson["id"] == "shift_candidates" and step["id"] in {"later", "shorter"}:
            assert shifts[0]["candidate_id"] == "direct"
            assert shifts[0]["segments"] == request["shift_candidates"][0]["segments"]
        if lesson["id"] == "breaks":
            main = next(s for s in shifts if s["employee_id"] == "a")
            assert (
                main["segments"][0]["breaks"]
                == request["shift_candidates"][0]["segments"][0]["breaks"]
            )
            assert sum(minutes(b) for b in main["segments"][0]["breaks"]) == 60
            # 13〜14時の待機は勤務量に含むが担当時間には含めない。
            assert expected["original_work_minutes"] - expected["assigned_minutes"] == 60
        for shift in shifts:
            assert shift["work_day"] == shift["segments"][0]["interval"]["start"][:10]
            for first, second in zip(shift["segments"], shift["segments"][1:], strict=False):
                gap = minutes(
                    {"start": first["interval"]["end"], "end": second["interval"]["start"]}
                )
                assert gap >= request["constraints"][0]["limit_minutes"]
        if lesson["id"] == "split_shift" and step["id"] == "long_gap":
            assert shifts == []
            assert request["demand"] == baseline["demand"]
        if lesson["id"].startswith("coverage_"):
            assert request["continuity"] == baseline["continuity"]
            assert request["shift_templates"] == baseline["shift_templates"]
            if step["id"] in {"initial", "restored", "night_need"}:
                night = max(shifts, key=lambda s: s["segments"][-1]["interval"]["end"])
                assert datetime.fromisoformat(
                    night["segments"][-1]["interval"]["end"]
                ) > datetime.fromisoformat(request["planning_window"]["end"])
                assert (
                    night["segments"][-1]["breaks"][0]["start"] == request["planning_window"]["end"]
                )
            if step["id"] == "rest":
                assert Counter(s["employee_id"] for s in shifts).most_common(1)[0][1] == 1
                unchanged = copy.deepcopy(request)
                unchanged["constraints"] = baseline["constraints"]
                assert unchanged == baseline
        if step["id"] in {"initial", "restored"}:
            assert request == baseline
    assert baseline == saved
