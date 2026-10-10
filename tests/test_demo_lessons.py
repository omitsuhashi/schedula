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
    assert {t["id"] for t in entries if "lesson_file" in t} == {lesson["id"] for lesson in LESSONS}


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


@pytest.mark.parametrize(
    "lesson",
    [
        item
        for item in LESSONS
        if item["operation"] == "solve"
        and item.get("module") not in {"basic", "conditions", "days"}
    ],
    ids=lambda item: item["id"],
)
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
        elif lesson["id"] == "consecutive_days":
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
        else:
            assert request["demand"] == baseline["demand"]
            assert request["shift_candidates"] == baseline["shift_candidates"]
            assert request["continuity"] == baseline["continuity"]
            summary = result["shift_count_balance_summary"][0]
            assert summary == checked["shift_count_balance_summary"][0]
            assert summary["total_deviation_count"] == expected["total_deviation_count"]
            if "actual_counts" in expected:
                assert {
                    e["employee_id"]: e["actual_count"] for e in summary["employees"]
                } == expected["actual_counts"]
            if step["id"] == "goals":
                unchanged = copy.deepcopy(request)
                unchanged["shift_count_balance"] = baseline["shift_count_balance"]
                assert unchanged == baseline
            if step["id"] == "zero":
                assert all(e["target_count"] == 0 for e in summary["employees"])
            if step["id"] == "unspecified":
                assert {e["employee_id"] for e in summary["employees"]} == {"bob"}
            assert summary["unit"] == "shifts" and summary["scale"] == "absolute_deviation"
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


def test_manual_verify_invalid_partial_repair_and_restore():
    from shift_schedula.contract import schema_errors

    lesson = next(item for item in LESSONS if item["id"] == "verify")
    request = json.loads((SAMPLES / lesson["request_file"]).read_text())
    initial = json.loads((SAMPLES / lesson["solution_file"]).read_text())
    solution = copy.deepcopy(initial)
    original_request = copy.deepcopy(request)
    for step in lesson["steps"]:
        if step["restore"]:
            solution = copy.deepcopy(initial)
        if "kitchen_employee" in step["changes"]:
            solution["assignments"] = [
                a for a in solution["assignments"] if a["role_id"] != "kitchen"
            ]
            employee = step["changes"]["kitchen_employee"]
            if employee:
                solution["assignments"].insert(
                    0, {**copy.deepcopy(initial["assignments"][0]), "employee_id": employee}
                )
        saved = copy.deepcopy(solution)
        result = verify(request, solution)
        assert result["status"] == step["expected"]["status"]
        assert not schema_errors("verification", result)
        assert solution == saved and request == original_request
        assert result["verification"]["valid"] == (result["status"] != "INVALID_PLAN")
        if result["status"] == "INVALID_PLAN":
            assert all(
                v["code"] == "DOUBLE_ASSIGNMENT" and v["json_pointer"] == "/assignments/1"
                for v in result["verification"]["violations"]
            )
            assert result["shortage_summary"] is None
        else:
            assert (
                result["shortage_summary"]["total_person_minutes"]
                == step["expected"]["total_person_minutes"]
            )
            assert not result["shortage_summary"]["proven_minimal"]
            assert all(not g["proven_minimal"] for g in result["priority_summary"]["groups"])
        assert all(not o["proven_optimal"] for o in result["objectives"])
        assert solution["shifts"] == initial["shifts"]
        if step["id"] in {"initial", "restored"}:
            assert solution == initial
    request["demand"][0]["required_people"] = -1
    result = verify(request, initial)
    assert result["status"] == "INVALID_INPUT"
    assert not result["verification"]["performed"] and result["verification"]["valid"] is None
