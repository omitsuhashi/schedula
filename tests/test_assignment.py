import copy
import itertools
import random
from datetime import datetime, timedelta

import pytest

from shift_schedula import solve, verify
from shift_schedula.contract import get_schema
from shift_schedula.model import normalize
from shift_schedula.verify import verify_solution
from tests.support import assert_response, require_complete_demand


@pytest.mark.parametrize("assignment_request", ["0.1", "0.15"], indirect=True)
@pytest.mark.parametrize("backend", ["auto", "min_cost_flow"])
def test_restaurant_example(assignment_request, backend):
    assignment_request["solver"]["backend"] = backend
    if assignment_request["schema_version"] == "0.15":
        require_complete_demand(assignment_request)
    original = copy.deepcopy(assignment_request)
    result = solve(assignment_request)
    assert_response(result, "OPTIMAL")
    assert result["solver"]["backend"] == "min_cost_flow"
    assert result["objectives"][0]["value"] == 0
    assert len(result["solution"]["assignments"]) == 3
    assert result["solution"]["shifts"] == []
    assert assignment_request == original
    assert verify_solution(normalize(assignment_request), result["solution"]) == ([], (0,))
    assert verify(assignment_request, result["solution"])["status"] == "VALID"


@pytest.mark.parametrize("backend", ["auto", "min_cost_flow"])
@pytest.mark.parametrize("demand", [[], "zero"])
def test_empty_demand_and_objectives(assignment_request, backend, demand):
    assignment_request["solver"]["backend"] = backend
    if demand == "zero":
        for item in assignment_request["demand"]:
            item["required_people"] = 0
    else:
        assignment_request["demand"] = []
    assignment_request["preferences"] = []
    assignment_request["objectives"] = []
    result = solve(assignment_request)
    assert_response(result, "OPTIMAL")
    assert result["solution"] == {"assignments": [], "shifts": []}
    assert result["objectives"] == []


@pytest.mark.parametrize("field", ["skills", "availability"])
def test_shortage_is_infeasible(assignment_request, field):
    assignment_request["employees"][0][field] = []
    result = solve(assignment_request)
    assert_response(result, "INFEASIBLE")
    assert result["diagnostics"][0]["code"] == "INSUFFICIENT_QUALIFIED_EMPLOYEES"
    assert result["verification"] == {"performed": False, "valid": None, "violations": []}


def test_missing_skill_does_not_satisfy_level_zero(assignment_request):
    assignment_request["roles"][0]["required_skills"][0]["min_level"] = 0
    assignment_request["employees"][0]["skills"] = []
    assert_response(solve(assignment_request), "INFEASIBLE")


def test_required_skills_are_and_conditions(assignment_request):
    assignment_request["roles"][0]["required_skills"].append(
        {"skill_id": "service", "min_level": 1}
    )
    assert_response(solve(assignment_request), "INFEASIBLE")
    assignment_request["employees"][0]["skills"].append({"skill_id": "service", "level": 1})
    assert_response(solve(assignment_request), "OPTIMAL")


def test_multi_skill_competition_is_not_individual_role_shortage(assignment_request):
    assignment_request["employees"][0]["skills"].append({"skill_id": "service", "level": 1})
    assignment_request["employees"][1]["skills"] = []
    result = solve(assignment_request)
    assert_response(result, "INFEASIBLE")
    assert result["diagnostics"][0]["code"] == "COMPETING_ROLE_DEMAND"


def test_residual_path_reassigns_multi_skill_employee(assignment_request):
    assignment_request["employees"][0]["skills"].append({"skill_id": "service", "level": 1})
    result = solve(assignment_request)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 0
    assert {item["employee_id"]: item["role_id"] for item in result["solution"]["assignments"]} == {
        "alice": "kitchen",
        "bob": "hall",
        "carol": "washing",
    }


def test_necessary_preference_violation_and_additive_preferences(assignment_request):
    assignment_request["preferences"][0]["employee_ids"] = ["carol"]
    assignment_request["preferences"][0]["penalty_per_minute"] = 3
    assignment_request["preferences"].append(
        {**assignment_request["preferences"][0], "id": "second", "penalty_per_minute": 2}
    )
    result = solve(assignment_request)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 120 * (3 + 2)


def test_unspecified_demand_and_unavailable_employee(assignment_request):
    assignment_request["demand"] = assignment_request["demand"][:1]
    assignment_request["employees"][2]["availability"] = []
    result = solve(assignment_request)
    assert_response(result, "OPTIMAL")
    assert {item["role_id"] for item in result["solution"]["assignments"]} == {"kitchen"}


def test_adjacent_availability_and_demand_use_half_open_intervals(assignment_request):
    split = "2026-10-05T12:00:00+09:00"
    employee = assignment_request["employees"][0]
    employee["availability"] = [
        {**employee["availability"][0], "end": split},
        {**employee["availability"][0], "start": split},
    ]
    demand = assignment_request["demand"][0]
    assignment_request["demand"][0] = {**demand, "interval": {**demand["interval"], "end": split}}
    assignment_request["demand"].append(
        {**demand, "id": "kitchen_later", "interval": {**demand["interval"], "start": split}}
    )
    assert_response(solve(assignment_request), "OPTIMAL")


def test_assignment_merging_preserves_gaps_and_role_changes(assignment_request):
    assignment_request["demand"] = [
        {
            "id": "first",
            "role_id": "washing",
            "interval": {"start": "2026-10-05T11:00:00+09:00", "end": "2026-10-05T11:30:00+09:00"},
            "required_people": 1,
        },
        {
            "id": "second",
            "role_id": "washing",
            "interval": {"start": "2026-10-05T12:00:00+09:00", "end": "2026-10-05T13:00:00+09:00"},
            "required_people": 1,
        },
    ]
    result = solve(assignment_request)
    assert_response(result, "OPTIMAL")
    assert len(result["solution"]["assignments"]) == 2
    assert all(item["employee_id"] == "carol" for item in result["solution"]["assignments"])


def exhaustive_value(request):
    start = datetime.fromisoformat(request["planning_window"]["start"])
    slots = int(
        (datetime.fromisoformat(request["planning_window"]["end"]) - start).total_seconds() // 1800
    )
    total = 0
    for slot in range(slots):
        a, b = start + timedelta(minutes=30 * slot), start + timedelta(minutes=30 * (slot + 1))
        needed = {role["id"]: 0 for role in request["roles"]}
        for demand in request["demand"]:
            if datetime.fromisoformat(
                demand["interval"]["start"]
            ) <= a and b <= datetime.fromisoformat(demand["interval"]["end"]):
                needed[demand["role_id"]] = demand["required_people"]
        choices = []
        for employee in request["employees"]:
            levels = {skill["skill_id"]: skill["level"] for skill in employee["skills"]}
            available = any(
                datetime.fromisoformat(value["start"]) <= a
                and b <= datetime.fromisoformat(value["end"])
                for value in employee["availability"]
            )
            roles = [
                role["id"]
                for role in request["roles"]
                if available
                and all(
                    skill["skill_id"] in levels and levels[skill["skill_id"]] >= skill["min_level"]
                    for skill in role["required_skills"]
                )
            ]
            choices.append([None, *roles])
        best = None
        for assignments in itertools.product(*choices):
            if any(assignments.count(role) != count for role, count in needed.items()):
                continue
            cost = sum(
                30 * preference["penalty_per_minute"]
                for employee, role in zip(request["employees"], assignments, strict=True)
                for preference in request["preferences"]
                if employee["id"] in preference["employee_ids"] and role == preference["role_id"]
            )
            best = cost if best is None else min(best, cost)
        if best is None:
            return None
        total += best
    return total


@pytest.mark.parametrize("backend", ["min_cost_flow", "cp_sat"])
@pytest.mark.parametrize("seed", range(150))
@pytest.mark.parametrize("assignment_request", ["0.1", "0.15"], indirect=True)
def test_optimum_and_infeasibility_match_exhaustive_search(assignment_request, seed, backend):
    randomizer = random.Random(seed)
    request = assignment_request
    request["solver"]["backend"] = backend
    request["planning_window"]["end"] = "2026-10-05T12:00:00+09:00"
    request["employees"].append({**copy.deepcopy(request["employees"][2]), "id": "dave"})
    for employee in request["employees"]:
        employee["skills"] = [
            {"skill_id": skill["id"], "level": randomizer.randrange(3)}
            for skill in request["skills"]
            if randomizer.choice([True, False])
        ]
        employee["availability"] = []
        for slot in range(2):
            if randomizer.choice([True, True, False]):
                employee["availability"].append(
                    {
                        "start": f"2026-10-05T11:{slot * 30:02d}:00+09:00",
                        "end": "2026-10-05T11:30:00+09:00"
                        if slot == 0
                        else "2026-10-05T12:00:00+09:00",
                    }
                )
    for role in request["roles"]:
        for skill in role["required_skills"]:
            skill["min_level"] = randomizer.randrange(3)
    request["demand"] = []
    for role in request["roles"]:
        for slot in range(2):
            interval = {
                "start": f"2026-10-05T11:{slot * 30:02d}:00+09:00",
                "end": "2026-10-05T11:30:00+09:00" if slot == 0 else "2026-10-05T12:00:00+09:00",
            }
            request["demand"].append(
                {
                    "id": f"need_{role['id']}_{slot}",
                    "role_id": role["id"],
                    "interval": interval,
                    "required_people": randomizer.randrange(3),
                }
            )
    request["preferences"] = [
        {
            "id": f"avoid_{index}",
            "type": "avoid_role",
            "employee_ids": [employee["id"]],
            "role_id": randomizer.choice(request["roles"])["id"],
            "penalty_per_minute": randomizer.randrange(1, 10),
        }
        for index, employee in enumerate(request["employees"])
    ]
    if request["schema_version"] == "0.15":
        require_complete_demand(request)
    saved = copy.deepcopy(request)
    expected = exhaustive_value(request)
    result = solve(request)
    assert_response(result, "INFEASIBLE" if expected is None else "OPTIMAL")
    if expected is not None:
        assert result["objectives"][0]["value"] == expected
        assert verify(request, result["solution"])["status"] == "VALID"
    assert request == saved


def test_schema_identity_and_meta_validation():
    from jsonschema import Draft202012Validator

    for kind in ["request", "response"]:
        schema = get_schema(kind)
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == f"urn:schedula:{kind}:0.1"
        schema.clear()
        assert get_schema(kind)
