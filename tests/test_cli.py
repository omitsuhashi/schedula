import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from schedula.contract import schema_errors
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, input=None):
    return subprocess.run(
        [sys.executable, "-m", "schedula", *args], input=input, capture_output=True, text=True
    )


def test_cli_example_and_stdin(assignment_request):
    for result in [
        cli("solve", str(ROOT / "examples/assignment.json")),
        cli("solve", "-", input=json.dumps(assignment_request)),
    ]:
        assert result.returncode == 0
        assert result.stderr == ""
        assert_response(json.loads(result.stdout), "OPTIMAL")


def test_cli_infeasible(assignment_request):
    assignment_request["employees"][0]["availability"] = []
    result = cli("solve", "-", input=json.dumps(assignment_request))
    assert result.returncode == 2
    assert result.stderr == ""
    assert_response(json.loads(result.stdout), "INFEASIBLE")


@pytest.mark.parametrize(
    "text",
    [
        "{",
        '{"a":1,"a":2}',
        '{"nested":{"a":1,"a":2}}',
        '{"n":NaN}',
        '{"n":Infinity}',
        '{"n":1e10000}',
        "[]",
        "{}",
        "",
    ],
)
def test_cli_invalid_input_is_json_only(text):
    result = cli("solve", "-", input=text)
    assert result.returncode == 2
    assert result.stderr == ""
    assert_response(json.loads(result.stdout), "INVALID_INPUT")


def test_cli_missing_file_and_invalid_utf8(tmp_path):
    path = tmp_path / "input.json"
    result = cli("solve", str(path))
    assert result.returncode == 2
    assert_response(json.loads(result.stdout), "INVALID_INPUT")
    path.write_bytes(b"\xff")
    result = cli("solve", str(path))
    assert result.returncode == 2
    assert_response(json.loads(result.stdout), "INVALID_INPUT")


@pytest.mark.parametrize("kind", ["request", "response"])
def test_cli_schema(kind):
    result = cli("schema", kind)
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["$id"] == f"urn:schedula:{kind}:0.1"


@pytest.mark.parametrize("args", [[], ["solve"], ["schema", "other"], ["unknown"]])
def test_cli_usage_errors(args):
    result = cli(*args)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr


def test_wheel_contains_schemas_and_runs_without_checkout_imports(tmp_path):
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    (wheel,) = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert "schedula/schemas/0.1/request.schema.json" in archive.namelist()
        assert "schedula/schemas/0.1/response.schema.json" in archive.namelist()
        assert not any("reference/" in name or "tests/" in name for name in archive.namelist())
    script = """
import json, runpy, sys
sys.path.insert(0, sys.argv[1])
import schedula
assert sys.argv[1] in schedula.__file__
from schedula.contract import get_schema
assert get_schema("request")["$id"] == "urn:schedula:request:0.1"
assert get_schema("response")["$id"] == "urn:schedula:response:0.1"
request = json.load(open(sys.argv[2]))
assert schedula.solve(request)["status"] == "OPTIMAL"
sys.argv = ["schedula", "solve", sys.argv[2]]
runpy.run_module("schedula", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(wheel), str(ROOT / "examples/assignment.json")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not schema_errors("response", json.loads(result.stdout))
    assert json.loads(result.stdout)["objectives"][0]["value"] == 0


def test_invalid_unicode_identifier_still_returns_json(assignment_request):
    assignment_request["request_id"] = "\ud800"
    result = cli("solve", "-", input=json.dumps(assignment_request))
    assert result.returncode == 2
    assert result.stderr == ""
    assert_response(json.loads(result.stdout), "INVALID_INPUT")
