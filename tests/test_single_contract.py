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
from tests.roster_support import request

REJECTED = [*(f"0.{i}" for i in range(1, 15)), "0.16", "1.0", "", None, 15, True, []]


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
