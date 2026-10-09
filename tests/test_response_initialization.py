"""単一契約への整理前後で、失敗応答の形と未実施の検証を保持する。"""

import copy
import json
import subprocess
import sys

import pytest

from shift_schedula import solve, verify
from shift_schedula.contract import SCHEMA_VERSIONS, get_schema, schema_errors
from shift_schedula.engine import response
from shift_schedula.verify import verification_response


@pytest.mark.parametrize("version", SCHEMA_VERSIONS)
@pytest.mark.parametrize("status", ["INVALID_INPUT", "INTERNAL_ERROR", "BACKEND_UNAVAILABLE"])
def test_failure_response_matches_declared_contract(version, status):
    result = response("failure", status, schema_version=version)
    assert set(result) == set(get_schema("response", version)["properties"])
    assert schema_errors("response", result) == []
    assert all(value is None for name, value in result.items() if name.endswith("_summary"))
    assert result["solution"] is None and result["objectives"] == []
    assert result["verification"] == {"performed": False, "valid": None, "violations": []}


@pytest.mark.parametrize("version", SCHEMA_VERSIONS)
def test_invalid_request_keeps_identity_and_unperformed_verification(version):
    request = {"schema_version": version, "request_id": "invalid"}
    original = copy.deepcopy(request)
    result = solve(request)
    checked = verify(request, {})
    assert result["status"] == checked["status"] == "INVALID_INPUT"
    assert result["schema_version"] == checked["schema_version"] == version
    assert result["request_id"] == checked["request_id"] == "invalid"
    assert set(checked) == set(get_schema("verification", version)["properties"])
    assert checked["verification"] == result["verification"]
    assert schema_errors("verification", checked) == []
    assert request == original


def test_cli_solution_read_failure_does_not_validate_or_complete_request(tmp_path):
    request = {"schema_version": "0.15", "request_id": "unfinished"}
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request))
    proc = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "verify", str(request_file), "missing.json"],
        text=True,
        capture_output=True,
        check=False,
    )
    result = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert result["diagnostics"][0]["code"] == "INPUT_READ_ERROR"
    assert result == {**verification_response(request, result["diagnostics"])}
    assert schema_errors("verification", result) == []
