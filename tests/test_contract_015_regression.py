"""旧版の意味の比較と、現行0.15の独立した回帰基準。"""

import copy
import itertools

import pytest

from shift_schedula import InvalidInput, cp_sat, engine, load_json, solve, validate, verify
from tests.roster_support import demand, request
from tests.support import assert_response, require_complete_demand
from tests.test_assignment import exhaustive_value
from tests.test_objectives import METRICS, control_search, tradeoff_request
from tests.test_roster import exhaustive_value as exhaustive_roster_value


@pytest.mark.parametrize("complete", [False, True])
def test_common_roster_fixture_keeps_partial_and_complete_meanings(complete):
    data = request()
    data["demand"] = [demand(people=2)]
    if complete:
        require_complete_demand(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE" if complete else "PARTIAL")
    if not complete:
        assert result["shortage_summary"]["total_person_minutes"] == 30
        assert result["objectives"][0]["value"] == 90
        assert verify(data, result["solution"])["status"] == "PARTIAL"


@pytest.mark.parametrize("order", tuple(itertools.permutations(METRICS)))
def test_current_015_objective_order_matches_raw_json_enumeration(order):
    data = tradeoff_request(order)
    require_complete_demand(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert tuple(o["value"] for o in result["objectives"]) == exhaustive_roster_value(data)
    assert verify(data, result["solution"])["status"] == "VALID"


def test_current_015_assignment_matches_raw_json_enumeration(assignment_request015):
    data = assignment_request015
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == exhaustive_value(data) == 0
    corrupted = copy.deepcopy(result["solution"])
    corrupted["assignments"].pop()
    assert verify(data, corrupted)["status"] == "INVALID_PLAN"


@pytest.mark.parametrize("minimum", [None, 0])
@pytest.mark.parametrize("priority", [None, 0])
def test_current_015_defaults_and_empty_output_structure(assignment_request015, minimum, priority):
    data = assignment_request015
    for item in data["demand"]:
        item.pop("minimum_people")
        if minimum is not None:
            item["minimum_people"] = minimum
        if priority is not None:
            item["priority"] = priority
    data["employees"][0]["availability"] = []
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 120
    assert result["shortage_summary"]["shortages"][0]["minimum_people"] == 0
    for key in ("fairness_summary", "change_summary", "continuity_summary", "cost_summary"):
        assert result[key] is None
    for key in ("duty_balance_summary", "day_count_summary", "shift_count_balance_summary"):
        assert result[key] is None
    data["demand"] = []
    data["objectives"] = data["preferences"] = []
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["solution"] == {"assignments": [], "shifts": []}
    assert result["priority_summary"] == {"groups": []}


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (("UNKNOWN",), "UNKNOWN"),
        (("MODEL_INVALID",), "INTERNAL_ERROR"),
        (("FEASIBLE",), "FEASIBLE"),
    ],
)
def test_current_015_search_endings_keep_proof_scope(monkeypatch, statuses, expected):
    data = request()
    data["demand"] = [demand()]
    control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, expected)
    if result["solution"] is not None:
        assert result["shortage_summary"]["proven_minimal"] is True
        assert not result["objectives"][0]["proven_optimal"]


def test_current_015_dependency_missing_and_internal_failure(monkeypatch):
    def unavailable():
        raise cp_sat.BackendUnavailable

    monkeypatch.setattr(cp_sat, "load_backend", unavailable)
    assert_response(solve(request()), "BACKEND_UNAVAILABLE")

    def broken(_):
        raise RuntimeError("検証境界の障害")

    monkeypatch.setattr(engine, "normalize", broken)
    assert_response(solve(request()), "INTERNAL_ERROR")


@pytest.mark.parametrize("value", [None, False, 15, "99.0", ""])
def test_current_015_version_and_missing_version_are_rejected(assignment_request015, value):
    data = assignment_request015
    data["schema_version"] = value
    assert_response(solve(data), "INVALID_INPUT")
    del data["schema_version"]
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("mutation", ["null", "bool", "unknown", "duplicate", "nonfinite"])
def test_current_015_trust_boundary_is_unchanged(assignment_request015, mutation):
    data = assignment_request015
    if mutation in {"null", "bool"}:
        data["demand"][0]["minimum_people"] = None if mutation == "null" else True
    elif mutation == "unknown":
        data["unexpected"] = 0
    elif mutation == "duplicate":
        data["employees"].append(copy.deepcopy(data["employees"][0]))
    else:
        data["solver"]["time_limit_seconds"] = float("nan")
    assert validate(data)["status"] == "INVALID_INPUT"
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e10000}'])
def test_strict_json_does_not_lose_duplicate_or_nonfinite_checks(text):
    with pytest.raises(InvalidInput):
        load_json(text)
