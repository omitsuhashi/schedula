"""先行教材の指標変化と、残る主題の担当・契約対応を確認する。"""

import copy
import json
from collections import Counter
from datetime import date, datetime, timedelta

import pytest

from shift_schedula import get_schema, solve, verify
from tests.support import assert_response
from tests.test_playground_scenarios import SAMPLES, scenario_requests

CATALOG = json.loads((SAMPLES / "catalog.json").read_text(encoding="utf-8"))
LESSONS = json.loads((SAMPLES / "lessons.json").read_text(encoding="utf-8"))


def test_catalog_covers_contract_and_tracks_supplemental_templates():
    topics = CATALOG["topics"]
    assert len(topics) == 44
    assert Counter(t["group"] for t in topics) == {
        "basic": 7,
        "conditions": 13,
        "objectives": 10,
        "shortage": 3,
        "replanning": 5,
        "input": 6,
    }
    features = {f for t in topics for f in t["features"]}
    properties = get_schema("request", "0.15")["properties"]
    rules = properties["constraints"]["items"]["oneOf"]
    assert {r["properties"]["type"]["const"] for r in rules} <= features
    assert {"avoid_role", "prefer_work", "avoid_work"} <= features
    assert set(properties["objectives"]["items"]["properties"]["metric"]["enum"]) <= features
    assert {
        "history",
        "continuity",
        "baseline",
        "fixed_parts",
        "diagnosis",
        "allowed_changes",
        "verify",
        "split_request",
        "assemble",
        "confirm_source",
        "create_record",
        "check_record",
    } <= features
    entries = topics + CATALOG["templates"]
    assert len({t["id"] for t in entries}) == len(entries)
    assert {t["planning_hours"] for t in CATALOG["templates"]} == {24, 48}
    for topic in entries:
        assert topic["contract"] == "0.15"
        assert topic["issue"] in {119, 122, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137}
        assert set(topic["progress"]) == {"detail", "measurement", "screen", "test"}
        assert set(topic["progress"].values()) <= {"pending", "confirmed"}
        assert all((SAMPLES.parents[1] / p).is_file() for p in topic["materials"])
    for template in CATALOG["templates"]:
        assert template["issue"] == 127
        assert template["integration_issue"] == 120
        assert template["acceptance_issue"] == 123
    assert {t["id"] for t in topics if "lesson_file" in t} == {lesson["id"] for lesson in LESSONS}


def work_runs(request, solution):
    """開始日の勤務日と明示履歴から連勤・初日のまとまりを数える。"""
    first = date.fromisoformat(request["planning_window"]["start"][:10])
    end = date.fromisoformat(request["planning_window"]["end"][:10])
    longest, first_runs = {}, {}
    for employee in request["employees"]:
        days = {
            date.fromisoformat(s["work_day"])
            for s in solution["shifts"]
            if s["employee_id"] == employee["id"]
        }
        run = employee["history"]["consecutive_work_days_before_window"]
        maximum = run
        prefix = 0
        day = first
        while day < end:
            run = run + 1 if day in days else 0
            maximum = max(maximum, run)
            if day == first + timedelta(days=prefix) and day in days:
                prefix += 1
            day += timedelta(days=1)
        longest[employee["id"]] = maximum
        first_runs[employee["id"]] = prefix
    return longest, first_runs


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda item: item["id"])
def test_lesson_initial_changes_history_and_restore(lesson):
    baseline = json.loads((SAMPLES / lesson["request_file"]).read_text(encoding="utf-8"))
    saved = copy.deepcopy(baseline)
    for step, request in scenario_requests(lesson, baseline):
        before = copy.deepcopy(request)
        expected = step["expected"]
        result = solve(request, num_workers=1)
        assert request == before
        assert_response(result, expected["status"])
        assert result["verification"]["valid"]
        assert (
            result["shortage_summary"]["total_person_minutes"] == expected["total_person_minutes"]
        )
        assert result["shortage_summary"]["proven_minimal"]
        checked = verify(request, result["solution"])
        assert checked["status"] == ("PARTIAL" if expected["total_person_minutes"] else "VALID")
        assert checked["verification"]["valid"]
        assert not checked["shortage_summary"]["proven_minimal"]
        if lesson["id"] == "demand":
            assert request["employees"] == baseline["employees"]
            assert request["constraints"] == baseline["constraints"]
            assert request["objectives"] == baseline["objectives"]
            # 各担当区間の長さは、統合されても同じ30分枠数になる。
            slots = sum(
                (
                    datetime.fromisoformat(a["interval"]["end"])
                    - datetime.fromisoformat(a["interval"]["start"])
                ).total_seconds()
                / 1800
                for a in result["solution"]["assignments"]
            )
            assert slots == expected["assigned_slots"]
            if step["id"] == "shortage":
                needs = {d["id"]: d["required_people"] for d in request["demand"]}
                assert needs["hall_2"] == needs["hall_3"] == 4
                assert {s["demand_id"] for s in result["shortage_summary"]["shortages"]} <= set(
                    needs
                )
        else:
            assert request["demand"] == baseline["demand"]
            assert request["shift_templates"] == baseline["shift_templates"]
            assert request["preferences"] == baseline["preferences"]
            assert request["objectives"] == baseline["objectives"]
            longest, first_runs = work_runs(request, result["solution"])
            assert max(longest.values()) == expected["max_consecutive_days"]
            assert all(r <= request["constraints"][0]["limit_days"] for r in longest.values())
            if "first_run_a" in expected:
                assert first_runs["a"] == expected["first_run_a"]
            if "first_run_a_max" in expected:
                assert 0 < first_runs["a"] <= expected["first_run_a_max"]
            if step["id"] == "shorter":
                unchanged = copy.deepcopy(request)
                unchanged["constraints"][0]["limit_days"] = 5
                assert unchanged == baseline
            if step["id"] == "fewer_backups":
                assert {
                    s["employee_id"]
                    for s in result["solution"]["shifts"]
                    if s["work_day"] < "2026-10-10"
                } <= {"a"}
        if step["id"] == "restored" or step["id"] == "initial":
            assert request == baseline
    assert baseline == saved


def test_invalid_input_and_required_minimum_are_not_partial_plans():
    lesson = LESSONS[0]
    baseline = json.loads((SAMPLES / lesson["request_file"]).read_text(encoding="utf-8"))
    request = next(r for s, r in scenario_requests(lesson, baseline) if s["id"] == "shortage")
    for demand in request["demand"]:
        demand["minimum_people"] = demand["required_people"]
    assert solve(request)["status"] == "INFEASIBLE"
    request["demand"][0]["required_people"] = -1
    assert solve(request)["status"] == "INVALID_INPUT"
