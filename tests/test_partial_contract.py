"""不足の合成応答と、現在契約の検証境界を確認する。"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shift_schedula import diagnosis, solve
from shift_schedula.contract import InvalidInput, get_schema, schema_errors
from shift_schedula.engine import response, validate_response
from shift_schedula.model import normalize
from shift_schedula.verify import verify_solution
from tests.test_extensions import baseline as baseline

ROOT = Path(__file__).resolve().parents[1]


def result_example(status, version="0.15"):
    result = response("contract_example", status)
    result.update(
        schema_version=version,
        fairness_summary=None,
        change_summary=None,
        diagnosis_result=None,
        shortage_summary=None,
    )
    if status in {"OPTIMAL", "FEASIBLE", "PARTIAL"}:
        result["solver"]["backend"] = "min_cost_flow"
        result["solution"] = {"assignments": [], "shifts": []}
        result["verification"] = {"performed": True, "valid": True, "violations": []}
        result["objectives"] = [
            {
                "id": "preferences",
                "metric": "preference_penalty",
                "value": 0,
                "proven_optimal": status == "OPTIMAL",
            }
        ]
        result["shortage_summary"] = {
            "total_person_minutes": 0,
            "proven_minimal": True,
            "shortages": [],
        }
    if status == "PARTIAL":
        result["shortage_summary"] = {
            "total_person_minutes": 60,
            "proven_minimal": False,
            "shortages": [
                {
                    "demand_id": "lunch",
                    "role_id": "kitchen",
                    "interval": {
                        "start": "2026-10-05T12:00:00+09:00",
                        "end": "2026-10-05T13:00:00+09:00",
                    },
                    "required_people": 1,
                    "assigned_people": 0,
                    "missing_people": 1,
                }
            ],
        }
    if version == "0.15":
        result.update(
            priority_summary=None,
            continuity_summary=None,
            cost_summary=None,
            duty_balance_summary=None,
            day_count_summary=None,
            shift_count_balance_summary=None,
        )
        if result["solution"] is not None:
            summary = result["shortage_summary"]
            for row in summary["shortages"]:
                row["minimum_people"] = 0
            result["priority_summary"] = {
                "groups": [
                    {
                        "priority": 0,
                        "total_person_minutes": summary["total_person_minutes"],
                        "proven_minimal": summary["proven_minimal"],
                    }
                ]
            }
    return result


@pytest.mark.parametrize(
    "status",
    [
        "OPTIMAL",
        "FEASIBLE",
        "PARTIAL",
        "INFEASIBLE",
        "UNKNOWN",
        "INVALID_INPUT",
        "BACKEND_UNAVAILABLE",
        "INTERNAL_ERROR",
    ],
)
def test_response_examples(status):
    result = result_example(status)
    assert not schema_errors("response", result)
    validate_response(result)


@pytest.mark.parametrize(
    "case",
    [
        "partial_zero",
        "partial_empty",
        "complete_shortage",
        "no_plan_summary",
        "unverified",
        "unproven_shortage_with_proven_objective",
        "missing_summary",
        "old_version",
    ],
)
def test_schema_rejects_contradictory_states(case):
    result = result_example("PARTIAL")
    if case == "partial_zero":
        result["shortage_summary"]["total_person_minutes"] = 0
    elif case == "partial_empty":
        result["shortage_summary"]["shortages"] = []
    elif case == "complete_shortage":
        result["status"] = "FEASIBLE"
    elif case == "no_plan_summary":
        result.update(status="UNKNOWN", solution=None, objectives=[])
        result["verification"] = {"performed": False, "valid": None, "violations": []}
    elif case == "unverified":
        result["verification"] = {"performed": False, "valid": None, "violations": []}
    elif case == "unproven_shortage_with_proven_objective":
        result["objectives"][0]["proven_optimal"] = True
    elif case == "missing_summary":
        del result["shortage_summary"]
    else:
        result["schema_version"] = "0.2"
    assert schema_errors("response", result)
    with pytest.raises(InvalidInput):
        validate_response(result)


@pytest.mark.parametrize(
    "case", ["total", "people", "interval", "precision", "proof_order", "empty_feasible"]
)
def test_semantics_reject_contradictory_values(case):
    result = result_example("PARTIAL")
    if case == "total":
        result["shortage_summary"]["total_person_minutes"] += 1
    elif case == "people":
        result["shortage_summary"]["shortages"][0]["assigned_people"] = 1
    elif case == "interval":
        row = result["shortage_summary"]["shortages"][0]
        row["interval"]["end"] = row["interval"]["start"]
    elif case == "precision":
        row = result["shortage_summary"]["shortages"][0]
        row["interval"] = {
            k: v.replace(":00+09:00", ":01+09:00") for k, v in row["interval"].items()
        }
    elif case == "proof_order":
        result["shortage_summary"]["proven_minimal"] = True
        result["priority_summary"]["groups"][0]["proven_minimal"] = True
        result["objectives"].append(
            {"id": "changes", "metric": "role_switches", "value": 0, "proven_optimal": True}
        )
    else:
        result = result_example("FEASIBLE")
        result["objectives"] = []
    assert not schema_errors("response", result)
    with pytest.raises(InvalidInput):
        validate_response(result)


@pytest.mark.parametrize("proven", [False, True])
def test_partial_optimality_is_separate_from_completeness(proven):
    result = result_example("PARTIAL")
    result["shortage_summary"]["proven_minimal"] = proven
    result["priority_summary"]["groups"][0]["proven_minimal"] = proven
    result["objectives"][0]["proven_optimal"] = proven
    validate_response(result)
    result["objectives"] = []
    validate_response(result)


def test_shortages_are_not_limited_by_diagnostic_count():
    result = result_example("PARTIAL")
    row = result["shortage_summary"]["shortages"][0]
    result["shortage_summary"]["shortages"] = [
        {**row, "demand_id": f"demand_{i}"} for i in range(10001)
    ]
    result["shortage_summary"]["total_person_minutes"] = 60 * 10001
    result["priority_summary"]["groups"][0]["total_person_minutes"] = 60 * 10001
    validate_response(result)


@pytest.mark.parametrize("name", ["assignment", "overnight", "replan", "partial_roster"])
def test_current_examples_keep_extended_input_semantics(name):
    request = json.loads((ROOT / "examples" / f"{name}.json").read_text())
    original = copy.deepcopy(request)
    result = solve(request)
    assert result["schema_version"] == "0.15"
    assert result["status"] in {"OPTIMAL", "PARTIAL"}
    assert result["shortage_summary"]["proven_minimal"]
    assert result["verification"]["valid"]
    validate_response(result, request)
    assert request == original


@pytest.mark.parametrize("case", ["history", "fairness", "fixed", "diagnosis"])
@pytest.mark.parametrize("version", ["0.15"])
def test_extended_invalid_inputs_still_fail_before_execution_gate(case, version):
    request = json.loads((ROOT / "examples/replan.json").read_text())
    request["schema_version"] = version
    if case == "history":
        request["employees"][0]["history"]["last_work_day"] = "2026-10-05"
    elif case == "fairness":
        request["fairness"]["employee_targets"][0]["employee_id"] = "missing"
    elif case == "fixed":
        request["fixed_parts"][0]["employee_id"] = "missing"
    else:
        request["diagnosis"] = {
            "time_limit_seconds": 1,
            "max_suggestions": 1,
            "allowed_changes": [
                {"id": "bad", "edits": [{"json_pointer": "/employees/0/skills", "value": 0}]}
            ],
        }
    result = solve(request)
    assert result["schema_version"] == version and result["status"] == "INVALID_INPUT"
    assert result["shortage_summary"] is None
    validate_response(result)


def test_baseline_verifies_original_input_and_solution():
    request = baseline()
    request["baseline"]["source_solution"]["assignments"] = []
    with pytest.raises(InvalidInput) as error:
        normalize(request)
    assert any(d["code"] == "MINIMUM_DEMAND_VIOLATION" for d in error.value.diagnostics)


def test_partial_diagnosis_never_searches_changes(assignment_request):
    for item in assignment_request["demand"]:
        item["minimum_people"] = 0
    assignment_request["diagnosis"] = {
        "time_limit_seconds": 1,
        "max_suggestions": 1,
        "allowed_changes": [],
    }
    result = result_example("PARTIAL")
    result["diagnosis_result"] = diagnosis.diagnose(
        assignment_request,
        "PARTIAL",
        lambda _: pytest.fail("変更案を探索してはいけません。"),
    )
    detail = result["diagnosis_result"]
    assert detail["status"] == "NOT_APPLICABLE" and detail["reason"] == "ORIGINAL_PARTIAL"
    assert detail["conflict"] is None and detail["suggestions"] == []
    codes = {item["code"] for item in diagnosis.conditions(assignment_request)}
    assert "DEMAND_LIMIT_AND_SINGLE_ASSIGNMENT" in codes
    assert "EXACT_DEMAND_AND_SINGLE_ASSIGNMENT" not in codes
    validate_response(result)
    assert diagnosis.validate_result(assignment_request, result) == []
    detail["reason"] = "ORIGINAL_FEASIBLE"
    assert diagnosis.validate_result(assignment_request, result)
    assert schema_errors("response", result)


def test_full_response_cannot_forge_shortage(assignment_request):
    result = solve(assignment_request)
    validate_response(result, assignment_request)
    assert verify_solution(normalize(assignment_request), result["solution"])[0] == []
    result.update(status="PARTIAL", shortage_summary=result_example("PARTIAL")["shortage_summary"])
    result["shortage_summary"]["proven_minimal"] = True
    result["priority_summary"]["groups"][0]["total_person_minutes"] = 60
    with pytest.raises(InvalidInput) as error:
        validate_response(result, assignment_request)
    assert error.value.diagnostics[0]["code"] == "SHORTAGE_MISMATCH"


@pytest.mark.parametrize("kind", ["request", "response"])
def test_cli_reads_current_contract(kind):
    result = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.15"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == get_schema(kind, "0.15")
