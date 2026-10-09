import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shift_schedula import cp_sat, diagnosis, solve, verify
from shift_schedula.contract import InvalidInput, get_schema
from shift_schedula.engine import validate_response
from shift_schedula.model import normalize
from shift_schedula.verify import verify_solution
from tests.roster_support import complete_demand as demand
from tests.roster_support import request, rule
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def impossible(mode="roster"):
    data = request()
    data["demand"] = [demand(people=2)]
    data["diagnosis"] = {
        "time_limit_seconds": 10,
        "max_suggestions": 2,
        "allowed_changes": [
            {
                "id": "one_person",
                "edits": [
                    {"json_pointer": "/demand/0/required_people", "value": 1},
                    {"json_pointer": "/demand/0/minimum_people", "value": 1},
                ],
            },
            {
                "id": "unchanged",
                "edits": [
                    {"json_pointer": "/demand/0/required_people", "value": 2},
                    {"json_pointer": "/demand/0/minimum_people", "value": 2},
                ],
            },
        ],
    }
    if mode == "assignment":
        data["problem_type"] = mode
        data["shift_candidates"] = []
        data["objectives"] = []
        for employee in data["employees"]:
            employee.pop("history")
    return data


@pytest.mark.parametrize("mode", ["assignment", "roster"])
def test_allowed_change_is_a_separate_verified_plan(mode):
    data = impossible(mode)
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    assert detail["status"] == "COMPLETE"
    assert detail["conflict"]["infeasibility_proven"] is True
    assert detail["conflict"]["minimality"] == detail["suggestion_minimality"] == "not_proven"
    assert len(detail["suggestions"]) == 1
    suggestion = detail["suggestions"][0]
    modified = suggestion["modified_request"]
    assert suggestion["option_id"] == "one_person"
    assert modified["demand"][0]["required_people"] == 1
    assert modified["demand"][0]["minimum_people"] == 1
    assert modified["schema_version"] == suggestion["response"]["schema_version"] == "0.15"
    assert "diagnosis" not in modified
    assert 0 < modified["solver"]["time_limit_seconds"] <= 10
    assert_response(suggestion["response"], "OPTIMAL")
    assert verify_solution(normalize(modified), suggestion["response"]["solution"])[0] == []
    for condition in detail["conflict"]["conditions"]:
        value = data
        for part in condition["json_pointer"].split("/")[1:]:
            value = value[int(part)] if isinstance(value, list) else value[part]
        assert value is not None
    # 全必須条件を保持した十分集合は再求解でも不可能。最小性は主張しない。
    without_diagnosis = copy.deepcopy(data)
    without_diagnosis.pop("diagnosis")
    assert_response(solve(without_diagnosis), "INFEASIBLE")
    assert data == original
    validate_response(result, data)


@pytest.mark.parametrize("case", ["skills", "candidates", "scheduled", "consecutive", "rest"])
def test_conflict_tracks_competing_and_joint_conditions(case):
    data = impossible()
    data["demand"][0].update(required_people=1, minimum_people=1)
    data["diagnosis"]["allowed_changes"] = []
    if case == "skills":
        data["demand"].append({**data["demand"][0], "id": "hall_need", "role_id": "hall"})
    elif case == "candidates":
        data["shift_candidates"] = []
    elif case == "scheduled":
        data["constraints"] = [rule("max_scheduled_minutes", 60)]
    elif case == "consecutive":
        data["constraints"] = [rule("max_consecutive_days", 0)]
    else:
        data["employees"][0]["history"] = {
            "last_shift_end": "2026-10-04T23:00:00+09:00",
            "last_work_day": "2026-10-04",
            "consecutive_work_days_before_window": 1,
        }
        data["constraints"] = [rule("min_rest_minutes", 720)]
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conditions = result["diagnosis_result"]["conflict"]["conditions"]
    pointers = {condition["json_pointer"] for condition in conditions}
    background = {
        condition["json_pointer"]
        for condition in result["diagnosis_result"]["conflict"]["background_conditions"]
    }
    assert "/demand/0" in pointers and "/employees/0/skills" in background
    assert "/shift_candidates" in background
    if case in {"scheduled", "consecutive", "rest"}:
        assert "/constraints/0" in pointers
    assert result["diagnosis_result"]["suggestions"] == []


@pytest.mark.parametrize(
    "pointer,value",
    [
        ("/employees/0/skills", 1),
        ("/fixed_parts/0", 0),
        ("/demand/99/required_people", 1),
        ("/demand/00/required_people", 1),
        ("/demand/0/required_people", 251),
        ("/constraints/0/limit_count", 1),
        ("/solver/time_limit_seconds", 10),
    ],
)
def test_unknown_or_unpermitted_changes_are_rejected(pointer, value):
    data = impossible()
    data["diagnosis"]["allowed_changes"][0]["edits"] = [{"json_pointer": pointer, "value": value}]
    assert_response(solve(data), "INVALID_INPUT")


def test_duplicate_edits_and_explicit_flow_are_rejected():
    data = impossible()
    edits = data["diagnosis"]["allowed_changes"][0]["edits"]
    edits.append(copy.deepcopy(edits[0]))
    assert_response(solve(data), "INVALID_INPUT")
    data = impossible("assignment")
    data["solver"]["backend"] = "min_cost_flow"
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize(
    "status,reason",
    [
        ("UNKNOWN", "ORIGINAL_UNKNOWN"),
        ("OPTIMAL", "ORIGINAL_FEASIBLE"),
        ("PARTIAL", "ORIGINAL_PARTIAL"),
    ],
)
def test_unknown_does_not_claim_impossibility_or_retry(status, reason):
    result = diagnosis.diagnose(impossible(), status, lambda _: pytest.fail("Unexpected retry"))
    assert result["status"] == "NOT_APPLICABLE" and result["reason"] == reason
    assert result["conflict"] is None and result["suggestions"] == []


def test_diagnosis_error_preserves_original_infeasible(monkeypatch):
    def broken(_):
        raise RuntimeError("diagnosis failure")

    monkeypatch.setattr(diagnosis, "conditions", broken)
    result = solve(impossible())
    assert_response(result, "INFEASIBLE")
    assert result["diagnosis_result"]["status"] == "ERROR"
    assert result["diagnosis_result"]["suggestions"] == []


def test_expired_diagnosis_publishes_no_unfinished_result(monkeypatch):
    ticks = iter([0, 11, 11])
    monkeypatch.setattr(diagnosis.time, "monotonic", lambda: next(ticks))
    result = diagnosis.diagnose(
        impossible(), "INFEASIBLE", lambda _: pytest.fail("Unexpected retry")
    )
    assert result["status"] == "TIME_LIMIT"
    assert result["conflict"] is None and result["suggestions"] == []


def test_tampered_suggestion_and_objectives_are_rejected():
    data = impossible()
    result = solve(data)
    for target in ["request", "objective", "solution"]:
        broken = copy.deepcopy(result)
        suggestion = broken["diagnosis_result"]["suggestions"][0]
        if target == "request":
            suggestion["modified_request"]["employees"][0]["availability"] = []
        elif target == "objective":
            suggestion["response"]["objectives"][0]["value"] += 1
        else:
            suggestion["response"]["solution"]["assignments"] = []
        with pytest.raises(InvalidInput):
            validate_response(broken, data)
    valid_child = result["diagnosis_result"]["suggestions"][0]["response"]
    valid_child["objectives"][0]["value"] += 1
    detail = diagnosis.diagnose(data, "INFEASIBLE", lambda _: valid_child)
    assert detail["status"] == "ERROR" and detail["suggestions"] == []


@pytest.mark.parametrize("version", ["0.15"])
def test_cli_diagnosis_and_schema_version(tmp_path, version):
    data = impossible()
    data["schema_version"] = version
    path = tmp_path / "diagnosis.json"
    path.write_text(json.dumps(data))
    process = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "solve", str(path)], capture_output=True, text=True
    )
    assert process.returncode == 2 and not process.stderr
    result = json.loads(process.stdout)
    assert_response(result, "INFEASIBLE")
    assert result["schema_version"] == version
    kinds = ["request", "response", "solution", "verification"]
    for kind in kinds:
        process = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", version],
            capture_output=True,
            text=True,
        )
        assert process.returncode == 0 and json.loads(process.stdout) == get_schema(kind, version)


def test_broken_diagnosis_output_preserves_original_result(monkeypatch):
    monkeypatch.setattr(diagnosis, "diagnose", lambda *_: {"status": "COMPLETE"})
    result = solve(impossible())
    assert_response(result, "INFEASIBLE")
    assert result["diagnosis_result"]["status"] == "ERROR"
    assert result["diagnosis_result"]["conflict"] is None


def test_conflict_output_does_not_share_input_intervals():
    data = impossible()
    original = copy.deepcopy(data)
    result = solve(data)
    for condition in result["diagnosis_result"]["conflict"]["conditions"]:
        if condition["interval"] is not None:
            condition["interval"]["start"] = "changed"
    assert data == original


def test_summaries_and_values_are_checked_against_returned_solution():
    data = json.loads((ROOT / "examples/replan.json").read_text())
    result = solve(data)
    for name in ["fairness_summary", "change_summary", "objectives"]:
        broken = copy.deepcopy(result)
        if name == "fairness_summary":
            broken[name]["employees"][0]["deviation_minutes"] += 1
        elif name == "change_summary":
            broken[name]["total_changes"] += 1
        else:
            broken[name][0]["value"] += 1
        with pytest.raises(InvalidInput):
            validate_response(broken, data)


def test_child_validation_expiring_budget_does_not_publish_suggestion(monkeypatch):
    from shift_schedula import engine

    data = impossible()
    clock = [0]
    child = {"status": "OPTIMAL", "verification": {"valid": True}}
    monkeypatch.setattr(diagnosis.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine, "validate_response", lambda *_: clock.__setitem__(0, 11))
    result = diagnosis.diagnose(data, "INFEASIBLE", lambda _: child)
    assert result["status"] == "TIME_LIMIT" and result["elapsed_seconds"] == 11
    assert result["suggestions"] == []


def test_outer_diagnosis_validation_is_in_elapsed_and_timeout(monkeypatch):
    from shift_schedula import engine

    clock = [0]
    validate = engine.validate_response

    def delayed(result, request=None):
        validate(result, request)
        if result.get("diagnosis_result") is not None:
            clock[0] = 11

    monkeypatch.setattr(engine.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(engine, "validate_response", delayed)
    result = solve(impossible())
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    assert detail["status"] == "TIME_LIMIT" and detail["elapsed_seconds"] == 11
    assert len(detail["suggestions"]) == 1


@pytest.mark.parametrize("mode", ["assignment", "roster"])
@pytest.mark.parametrize("edit", ["upper_only", "lower_only", "both"])
def test_explicit_demand_edits_keep_original_and_reverify_without_proofs(monkeypatch, mode, edit):
    data = impossible(mode)
    option = data["diagnosis"]["allowed_changes"][0]
    option["id"] = edit
    if edit == "upper_only":
        option["edits"] = option["edits"][:1]
    elif edit == "lower_only":
        option["edits"] = option["edits"][1:]
    data["diagnosis"]["allowed_changes"] = [option]
    saved = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    assert detail["conflict"]["infeasibility_proven"]
    if edit == "upper_only":
        assert detail["suggestions"] == []
        assert any(d["code"] == "OPTION_REJECTED" for d in detail["diagnostics"])
    else:
        suggestion = detail["suggestions"][0]
        modified, response = suggestion["modified_request"], suggestion["response"]
        assert_response(response, "PARTIAL" if edit == "lower_only" else "OPTIMAL")
        assert modified["demand"][0]["required_people"] == (2 if edit == "lower_only" else 1)
        assert modified["demand"][0]["minimum_people"] == 1
        assert response["shortage_summary"]["total_person_minutes"] == (
            30 if edit == "lower_only" else 0
        )
        assert modified["planning_window"] == data["planning_window"]
        for key in ("employees", "shift_candidates", "constraints", "objectives"):
            assert modified[key] == data[key]
        monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("検証が探索を開始しました"))
        checked = verify(modified, response["solution"])
        assert checked["status"] == ("PARTIAL" if edit == "lower_only" else "VALID")
        assert not checked["shortage_summary"]["proven_minimal"]
        assert all(not o["proven_optimal"] for o in checked["objectives"])
        assert verify(data, response["solution"])["status"] == "INVALID_PLAN"
    assert data == saved
