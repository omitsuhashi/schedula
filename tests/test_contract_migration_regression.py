"""旧版の意味の比較と、現行0.15の独立した回帰基準。"""

import copy
import hashlib
import itertools
from pathlib import Path

import pytest

from shift_schedula import InvalidInput, cp_sat, engine, load_json, solve, validate, verify
from shift_schedula.model import normalize
from tests.roster_support import demand, request015
from tests.support import assert_response, require_complete_demand
from tests.test_assignment import exhaustive_value
from tests.test_objectives import METRICS, control_search, tradeoff_request
from tests.test_roster import exhaustive_value as exhaustive_roster_value

FIXTURES = Path(__file__).parent / "fixtures/contract-migration"
MANIFEST = load_json((FIXTURES / "cases.json").read_text(encoding="utf-8"))
CASES = tuple(row["name"] for row in MANIFEST["cases"])


def read_case(name, kind):
    return load_json((FIXTURES / f"{name}.{kind}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=CASES)
def test_representative_bytes_match_recorded_hashes(case):
    for kind, field in (("legacy", "legacy_sha256"), ("015", "target_sha256")):
        path = FIXTURES / f"{case['name']}.{kind}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == case[field], path.name


def test_representatives_cover_every_legacy_version():
    assert {read_case(name, "legacy")["schema_version"] for name in CASES} == {
        f"0.{i}" for i in range(1, 15)
    }


@pytest.mark.parametrize("name", CASES)
def test_legacy_and_explicit_target_keep_conditions_values_and_proofs(name):
    legacy, target = read_case(name, "legacy"), read_case(name, "015")
    saved = copy.deepcopy((legacy, target))
    assert target["schema_version"] == "0.15"
    assert legacy["planning_window"] == target["planning_window"]
    for key in ("skills", "roles", "constraints", "preferences", "objectives", "solver"):
        assert legacy[key] == target[key]
    for old, new in zip(legacy["demand"], target["demand"], strict=True):
        assert old.items() <= new.items()
        assert new.get("minimum_people", 0) == (
            old["required_people"]
            if legacy["schema_version"] in {"0.1", "0.2"}
            else old.get("minimum_people", 0)
        )
    results = []
    for data in (legacy, target):
        assert validate(data)["status"] == "VALID"
        result = solve(data)
        assert_response(result, result["status"])
        assert result["status"] in {"OPTIMAL", "PARTIAL", "INFEASIBLE"}
        if result["solution"] is not None:
            checked = verify(data, result["solution"])
            assert checked["status"] == ("PARTIAL" if result["status"] == "PARTIAL" else "VALID")
            assert all(not item["proven_optimal"] for item in checked["objectives"])
        results.append(result)
    before, after = results
    assert before["status"] == after["status"]
    assert before["objectives"] == after["objectives"]
    if before.get("shortage_summary") is not None:
        for key in ("total_person_minutes", "proven_minimal"):
            assert before["shortage_summary"][key] == after["shortage_summary"][key]
    elif before["solution"] is not None:
        assert after["shortage_summary"] == {
            "total_person_minutes": 0,
            "proven_minimal": True,
            "shortages": [],
        }
    else:
        assert after["shortage_summary"] is None
    assert (legacy, target) == saved


def test_original_candidate_ids_intervals_breaks_and_template_expansion_are_preserved():
    def candidates(data):
        return [
            (c.id, c.employee_id, c.day, c.start, c.end, c.breaks, c.work_slots)
            for c in normalize(data).candidates
        ]

    assert candidates(read_case("roster", "legacy")) == candidates(read_case("roster", "015"))


@pytest.mark.parametrize("complete", [False, True])
def test_common_roster_fixture_keeps_partial_and_complete_meanings(complete):
    data = request015()
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
    legacy = tradeoff_request(order)
    data = request015(employees=("alice", "bob"))
    for key in ("demand", "preferences", "objectives"):
        data[key] = copy.deepcopy(legacy[key])
    data["shift_candidates"][1]["segments"][0]["interval"]["end"] = legacy["shift_candidates"][1][
        "interval"
    ]["end"]
    require_complete_demand(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert tuple(o["value"] for o in result["objectives"]) == exhaustive_roster_value(legacy)
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
    data = request015()
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
    assert_response(solve(request015()), "BACKEND_UNAVAILABLE")

    def broken(_):
        raise RuntimeError("検証境界の障害")

    monkeypatch.setattr(engine, "normalize", broken)
    assert_response(solve(request015()), "INTERNAL_ERROR")


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
