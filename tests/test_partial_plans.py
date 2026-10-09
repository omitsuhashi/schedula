"""元需要を保持した不足付き計画の検証・探索・利用境界を確認する。"""

import copy
import itertools
import json
from pathlib import Path

import pytest

from shift_schedula import flow, solve
from shift_schedula.contract import InvalidInput
from shift_schedula.engine import validate_response
from shift_schedula.model import normalize
from shift_schedula.verify import verify_plan, verify_solution
from tests.roster_support import demand, interval, request, rule
from tests.support import assert_response
from tests.test_cli import cli
from tests.test_cp_sat import small_request, stamp
from tests.test_extensions import baseline, extended, fairness, selected
from tests.test_objectives import control_search

ROOT = Path(__file__).resolve().parents[1]


def partial(data):
    data = copy.deepcopy(data)
    data["schema_version"] = "0.3"
    return data


def test_verification_merges_only_equal_adjacent_shortages(assignment_request):
    data = partial(assignment_request)
    data["demand"] = data["demand"][:1]
    data["demand"][0]["interval"]["end"] = "2026-10-05T12:00:00+09:00"
    data["demand"][0]["required_people"] = 2
    data["demand"].append(
        {
            **data["demand"][0],
            "id": "later",
            "interval": {"start": "2026-10-05T12:00:00+09:00", "end": "2026-10-05T13:00:00+09:00"},
        }
    )
    data["planning_window"]["end"] = "2026-10-05T13:30:00+09:00"
    problem = normalize(data)
    solution = {
        "assignments": [
            {
                "employee_id": "alice",
                "role_id": "kitchen",
                "interval": {
                    "start": "2026-10-05T11:00:00+09:00",
                    "end": "2026-10-05T11:30:00+09:00",
                },
            }
        ],
        "shifts": [],
    }
    violations, values, summary = verify_plan(problem, solution)
    assert violations == [] and values == (0,)
    assert summary["total_person_minutes"] == 210
    assert [(s["demand_id"], s["missing_people"]) for s in summary["shortages"]] == [
        ("kitchen_lunch", 1),
        ("kitchen_lunch", 2),
        ("later", 2),
    ]
    assert summary["shortages"][2]["interval"] == data["demand"][1]["interval"]
    assert verify_solution(normalize({**data, "schema_version": "0.2"}), solution)[0]
    assert verify_solution(problem, solution, require_complete=True)[0]


def test_shortage_uses_elapsed_minutes_across_clock_change(assignment_request):
    data = partial(assignment_request)
    window = {"start": "2026-11-01T00:00:00-04:00", "end": "2026-11-01T03:00:00-05:00"}
    data["planning_window"].update(window, timezone="America/New_York")
    data["demand"] = [{**data["demand"][0], "interval": window}]
    for e in data["employees"]:
        e["availability"] = []
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 240
    assert result["shortage_summary"]["shortages"][0]["interval"] == window


@pytest.mark.parametrize(
    "case", ["hidden", "count", "time", "demand", "total", "order", "unmerged"]
)
def test_response_rejects_tampered_shortages(case):
    data = json.loads((ROOT / "examples/partial_assignment.json").read_text())
    result = solve(data)
    summary = result["shortage_summary"]
    row = summary["shortages"][0]
    if case == "hidden":
        summary["shortages"].pop()
        summary["total_person_minutes"] = 30
    elif case == "count":
        row.update(required_people=3, missing_people=2)
        summary["total_person_minutes"] = 90
    elif case == "time":
        row["interval"]["start"] = row["interval"]["start"].replace("12:00", "11:30")
        summary["total_person_minutes"] = 90
    elif case == "demand":
        row["demand_id"] = "other"
    elif case == "total":
        summary["total_person_minutes"] += 30
    elif case == "order":
        summary["shortages"].reverse()
    else:
        # 同一需要内で分割した不足一覧も正規の集計と一致させる。
        next(d for d in data["demand"] if d["id"] == "kitchen_2")["interval"]["end"] = (
            "2026-10-06T13:00:00+09:00"
        )
        data["demand"] = [d for d in data["demand"] if d["id"] != "kitchen_3"]
        result = solve(data)
        row = result["shortage_summary"]["shortages"][0]
        left, right = copy.deepcopy(row), copy.deepcopy(row)
        left["interval"]["end"] = right["interval"]["start"] = "2026-10-06T12:30:00+09:00"
        result["shortage_summary"]["shortages"] = [left, right]
    with pytest.raises(InvalidInput):
        validate_response(result, data)


@pytest.mark.parametrize("case", ["skill", "double", "excess", "unspecified", "break", "fixed"])
def test_partial_verification_does_not_relax_other_rules(assignment_request, case):
    data = partial(assignment_request)
    solution = solve(data)["solution"]
    code = {
        "skill": "SKILL_VIOLATION",
        "double": "DOUBLE_ASSIGNMENT",
        "excess": "DEMAND_EXCESS",
        "unspecified": "DEMAND_EXCESS",
        "break": "BREAK_ASSIGNMENT",
        "fixed": "FIXED_PART_VIOLATION",
    }[case]
    if case == "skill":
        data["employees"][0]["skills"] = []
    elif case == "double":
        solution["assignments"].append(copy.deepcopy(solution["assignments"][0]))
    elif case == "excess":
        data["employees"][1]["skills"] = copy.deepcopy(data["employees"][0]["skills"])
        solution["assignments"].append(
            {**solution["assignments"][0], "employee_id": data["employees"][1]["id"]}
        )
    elif case == "unspecified":
        data["demand"] = []
    elif case == "break":
        data = partial(extended(request()))
        data["demand"] = [demand()]
        data["shift_candidates"][0]["segments"][0]["breaks"] = [interval(start=630, end=660)]
        solution = {
            "assignments": [
                {
                    "employee_id": "alice",
                    "role_id": "kitchen",
                    "interval": interval(start=630, end=660),
                }
            ],
            "shifts": [selected(data["shift_candidates"][0])],
        }
    else:
        data = partial(baseline())
        data["fixed_parts"] = [
            {
                "id": "keep",
                "employee_id": "alice",
                "interval": interval(end=660),
                "components": ["work", "role"],
            }
        ]
        solution = {"assignments": [], "shifts": []}
    violations, _, _ = verify_plan(normalize(data), solution)
    assert code in {v["code"] for v in violations}


def test_shortage_list_is_not_truncated(assignment_request):
    data = partial(assignment_request)
    data["planning_window"]["end"] = "2026-10-26T11:30:00+09:00"
    data["demand"] = [
        {**data["demand"][0], "id": f"d{i}", "interval": {"start": stamp(i), "end": stamp(i + 1)}}
        for i in range(1001)
    ]
    for e in data["employees"]:
        e["availability"] = []
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert len(result["shortage_summary"]["shortages"]) == 1001
    assert result["shortage_summary"]["total_person_minutes"] == 30030


@pytest.mark.parametrize("backend", ["min_cost_flow", "cp_sat"])
@pytest.mark.parametrize("mode", ["some", "all", "zero", "competition"])
def test_common_backends_preserve_original_demand_and_empty_objectives(
    assignment_request, backend, mode
):
    data = partial(small_request(assignment_request, ["kitchen", "hall"], employees=2))
    data["demand"] += [
        {
            **d,
            "id": d["id"] + "_other",
            "role_id": "hall" if d["role_id"] == "kitchen" else "kitchen",
        }
        for d in data["demand"]
    ]
    data["solver"]["backend"] = backend
    data["objectives"] = []
    if mode == "some":
        data["employees"][0]["availability"] = []
    elif mode == "all":
        for e in data["employees"]:
            e["availability"] = []
    elif mode == "zero":
        for d in data["demand"]:
            d["required_people"] = 0
    else:
        data["roles"][1]["required_skills"] = []
        data["employees"] = data["employees"][:1]
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL" if mode == "zero" else "PARTIAL")
    assert (
        result["shortage_summary"]["total_person_minutes"]
        == {"some": 60, "all": 120, "zero": 0, "competition": 60}[mode]
    )
    assert result["shortage_summary"]["proven_minimal"]
    assert data == original
    validate_response(result, data)


@pytest.mark.parametrize("linked", [False, True])
def test_small_assignment_matches_exhaustive_lexicographic_search(assignment_request, linked):
    for availability in [(True, True), (True, False), (False, False)]:
        data = partial(small_request(assignment_request, ["kitchen", "hall"], employees=2))
        data["demand"] += [
            {
                **d,
                "id": d["id"] + "_more",
                "role_id": "hall" if d["role_id"] == "kitchen" else "kitchen",
            }
            for d in data["demand"]
        ]
        data["employees"][0]["availability"] = (
            [{"start": stamp(0), "end": stamp(2)}] if availability[0] else []
        )
        data["employees"][1]["availability"] = (
            [{"start": stamp(0), "end": stamp(2)}] if availability[1] else []
        )
        data["preferences"] = [
            {
                "id": "avoid",
                "type": "avoid_role",
                "employee_ids": ["alice"],
                "role_id": "kitchen",
                "penalty_per_minute": 1000,
            }
        ]
        data["objectives"] = [{"id": "pref", "metric": "preference_penalty"}]
        if linked:
            data["objectives"].append({"id": "switches", "metric": "role_switches"})
            data["constraints"] = [rule("max_assigned_minutes", 30)]
        scores = []
        for plan in itertools.product([None, "kitchen", "hall"], repeat=4):
            if any(plan[e * 2 + s] and not availability[e] for e in range(2) for s in range(2)):
                continue
            if linked and sum(x is not None for x in plan[:2]) > 1:
                continue
            if any(
                sum(plan[e * 2 + s] == r for e in range(2)) > 1
                for s in range(2)
                for r in ["kitchen", "hall"]
            ):
                continue
            shortage = (4 - sum(x is not None for x in plan)) * 30
            penalty = sum(x == "kitchen" for x in plan[:2]) * 30 * 1000
            switches = sum(
                plan[e * 2] is not None
                and plan[e * 2 + 1] is not None
                and plan[e * 2] != plan[e * 2 + 1]
                for e in range(2)
            )
            scores.append((shortage, penalty, switches) if linked else (shortage, penalty))
        for backend in ["cp_sat"] if linked else ["cp_sat", "min_cost_flow"]:
            data["solver"]["backend"] = backend
            result = solve(data)
            assert (
                result["shortage_summary"]["total_person_minutes"],
                *[o["value"] for o in result["objectives"]],
            ) == min(scores)


@pytest.mark.parametrize("name", ["overnight", "split_roster", "fairness", "replan", "diagnosis"])
def test_partial_extended_roster_interactions(name):
    data = json.loads((ROOT / "examples" / f"{name}.json").read_text())
    for d in data["demand"]:
        d["required_people"] += 2
        d["minimum_people"] = 0
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "PARTIAL")
    validate_response(result, data)
    assert result["shortage_summary"]["proven_minimal"]
    assert all(o["proven_optimal"] for o in result["objectives"])
    assert data == original
    if name == "diagnosis":
        assert result["diagnosis_result"]["reason"] == "ORIGINAL_PARTIAL"
    if name in ["fairness", "replan"]:
        assert result["fairness_summary"] is not None
    if name == "replan":
        assert result["change_summary"] is not None


@pytest.mark.parametrize(
    "kind,value",
    [
        ("max_assigned_minutes", 30),
        ("max_scheduled_minutes", 0),
        ("min_rest_minutes", 1440),
        ("max_consecutive_days", 0),
    ],
)
def test_roster_shortage_keeps_hard_limits(kind, value):
    data = partial(extended(request()))
    data["demand"] = [demand(end=690)]
    data["constraints"] = [rule(kind, value)]
    if kind == "max_consecutive_days":
        data["constraints"][0]["limit_days"] = 1
        data["employees"][0]["history"].update(
            last_shift_end="2026-10-04T23:00:00+09:00",
            last_work_day="2026-10-04",
            consecutive_work_days_before_window=1,
        )
    if kind == "min_rest_minutes":
        data["employees"][0]["history"].update(
            last_shift_end="2026-10-04T23:00:00+09:00",
            last_work_day="2026-10-04",
            consecutive_work_days_before_window=1,
        )
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == (
        60 if kind == "max_assigned_minutes" else 90
    )
    validate_response(result, data)


def test_shortage_precedes_fairness_and_workload():
    data = partial(extended(request()))
    data["demand"] = [demand(people=2)]
    fairness(data, {"alice": 0})
    data["objectives"].append({"id": "work", "metric": "scheduled_minutes"})
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 30
    assert [o["value"] for o in result["objectives"]] == [90, 90]


def test_fixed_parts_can_make_partial_model_infeasible():
    data = partial(baseline())
    data["fixed_parts"] = [
        {
            "id": "keep",
            "employee_id": "alice",
            "interval": interval(end=660),
            "components": ["work", "role"],
        }
    ]
    data["constraints"] = [rule("max_scheduled_minutes", 0)]
    assert_response(solve(data), "INFEASIBLE")
    data["constraints"] = []
    data["employees"][0]["availability"] = [interval(end=660)]
    data["demand"][0]["required_people"] = 0
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize(
    "statuses,expected,minimal,proofs",
    [
        (("FEASIBLE",), "PARTIAL", False, (False,)),
        (("OPTIMAL", "UNKNOWN"), "PARTIAL", True, (False,)),
        (("OPTIMAL", "FEASIBLE"), "PARTIAL", True, (False,)),
        (("OPTIMAL", "OPTIMAL"), "PARTIAL", True, (True,)),
        (("UNKNOWN",), "UNKNOWN", None, ()),
    ],
)
def test_cp_sat_time_limit_keeps_plan_and_proof_scope(
    assignment_request, monkeypatch, statuses, expected, minimal, proofs
):
    data = partial(assignment_request)
    data["employees"][0]["availability"] = []
    data["solver"]["backend"] = "cp_sat"
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, expected)
    assert len(calls) == len(statuses) and all(
        0 < b <= data["solver"]["time_limit_seconds"] for b in calls
    )
    assert tuple(o["proven_optimal"] for o in result["objectives"]) == proofs
    if minimal is not None:
        assert result["shortage_summary"]["proven_minimal"] == minimal


def test_flow_timeout_returns_verified_partial_prefix(assignment_request, monkeypatch):
    data = partial(assignment_request)
    augment = flow.augment
    calls = []

    def timed(graph, required, deadline):
        calls.append(deadline)
        _, cost = augment(graph, 1, deadline)
        return "UNKNOWN", cost

    monkeypatch.setattr(flow, "augment", timed)
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["solution"]["assignments"]
    assert not result["shortage_summary"]["proven_minimal"]
    assert all(not o["proven_optimal"] for o in result["objectives"])
    assert len(calls) == 1
    validate_response(result, data)


@pytest.mark.parametrize("objectives", [False, True])
def test_zero_shortage_proves_minimality_even_with_native_feasible(
    assignment_request, monkeypatch, objectives
):
    data = partial(assignment_request)
    data["solver"]["backend"] = "cp_sat"
    if not objectives:
        data["objectives"] = data["preferences"] = []
    control_search(monkeypatch, ("FEASIBLE",))
    result = solve(data)
    assert_response(result, "FEASIBLE" if objectives else "OPTIMAL")
    assert result["shortage_summary"] == {
        "total_person_minutes": 0,
        "proven_minimal": True,
        "shortages": [],
    }


def test_solver_shortage_tampering_is_internal_error(assignment_request, monkeypatch):
    data = partial(assignment_request)
    run = flow.run

    def tampered(problem):
        outcome = run(problem)
        outcome.shortage_person_minutes = 1
        return outcome

    monkeypatch.setattr(flow, "run", tampered)
    result = solve(data)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["valid"] is False and result["shortage_summary"] is None


@pytest.mark.parametrize("name,total", [("partial_assignment", 60), ("partial_roster", 30)])
def test_partial_cli_saves_complete_json(name, total):
    result = cli("solve", str(ROOT / "examples" / f"{name}.json"))
    assert result.returncode == 2 and result.stderr == ""
    response = json.loads(result.stdout)
    assert_response(response, "PARTIAL")
    assert response["shortage_summary"]["total_person_minutes"] == total
