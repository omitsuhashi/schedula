"""旧版・未知版を全通常入口で拒否し、原入力と失敗応答の意味を保つ。"""

import copy
import json
import subprocess
import sys

import pytest

from shift_schedula import (
    InvalidInput,
    assemble,
    get_schema,
    import_request,
    make_baseline,
    solve,
    split_request,
    validate,
    verify,
)
from shift_schedula.contract import SCHEMA_VERSIONS, schema_errors
from shift_schedula.model import normalize
from tests.roster_support import request, template

REJECTED = [*(f"0.{i}" for i in range(1, 15)), "0.16", "1.0", "", None, 15, True, []]


def test_current_shift_shape_and_template_candidate_id_are_preserved():
    data = request()
    data["demand"] = []
    data["shift_candidates"] = []
    data["shift_templates"] = [template()]
    problem = normalize(data)
    (candidate,) = problem.candidates
    assert candidate.id == "tmpl.cf8645f34824c400a0a65467ef0c76fda6734e1753e6e75227cfc2182b55e81e"
    assert candidate.work_slots == {20, 21, 22}
    shift = candidate.output(problem.grid)
    assert shift == {
        "candidate_id": candidate.id,
        "employee_id": "alice",
        "work_day": "2026-10-05",
        "segments": [
            {
                "interval": {
                    "start": "2026-10-05T10:00:00+09:00",
                    "end": "2026-10-05T11:30:00+09:00",
                },
                "breaks": [],
            }
        ],
    }
    solution = {"assignments": [], "shifts": [shift]}
    assert verify(data, solution)["status"] == "VALID"
    assert make_baseline(data, solution, "saved")["source_solution"] == solution


def test_current_contract_rejects_old_candidate_and_solution_shapes():
    data = request()
    data["demand"] = []
    problem = normalize(data)
    shift = problem.candidates[0].output(problem.grid)
    solution = {"assignments": [], "shifts": [shift]}
    assert verify(data, solution)["status"] == "VALID"
    baseline = make_baseline(data, solution, "saved")
    shift.update(shift.pop("segments")[0])
    shift.pop("work_day")
    original = copy.deepcopy(solution)
    checked = verify(data, solution)
    assert checked["status"] == "INVALID_PLAN"
    assert any(d["json_pointer"].startswith("/shifts/0") for d in checked["diagnostics"])
    with pytest.raises(InvalidInput):
        make_baseline(data, solution, "saved")
    baseline["source_solution"] = solution
    assert validate({**data, "baseline": baseline})["status"] == "INVALID_INPUT"
    data["shift_candidates"][0].update(data["shift_candidates"][0].pop("segments")[0])
    assert validate(data)["status"] == "INVALID_INPUT"
    assert solution == original


@pytest.mark.parametrize("version", REJECTED)
def test_normal_apis_reject_version_without_modifying_input(version, assignment_request):
    assignment_request["schema_version"] = version
    original = copy.deepcopy(assignment_request)
    for result, kind in (
        (validate(assignment_request), None),
        (solve(assignment_request), "response"),
        (verify(assignment_request, {"assignments": [], "shifts": []}), "verification"),
    ):
        assert result["status"] == "INVALID_INPUT"
        assert result["schema_version"] == "0.15"
        assert result["request_id"] == original["request_id"]
        assert any(d["json_pointer"] == "/schema_version" for d in result["diagnostics"])
        if kind:
            assert schema_errors(kind, result) == []
            assert result["verification"] == {"performed": False, "valid": None, "violations": []}
            assert result["objectives"] == []
            assert all(v is None for k, v in result.items() if k.endswith("_summary"))
    for entry in (split_request, import_request):
        with pytest.raises(InvalidInput):
            entry(assignment_request)
    roster = request()
    roster["schema_version"] = version
    with pytest.raises(InvalidInput):
        make_baseline(roster, {"assignments": [], "shifts": []}, "saved")
    assert assignment_request == original


def test_missing_version_is_not_completed(assignment_request):
    del assignment_request["schema_version"]
    original = copy.deepcopy(assignment_request)
    assert validate(assignment_request)["status"] == "INVALID_INPUT"
    assert solve(assignment_request)["schema_version"] == "0.15"
    assert verify(assignment_request, {})["status"] == "INVALID_INPUT"
    assert assignment_request == original


@pytest.mark.parametrize("version", REJECTED[:16])
@pytest.mark.parametrize("kind", ["request", "response", "solution", "verification"])
def test_schema_api_and_cli_reject_old_and_unknown_version(version, kind):
    assert SCHEMA_VERSIONS == ("0.15",)
    with pytest.raises(ValueError, match="0.15"):
        get_schema(kind, version)
    proc = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", version],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2 and proc.stdout == ""
    assert "invalid choice" in proc.stderr


@pytest.mark.parametrize("version", REJECTED[:16])
def test_cli_and_adapter_reject_old_version(version, assignment_request, tmp_path):
    draft = split_request(assignment_request)
    draft["schema_version"] = version
    assert assemble(draft)["status"] == "INVALID_INPUT"
    assignment_request["schema_version"] = version
    path = tmp_path / "request.json"
    path.write_text(json.dumps(assignment_request), encoding="utf-8")
    solution = tmp_path / "solution.json"
    solution.write_text('{"assignments": [], "shifts": []}', encoding="utf-8")
    for command in (("solve", str(path)), ("verify", str(path), str(solution))):
        proc = subprocess.run(
            [sys.executable, "-m", "shift_schedula", *command], capture_output=True, text=True
        )
        result = json.loads(proc.stdout)
        assert proc.returncode == 2 and proc.stderr == ""
        assert result["status"] == "INVALID_INPUT" and result["schema_version"] == "0.15"


@pytest.mark.parametrize("version", REJECTED[:16])
def test_record_rejects_old_request_and_response(version, assignment_request):
    from shift_schedula import check_record, create_record

    result = solve(assignment_request)
    record = create_record(assignment_request, result)
    original = copy.deepcopy(record)
    record["request"]["schema_version"] = version
    with pytest.raises(InvalidInput):
        check_record(record)
    record = copy.deepcopy(original)
    record["response"]["schema_version"] = version
    with pytest.raises(InvalidInput):
        check_record(record)
    assignment_request["schema_version"] = version
    with pytest.raises(InvalidInput):
        create_record(assignment_request, result)
