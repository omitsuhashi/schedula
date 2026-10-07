import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

import pytest

from shift_schedula import model, solve, verify

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("error", [ZoneInfoNotFoundError("missing"), ValueError("bad TZif")])
def test_timezone_data_failure_is_not_invalid_input(assignment_request, monkeypatch, error):
    class BrokenZoneInfo:
        def __new__(cls, key):
            raise error

        @staticmethod
        def no_cache(key):
            raise error

    monkeypatch.setattr(model, "ZoneInfo", BrokenZoneInfo)
    for result in (solve(assignment_request), verify(assignment_request, {"assignments": []})):
        assert result["status"] == "INTERNAL_ERROR"
        assert result["diagnostics"][0]["code"] == "TIMEZONE_DATA_UNAVAILABLE"


def test_wheel_timezone_database_without_system_data(tmp_path):
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    (wheel,) = tmp_path.glob("*.whl")
    extra = importlib.util.find_spec("ortools") is not None
    script = """
import importlib.util, json, pathlib, sys, zoneinfo
from importlib.metadata import version
from shift_schedula import get_schema, solve, verify
assert zoneinfo.TZPATH == ()
assert bool(importlib.util.find_spec('ortools')) == (sys.argv[2] == 'True')
root = pathlib.Path(sys.argv[1])
request = json.loads((root / 'examples/assignment.json').read_text(encoding='utf-8'))
result = solve(request)
assert result['status'] == 'OPTIMAL'
assert verify(request, result['solution'])['status'] == 'VALID'
assert get_schema('request', '0.4')['$id'] == 'urn:schedula:request:0.4'
request['planning_window']['timezone'] = 'unknown/zone'
result = solve(request)
assert result['status'] == 'INVALID_INPUT'
assert result['diagnostics'][0]['code'] == 'INVALID_TIMEZONE'
request = json.loads((root / 'examples/linked_assignment.json').read_text(encoding='utf-8'))
assert solve(request)['status'] == ('OPTIMAL' if sys.argv[2] == 'True' else 'BACKEND_UNAVAILABLE')
print('tzdata', version('tzdata'), 'cp-sat', sys.argv[2], 'solve/verify/schema OK')
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
            f"{wheel}[cp-sat]" if extra else str(wheel),
            "python",
            "-I",
            "-c",
            script,
            str(ROOT),
            str(extra),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONTZPATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
