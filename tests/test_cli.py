import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from schedula import solve
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


def test_readme_request_is_a_complete_working_input():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    request = json.loads(text.split("```json\n", 1)[1].split("```", 1)[0])
    result = solve(request)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 0
    assert result["solution"]["assignments"] == [
        {
            "employee_id": "alice",
            "role_id": "kitchen",
            "interval": {"start": "2026-10-05T11:00:00+09:00", "end": "2026-10-05T12:00:00+09:00"},
        }
    ]


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


def test_wheel_installs_and_runs_library_and_cli_in_clean_environment(tmp_path):
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
    requirements = tmp_path / "runtime-requirements.txt"
    export = subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--extra",
            "cp-sat",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert export.returncode == 0, export.stderr
    script = """
import json, pathlib, subprocess, sys
import schedula
root = pathlib.Path(sys.argv[1])
assert str(root) not in schedula.__file__
from schedula.contract import get_schema, schema_errors
assert get_schema("request")["$id"] == "urn:schedula:request:0.1"
assert get_schema("response")["$id"] == "urn:schedula:response:0.1"
for filename, status, values in [
    ('assignment.json', 'OPTIMAL', [0]),
    ('linked_assignment.json', 'OPTIMAL', [0]),
    ('roster.json', 'OPTIMAL', [60, 2640, 0]),
    ('infeasible.json', 'INFEASIBLE', []),
    ('invalid-input.json', 'INVALID_INPUT', []),
]:
    path = root / 'examples' / filename
    request = json.loads(path.read_text(encoding='utf-8'))
    result = schedula.solve(request)
    cli = subprocess.run([sys.executable, '-I', '-m', 'schedula', 'solve', str(path)],
                         capture_output=True, text=True)
    assert cli.returncode == (0 if status == 'OPTIMAL' else 2) and cli.stderr == ''
    for response in [result, json.loads(cli.stdout)]:
        assert response['status'] == status
        assert not schema_errors('response', response)
        assert [o['value'] for o in response['objectives']] == values
        if status == 'OPTIMAL':
            assert response['verification'] == {
                'performed': True, 'valid': True, 'violations': []}
            assert all(o['proven_optimal'] for o in response['objectives'])
        else:
            assert response['solution'] is None and response['diagnostics']
print('clean wheel: library and CLI; assignment, roster, infeasible, invalid input')
"""
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--isolated",
            "--python",
            sys.executable,
            "--with",
            str(wheel),
            "--with-requirements",
            str(requirements),
            "python",
            "-I",
            "-c",
            script,
            str(ROOT),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean wheel: library and CLI" in result.stdout


def test_invalid_unicode_identifier_still_returns_json(assignment_request):
    assignment_request["request_id"] = "\ud800"
    result = cli("solve", "-", input=json.dumps(assignment_request))
    assert result.returncode == 2
    assert result.stderr == ""
    assert_response(json.loads(result.stdout), "INVALID_INPUT")
