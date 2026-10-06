import copy

import pytest

from schedula import flow, solve
from schedula.contract import InvalidInput, schema_errors
from schedula.engine import validate_response
from schedula.model import normalize
from schedula.verify import verify_solution
from tests.support import assert_response


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("skill", "SKILL_VIOLATION"),
        ("double", "DOUBLE_ASSIGNMENT"),
        ("shortage", "DEMAND_SHORTAGE"),
        ("excess", "DEMAND_EXCESS"),
        ("availability", "AVAILABILITY_VIOLATION"),
        ("reference", "UNKNOWN_REFERENCE"),
        ("interval", "MISALIGNED_INTERVAL"),
        ("extra_property", "SCHEMA_VIOLATION"),
        ("missing_property", "SCHEMA_VIOLATION"),
        ("wrong_type", "SCHEMA_VIOLATION"),
        ("shifts", "UNEXPECTED_SHIFTS"),
    ],
)
def test_corrupt_solutions_detected_and_blocked(assignment_request, monkeypatch, mutation, code):
    solution = copy.deepcopy(solve(assignment_request)["solution"])
    if mutation == "skill":
        solution["assignments"][0]["employee_id"] = "carol"
    elif mutation == "double":
        solution["assignments"][1]["employee_id"] = "alice"
    elif mutation == "shortage":
        solution["assignments"].pop()
    elif mutation == "excess":
        solution["assignments"].append(copy.deepcopy(solution["assignments"][-1]))
    elif mutation == "availability":
        assignment_request["employees"][0]["availability"] = []
    elif mutation == "reference":
        solution["assignments"][0]["employee_id"] = "unregistered"
    elif mutation == "interval":
        solution["assignments"][0]["interval"]["end"] = "2026-10-05T12:15:00+09:00"
    elif mutation == "extra_property":
        solution["unexpected"] = True
    elif mutation == "missing_property":
        del solution["assignments"][0]["employee_id"]
    elif mutation == "wrong_type":
        solution["assignments"] = {}
    elif mutation == "shifts":
        solution["shifts"] = [
            {
                "candidate_id": "shift",
                "employee_id": "alice",
                "interval": assignment_request["employees"][0]["availability"][0],
                "breaks": [],
            }
        ]
    violations, _ = verify_solution(normalize(assignment_request), solution)
    assert code in {item["code"] for item in violations}
    monkeypatch.setattr(flow, "run", lambda _: flow.FlowResult("OPTIMAL", solution))
    result = solve(assignment_request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["performed"]
    assert not result["verification"]["valid"]
    assert code in {item["code"] for item in result["verification"]["violations"]}


def test_verifier_does_not_trust_solver_tables(assignment_request):
    problem = normalize(assignment_request)
    solution = solve(assignment_request)["solution"]
    problem.available.clear()
    problem.qualified.clear()
    problem.demand.clear()
    problem.costs[("carol", "washing")] = 999
    assert verify_solution(problem, solution) == ([], (0,))
    solution["assignments"][0]["employee_id"] = "carol"
    violations, _ = verify_solution(problem, solution)
    assert "SKILL_VIOLATION" in {item["code"] for item in violations}


def test_unspecified_demand_cannot_be_overassigned(assignment_request):
    solution = solve(assignment_request)["solution"]
    assignment_request["demand"].pop()
    violations, _ = verify_solution(normalize(assignment_request), solution)
    assert "DEMAND_EXCESS" in {item["code"] for item in violations}


def test_objective_recomputed_and_mismatch_blocks_solution(assignment_request, monkeypatch):
    assignment_request["preferences"][0]["employee_ids"] = ["carol"]
    assignment_request["preferences"][0]["penalty_per_minute"] = 2
    solution = solve(assignment_request)["solution"]
    assert verify_solution(normalize(assignment_request), solution) == ([], (240,))
    monkeypatch.setattr(flow, "run", lambda _: flow.FlowResult("OPTIMAL", solution, (0,), (True,)))
    result = solve(assignment_request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["diagnostics"][0]["code"] == "OBJECTIVE_VALUE_MISMATCH"


@pytest.mark.parametrize("status", ["INFEASIBLE", "UNKNOWN", "FEASIBLE", "made_up"])
def test_flow_status_cannot_bypass_verification(assignment_request, monkeypatch, status):
    solution = solve(assignment_request)["solution"]
    monkeypatch.setattr(flow, "run", lambda _: flow.FlowResult(status, solution))
    assert_response(solve(assignment_request), "INTERNAL_ERROR")


def test_unexpected_solver_exception_returns_internal_error(assignment_request, monkeypatch):
    def broken(_):
        raise RuntimeError("deliberate fault")

    monkeypatch.setattr(flow, "run", broken)
    result = solve(assignment_request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["valid"] is None


def test_malformed_response_diagnostics_block_output(assignment_request, monkeypatch):
    monkeypatch.setattr(
        flow, "run", lambda _: flow.FlowResult("INFEASIBLE", None, diagnostics=({"unknown": True},))
    )
    result = solve(assignment_request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["valid"] is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["status"], "UNKNOWN"),
        (["solution"], None),
        (["verification", "valid"], False),
        (["verification", "performed"], False),
        (["objectives", 0, "proven_optimal"], False),
        (
            ["verification", "violations"],
            [
                {
                    "code": "FAIL",
                    "message": "failure",
                    "json_pointer": "",
                    "related_ids": [],
                    "facts": [],
                }
            ],
        ),
        (["stats", "elapsed_seconds"], -1),
        (["unexpected"], True),
    ],
)
def test_response_schema_enforces_status_consistency(assignment_request, path, value):
    from tests.test_input_contract import replace

    result = solve(assignment_request)
    replace(result, path, value)
    assert schema_errors("response", result)
    with pytest.raises(InvalidInput):
        validate_response(result)


def test_response_objectives_match_request_order_and_ids(assignment_request):
    result = solve(assignment_request)
    result["objectives"][0]["id"] = "another"
    with pytest.raises(InvalidInput):
        validate_response(result, assignment_request)


def test_search_timeout_is_unknown_with_no_partial_solution(assignment_request, monkeypatch):
    clock = iter([0, 20, 20])
    monkeypatch.setattr(flow.time, "monotonic", lambda: next(clock))
    result = solve(assignment_request)
    assert_response(result, "UNKNOWN")
    assert result["diagnostics"][0]["code"] == "TIME_LIMIT"


def test_model_preparation_does_not_consume_search_budget(assignment_request, monkeypatch):
    clock = [0]
    prepare = flow.prepare

    def slow_prepare(problem):
        result = prepare(problem)
        clock[0] += 100
        return result

    monkeypatch.setattr(flow, "prepare", slow_prepare)
    monkeypatch.setattr(flow.time, "monotonic", lambda: clock[0])
    assert_response(solve(assignment_request), "OPTIMAL")


def test_verification_performed_cannot_have_null_validity(assignment_request):
    result = solve(assignment_request)
    result["status"] = "INTERNAL_ERROR"
    result["solution"] = None
    result["objectives"] = []
    result["verification"]["valid"] = None
    assert schema_errors("response", result)


def test_partial_solution_is_discarded_on_later_slot_timeout(assignment_request, monkeypatch):
    original = flow.augment
    calls = [0]

    def limited(graph, required, deadline):
        calls[0] += 1
        return original(graph, required, deadline) if calls[0] == 1 else ("UNKNOWN", 0)

    monkeypatch.setattr(flow, "augment", limited)
    result = solve(assignment_request)
    assert calls[0] == 2
    assert_response(result, "UNKNOWN")
    assert result["verification"]["performed"] is False


@pytest.mark.parametrize("reverse_order", [False, True])
def test_split_same_assignment_is_detected_and_blocked(
    assignment_request, monkeypatch, reverse_order
):
    solution = solve(assignment_request)["solution"]
    original = solution["assignments"].pop(0)
    solution["assignments"] += [
        {**original, "interval": {**original["interval"], "end": "2026-10-05T12:00:00+09:00"}},
        {**original, "interval": {**original["interval"], "start": "2026-10-05T12:00:00+09:00"}},
    ]
    if reverse_order:
        solution["assignments"].reverse()
    violations, penalty = verify_solution(normalize(assignment_request), solution)
    assert penalty == (0,)
    assert {item["code"] for item in violations} == {"UNMERGED_ASSIGNMENTS"}
    assert violations[0]["related_ids"] == ["alice", "kitchen"]
    monkeypatch.setattr(flow, "run", lambda _: flow.FlowResult("OPTIMAL", solution, (0,), (True,)))
    result = solve(assignment_request)
    assert_response(result, "INTERNAL_ERROR")
    assert result["verification"]["performed"] is True
    assert result["verification"]["valid"] is False
    assert result["verification"]["violations"][0]["code"] == "UNMERGED_ASSIGNMENTS"


@pytest.mark.parametrize("gap", [False, True])
def test_distinct_adjacent_assignments_or_gaps_need_no_merging(assignment_request, gap):
    request = assignment_request
    request["demand"] = [
        {
            "id": "first",
            "role_id": "kitchen",
            "interval": {
                "start": "2026-10-05T11:00:00+09:00",
                "end": "2026-10-05T11:30:00+09:00",
            },
            "required_people": 1,
        },
        {
            "id": "second",
            "role_id": "kitchen" if gap else "washing",
            "interval": {
                "start": "2026-10-05T12:00:00+09:00" if gap else "2026-10-05T11:30:00+09:00",
                "end": "2026-10-05T13:00:00+09:00",
            },
            "required_people": 1,
        },
    ]
    request["preferences"] = []
    request["objectives"] = []
    solution = {
        "assignments": [
            {"employee_id": "alice", "role_id": item["role_id"], "interval": item["interval"]}
            for item in request["demand"]
        ],
        "shifts": [],
    }
    assert verify_solution(normalize(request), solution) == ([], ())
