import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

from shift_schedula import InvalidInput, engine, get_schema, load_json, solve, types, validate

ROOT = Path(__file__).resolve().parents[1]


def test_public_validation_reuses_entry_checks_without_solving(assignment_request, monkeypatch):
    original = copy.deepcopy(assignment_request)
    variants = [assignment_request, {**assignment_request, "employees": []}]
    bad_time = copy.deepcopy(assignment_request)
    bad_time["planning_window"]["start"] = "invalid"
    variants.append(bad_time)
    baseline = json.loads((ROOT / "examples/replan.json").read_text(encoding="utf-8"))
    variants.append(baseline)
    bad_baseline = copy.deepcopy(baseline)
    bad_baseline["baseline"]["source_solution"]["shifts"] = []
    variants.append(bad_baseline)
    for request in variants:
        saved = copy.deepcopy(request)
        result = validate(request)
        response = solve(request)
        assert (result["status"] == "INVALID_INPUT") == (response["status"] == "INVALID_INPUT")
        assert request == saved
    assert assignment_request == original

    def unexpected_solver(*args):
        raise AssertionError("validate must not call the solver")

    monkeypatch.setattr(engine.cp_sat, "load_backend", unexpected_solver)
    monkeypatch.setattr(engine.flow, "run", unexpected_solver)
    assert validate(assignment_request)["status"] == "VALID"
    assert validate(baseline)["status"] == "VALID"
    for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e10000}'):
        with pytest.raises(InvalidInput) as error:
            load_json(text)
        assert error.value.diagnostics
    assert load_json('{"x":1}') == {"x": 1}
    monkeypatch.setattr(engine, "normalize", unexpected_solver)
    assert validate(assignment_request)["status"] == "INTERNAL_ERROR"


def test_public_types_match_version_fields_and_literals():
    for version, request_type in zip(
        ("0.1", "0.2", "0.3", "0.4"),
        (types.Request01, types.Request02, types.Request03, types.Request04),
        strict=True,
    ):
        schema = get_schema("request", version)
        assert set(schema["required"]) == request_type.__required_keys__
        assert set(schema["properties"]) == set(get_type_hints(request_type))
        assert get_args(get_type_hints(request_type)["schema_version"]) == (version,)
    assert set(get_args(types.SchemaVersion.__value__)) == {"0.1", "0.2", "0.3", "0.4"}
    assert "PARTIAL" not in get_args(get_type_hints(types.Response01Success)["status"])
    assert "PARTIAL" in get_args(get_type_hints(types.Response04Success)["status"])


@pytest.mark.distribution
def test_installed_wheel_types_check_consumer_and_reject_typos(tmp_path):
    def run(*command, expected=0):
        result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == expected, result.stdout + result.stderr
        return result

    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    (wheel,) = tmp_path.glob("*.whl")
    run("uv", "venv", "--python", sys.executable, str(tmp_path / "consumer"))
    python = (
        tmp_path / "consumer" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    run("uv", "pip", "install", "--python", str(python), str(wheel), "mypy==2.4.0")
    run(
        str(python),
        "-I",
        "-c",
        "from shift_schedula import validate; "
        "assert validate({'request_id':'incomplete'})['status'] == 'INVALID_INPUT'",
    )
    run(str(python), "-m", "mypy", "--strict", str(ROOT / "examples/typed_api.py"))
    invalid = tmp_path / "invalid_consumer.py"
    invalid.write_text(
        "from shift_schedula import Response\n"
        "from shift_schedula.types import Request03\n"
        "def broken(response: Response, request: Request03) -> None:\n"
        "    response['status'] = 'OPTIMLA'\n"
        "    request['unexpected'] = 1\n",
        encoding="utf-8",
    )
    result = run(str(python), "-m", "mypy", "--strict", str(invalid), expected=1)
    assert "OPTIMLA" in result.stdout and "unexpected" in result.stdout
