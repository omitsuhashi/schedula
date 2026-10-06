import copy
import itertools

import pytest
from ortools.sat.python import cp_model

from schedula import cp_sat, engine, solve
from schedula.contract import InvalidInput
from schedula.model import normalize
from schedula.verify import verify_solution
from tests.roster_support import candidate, demand, request
from tests.support import assert_response
from tests.test_cp_sat import exhaustive_linked_value, small_request, stamp
from tests.test_roster import exhaustive_value

METRICS = ("preference_penalty", "scheduled_minutes", "role_switches")


def tradeoff_request(order=METRICS):
    data = request(employees=("alice", "bob"))
    data["shift_candidates"] = [candidate("alice"), candidate("bob", end=660)]
    data["demand"] = [demand(), demand(start=630, end=660, role="hall")]
    data["preferences"] = [
        {
            "id": "avoid",
            "type": "avoid_role",
            "employee_ids": ["bob"],
            "role_id": "kitchen",
            "penalty_per_minute": 1,
        }
    ]
    data["objectives"] = [{"id": metric, "metric": metric} for metric in order]
    return data


@pytest.mark.parametrize("order", list(itertools.permutations(METRICS)))
def test_roster_priority_matches_independent_enumeration(order):
    data = tradeoff_request(order)
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    actual = tuple(o["value"] for o in result["objectives"])
    assert actual == exhaustive_value(data)
    expected = (
        (30, 60, 1)
        if order[0] == "scheduled_minutes"
        else (0, 150, 0)
        if order.index("role_switches") < order.index("scheduled_minutes")
        else (0, 90, 1)
    )
    assert dict(zip(order, actual, strict=True)) == dict(zip(METRICS, expected, strict=True))
    assert verify_solution(normalize(data), result["solution"]) == ([], actual)
    assert data == original


@pytest.mark.parametrize("reverse", [False, True])
def test_assignment_priority_changes_the_selected_plan(assignment_request, reverse):
    data = small_request(assignment_request, ["kitchen", "hall"], employees=2)
    data["employees"][0]["availability"][0]["end"] = stamp(1)
    data["preferences"] = tradeoff_request()["preferences"]
    data["preferences"][0]["employee_ids"] = ["alice"]
    order = ["preference_penalty", "role_switches"]
    if reverse:
        order.reverse()
    data["objectives"] = [{"id": m, "metric": m} for m in order]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["solver"]["selection_reason"] == "ROLE_SWITCH_OBJECTIVE"
    actual = {o["metric"]: o["value"] for o in result["objectives"]}
    assert actual == {
        "preference_penalty": 30 if reverse else 0,
        "role_switches": 0 if reverse else 1,
    }
    assert tuple(o["value"] for o in result["objectives"]) == exhaustive_linked_value(data)


def control_search(monkeypatch, statuses):
    search, make_solution = cp_model.CpSolver.solve, cp_sat.make_solution
    calls, snapshots = [], []

    def controlled(solver, model):
        status = statuses[len(calls)]
        calls.append(solver.parameters.max_time_in_seconds)
        if status == "ERROR":
            raise RuntimeError("controlled backend failure")
        if status in {"OPTIMAL", "FEASIBLE"}:
            assert search(solver, model) == cp_model.OPTIMAL
        return getattr(cp_model, status)

    def capture(*args):
        solution = make_solution(*args)
        snapshots.append(solution)
        return solution

    monkeypatch.setattr(cp_model.CpSolver, "solve", controlled)
    monkeypatch.setattr(cp_sat, "make_solution", capture)
    return calls, snapshots


@pytest.mark.parametrize(
    "statuses,expected,proofs",
    [
        (("FEASIBLE",), "FEASIBLE", (False, False, False)),
        (("OPTIMAL", "FEASIBLE"), "FEASIBLE", (True, False, False)),
        (("OPTIMAL", "OPTIMAL", "FEASIBLE"), "FEASIBLE", (True, True, False)),
        (("UNKNOWN",), "UNKNOWN", ()),
        (("OPTIMAL", "UNKNOWN"), "FEASIBLE", (True, False, False)),
        (("OPTIMAL", "OPTIMAL", "UNKNOWN"), "FEASIBLE", (True, True, False)),
        (("INFEASIBLE",), "INFEASIBLE", ()),
        (("OPTIMAL", "INFEASIBLE"), "INTERNAL_ERROR", ()),
        (("MODEL_INVALID",), "INTERNAL_ERROR", ()),
        (("OPTIMAL", "MODEL_INVALID"), "INTERNAL_ERROR", ()),
        (("ERROR",), "INTERNAL_ERROR", ()),
        (("OPTIMAL", "ERROR"), "INTERNAL_ERROR", ()),
    ],
)
def test_stage_endings_preserve_only_valid_solutions(monkeypatch, statuses, expected, proofs):
    data = tradeoff_request()
    calls, snapshots = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, expected)
    assert len(calls) == len(statuses)
    assert tuple(o["proven_optimal"] for o in result["objectives"]) == proofs
    if result["solution"] is not None:
        assert result["solution"] == snapshots[-1]
        assert verify_solution(normalize(data), result["solution"]) == (
            [],
            tuple(o["value"] for o in result["objectives"]),
        )
        assert result["objectives"][0]["value"] == 0


@pytest.mark.parametrize("completed", [1, 2])
def test_budget_expires_between_stages(monkeypatch, completed):
    data = tradeoff_request()
    clock = [0.0]
    calls, snapshots = control_search(monkeypatch, ("OPTIMAL",) * completed)
    controlled = cp_model.CpSolver.solve

    def search(*args):
        status = controlled(*args)
        clock[0] = 10.0 if len(calls) == completed else 2.0
        return status

    monkeypatch.setattr(cp_sat.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cp_model.CpSolver, "solve", search)
    result = solve(data)
    assert_response(result, "FEASIBLE")
    assert len(calls) == completed
    assert result["solution"] == snapshots[-1]
    assert [o["proven_optimal"] for o in result["objectives"]] == [i < completed for i in range(3)]
    assert result["diagnostics"][0]["code"] == "TIME_LIMIT"
    assert result["diagnostics"][0]["json_pointer"] == f"/objectives/{completed}"


def test_shared_budget_excludes_preparation_and_records_total_elapsed(monkeypatch):
    data = tradeoff_request()
    clock = [0.0]
    load, prepare, search, verify, validate = (
        cp_sat.load_backend,
        cp_sat.prepare,
        cp_model.CpSolver.solve,
        engine.verify_solution,
        engine.validate_response,
    )
    limits = []

    def delayed_load():
        clock[0] += 100
        return load()

    def delayed_prepare(*args):
        clock[0] += 200
        return prepare(*args)

    def timed_search(solver, model):
        limits.append(solver.parameters.max_time_in_seconds)
        clock[0] += 2
        return search(solver, model)

    def delayed_verify(*args):
        clock[0] += 400
        return verify(*args)

    def delayed_validate(*args):
        clock[0] += 50
        return validate(*args)

    monkeypatch.setattr(cp_sat.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(cp_sat, "load_backend", delayed_load)
    monkeypatch.setattr(cp_sat, "prepare", delayed_prepare)
    monkeypatch.setattr(cp_model.CpSolver, "solve", timed_search)
    monkeypatch.setattr(engine, "verify_solution", delayed_verify)
    monkeypatch.setattr(engine, "validate_response", delayed_validate)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert limits == [10, 8, 6]
    stats = next(d for d in result["diagnostics"] if d["code"] == "SEARCH_STATS")
    assert {f["name"]: f["value"] for f in stats["facts"]} == {
        "time_limit_seconds": 10,
        "search_elapsed_seconds": 6,
    }
    assert result["stats"]["elapsed_seconds"] == 756


@pytest.mark.parametrize("index", range(3))
def test_each_objective_value_is_independently_checked(monkeypatch, index):
    data = tradeoff_request()
    problem = normalize(data)
    outcome = cp_sat.run(problem, cp_model)
    values = list(outcome.values)
    values[index] += 1
    outcome.values = tuple(values)
    monkeypatch.setattr(cp_sat, "run", lambda *_: outcome)
    result = solve(data)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["valid"] is False
    assert result["diagnostics"][0]["code"] == "OBJECTIVE_VALUE_MISMATCH"
    assert result["diagnostics"][0]["json_pointer"] == f"/objectives/{index}"


@pytest.mark.parametrize("proofs", [(True, False, True), (False, True, False), (True, True, True)])
def test_feasible_proofs_must_be_an_incomplete_prefix(monkeypatch, proofs):
    data = tradeoff_request()
    outcome = cp_sat.run(normalize(data), cp_model)
    outcome.status, outcome.proven_optimal = "FEASIBLE", proofs
    monkeypatch.setattr(cp_sat, "run", lambda *_: outcome)
    result = solve(data)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["valid"] is False
    assert result["diagnostics"][0]["code"] == "OPTIMALITY_MISMATCH"


def test_response_objective_order_must_match_request():
    data = tradeoff_request()
    result = solve(data)
    result["objectives"].reverse()
    with pytest.raises(InvalidInput):
        engine.validate_response(result, data)


@pytest.mark.parametrize("status", ["OPTIMAL", "FEASIBLE", "UNKNOWN"])
def test_empty_objectives_use_one_satisfaction_search(monkeypatch, status):
    data = tradeoff_request(())
    data["preferences"] = []
    calls, _ = control_search(monkeypatch, (status,))
    result = solve(data)
    assert_response(result, status)
    assert len(calls) == 1
    assert result["objectives"] == []


def test_model_failure_after_first_solution_does_not_publish_it(monkeypatch):
    validate = cp_model.CpModel.validate
    calls = []

    def controlled(model):
        calls.append(None)
        return validate(model) if len(calls) == 1 else "controlled invalid model"

    monkeypatch.setattr(cp_model.CpModel, "validate", controlled)
    result = solve(tradeoff_request())
    assert_response(result, "INTERNAL_ERROR")
    assert len(calls) == 2


def test_retained_solution_is_still_independently_verified(monkeypatch):
    control_search(monkeypatch, ("OPTIMAL", "UNKNOWN"))
    make_solution = cp_sat.make_solution

    def corrupt(*args):
        solution = make_solution(*args)
        solution["assignments"] = []
        return solution

    monkeypatch.setattr(cp_sat, "make_solution", corrupt)
    result = solve(tradeoff_request())
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["valid"] is False
    assert "DEMAND_SHORTAGE" in {d["code"] for d in result["verification"]["violations"]}
