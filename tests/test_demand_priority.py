import copy
import itertools
import json
from collections import Counter
from pathlib import Path

import pytest

from shift_schedula import cp_sat, get_schema, make_baseline, solve, verify
from shift_schedula.contract import InvalidInput
from shift_schedula.engine import validate_response
from tests.roster_support import demand, interval, request
from tests.support import assert_response
from tests.test_cli import cli
from tests.test_cp_sat import small_request
from tests.test_objectives import control_search


def assignment(data, priorities=(10, 0), employees=1):
    data = small_request(data, ["kitchen"], employees=employees)
    data["schema_version"] = "0.15"
    for item in data["demand"]:
        item.pop("minimum_people", None)
    for role in data["roles"]:
        role["required_skills"] = []
    data["demand"] = [
        {**data["demand"][0], "id": f"need_{role}", "role_id": role, "priority": priority}
        for role, priority in zip(("kitchen", "hall"), priorities, strict=True)
    ]
    data["preferences"] = [
        {
            "id": "prefer_hall",
            "type": "avoid_role",
            "employee_ids": ["alice"],
            "role_id": "kitchen",
            "penalty_per_minute": 1,
        }
    ]
    data["objectives"] = [{"id": "wishes", "metric": "preference_penalty"}]
    return data


@pytest.mark.parametrize("reverse", [False, True])
def test_important_demand_beats_preference_and_id_order(assignment_request, reverse):
    data = assignment(assignment_request)
    if reverse:
        data["demand"].reverse()
        data["roles"].reverse()
        for d in data["demand"]:
            d["id"] = "aaa" if d["priority"] == 0 else "zzz"
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["solver"]["selection_reason"] == "DEMAND_PRIORITY"
    assert {a["role_id"] for a in result["solution"]["assignments"]} == {"kitchen"}
    assert result["shortage_summary"]["total_person_minutes"] == 30
    assert result["priority_summary"]["groups"] == [
        {"priority": 10, "total_person_minutes": 0, "proven_minimal": True},
        {"priority": 0, "total_person_minutes": 30, "proven_minimal": True},
    ]
    checked = verify(data, result["solution"])
    assert checked["status"] == "PARTIAL"
    assert all(not g["proven_minimal"] for g in checked["priority_summary"]["groups"])
    assert data == original
    data["solver"]["backend"] = "min_cost_flow"
    assert solve(data)["diagnostics"][0]["code"] == "UNSUPPORTED_BACKEND"


def total_first():
    data = request()
    data["demand"] = [
        {**demand(end=630), "priority": 10},
        {**demand(start=630, end=690, role="hall"), "priority": 0},
    ]
    data["shift_candidates"][0]["segments"][0]["interval"] = interval(end=630)
    data["shift_candidates"].append(
        {
            "id": "long",
            "employee_id": "alice",
            "segments": [{"interval": interval(start=630), "breaks": []}],
        }
    )
    return data


@pytest.mark.parametrize("version", ["0.15"])
def test_total_shortage_precedes_priority_and_survives_replanning(version):
    data = total_first()
    data["schema_version"] = version
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 30
    assert result["priority_summary"]["groups"][0]["total_person_minutes"] == 30
    assert {a["role_id"] for a in result["solution"]["assignments"]} == {"hall"}
    baseline = make_baseline(data, result["solution"], "saved")
    for mode in ("preserve_assigned", "rebuild"):
        new = {**data, "baseline": baseline, "replan_mode": mode}
        again = solve(new)
        assert_response(again, "PARTIAL")
        assert again["priority_summary"] == result["priority_summary"]
        assert verify(new, again["solution"])["verification"]["valid"] is True
    old = {**data, "schema_version": "0.4", "baseline": baseline}
    for d in old["demand"]:
        d.pop("priority")
    assert solve(old)["diagnostics"][0]["code"] == "SCHEMA_VIOLATION"


@pytest.mark.parametrize("priorities", [(0, 1), (1, 0), (3, 2), (0, 0)])
@pytest.mark.parametrize("employees", [1, 2])
def test_small_exhaustive_oracle(assignment_request, priorities, employees):
    data = assignment(assignment_request, priorities, employees)
    window = data["planning_window"]
    window["end"] = window["end"].replace("11:30", "12:00")
    for d in data["demand"]:
        d["interval"]["end"] = window["end"]
    for e in data["employees"]:
        e["availability"][0]["end"] = window["end"]
    data["constraints"] = [
        {
            "id": "limit",
            "type": "max_assigned_minutes",
            "employee_ids": [e["id"] for e in data["employees"]],
            "limit_minutes": 30,
        }
    ]
    original = copy.deepcopy(data)
    levels = sorted(set(priorities), reverse=True)
    best = None
    for cells in itertools.product((None, "kitchen", "hall"), repeat=employees * 2):
        if any(sum(c is not None for c in cells[i * 2 : i * 2 + 2]) > 1 for i in range(employees)):
            continue
        counts = Counter((slot, cells[e * 2 + slot]) for e in range(employees) for slot in (0, 1))
        if any(counts[s, r] > 1 for s in (0, 1) for r in ("kitchen", "hall")):
            continue
        shortage = {(s, r): 30 * (1 - counts[s, r]) for s in (0, 1) for r in ("kitchen", "hall")}
        values = (
            sum(shortage.values()),
            *(
                sum(
                    shortage[s, r]
                    for s in (0, 1)
                    for r, p in zip(("kitchen", "hall"), priorities, strict=True)
                    if p == level
                )
                for level in levels
            ),
            30 * sum(c == "kitchen" for c in cells[:2]),
        )
        best = min(best, values) if best is not None else values
    result = solve(data)
    assert_response(result, "PARTIAL")
    actual = (
        result["shortage_summary"]["total_person_minutes"],
        *(g["total_person_minutes"] for g in result["priority_summary"]["groups"]),
        result["objectives"][0]["value"],
    )
    assert actual == best
    validate_response(result, data)
    assert verify(data, result["solution"])["verification"]["valid"] is True
    assert data == original


@pytest.mark.parametrize(
    "statuses,proofs",
    [
        (("FEASIBLE",), (False, False, False)),
        (("OPTIMAL", "FEASIBLE"), (True, False, False)),
        (("OPTIMAL", "OPTIMAL", "UNKNOWN"), (True, True, False)),
        (("OPTIMAL", "OPTIMAL", "OPTIMAL", "FEASIBLE"), (True, True, True)),
    ],
)
@pytest.mark.parametrize("version", ["0.15"])
def test_time_limit_proves_only_reached_prefix(
    assignment_request, monkeypatch, statuses, proofs, version
):
    data = assignment(assignment_request)
    data["schema_version"] = version
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "PARTIAL")
    actual = (
        result["shortage_summary"]["proven_minimal"],
        *(g["proven_minimal"] for g in result["priority_summary"]["groups"]),
    )
    assert actual == proofs
    assert len(calls) == len(statuses)
    assert result["objectives"][0]["proven_optimal"] is False
    reached = sum(d["code"] == "PRIORITY_SHORTAGE_BOUND" for d in result["diagnostics"])
    assert reached == min(2, len(statuses) - 1)


def test_shared_budget_and_tampered_priority_rejected(assignment_request, monkeypatch):
    data = assignment(assignment_request)
    module, _ = cp_sat.load_backend()
    search = module.CpSolver.solve
    clock, limits = [0], []

    def timed(solver, model):
        limits.append(solver.parameters.max_time_in_seconds)
        clock[0] += 2
        return search(solver, model)

    with monkeypatch.context() as patch:
        patch.setattr(cp_sat.time, "monotonic", lambda: clock[0])
        patch.setattr(module.CpSolver, "solve", timed)
        result = solve(data)
    assert_response(result, "PARTIAL")
    assert limits == [10, 8, 6, 4]
    for change in ("quantity", "priority", "order", "proof"):
        damaged = copy.deepcopy(result)
        groups = damaged["priority_summary"]["groups"]
        if change == "quantity":
            groups[0]["total_person_minutes"] += 30
            groups[1]["total_person_minutes"] -= 30
        elif change == "priority":
            groups[0]["priority"] = 9
        elif change == "order":
            groups.reverse()
        else:
            groups[0]["proven_minimal"] = False
        with pytest.raises(InvalidInput):
            validate_response(damaged, data)
    original_run = cp_sat.run

    def tampered(*args):
        outcome = original_run(*args)
        outcome.priority_values = tuple(reversed(outcome.priority_values))
        return outcome

    monkeypatch.setattr(cp_sat, "run", tampered)
    broken = solve(data)
    assert_response(broken, "INTERNAL_ERROR")
    assert broken["diagnostics"][0]["code"] == "PRIORITY_SHORTAGE_MISMATCH"


def test_old_contracts_reject_priority_and_default_is_compatible(assignment_request):
    data = assignment(assignment_request, (0, 0))
    data["schema_version"] = "0.15"
    for version in ("0.1", "0.2", "0.3", "0.4"):
        assert solve({**data, "schema_version": version})["status"] == "INVALID_INPUT"
    for value in (-1, True, 1.5, "1"):
        invalid = copy.deepcopy(data)
        invalid["demand"][0]["priority"] = value
        assert solve(invalid)["status"] == "INVALID_INPUT"
    omitted = copy.deepcopy(data)
    for d in omitted["demand"]:
        d.pop("priority")
    for backend in ("auto", "cp_sat", "min_cost_flow"):
        default = copy.deepcopy(omitted)
        default["solver"]["backend"] = backend
        explicit = copy.deepcopy(default)
        for d in explicit["demand"]:
            d["priority"] = 0
        before, after = solve(default), solve(explicit)
        assert before["status"] == after["status"] == "PARTIAL"
        for field in ("solution", "objectives", "shortage_summary"):
            assert before[field] == after[field]
        assert after["priority_summary"]["groups"][0]["proven_minimal"] is True
    empty = {**omitted, "demand": [], "preferences": [], "objectives": []}
    assert solve(empty)["priority_summary"] == {"groups": []}


@pytest.mark.parametrize("minimum", [None, 0])
@pytest.mark.parametrize("priority", [None, 0])
@pytest.mark.parametrize("backend", ["auto", "cp_sat", "min_cost_flow"])
def test_current_defaults_keep_shortage_and_flow(assignment_request, minimum, priority, backend):
    data = assignment(assignment_request, (0, 0))
    for item in data["demand"]:
        if priority is None:
            item.pop("priority")
        if minimum is not None:
            item["minimum_people"] = minimum
    data["solver"]["backend"] = backend
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["solver"]["backend"] == ("cp_sat" if backend == "cp_sat" else "min_cost_flow")
    assert result["shortage_summary"]["total_person_minutes"] == 30
    assert result["shortage_summary"]["shortages"][0]["minimum_people"] == 0
    assert result["priority_summary"] == {
        "groups": [{"priority": 0, "total_person_minutes": 30, "proven_minimal": True}]
    }
    assert result["objectives"][0]["value"] == 0
    assert verify(data, result["solution"])["verification"]["valid"] is True
    assert data == original


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_current_rejects_invalid_priority(assignment_request, value):
    data = assignment(assignment_request)
    data["demand"][0]["priority"] = value
    assert_response(solve(data), "INVALID_INPUT")


def test_priority_cli_and_schemas(assignment_request, tmp_path):
    data = assignment(assignment_request)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = cli("solve", str(path))
    assert result.returncode == 2
    response = json.loads(result.stdout)
    assert_response(response, "PARTIAL")
    solution = tmp_path / "solution.json"
    solution.write_text(json.dumps(response["solution"]), encoding="utf-8")
    checked = json.loads(cli("verify", str(path), str(solution)).stdout)
    assert checked["priority_summary"]["groups"][0]["total_person_minutes"] == 0
    assert (
        json.loads(cli("verify", str(path), str(tmp_path / "missing")).stdout)["priority_summary"]
        is None
    )
    for kind in ("request", "response", "solution", "verification"):
        assert json.loads(cli("schema", kind, "--schema-version", "0.15").stdout) == get_schema(
            kind, "0.15"
        )
    assert Path(__file__).resolve().parents[1].joinpath("examples/demand_priority.json").exists()
