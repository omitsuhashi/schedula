"""契約の合成応答を検証する。0.3ソルバーの実行結果ではない。"""

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
from tests.test_extensions import baseline

ROOT = Path(__file__).resolve().parents[1]


def result_example(status):
    result = response("contract_example", status)
    result.update(
        schema_version="0.3",
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
    validate_response(result)


@pytest.mark.parametrize(
    "name", ["assignment", "overnight", "split_roster", "fairness", "replan", "diagnosis"]
)
def test_version_three_preserves_extended_input_semantics(name):
    old = json.loads((ROOT / "examples" / f"{name}.json").read_text())
    request = copy.deepcopy(old)
    request["schema_version"] = "0.3"
    original = copy.deepcopy(request)
    before, after = normalize(old), normalize(request)
    assert after.candidates == before.candidates
    assert after.baseline == before.baseline
    assert after.demand == before.demand
    assert request == original
    complete = solve(old)
    if complete["status"] == "OPTIMAL":
        complete["schema_version"] = "0.3"
        complete["shortage_summary"] = {
            "total_person_minutes": 0,
            "proven_minimal": True,
            "shortages": [],
        }
        complete.setdefault("fairness_summary", None)
        complete.setdefault("change_summary", None)
        complete.setdefault("diagnosis_result", None)
        validate_response(complete, request)
    result = solve(request)
    assert result["schema_version"] == "0.3"
    assert result["status"] == ("PARTIAL" if name == "diagnosis" else "OPTIMAL")
    assert result["shortage_summary"]["proven_minimal"]
    assert result["verification"]["valid"]
    validate_response(result, request)


@pytest.mark.parametrize("case", ["history", "fairness", "fixed", "diagnosis"])
def test_extended_invalid_inputs_still_fail_before_execution_gate(case):
    request = json.loads((ROOT / "examples/replan.json").read_text())
    request["schema_version"] = "0.3"
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
    assert result["schema_version"] == "0.3" and result["status"] == "INVALID_INPUT"
    assert result["shortage_summary"] is None
    validate_response(result)


def test_baseline_requires_complete_plan_and_preserves_old_version_boundary():
    request = baseline()
    old = request["baseline"]
    # 旧基準は0.1なので、0.3の勤務区間表現へ明示的に移す。
    old["source_request"] = copy.deepcopy({k: v for k, v in request.items() if k != "baseline"})
    old["source_request"]["schema_version"] = "0.3"
    old["source_request"]["objectives"] = []
    shift = old["source_solution"]["shifts"][0]
    shift.update(
        work_day="2026-10-05",
        segments=[{"interval": shift.pop("interval"), "breaks": shift.pop("breaks")}],
    )
    with pytest.raises(InvalidInput, match="基準計画"):
        normalize(request)
    request["schema_version"] = "0.3"
    assert normalize(request).baseline is not None
    old["source_solution"]["assignments"] = []
    with pytest.raises(InvalidInput) as error:
        normalize(request)
    assert any(d["code"] == "DEMAND_SHORTAGE" for d in error.value.diagnostics)


def test_partial_diagnosis_never_searches_changes(assignment_request):
    assignment_request["schema_version"] = "0.3"
    assignment_request["diagnosis"] = {
        "time_limit_seconds": 1,
        "max_suggestions": 1,
        "allowed_changes": [],
    }
    result = result_example("PARTIAL")
    result["diagnosis_result"] = diagnosis.diagnose(
        assignment_request, "PARTIAL", lambda _: pytest.fail("変更案を探索してはいけません。")
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


def test_full_response_with_original_request_and_legacy_boundaries(assignment_request):
    assignment_request["schema_version"] = "0.2"
    result = solve(assignment_request)
    result["schema_version"] = assignment_request["schema_version"] = "0.3"
    result["shortage_summary"] = {
        "total_person_minutes": 0,
        "proven_minimal": True,
        "shortages": [],
    }
    validate_response(result, assignment_request)
    assert verify_solution(normalize(assignment_request), result["solution"])[0] == []
    for version in ("0.1", "0.2"):
        result["schema_version"] = version
        assert schema_errors("response", result)
    legacy = solve({**assignment_request, "schema_version": "0.2"})
    with pytest.raises(InvalidInput, match="契約版"):
        validate_response(legacy, assignment_request)
    # 元入力と合わない合成応答は独立検証で拒否する。
    with pytest.raises(InvalidInput):
        validate_response(result_example("PARTIAL"), assignment_request)
    # 完全な配置に架空の不足一覧を付けても照合をすり抜けさせない。
    legacy["schema_version"] = "0.3"
    legacy["status"] = "PARTIAL"
    legacy["shortage_summary"] = result_example("PARTIAL")["shortage_summary"]
    legacy["shortage_summary"]["proven_minimal"] = True
    with pytest.raises(InvalidInput) as error:
        validate_response(legacy, assignment_request)
    assert error.value.diagnostics[0]["code"] == "SHORTAGE_MISMATCH"


@pytest.mark.parametrize("kind", ["request", "response"])
def test_cli_reads_contract_three(kind):
    result = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.3"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == get_schema(kind, "0.3")
