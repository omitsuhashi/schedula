import copy

import pytest

from shift_schedula import cp_sat, solve
from shift_schedula.model import normalize
from shift_schedula.verify import verify_solution
from tests.roster_support import candidate, interval, request, rule, stamp, template
from tests.roster_support import complete_demand as demand
from tests.support import assert_response


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing_shift", "UNSELECTED_SHIFT_ASSIGNMENT"),
        ("unknown_shift", "UNKNOWN_CANDIDATE"),
        ("wrong_employee", "CANDIDATE_MISMATCH"),
        ("wrong_interval", "CANDIDATE_MISMATCH"),
        ("wrong_break", "CANDIDATE_MISMATCH"),
        ("duplicate", "DUPLICATE_SHIFT"),
        ("multiple_daily", "MULTIPLE_DAILY_SHIFTS"),
        ("during_break", "BREAK_ASSIGNMENT"),
        ("scheduled", "MAX_SCHEDULED_MINUTES_VIOLATION"),
        ("assigned", "MAX_ASSIGNED_MINUTES_VIOLATION"),
        ("rest", "MIN_REST_MINUTES_VIOLATION"),
        ("history_rest", "MIN_REST_MINUTES_VIOLATION"),
        ("consecutive", "MAX_CONSECUTIVE_DAYS_VIOLATION"),
        ("history_days", "MAX_CONSECUTIVE_DAYS_VIOLATION"),
    ],
)
def test_invalid_roster_results_detected_and_blocked(monkeypatch, mutation, code):
    data = request(days=2)
    data["shift_candidates"] = [candidate(day=d, breaks=[(630, 660)]) for d in range(2)]
    data["demand"] = [demand(d) for d in range(2)]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    solution = copy.deepcopy(result["solution"])
    shift = solution["shifts"][0]
    if mutation == "missing_shift":
        solution["shifts"].pop(0)
    elif mutation == "unknown_shift":
        shift["candidate_id"] = "unknown"
    elif mutation == "wrong_employee":
        shift["employee_id"] = "unknown"
    elif mutation == "wrong_interval":
        shift["segments"][0]["interval"]["end"] = stamp(0, 720)
    elif mutation == "wrong_break":
        shift["segments"][0]["breaks"] = []
    elif mutation == "duplicate":
        solution["shifts"].append(copy.deepcopy(shift))
    elif mutation == "multiple_daily":
        data["shift_candidates"].append(candidate(end=630))
        solution["shifts"].append(
            {
                "candidate_id": data["shift_candidates"][-1]["id"],
                "employee_id": "alice",
                "work_day": "2026-10-05",
                "segments": [{"interval": interval(end=630), "breaks": []}],
            }
        )
    elif mutation == "during_break":
        solution["assignments"].append(
            {"employee_id": "alice", "role_id": "kitchen", "interval": interval(start=630, end=660)}
        )
    elif mutation in {"scheduled", "assigned", "rest", "consecutive"}:
        data["constraints"] = [
            rule(
                {
                    "scheduled": "max_scheduled_minutes",
                    "assigned": "max_assigned_minutes",
                    "rest": "min_rest_minutes",
                    "consecutive": "max_consecutive_days",
                }[mutation],
                {"scheduled": 119, "assigned": 59, "rest": 1351, "consecutive": 1}[mutation],
            )
        ]
    elif mutation == "history_rest":
        data["employees"][0]["history"] = {
            "last_shift_end": stamp(0),
            "last_work_day": "2026-10-04",
            "consecutive_work_days_before_window": 1,
        }
        data["constraints"] = [rule("min_rest_minutes", 601)]
    else:
        data["employees"][0]["history"] = {
            "last_shift_end": stamp(-1, 780),
            "last_work_day": "2026-10-04",
            "consecutive_work_days_before_window": 1,
        }
        data["constraints"] = [rule("max_consecutive_days", 2)]
    problem = normalize(data)
    problem.available.clear()
    problem.qualified.clear()
    problem.demand.clear()
    problem.costs.clear()
    problem.candidates.clear()
    violations, _ = verify_solution(problem, solution)
    assert code in {v["code"] for v in violations}
    monkeypatch.setattr(
        cp_sat,
        "run",
        lambda *_: cp_sat.SatResult(
            "OPTIMAL", solution, (120,), (True,), shortage_person_minutes=0
        ),
    )
    blocked = solve(data)
    assert_response(blocked, "INTERNAL_ERROR")
    assert blocked["verification"]["performed"] is True
    assert code in {v["code"] for v in blocked["verification"]["violations"]}


def test_generated_solution_independent_of_solver_tables():
    data = request()
    data["shift_candidates"] = []
    data["shift_templates"] = [template()]
    data["demand"] = [demand()]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    problem = normalize(data)
    problem.candidates.clear()
    problem.available.clear()
    assert verify_solution(problem, result["solution"]) == ([], (90,))


def test_scheduled_value_mismatch_blocks_solution(monkeypatch):
    data = request()
    data["demand"] = [demand()]
    solution = solve(data)["solution"]
    monkeypatch.setattr(
        cp_sat,
        "run",
        lambda *_: cp_sat.SatResult(
            "FEASIBLE", solution, (30,), (False,), shortage_person_minutes=0
        ),
    )
    result = solve(data)
    assert_response(result, "INTERNAL_ERROR")
    assert result["diagnostics"][0]["code"] == "OBJECTIVE_VALUE_MISMATCH"
