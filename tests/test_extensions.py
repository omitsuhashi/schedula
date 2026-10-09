import copy
import itertools
import json
from pathlib import Path

import pytest

from shift_schedula import solve
from shift_schedula.extensions import evaluate
from shift_schedula.model import normalize
from shift_schedula.verify import verify_solution
from tests.roster_support import demand, interval, rule
from tests.roster_support import legacy_candidate as candidate
from tests.roster_support import legacy_request as request

ROOT = Path(__file__).resolve().parents[1]


def extended(data=None):
    data = copy.deepcopy(data if data is not None else request(employees=("alice", "bob")))
    data["schema_version"] = "0.2"
    for employee in data["employees"]:
        employee["history"]["last_work_day"] = None
    data["shift_candidates"] = [
        {
            "id": c["id"],
            "employee_id": c["employee_id"],
            "segments": [{"interval": c["interval"], "breaks": c["breaks"]}],
        }
        for c in data["shift_candidates"]
    ]
    return data


def fairness(data, targets):
    data["fairness"] = {
        "evaluation_period": {key: data["planning_window"][key] for key in ("start", "end")},
        "employee_targets": [
            {"employee_id": employee, "target_minutes": minutes}
            for employee, minutes in targets.items()
        ],
    }
    data["objectives"] = [{"id": "fairness", "metric": "fairness_deviation_minutes"}]


def selected(c):
    result = {
        "candidate_id": c["id"],
        "employee_id": c["employee_id"],
        **{key: value for key, value in c.items() if key in {"segments", "interval", "breaks"}},
    }
    if "segments" in c:
        result["work_day"] = c["segments"][0]["interval"]["start"][:10]
    return result


def baseline(data=None):
    old = copy.deepcopy(data if data is not None else request(employees=("alice", "bob")))
    old["shift_candidates"] = [candidate("alice", end=660), candidate("bob", end=660)]
    old["demand"] = [demand(end=660)]
    solution = {
        "assignments": [
            {"employee_id": "alice", "role_id": "kitchen", "interval": interval(end=660)}
        ],
        "shifts": [selected(old["shift_candidates"][0])],
    }
    data = extended(old)
    data["baseline"] = {"plan_id": "old_plan", "source_request": old, "source_solution": solution}
    data["objectives"] = [{"id": "changes", "metric": "plan_changes"}]
    return data


def test_different_targets_and_hard_demand():
    data = request(employees=("alice", "bob"))
    for employee in data["employees"]:
        employee["availability"] = [interval(start=540, end=1260)]
    data["shift_candidates"] = [candidate("alice", start=540, end=end) for end in (780, 1020)] + [
        candidate("bob", start=start, end=1260) for start in (780, 1020)
    ]
    data["demand"] = [demand(start=540, end=1260)]
    data = extended(data)
    fairness(data, {"alice": 240, "bob": 480})
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert result["objectives"][0]["value"] == 0
    assert [
        (item["employee_id"], item["scheduled_minutes"])
        for item in result["fairness_summary"]["employees"]
    ] == [("alice", 240), ("bob", 480)]
    assert verify_solution(normalize(data), result["solution"]) == ([], (0,))


def test_zero_target_and_excluded_employee_do_not_relax_demand():
    data = extended(request(employees=("alice", "bob")))
    data["shift_candidates"] = data["shift_candidates"][:1]
    data["demand"] = [demand()]
    fairness(data, {"alice": 0})
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert result["objectives"][0]["value"] == 90
    assert result["fairness_summary"]["normalized"] is False
    assert result["fairness_summary"]["employees"] == [
        {
            "employee_id": "alice",
            "target_minutes": 0,
            "scheduled_minutes": 90,
            "deviation_minutes": 90,
        }
    ]


@pytest.mark.parametrize("targets", [(45, 75), (0, 0), (60, 30), (120, 120)])
@pytest.mark.parametrize("reverse", [False, True])
def test_fairness_objective_order_matches_small_exhaustive_problem(targets, reverse):
    data = request(employees=("alice", "bob"))
    data["shift_candidates"] = [
        candidate(e, end=end) for e in ("alice", "bob") for end in (630, 660)
    ]
    data = extended(data)
    fairness(data, dict(zip(("alice", "bob"), targets, strict=True)))
    data["objectives"].append({"id": "work", "metric": "scheduled_minutes"})
    if reverse:
        data["objectives"].reverse()
    # 需要なしの各人0/30/60分を全探索し、目標の粒度と達成不能も含める。
    choices = []
    for scheduled in itertools.product((0, 30, 60), repeat=2):
        values = (sum(abs(a - b) for a, b in zip(scheduled, targets, strict=True)), sum(scheduled))
        choices.append(values[::-1] if reverse else values)
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert tuple(item["value"] for item in result["objectives"]) == min(choices)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_target",
        "unknown_employee",
        "duplicate_employee",
        "different_period",
        "missing_objective",
    ],
)
def test_fairness_invalid_input(mutation):
    data = extended()
    fairness(data, {"alice": 60})
    if mutation == "missing_target":
        del data["fairness"]["employee_targets"][0]["target_minutes"]
    elif mutation == "unknown_employee":
        data["fairness"]["employee_targets"][0]["employee_id"] = "unknown"
    elif mutation == "duplicate_employee":
        data["fairness"]["employee_targets"] *= 2
    elif mutation == "different_period":
        data["fairness"]["evaluation_period"]["end"] = interval(end=660)["end"]
    else:
        data["objectives"] = []
    result = solve(data)
    assert result["status"] == "INVALID_INPUT"
    assert result["solution"] is None


def test_candidate_id_change_has_zero_change_and_old_version_is_validated():
    data = baseline()
    data["shift_candidates"][0]["id"] = "renamed"
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert result["objectives"][0]["value"] == 0
    assert result["change_summary"] == {
        "plan_id": "old_plan",
        "unit": "slot_components",
        "work_changes": 0,
        "role_changes": 0,
        "total_changes": 0,
    }


@pytest.mark.parametrize("remove_employee", [False, True])
def test_absence_and_deleted_employee_are_eight_changes(remove_employee):
    data = baseline()
    data["shift_candidates"] = data["shift_candidates"][1:]
    if remove_employee:
        data["employees"] = data["employees"][1:]
    else:
        data["employees"][0]["availability"] = []
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert result["objectives"][0]["value"] == 8
    assert result["change_summary"]["work_changes"] == result["change_summary"]["role_changes"] == 4
    assert verify_solution(normalize(data), result["solution"]) == ([], (8,))


def test_role_id_change_counts_roles_without_changing_work():
    data = baseline()
    data["roles"] = [role for role in data["roles"] if role["id"] == "hall"]
    data["demand"][0]["role_id"] = "hall"
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert result["change_summary"]["work_changes"] == 0
    assert result["change_summary"]["role_changes"] == 2
    assert result["objectives"][0]["value"] == 2


def test_moved_break_counts_both_components_and_fixed_break_is_hard():
    old = request()
    old["employees"][0]["availability"] = [interval(end=720)]
    old["shift_candidates"] = [candidate(end=720, breaks=[(630, 660)])]
    old["demand"] = [demand(), demand(start=660, end=720)]
    solution = {
        "assignments": [
            {"employee_id": "alice", "role_id": "kitchen", "interval": item["interval"]}
            for item in old["demand"]
        ],
        "shifts": [selected(old["shift_candidates"][0])],
    }
    data = extended(old)
    data["baseline"] = {"plan_id": "break_plan", "source_request": old, "source_solution": solution}
    data["shift_candidates"][0]["segments"][0]["breaks"] = [interval(start=660, end=690)]
    data["demand"] = [demand(end=660), demand(start=690, end=720)]
    data["objectives"] = [{"id": "changes", "metric": "plan_changes"}]
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert result["change_summary"]["work_changes"] == 2
    assert result["change_summary"]["role_changes"] == 2
    assert result["objectives"][0]["value"] == 4
    data["fixed_parts"] = [
        {
            "id": "fixed_break",
            "employee_id": "alice",
            "interval": interval(start=630, end=660),
            "components": ["work"],
        }
    ]
    assert solve(data)["status"] == "INFEASIBLE"
    violations, _, _ = evaluate(normalize(data), result["solution"])
    assert "FIXED_PART_VIOLATION" in {item["code"] for item in violations}


@pytest.mark.parametrize("component", ["work", "role"])
def test_fixed_on_and_off_are_hard_and_independently_verified(component):
    data = baseline()
    data["fixed_parts"] = [
        {
            "id": "fixed",
            "employee_id": "alice",
            "interval": interval(end=660),
            "components": [component],
        }
    ]
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    broken = copy.deepcopy(result["solution"])
    broken["shifts"][0]["employee_id"] = "bob"
    broken["assignments"][0]["employee_id"] = "bob"
    violations, _, _ = evaluate(normalize(data), broken)
    assert "FIXED_PART_VIOLATION" in {item["code"] for item in violations}
    data["employees"][0]["availability"] = []
    data["shift_candidates"] = data["shift_candidates"][1:]
    assert solve(data)["status"] == "INFEASIBLE"
    # 基準が非勤務・未担当のBobも固定でき、目的を外しても必須になる。
    data = baseline()
    data["fixed_parts"] = [
        {
            "id": "off",
            "employee_id": "bob",
            "interval": interval(end=660),
            "components": [component],
        }
    ]
    data["objectives"] = []
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert {item["employee_id"] for item in result["solution"]["assignments"]} == {"alice"}


@pytest.mark.parametrize(
    "mutation",
    [
        "bad_old_solution",
        "nested_baseline",
        "nested_diagnosis",
        "different_grid",
        "unknown_fixed_employee",
        "no_baseline",
    ],
)
def test_invalid_baseline_and_fixed_reference(mutation):
    data = baseline()
    if mutation == "bad_old_solution":
        data["baseline"]["source_solution"]["assignments"] = []
    elif mutation.startswith("nested_"):
        data["baseline"]["source_request"][mutation.removeprefix("nested_")] = {}
    elif mutation == "different_grid":
        data["baseline"]["source_request"]["planning_window"]["slot_minutes"] = 15
    elif mutation == "unknown_fixed_employee":
        data["fixed_parts"] = [
            {
                "id": "bad",
                "employee_id": "unknown",
                "interval": interval(end=660),
                "components": ["work"],
            }
        ]
    else:
        del data["baseline"]
    assert solve(data)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize(
    "kind",
    ["max_assigned_minutes", "max_scheduled_minutes", "max_consecutive_days"],
)
def test_baseline_constraint_violation_points_to_source_request(kind):
    data = baseline()
    constraint = rule(kind, 0)
    data["baseline"]["source_request"]["constraints"] = [constraint]
    result = solve(data)
    assert result["status"] == "INVALID_INPUT"
    assert result["diagnostics"][0]["code"] == kind.upper() + "_VIOLATION"
    pointer = result["diagnostics"][0]["json_pointer"]
    assert pointer == "/baseline/source_request/constraints/0"
    value = data
    for token in pointer.lstrip("/").split("/"):
        value = value[int(token)] if isinstance(value, list) else value[token]
    assert value == constraint


@pytest.mark.parametrize("field", ["assignments", "shifts"])
def test_baseline_solution_violation_points_to_source_solution(field):
    data = baseline()
    solution = data["baseline"]["source_solution"]
    if field == "assignments":
        solution[field] = []
        code, suffix = "DEMAND_SHORTAGE", "/assignments"
    else:
        solution[field][0]["employee_id"] = "bob"
        code, suffix = "CANDIDATE_MISMATCH", "/shifts/0"
    result = solve(data)
    assert result["status"] == "INVALID_INPUT"
    item = next(item for item in result["diagnostics"] if item["code"] == code)
    pointer = item["json_pointer"]
    assert pointer == "/baseline/source_solution" + suffix
    value = data
    for token in pointer.lstrip("/").split("/"):
        value = value[int(token)] if isinstance(value, list) else value[token]
    assert value == (solution[field] if field == "assignments" else solution[field][0])


@pytest.mark.parametrize("schema_version", ["0.1", "0.2"])
@pytest.mark.parametrize("field", ["interval", "breaks"])
def test_baseline_misaligned_shift_points_to_existing_solution_interval(schema_version, field):
    data = baseline()
    if schema_version == "0.2":
        old = extended(data["baseline"]["source_request"])
        data["baseline"]["source_request"] = old
        data["baseline"]["source_solution"]["shifts"] = [selected(old["shift_candidates"][0])]
    # 候補と旧解の区間は別々に保持し、旧解だけを改ざんする。
    data["baseline"]["source_solution"] = copy.deepcopy(data["baseline"]["source_solution"])
    shift = data["baseline"]["source_solution"]["shifts"][0]
    segment = shift["segments"][0] if schema_version == "0.2" else shift
    if field == "interval":
        segment[field]["start"] = interval(start=615)["start"]
        expected, suffix = segment[field], "/interval"
    else:
        segment[field] = [interval(start=615, end=630)]
        expected, suffix = segment[field][0], "/breaks/0"
    result = solve(data)
    assert result["status"] == "INVALID_INPUT"
    item = next(item for item in result["diagnostics"] if item["code"] == "MISALIGNED_INTERVAL")
    pointer = item["json_pointer"]
    assert pointer == (
        "/baseline/source_solution/shifts/0"
        + ("/segments/0" if schema_version == "0.2" else "")
        + suffix
    )
    value = data
    for token in pointer.lstrip("/").split("/"):
        value = value[int(token)] if isinstance(value, list) else value[token]
    assert value == expected


def test_replan_accepts_zero_two_baseline_and_fairness_summary_is_independent():
    data = baseline()
    old = extended(data["baseline"]["source_request"])
    old_result = solve(old)
    assert old_result["status"] == "OPTIMAL"
    data["baseline"]["source_request"] = old
    data["baseline"]["source_solution"] = old_result["solution"]
    fairness(data, {"alice": 30, "bob": 30})
    data["objectives"].insert(0, {"id": "changes", "metric": "plan_changes"})
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert [item["value"] for item in result["objectives"]] == [0, 60]
    broken = copy.deepcopy(result["solution"])
    broken["shifts"] = []
    _, metrics, summaries = evaluate(normalize(data), broken)
    assert metrics["fairness_deviation_minutes"] == 60
    assert all(
        item["scheduled_minutes"] == 0 for item in summaries["fairness_summary"]["employees"]
    )


@pytest.mark.parametrize("name,values", [("fairness", [0, 720]), ("replan", [16, 0, 240])])
def test_extension_examples(name, values):
    data = json.loads((ROOT / f"examples/{name}.json").read_text())
    result = solve(data)
    assert result["status"] == "OPTIMAL"
    assert [item["value"] for item in result["objectives"]] == values
    assert verify_solution(normalize(data), result["solution"]) == ([], tuple(values))
