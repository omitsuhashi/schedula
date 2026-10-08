"""契約0.12の必須下限を元需要・固定・独立検証と同じ意味で確認する。"""

import copy
import itertools
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shift_schedula import InvalidInput, cp_sat, get_schema, make_baseline, solve, validate, verify
from shift_schedula.contract import SCHEMA_VERSIONS, schema_errors
from shift_schedula.engine import validate_response
from shift_schedula.model import normalize
from shift_schedula.verify import verify_plan
from tests.roster_support import demand, request
from tests.support import assert_response
from tests.test_cp_sat import small_request
from tests.test_day_counts import bounds, continuity, example
from tests.test_demand_priority import assignment, total_first
from tests.test_extensions import extended
from tests.test_objectives import control_search

ROOT = Path(__file__).resolve().parents[1]


def roster():
    data = extended(request(employees=("alice", "bob")))
    data["schema_version"] = "0.12"
    data["demand"] = [demand(people=3) | {"minimum_people": 1}]
    return data


@pytest.mark.parametrize("kind", ["assignment", "roster"])
@pytest.mark.parametrize("people", [0, 1, 2, 3])
def test_minimum_is_hard_and_original_target_is_retained(assignment_request, kind, people):
    data = roster() if kind == "roster" else small_request(assignment_request, ["kitchen"], 3)
    data["schema_version"] = "0.12"
    data["demand"][0].update(required_people=3, minimum_people=1)
    for employee in data["employees"][people:]:
        employee["availability"] = []
    if kind == "roster":
        # 元候補を不正にせず、配置できる人数を切り替える。
        data = extended(request(employees=tuple("abc"[:people]) or ("a",)))
        data["schema_version"] = "0.12"
        data["demand"] = [demand(people=3) | {"minimum_people": 1}]
        if not people:
            data["employees"][0]["availability"] = []
            data["shift_candidates"] = []
    saved = copy.deepcopy(data)
    assert validate(data)["status"] == "VALID"
    result = solve(data)
    assert_response(result, "INFEASIBLE" if not people else "OPTIMAL" if people == 3 else "PARTIAL")
    assert result["solver"]["selection_reason"] == "MANDATORY_DEMAND"
    assert data == saved
    if people:
        summary = result["shortage_summary"]
        assert summary["total_person_minutes"] == (3 - people) * 30
        assert summary["proven_minimal"]
        if people < 3:
            assert summary["shortages"][0]["minimum_people"] == 1
            assert summary["shortages"][0]["assigned_people"] == people
        checked = verify(data, result["solution"])
        assert checked["status"] == ("VALID" if people == 3 else "PARTIAL")
        assert not checked["shortage_summary"]["proven_minimal"]
    else:
        assert result["shortage_summary"] is None


@pytest.mark.parametrize("value", [None, True, False, -1, 1.5, 4, 251, "1"])
def test_invalid_minimum_rejected(value):
    data = roster()
    data["demand"][0]["minimum_people"] = value
    assert_response(solve(data), "INVALID_INPUT")
    assert validate(data)["diagnostics"][0]["json_pointer"].startswith("/demand/0")


@pytest.mark.parametrize("version", [v for v in SCHEMA_VERSIONS if v not in {"0.12", "0.13"}])
def test_old_versions_reject_minimum_even_zero(assignment_request, version):
    assignment_request["schema_version"] = version
    assignment_request["demand"][0]["minimum_people"] = 0
    assert_response(solve(assignment_request), "INVALID_INPUT")
    assert any(
        d["json_pointer"].startswith("/demand/0")
        for d in schema_errors("request", assignment_request)
    )


@pytest.mark.parametrize("minimum", [None, 0])
def test_zero_and_omission_keep_flow_and_priority_order(assignment_request, minimum):
    data = small_request(assignment_request, ["kitchen"], 1)
    data["schema_version"] = "0.12"
    data["demand"][0]["required_people"] = 3
    if minimum is not None:
        data["demand"][0]["minimum_people"] = minimum
    for backend in ("auto", "min_cost_flow"):
        data["solver"]["backend"] = backend
        result = solve(data)
        assert_response(result, "PARTIAL")
        assert result["solver"]["backend"] == "min_cost_flow"
        assert result["shortage_summary"]["shortages"][0]["minimum_people"] == 0
    data["demand"][0]["minimum_people"] = 1
    assert solve(data)["diagnostics"][0]["code"] == "UNSUPPORTED_BACKEND"


def test_zero_target_equal_minimum_and_qualification_competition(assignment_request):
    data = small_request(assignment_request, ["kitchen"])
    data["schema_version"] = "0.12"
    data["demand"][0].update(required_people=0, minimum_people=0)
    assert_response(solve(data), "OPTIMAL")
    data["demand"][0].update(required_people=1, minimum_people=1)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    data["demand"].append(data["demand"][0] | {"id": "hall", "role_id": "hall"})
    assert_response(solve(data), "INFEASIBLE")
    data["demand"].pop()
    data["skills"] = [{"id": "license", "label": "担当資格"}]
    data["roles"][0]["required_skills"] = [{"skill_id": "license", "min_level": 1}]
    assert_response(solve(data), "INFEASIBLE")


def test_mandatory_short_shift_overrides_total_shortage_and_fixed_baseline():
    data = total_first()
    data["schema_version"] = "0.12"
    original = solve(data)
    assert_response(original, "PARTIAL")
    assert original["shortage_summary"]["total_person_minutes"] == 30
    data["baseline"] = make_baseline(data, original["solution"], "optional")
    data["demand"][0]["minimum_people"] = 1
    data["replan_mode"] = "preserve_assigned"
    assert_response(solve(data), "INFEASIBLE")
    data["replan_mode"] = "rebuild"
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 60
    assert {a["role_id"] for a in result["solution"]["assignments"]} == {"kitchen"}
    baseline = make_baseline(data, result["solution"], "mandatory")
    assert baseline["source_request"]["demand"][0]["minimum_people"] == 1
    assert verify(baseline["source_request"], baseline["source_solution"])["status"] == "PARTIAL"
    baseline["source_solution"]["assignments"] = []
    assert validate(data | {"baseline": baseline})["status"] == "INVALID_INPUT"


def test_verifier_uses_raw_demand_and_rejects_tampering_without_backend(monkeypatch):
    data = roster()
    result = solve(data)
    problem = normalize(data)
    problem.minimums.clear()
    damaged = copy.deepcopy(result["solution"])
    damaged["assignments"] = []
    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("verifyがソルバーを呼びました"))
    violations, _, _ = verify_plan(problem, damaged)
    violation = next(d for d in violations if d["code"] == "MINIMUM_DEMAND_VIOLATION")
    assert violation["json_pointer"] == "/demand/0"
    assert violation["related_ids"] == [data["demand"][0]["id"], "kitchen"]
    assert dict((f["name"], f["value"]) for f in violation["facts"]) == {
        "interval_start": data["demand"][0]["interval"]["start"],
        "interval_end": data["demand"][0]["interval"]["end"],
        "minimum_people": 1,
        "assigned_people": 0,
    }
    assert verify(data, damaged)["status"] == "INVALID_PLAN"
    assert verify(data, result["solution"])["status"] == "PARTIAL"
    with pytest.raises(InvalidInput):
        make_baseline(data, damaged, "bad")
    for value in (0, 3):
        changed = copy.deepcopy(result)
        changed["shortage_summary"]["shortages"][0]["minimum_people"] = value
        with pytest.raises(InvalidInput):
            validate_response(changed, data)
    del result["shortage_summary"]["shortages"][0]["minimum_people"]
    assert schema_errors("response", result)


def diagnosis_options():
    return {
        "time_limit_seconds": 10,
        "max_suggestions": 3,
        "conflict_refinement": {"time_limit_seconds": 5},
        "allowed_changes": [
            {
                "id": "upper_only",
                "edits": [{"json_pointer": "/demand/0/required_people", "value": 0}],
            },
            {
                "id": "lower_only",
                "edits": [{"json_pointer": "/demand/0/minimum_people", "value": 0}],
            },
            {
                "id": "both",
                "edits": [
                    {"json_pointer": "/demand/0/required_people", "value": 0},
                    {"json_pointer": "/demand/0/minimum_people", "value": 0},
                ],
            },
        ],
    }


def test_diagnosis_removes_both_bounds_and_only_explicit_edits(assignment_request):
    data = small_request(assignment_request, ["kitchen"])
    data["schema_version"] = "0.12"
    data["demand"][0].update(required_people=3, minimum_people=1)
    data["employees"][0]["availability"] = []
    data["diagnosis"] = diagnosis_options()
    saved = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    assert detail["status"] == "COMPLETE"
    assert detail["conflict"]["minimality"] == "inclusion_minimal"
    assert [g["group_id"] for g in detail["conflict"]["conditions"]] == ["/demand/0"]
    assert {s["option_id"]: s["response"]["status"] for s in detail["suggestions"]} == {
        "lower_only": "PARTIAL",
        "both": "OPTIMAL",
    }
    rejected = next(d for d in detail["diagnostics"] if d["code"] == "OPTION_REJECTED")
    assert rejected["related_ids"] == ["upper_only"]
    assert data == saved
    for suggestion in detail["suggestions"]:
        modified = suggestion["modified_request"]
        assert modified["demand"][0]["minimum_people"] == 0
        assert verify(modified, suggestion["response"]["solution"])["verification"]["valid"]


def test_relaxation_keeps_assignment_variables_and_background(assignment_request):
    data = small_request(assignment_request, ["kitchen"], 2)
    data["schema_version"] = "0.12"
    data["demand"][0]["minimum_people"] = 1
    module, _ = cp_sat.load_backend()
    problem = normalize(data)
    models = [
        cp_sat.prepare(problem, module, active_groups=groups) for groups in ({"/demand/0"}, set())
    ]
    assert models[0][1].keys() == models[1][1].keys()
    for bits in itertools.product((0, 1), repeat=len(models[0][1])):
        for (model, variables, _, _), groups in zip(models, ({"/demand/0"}, set()), strict=True):
            fixed = model.clone()
            for variable, bit in zip(variables.values(), bits, strict=True):
                fixed.add(fixed.get_bool_var_from_proto_index(variable.index) == bit)
            feasible = module.CpSolver().solve(fixed) == module.OPTIMAL
            expected = sum(bits) == 1 if groups else True
            assert feasible == expected
            solution = {
                "shifts": [],
                "assignments": [
                    {"employee_id": e, "role_id": r, "interval": data["demand"][0]["interval"]}
                    for (e, _, r), bit in zip(variables, bits, strict=True)
                    if bit
                ],
            }
            assert (not verify_plan(problem, solution, active_groups=groups)[0]) == expected


def test_day_bounds_and_committed_background_survive_mandatory_demand():
    data = example(1)
    data["schema_version"] = "0.12"
    data["demand"] = [demand() | {"minimum_people": 1}]
    row = continuity(data)
    row["committed_shifts"] = [
        {"id": "confirmed", "segments": data["shift_candidates"][0]["segments"]}
    ]
    data["constraints"] = [bounds(data, max_days=0)]
    data["diagnosis"] = diagnosis_options() | {"allowed_changes": []}
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert [g["group_id"] for g in conflict["conditions"]] == ["/constraints/0"]
    assert any(g["code"] == "COMMITTED_SHIFT_BACKGROUND" for g in conflict["background_conditions"])
    data["constraints"] = []
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["solution"]["shifts"][0]["committed_shift_id"] == "confirmed"


@pytest.mark.parametrize("minimums", [(0, 0), (1, 0), (0, 1), (1, 1)])
@pytest.mark.parametrize("priorities", [(10, 0), (0, 10)])
def test_assignment_matches_independent_small_enumeration(assignment_request, minimums, priorities):
    data = assignment(assignment_request, priorities, employees=2)
    data["schema_version"] = "0.12"
    for d, minimum in zip(data["demand"], minimums, strict=True):
        d["minimum_people"] = minimum
        d["interval"]["end"] = d["interval"]["end"].replace("11:30", "12:00")
    data["planning_window"]["end"] = data["demand"][0]["interval"]["end"]
    for e in data["employees"]:
        e["availability"][0]["end"] = data["planning_window"]["end"]
    data["constraints"] = [
        {
            "id": "cap",
            "type": "max_assigned_minutes",
            "employee_ids": [e["id"] for e in data["employees"]],
            "limit_minutes": 30,
        }
    ]
    best = None
    levels = sorted(priorities, reverse=True)
    for cells in itertools.product((None, "kitchen", "hall"), repeat=4):
        if any(sum(c is not None for c in cells[e * 2 : e * 2 + 2]) > 1 for e in (0, 1)):
            continue
        counts = Counter((slot, cells[e * 2 + slot]) for e in (0, 1) for slot in (0, 1))
        if any(
            not minimum <= counts[slot, role] <= 1
            for slot in (0, 1)
            for role, minimum in zip(("kitchen", "hall"), minimums, strict=True)
        ):
            continue
        shortages = {
            role: sum(30 * (1 - counts[slot, role]) for slot in (0, 1))
            for role in ("kitchen", "hall")
        }
        values = (
            sum(shortages.values()),
            *(
                sum(
                    shortages[role]
                    for role, p in zip(("kitchen", "hall"), priorities, strict=True)
                    if p == level
                )
                for level in levels
            ),
            30 * sum(c == "kitchen" for c in cells[:2]),
        )
        best = values if best is None else min(best, values)
    result = solve(data)
    assert_response(result, "INFEASIBLE" if best is None else "PARTIAL")
    if best is not None:
        assert (
            result["shortage_summary"]["total_person_minutes"],
            *(g["total_person_minutes"] for g in result["priority_summary"]["groups"]),
            result["objectives"][0]["value"],
        ) == best


@pytest.mark.parametrize(
    "statuses",
    [("UNKNOWN",), ("FEASIBLE",), ("OPTIMAL", "UNKNOWN"), ("OPTIMAL", "OPTIMAL", "UNKNOWN")],
)
def test_time_limit_keeps_hard_minimum_and_proof_prefix(monkeypatch, statuses):
    data = total_first()
    data["schema_version"] = "0.12"
    data["demand"][0]["minimum_people"] = 1
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "UNKNOWN" if statuses == ("UNKNOWN",) else "PARTIAL")
    assert len(calls) == len(statuses)
    if result["solution"]:
        assert verify(data, result["solution"])["verification"]["valid"]
        assert result["shortage_summary"]["total_person_minutes"] == 60
        assert all(not o["proven_optimal"] for o in result["objectives"])


def test_schema_cli_and_example_round_trip(tmp_path):
    data = roster()
    result = solve(data)
    path, plan = tmp_path / "request.json", tmp_path / "solution.json"
    path.write_text(json.dumps(data))
    plan.write_text(json.dumps(result["solution"]))
    for args in (
        ["solve", str(path)],
        ["verify", str(path), str(plan)],
        ["verify", str(path), str(tmp_path / "missing")],
    ):
        process = subprocess.run(
            [sys.executable, "-m", "shift_schedula", *args], capture_output=True, text=True
        )
        assert process.returncode == 2 and not process.stderr
        output = json.loads(process.stdout)
        assert output["schema_version"] == "0.12"
        assert not schema_errors("response" if args[0] == "solve" else "verification", output)
    for kind in ("request", "response", "solution", "verification"):
        schema = get_schema(kind, "0.12")
        Draft202012Validator.check_schema(schema)
        process = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.12"],
            capture_output=True,
            text=True,
        )
        assert process.returncode == 0 and json.loads(process.stdout) == schema
    for kind in ("assignment", "roster"):
        input_data = json.loads((ROOT / f"examples/minimum_{kind}.json").read_text())
        assert_response(solve(input_data), "PARTIAL")


@pytest.mark.parametrize("minimum", [0, 1])
def test_roster_matches_all_candidate_subsets(minimum):
    data = total_first()
    data["schema_version"] = "0.12"
    data["demand"][0]["minimum_people"] = minimum
    best = None
    for short, long in itertools.product((0, 1), repeat=2):
        if short + long > 1 or short < minimum:
            continue
        shortages = (30 * (1 - short), 60 * (1 - long))
        values = (sum(shortages), *shortages, 30 * short + 60 * long)
        best = values if best is None else min(best, values)
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert (
        result["shortage_summary"]["total_person_minutes"],
        *(g["total_person_minutes"] for g in result["priority_summary"]["groups"]),
        result["objectives"][0]["value"],
    ) == best


def test_shared_search_budget_includes_all_shortage_and_priority_stages(monkeypatch):
    data = total_first()
    data["schema_version"] = "0.12"
    data["demand"][0]["minimum_people"] = 1
    module, _ = cp_sat.load_backend()
    search = module.CpSolver.solve
    clock, budgets = [0.0], []

    def timed(solver, model):
        budgets.append(solver.parameters.max_time_in_seconds)
        clock[0] += 2
        return search(solver, model)

    monkeypatch.setattr(cp_sat.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.CpSolver, "solve", timed)
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert budgets == [10, 8, 6, 4]
    assert all(g["proven_minimal"] for g in result["priority_summary"]["groups"])
    assert result["objectives"][0]["proven_optimal"]


def test_no_optional_dependency_verifies_minimum_and_reports_missing_backend(monkeypatch):
    data = roster()
    result = solve(data)

    def unavailable():
        raise cp_sat.BackendUnavailable

    monkeypatch.setattr(cp_sat, "load_backend", unavailable)
    assert verify(data, result["solution"])["status"] == "PARTIAL"
    failure = solve(data)
    assert_response(failure, "BACKEND_UNAVAILABLE")
    assert failure["solver"]["selection_reason"] == "MANDATORY_DEMAND"


@pytest.mark.parametrize("version", ["0.11", "0.12"])
def test_optional_minimum_edit_is_versioned_and_bounded(version):
    data = roster()
    data["schema_version"] = version
    del data["demand"][0]["minimum_people"]
    data["diagnosis"] = diagnosis_options() | {
        "allowed_changes": [
            {"id": "explicit", "edits": [{"json_pointer": "/demand/0/minimum_people", "value": 1}]}
        ]
    }
    assert validate(data)["status"] == ("VALID" if version == "0.12" else "INVALID_INPUT")
    if version == "0.12":
        data["diagnosis"]["allowed_changes"][0]["edits"][0]["value"] = 251
        assert validate(data)["diagnostics"][0]["code"] == "INVALID_DIAGNOSIS_VALUE"


def test_maximum_people_bound_is_valid_but_unreachable():
    data = roster()
    data["demand"][0].update(required_people=250, minimum_people=250)
    assert validate(data)["status"] == "VALID"
    assert_response(solve(data), "INFEASIBLE")
