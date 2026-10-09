import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from shift_schedula import solve
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, input=None):
    return subprocess.run(
        [sys.executable, "-m", "shift_schedula", *args], input=input, capture_output=True, text=True
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
    assert json.loads(result.stdout)["$id"] == f"urn:schedula:{kind}:0.15"


@pytest.mark.parametrize("args", [[], ["solve"], ["schema", "other"], ["unknown"]])
def test_cli_usage_errors(args):
    result = cli(*args)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr


@pytest.mark.parametrize("dependencies", ["requirements", "metadata"])
def test_wheel_installs_and_runs_library_and_cli_in_clean_environment(tmp_path, dependencies):
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    (wheel,) = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert "shift_schedula/py.typed" in archive.namelist()
        assert "shift_schedula/__init__.pyi" in archive.namelist()
        schemas = {name for name in archive.namelist() if "/schemas/" in name}
        assert schemas == {
            "shift_schedula/schemas/0.15/request.schema.json",
            "shift_schedula/schemas/0.15/response.schema.json",
            "shift_schedula/schemas/adapter/draft.schema.json",
            "shift_schedula/schemas/adapter/manifest.schema.json",
            "shift_schedula/schemas/adapter/record.schema.json",
        }
        assert not any(name.startswith("schedula/") for name in archive.namelist())
        (metadata,) = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        assert metadata.startswith("shift_schedula-")
        assert b"Name: shift-schedula\n" in archive.read(metadata)
        assert b"Requires-Python: >=3.14\n" in archive.read(metadata)
        assert any(name.endswith("/licenses/LICENSE") for name in archive.namelist())
        assert any(name.endswith("/licenses/THIRD_PARTY_NOTICES.md") for name in archive.namelist())
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
import importlib.util, json, pathlib, subprocess, sys
from importlib.metadata import metadata, version
import shift_schedula
root = pathlib.Path(sys.argv[1])
assert str(root) not in shift_schedula.__file__
if sys.argv[2] == 'metadata':
    import schedula
    assert version('schedula') == '1.6.15'
    assert metadata('schedula')['Author'] == 'Vincenzo Arcidiacono'
    assert schedula.Dispatcher is not None and schedula.__file__ != shift_schedula.__file__
else:
    assert importlib.util.find_spec('schedula') is None
from shift_schedula import get_schema, verify, make_baseline
from jsonschema import Draft202012Validator
def schema_errors(kind, value):
    return list(Draft202012Validator(get_schema(kind, value['schema_version'])).iter_errors(value))
for schema_version in ('0.15',):
    for kind in ('request', 'response', 'solution', 'verification'):
        schema = get_schema(kind, schema_version)
        assert schema['$id'] == f'urn:schedula:{kind}:{schema_version}'
        Draft202012Validator.check_schema(schema)
for filename, status, values in [
    ('assignment.json', 'OPTIMAL', [0]),
    ('linked_assignment.json', 'OPTIMAL', [0]),
    ('roster.json', 'OPTIMAL', [60, 2640, 0]),
    ('infeasible.json', 'INFEASIBLE', []),
    ('invalid-input.json', 'INVALID_INPUT', []),
    ('overnight.json', 'OPTIMAL', [420]),
    ('split_roster.json', 'OPTIMAL', [420]),
    ('fairness.json', 'OPTIMAL', [0, 720]),
    ('replan.json', 'OPTIMAL', [16, 0, 240]),
    ('diagnosis.json', 'INFEASIBLE', []),
    ('conflict_refinement.json', 'INFEASIBLE', []),
    ('partial_assignment.json', 'PARTIAL', []),
    ('partial_roster.json', 'PARTIAL', [90]),
    ('minimum_assignment.json', 'PARTIAL', []),
    ('minimum_roster.json', 'PARTIAL', [180]),
    ('minimum_conflict.json', 'INFEASIBLE', []),
    ('roster_conditions.json', 'OPTIMAL', [0, 180]),
    ('partial_replan_preserve_assigned.json', 'PARTIAL', [90]),
    ('partial_replan_rebuild.json', 'OPTIMAL', [180]),
    ('continuity_replan.json', 'OPTIMAL', [0, 180]),
    ('scheduled_cost.json', 'OPTIMAL', [108000, 60]),
    ('duty_balance.json', 'OPTIMAL', [0, 240, 2016000]),
]:
    path = root / 'examples' / filename
    request = json.loads(path.read_text(encoding='utf-8'))
    result = shift_schedula.solve(request)
    cli = subprocess.run([sys.executable, '-I', '-m', 'shift_schedula', 'solve', str(path)],
                         capture_output=True, text=True)
    assert cli.returncode == (0 if status == 'OPTIMAL' else 2) and cli.stderr == ''
    for response in [result, json.loads(cli.stdout)]:
        assert response['status'] == status
        assert response['solver']['engine_version'] == version('shift-schedula')
        assert not schema_errors('response', response)
        assert [o['value'] for o in response['objectives']] == values
        if status in {'OPTIMAL', 'PARTIAL'}:
            assert response['verification'] == {
                'performed': True, 'valid': True, 'violations': []}
            assert all(o['proven_optimal'] for o in response['objectives'])
            if status == 'PARTIAL':
                assert response['shortage_summary']['proven_minimal']
                assert response['shortage_summary']['total_person_minutes'] > 0
        else:
            assert response['solution'] is None and response['diagnostics']
        if response['solution'] is not None:
            checked = verify(request, response['solution'])
            assert checked['status'] == ('PARTIAL' if status == 'PARTIAL' else 'VALID')
            assert [o['value'] for o in checked['objectives']] == values
            assert not any(o['proven_optimal'] for o in checked['objectives'])
print('clean wheel: library and CLI; assignment, roster, infeasible, invalid input')
"""
    if dependencies == "requirements":
        command = [
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
            dependencies,
        ]
    else:
        environment = tmp_path / "metadata-env"
        setup = subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(environment)],
            capture_output=True,
            text=True,
        )
        assert setup.returncode == 0, setup.stderr
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        install = subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--constraints",
                str(requirements),
                f"{wheel}[cp-sat]",
                "schedula==1.6.15",
            ],
            capture_output=True,
            text=True,
        )
        assert install.returncode == 0, install.stderr
        command = [str(python), "-I", "-c", script, str(ROOT), dependencies]
    result = subprocess.run(
        command,
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
