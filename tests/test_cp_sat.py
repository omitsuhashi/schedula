import copy
import itertools
import json
import random
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from ortools import __version__ as ortools_version
from ortools.sat.python import cp_model

from schedula import cp_sat, flow, solve
from schedula.model import normalize
from schedula.verify import verify_solution
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def stamp(slot):
    return (datetime(2026, 10, 5, 11) + timedelta(minutes=30 * slot)).isoformat() + "+09:00"


def small_request(base, sequence, employees=1):
    request = copy.deepcopy(base)
    request["planning_window"]["end"] = stamp(len(sequence))
    request["skills"] = []
    request["roles"] = [
        {"id": role, "label": role, "required_skills": []} for role in ["kitchen", "hall"]
    ]
    request["employees"] = request["employees"][:employees]
    for employee in request["employees"]:
        employee["skills"] = []
        employee["availability"] = [{"start": stamp(0), "end": stamp(len(sequence))}]
    request["demand"] = [
        {
            "id": f"need_{slot}",
            "role_id": role,
            "interval": {"start": stamp(slot), "end": stamp(slot + 1)},
            "required_people": 1,
        }
        for slot, role in enumerate(sequence)
        if role is not None
    ]
    request["preferences"] = []
    request["objectives"] = []
    return request


def limit(kind, value, employee_ids=("alice",), identifier="cap"):
    return {
        "id": identifier,
        "type": kind,
        "employee_ids": list(employee_ids),
        "limit_minutes" if kind == "max_assigned_minutes" else "limit_count": value,
    }


@pytest.mark.parametrize("backend", ["auto", "cp_sat"])
def test_linked_example(backend):
    request = json.loads((ROOT / "examples/linked_assignment.json").read_text(encoding="utf-8"))
    request["solver"]["backend"] = backend
    original = copy.deepcopy(request)
    result = solve(request)
    assert_response(result, "OPTIMAL")
    assert result["solver"]["backend"] == "cp_sat"
    assert result["solver"]["library_version"] == ortools_version
    assert result["solver"]["selection_reason"] == (
        "ASSIGNMENT_CONSTRAINTS" if backend == "auto" else "EXPLICIT_BACKEND"
    )
    assert result["objectives"][0]["value"] == 0
    assert verify_solution(normalize(request), result["solution"]) == ([], (0,))
    assert request == original


@pytest.mark.parametrize("minutes", [0, 29, 30, 59, 60, 61])
def test_assigned_minutes_boundary(assignment_request, minutes):
    request = small_request(assignment_request, ["kitchen", "kitchen"])
    request["constraints"] = [limit("max_assigned_minutes", minutes)]
    assert_response(solve(request), "OPTIMAL" if minutes >= 60 else "INFEASIBLE")


@pytest.mark.parametrize(
    "sequence, switches",
    [
        (["kitchen", "hall", "kitchen"], 2),
        (["kitchen", "kitchen", "hall"], 1),
        (["kitchen", None, "hall"], 0),
        ([None, "kitchen", "hall", None], 1),
        (["kitchen", None, None, "hall"], 0),
        (["kitchen", "kitchen", "kitchen"], 0),
        ([None, None], 0),
    ],
)
def test_switch_definition_objective_and_limit(assignment_request, sequence, switches):
    request = small_request(assignment_request, sequence)
    request["objectives"] = [{"id": "changes", "metric": "role_switches"}]
    result = solve(request)
    assert_response(result, "OPTIMAL")
    assert result["solver"]["selection_reason"] == "ROLE_SWITCH_OBJECTIVE"
    assert result["objectives"][0]["value"] == switches
    # 上限だけでも正確に数える。目的がなくても無断で切替を認めない。
    request["objectives"] = []
    for bound in {0, switches, switches + 1}:
        request["constraints"] = [limit("max_role_switches", bound)]
        assert_response(solve(request), "OPTIMAL" if bound >= switches else "INFEASIBLE")


def test_limits_apply_to_each_employee_and_all_constraints(assignment_request):
    request = small_request(assignment_request, ["kitchen", "hall"], employees=2)
    request["constraints"] = [limit("max_assigned_minutes", 30, ("alice", "bob"))]
    result = solve(request)
    assert_response(result, "OPTIMAL")
    assert {a["employee_id"] for a in result["solution"]["assignments"]} == {"alice", "bob"}
    request["constraints"].append(limit("max_assigned_minutes", 0, identifier="stricter"))
    assert_response(solve(request), "INFEASIBLE")


def test_zero_limits_allow_idle_and_unavailable_employees(assignment_request):
    request = small_request(assignment_request, [None, None], employees=2)
    request["employees"][0]["availability"] = []
    request["constraints"] = [
        limit("max_assigned_minutes", 0, ("alice", "bob")),
        limit("max_role_switches", 0, ("alice", "bob"), "switch_cap"),
    ]
    assert_response(solve(request), "OPTIMAL")


@pytest.mark.parametrize("metric", ["preference_penalty", "role_switches"])
def test_two_employee_switch_objective(assignment_request, metric):
    request = small_request(assignment_request, ["kitchen", "hall", "kitchen"], employees=2)
    request["solver"]["backend"] = "cp_sat"
    request["objectives"] = [{"id": "goal", "metric": metric}]
    result = solve(request)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_employee",
        "duplicate_id",
        "duplicate_employee",
        "negative",
        "fraction",
        "unknown_type",
        "roster_rule",
        "extra_field",
        "duplicate_metric",
        "flow_constraint",
        "flow_switch_objective",
    ],
)
def test_invalid_linked_input_rejected_before_solver(assignment_request, monkeypatch, mutation):
    request = small_request(assignment_request, ["kitchen", "hall"])
    request["constraints"] = [limit("max_role_switches", 0)]
    if mutation == "unknown_employee":
        request["constraints"][0]["employee_ids"] = ["missing"]
    elif mutation == "duplicate_id":
        request["constraints"] *= 2
    elif mutation == "duplicate_employee":
        request["constraints"][0]["employee_ids"] *= 2
    elif mutation in {"negative", "fraction"}:
        request["constraints"][0]["limit_count"] = -1 if mutation == "negative" else 0.5
    elif mutation in {"unknown_type", "roster_rule"}:
        request["constraints"][0] = {
            "id": "cap",
            "type": "ignore_me" if mutation == "unknown_type" else "max_scheduled_minutes",
            "employee_ids": ["alice"],
            "limit_minutes": 30,
        }
    elif mutation == "extra_field":
        request["constraints"][0]["unexpected"] = True
    elif mutation == "duplicate_metric":
        request["objectives"] = [
            {"id": "first", "metric": "preference_penalty"},
            {"id": "second", "metric": "preference_penalty"},
        ]
    elif mutation == "flow_constraint":
        request["solver"]["backend"] = "min_cost_flow"
    else:
        request["constraints"] = []
        request["solver"]["backend"] = "min_cost_flow"
        request["objectives"] = [{"id": "goal", "metric": "role_switches"}]
    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("invalid input loaded backend"))
    result = solve(request)
    assert_response(result, "INVALID_INPUT")
    assert result["solver"]["backend"] == "none"


@pytest.mark.parametrize(
    "backend, constraints, metric, selected, reason",
    [
        ("auto", False, None, "min_cost_flow", "INDEPENDENT_ADDITIVE_ASSIGNMENTS"),
        ("auto", False, "preference_penalty", "min_cost_flow", "INDEPENDENT_ADDITIVE_ASSIGNMENTS"),
        ("auto", True, None, "cp_sat", "ASSIGNMENT_CONSTRAINTS"),
        ("auto", True, "preference_penalty", "cp_sat", "ASSIGNMENT_CONSTRAINTS"),
        ("auto", False, "role_switches", "cp_sat", "ROLE_SWITCH_OBJECTIVE"),
        ("min_cost_flow", False, None, "min_cost_flow", "EXPLICIT_BACKEND"),
        ("cp_sat", False, None, "cp_sat", "EXPLICIT_BACKEND"),
    ],
)
def test_only_one_backend_is_called(
    assignment_request, monkeypatch, backend, constraints, metric, selected, reason
):
    request = small_request(assignment_request, ["kitchen", "kitchen"])
    request["solver"]["backend"] = backend
    if constraints:
        request["constraints"] = [limit("max_assigned_minutes", 60)]
    if metric:
        request["objectives"] = [{"id": "goal", "metric": metric}]
    calls = Counter()
    original_flow, original_sat = flow.run, cp_sat.run

    def run_flow(problem):
        calls["min_cost_flow"] += 1
        return original_flow(problem)

    def run_sat(problem, module):
        calls["cp_sat"] += 1
        return original_sat(problem, module)

    monkeypatch.setattr(flow, "run", run_flow)
    monkeypatch.setattr(cp_sat, "run", run_sat)
    result = solve(request)
    assert_response(result, "OPTIMAL")
    assert calls == {selected: 1}
    assert result["solver"]["selection_reason"] == reason
    assert result["solver"]["library_version"] == (
        ortools_version if selected == "cp_sat" else None
    )


@pytest.mark.parametrize("selection", ["explicit", "constraint", "objective"])
def test_dependency_missing_never_falls_back(assignment_request, monkeypatch, selection):
    import builtins

    request = small_request(assignment_request, ["kitchen", "hall"])
    if selection == "explicit":
        request["solver"]["backend"] = "cp_sat"
    elif selection == "constraint":
        request["constraints"] = [limit("max_role_switches", 1)]
    else:
        request["objectives"] = [{"id": "goal", "metric": "role_switches"}]
    original_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "ortools" or name.startswith("ortools."):
            raise ModuleNotFoundError("deliberate missing dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    monkeypatch.setattr(flow, "run", lambda _: pytest.fail("fallback is forbidden"))
    result = solve(request)
    assert_response(result, "BACKEND_UNAVAILABLE")
    assert result["solver"]["backend"] == "cp_sat"
    assert result["solver"]["selection_reason"] != "NOT_SELECTED"
    assert result["solver"]["library_version"] is None
    assert result["diagnostics"][0]["code"] == "BACKEND_UNAVAILABLE"


@pytest.mark.parametrize("kind", ["max_assigned_minutes", "max_role_switches"])
def test_corrupt_linked_solution_is_independently_blocked(assignment_request, monkeypatch, kind):
    request = small_request(assignment_request, ["kitchen", "hall", "kitchen"])
    request["objectives"] = [{"id": "goal", "metric": "role_switches"}]
    solution = solve(request)["solution"]
    request["constraints"] = [limit(kind, 0)]
    problem = normalize(request)
    problem.available.clear()
    problem.qualified.clear()
    problem.demand.clear()
    problem.costs.clear()
    violations, value = verify_solution(problem, solution)
    code = (
        "MAX_ASSIGNED_MINUTES_VIOLATION"
        if kind == "max_assigned_minutes"
        else "MAX_ROLE_SWITCHES_VIOLATION"
    )
    assert code in {v["code"] for v in violations}
    assert value == (2,)
    assert violations[0]["related_ids"] == ["cap", "alice"]
    monkeypatch.setattr(
        cp_sat, "run", lambda *_: cp_sat.SatResult("OPTIMAL", solution, (2,), (True,))
    )
    result = solve(request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["performed"]
    assert code in {v["code"] for v in result["verification"]["violations"]}


def test_switch_objective_mismatch_is_blocked(assignment_request, monkeypatch):
    request = small_request(assignment_request, ["kitchen", "hall"])
    request["objectives"] = [{"id": "goal", "metric": "role_switches"}]
    solution = solve(request)["solution"]
    monkeypatch.setattr(
        cp_sat, "run", lambda *_: cp_sat.SatResult("OPTIMAL", solution, (0,), (True,))
    )
    result = solve(request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["diagnostics"][0]["code"] == "OBJECTIVE_VALUE_MISMATCH"


@pytest.mark.parametrize("status", ["FEASIBLE", "UNKNOWN", "INFEASIBLE", "MODEL_INVALID"])
def test_native_statuses_and_feasible_verification(assignment_request, monkeypatch, status):
    request = small_request(assignment_request, ["kitchen", "hall"])
    request["objectives"] = [{"id": "goal", "metric": "role_switches"}]
    original = cp_model.CpSolver.solve

    def controlled(solver, model):
        if status == "FEASIBLE":
            assert original(solver, model) == cp_model.OPTIMAL
        return getattr(cp_model, status)

    monkeypatch.setattr(cp_model.CpSolver, "solve", controlled)
    result = solve(request)
    assert_response(result, "INTERNAL_ERROR" if status == "MODEL_INVALID" else status)
    assert result["solver"]["library_version"] == ortools_version
    if status == "FEASIBLE":
        assert result["objectives"][0] == {
            "id": "goal",
            "metric": "role_switches",
            "value": 1,
            "proven_optimal": False,
        }


def test_feasible_solution_is_still_checked(assignment_request, monkeypatch):
    request = small_request(assignment_request, ["kitchen", "hall"])
    request["solver"]["backend"] = "cp_sat"
    monkeypatch.setattr(
        cp_sat, "run", lambda *_: cp_sat.SatResult("FEASIBLE", {"assignments": [], "shifts": []})
    )
    result = solve(request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["valid"] is False


def test_preparation_and_import_are_outside_search_limit(assignment_request, monkeypatch):
    request = small_request(assignment_request, ["kitchen", "hall"])
    request["solver"]["backend"] = "cp_sat"
    original_load, original_prepare, original_solve = (
        cp_sat.load_backend,
        cp_sat.prepare,
        cp_model.CpSolver.solve,
    )
    stages = []

    def load():
        stages.append("load")
        return original_load()

    def prepare(*args):
        stages.append("prepare")
        return original_prepare(*args)

    def search(solver, model):
        stages.append("search")
        assert solver.parameters.max_time_in_seconds == request["solver"]["time_limit_seconds"]
        assert solver.parameters.random_seed == request["solver"]["seed"]
        return original_solve(solver, model)

    monkeypatch.setattr(cp_sat, "load_backend", load)
    monkeypatch.setattr(cp_sat, "prepare", prepare)
    monkeypatch.setattr(cp_model.CpSolver, "solve", search)
    assert_response(solve(request), "OPTIMAL")
    assert stages == ["load", "prepare", "search"]


def exhaustive_linked_value(request):
    # この小規模 fixture は技能なし・30分枠。元入力から勤務可能・需要・上限を照合する。
    start = datetime.fromisoformat(request["planning_window"]["start"])
    end = datetime.fromisoformat(request["planning_window"]["end"])
    slots = int((end - start).total_seconds() // 1800)
    employees = [e["id"] for e in request["employees"]]
    roles = [r["id"] for r in request["roles"]]
    needed = Counter()
    choices = []
    for slot in range(slots):
        a, b = start + timedelta(minutes=30 * slot), start + timedelta(minutes=30 * (slot + 1))
        for demand in request["demand"]:
            if datetime.fromisoformat(
                demand["interval"]["start"]
            ) <= a and b <= datetime.fromisoformat(demand["interval"]["end"]):
                needed[slot, demand["role_id"]] = demand["required_people"]
        for employee in request["employees"]:
            available = any(
                datetime.fromisoformat(i["start"]) <= a and b <= datetime.fromisoformat(i["end"])
                for i in employee["availability"]
            )
            choices.append([None, *roles] if available else [None])
    best = None
    for values in itertools.product(*choices):
        per_employee = {
            employee: values[i :: len(employees)] for i, employee in enumerate(employees)
        }
        if any(
            sum(per_employee[e][slot] == role for e in employees) != needed[slot, role]
            for slot in range(slots)
            for role in roles
        ):
            continue
        minutes = {e: 30 * sum(r is not None for r in row) for e, row in per_employee.items()}
        switches = {
            e: sum(
                a is not None and b is not None and a != b
                for a, b in zip(row, row[1:], strict=False)
            )
            for e, row in per_employee.items()
        }
        if any(
            (
                minutes[e] > c["limit_minutes"]
                if c["type"] == "max_assigned_minutes"
                else switches[e] > c["limit_count"]
            )
            for c in request["constraints"]
            for e in c["employee_ids"]
        ):
            continue
        metrics = {
            "role_switches": sum(switches.values()),
            "preference_penalty": sum(
                30 * p["penalty_per_minute"]
                for e, row in per_employee.items()
                for role in row
                for p in request["preferences"]
                if e in p["employee_ids"] and role == p["role_id"]
            ),
        }
        value = tuple(metrics[o["metric"]] for o in request["objectives"])
        best = value if best is None else min(best, value)
    return best


@pytest.mark.parametrize("seed", range(80))
def test_linked_optimum_matches_independent_exhaustive_search(assignment_request, seed):
    rng = random.Random(seed)
    sequence = [rng.choice(["kitchen", "hall", None]) for _ in range(3)]
    request = small_request(assignment_request, sequence, employees=2)
    for employee in request["employees"]:
        employee["availability"] = [
            {"start": stamp(slot), "end": stamp(slot + 1)}
            for slot in range(3)
            if rng.choice([True, True, False])
        ]
    request["constraints"] = [
        limit("max_assigned_minutes", rng.choice([0, 30, 60, 90]), (e["id"],), f"minutes_{e['id']}")
        for e in request["employees"]
    ] + [
        limit("max_role_switches", rng.randrange(3), (e["id"],), f"switches_{e['id']}")
        for e in request["employees"]
    ]
    metrics = rng.sample(["preference_penalty", "role_switches"], rng.randrange(3))
    request["objectives"] = [{"id": metric, "metric": metric} for metric in metrics]
    if "preference_penalty" in metrics:
        request["preferences"] = [
            {
                "id": "avoid",
                "type": "avoid_role",
                "employee_ids": ["alice"],
                "role_id": rng.choice(["kitchen", "hall"]),
                "penalty_per_minute": rng.randrange(1, 5),
            }
        ]
    expected = exhaustive_linked_value(request)
    result = solve(request)
    assert_response(result, "INFEASIBLE" if expected is None else "OPTIMAL")
    if expected is not None:
        assert tuple(o["value"] for o in result["objectives"]) == expected


def test_cp_sat_cli_json_only():
    result = subprocess.run(
        [sys.executable, "-m", "schedula", "solve", str(ROOT / "examples/linked_assignment.json")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    response = json.loads(result.stdout)
    assert_response(response, "OPTIMAL")
    assert response["solver"]["backend"] == "cp_sat"


def test_real_search_timeout_is_unknown(assignment_request):
    request = small_request(assignment_request, ["kitchen", "hall"])
    request["solver"]["backend"] = "cp_sat"
    request["solver"]["time_limit_seconds"] = 1e-9
    result = solve(request)
    assert_response(result, "UNKNOWN")
    assert result["diagnostics"][0]["code"] == "TIME_LIMIT"


def test_wheel_without_ortools_reports_unavailable_and_preserves_flow(tmp_path):
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    (wheel,) = tmp_path.glob("*.whl")
    script = """
import importlib.util, json, pathlib, subprocess, sys
assert importlib.util.find_spec('ortools') is None
import schedula
from schedula.contract import schema_errors
root = pathlib.Path(sys.argv[1])
assert str(root) not in schedula.__file__
request = json.loads((root / 'examples/assignment.json').read_text(encoding='utf-8'))
result = schedula.solve(request)
assert result['status'] == 'OPTIMAL' and result['verification']['valid'] is True
assert result['solver']['backend'] == 'min_cost_flow' and not schema_errors('response', result)
for example in ['linked_assignment.json', 'roster.json']:
    request = json.loads((root / 'examples' / example).read_text(encoding='utf-8'))
    for backend in ['auto', 'cp_sat']:
        request['solver']['backend'] = backend
        result = schedula.solve(request)
        assert result['status'] == 'BACKEND_UNAVAILABLE' and result['solution'] is None
        assert result['solver']['backend'] == 'cp_sat' and not schema_errors('response', result)
    request['solver']['backend'] = 'min_cost_flow'
    assert schedula.solve(request)['status'] == 'INVALID_INPUT'
cli = subprocess.run(
    [sys.executable, '-I', '-m', 'schedula', 'solve',
     str(root / 'examples/linked_assignment.json')], capture_output=True, text=True,
)
assert cli.returncode == 2 and cli.stderr == ''
assert json.loads(cli.stdout)['status'] == 'BACKEND_UNAVAILABLE'
print('isolated wheel: flow OPTIMAL; CP-SAT BACKEND_UNAVAILABLE; incompatible flow INVALID_INPUT')
"""
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--isolated",
            "--python",
            sys.executable,
            "--with",
            str(wheel),
            "--with",
            "jsonschema==4.26.0",
            "python",
            "-I",
            "-c",
            script,
            str(ROOT),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "isolated wheel: flow OPTIMAL" in result.stdout
