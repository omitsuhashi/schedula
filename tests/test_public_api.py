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
        (
            "0.1",
            "0.2",
            "0.3",
            "0.4",
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        ),
        (
            types.Request01,
            types.Request02,
            types.Request03,
            types.Request04,
            types.Request05,
            types.Request06,
            types.Request07,
            types.Request08,
            types.Request09,
            types.Request010,
            types.Request011,
            types.Request012,
            types.Request013,
            types.Request014,
            types.Request015,
        ),
        strict=True,
    ):
        schema = get_schema("request", version)
        assert set(schema["required"]) == request_type.__required_keys__
        assert set(schema["properties"]) == set(get_type_hints(request_type))
        assert get_args(get_type_hints(request_type)["schema_version"]) == (version,)
    assert set(get_args(types.SchemaVersion.__value__)) == {
        "0.1",
        "0.2",
        "0.3",
        "0.4",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "0.10",
        "0.11",
        "0.12",
        "0.13",
        "0.14",
        "0.15",
    }
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
    minimum_request = json.loads(
        (ROOT / "examples/minimum_roster.json").read_text(encoding="utf-8")
    )
    minimum_solution = solve(minimum_request)["solution"]
    run(
        str(python),
        "-I",
        "-c",
        "import importlib.util, json, sys; "
        "from shift_schedula import solve, verify; "
        "assert importlib.util.find_spec('ortools') is None; "
        "request, solution = map(json.loads, sys.argv[1:]); "
        "assert verify(request, solution)['status'] == 'PARTIAL'; "
        "solution['assignments'] = []; "
        "assert verify(request, solution)['status'] == 'INVALID_PLAN'; "
        "assert solve(request)['status'] == 'BACKEND_UNAVAILABLE'",
        json.dumps(minimum_request),
        json.dumps(minimum_solution),
    )
    patterns_request = json.loads(
        (ROOT / "examples/shift_patterns.json").read_text(encoding="utf-8")
    )
    patterns_solution = solve(patterns_request)["solution"]
    run(
        str(python),
        "-I",
        "-c",
        "import importlib.util, json, sys; "
        "from shift_schedula import solve, verify, make_baseline; "
        "assert importlib.util.find_spec('ortools') is None; "
        "request, solution = map(json.loads, sys.argv[1:]); "
        "assert verify(request, solution)['status'] == 'PARTIAL'; "
        "assert make_baseline(request, solution, 'saved')['source_request']"
        "['shift_categories'] == request['shift_categories']; "
        "early = next(c for c in request['shift_candidates'] if c['id'] == 'early'); "
        "solution['shifts'].append({'candidate_id':'early', 'employee_id':'alice', "
        "'work_day':early['segments'][0]['interval']['start'][:10], "
        "'segments':early['segments']}); "
        "checked = verify(request, solution); "
        "assert checked['status'] == 'INVALID_PLAN'; "
        "assert any(v['code']=='SHIFT_PATTERN_VIOLATION' for v in checked['diagnostics']); "
        "assert solve(request)['status'] == 'BACKEND_UNAVAILABLE'",
        json.dumps(patterns_request),
        json.dumps(patterns_solution),
    )
    run(
        str(python),
        "-I",
        "-c",
        "from shift_schedula import validate; "
        "assert validate({'request_id':'incomplete'})['status'] == 'INVALID_INPUT'",
    )
    run(str(python), "-m", "mypy", "--strict", str(ROOT / "examples/typed_api.py"))
    overlap_consumer = tmp_path / "overlap_consumer.py"
    overlap_consumer.write_text(
        "from shift_schedula import make_baseline, solve\n"
        "from shift_schedula.types import Request07\n"
        "def roundtrip(request: Request07) -> None:\n"
        "    result = solve(request)\n"
        '    if result["schema_version"] == "0.7" and '
        'result["status"] in {"OPTIMAL", "FEASIBLE", "PARTIAL"}:\n'
        '        make_baseline(request, result["solution"], "saved")\n'
        '        summary = result["change_summary"]\n'
        '        if summary is not None and "comparison_interval" in summary:\n'
        '            print(summary["comparison_interval"], summary["slot_minutes"])\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(overlap_consumer))
    refinement_consumer = tmp_path / "refinement_consumer.py"
    refinement_consumer.write_text(
        overlap_consumer.read_text(encoding="utf-8")
        .replace("Request07", "Request08")
        .replace('"0.7"', '"0.8"')
        + '    if result["schema_version"] == "0.8":\n'
        + '        detail = result["diagnosis_result"]\n'
        + '        if detail is not None and detail["conflict"] is not None:\n'
        + '            conflict = detail["conflict"]\n'
        + '            print(conflict["background_only"], conflict["checks"])\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(refinement_consumer))
    metrics_consumer = tmp_path / "metrics_consumer.py"
    metrics_consumer.write_text(
        "from shift_schedula import make_baseline, solve, verify\n"
        "from shift_schedula.types import Request09, CostObjective, DutyObjective\n"
        "def evaluate(request: Request09) -> None:\n"
        '    cost: CostObjective = {"id": "cost", "metric": "scheduled_cost"}\n'
        '    duty: DutyObjective = {"id": "night", "metric": "duty_deviation_minutes", '
        '"duty_id": "night"}\n'
        '    request["objectives"] = [cost, duty]\n'
        "    result = solve(request)\n"
        '    if result["schema_version"] == "0.9" and '
        'result["status"] in {"OPTIMAL", "FEASIBLE", "PARTIAL"}:\n'
        '        make_baseline(request, result["solution"], "saved")\n'
        '        checked = verify(request, result["solution"])\n'
        '        print(result["cost_summary"], result["duty_balance_summary"], '
        'checked.get("cost_summary"))\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(metrics_consumer))
    history_consumer = tmp_path / "history_consumer.py"
    history_consumer.write_text(
        metrics_consumer.read_text(encoding="utf-8")
        .replace("Request09", "Request010")
        .replace('"0.9"', '"0.10"'),
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(history_consumer))
    days_consumer = tmp_path / "days_consumer.py"
    days_consumer.write_text(
        history_consumer.read_text(encoding="utf-8")
        .replace("Request010", "Request011")
        .replace('"0.10"', '"0.11"')
        + '        print(result["day_count_summary"])\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(days_consumer))
    minimum_consumer = tmp_path / "minimum_consumer.py"
    minimum_consumer.write_text(
        days_consumer.read_text(encoding="utf-8")
        .replace("Request011", "Request012")
        .replace('"0.11"', '"0.12"')
        + '        request["demand"][0]["minimum_people"] = 1\n'
        + '        if result["shortage_summary"] is not None:\n'
        + '            print(result["shortage_summary"]["shortages"][0].get("minimum_people"))\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(minimum_consumer))
    patterns_consumer = tmp_path / "patterns_consumer.py"
    patterns_consumer.write_text(
        minimum_consumer.read_text(encoding="utf-8")
        .replace("Request012", "Request013")
        .replace('"0.12"', '"0.13"')
        + '        request["shift_categories"] = [{"id": "night", "label": "夜勤", '
        '"intervals": [], "min_overlap_minutes": 60}]\n'
        + '        request["constraints"].append({"id": "off", '
        '"type": "min_consecutive_days_off", "employee_ids": ["alice"], '
        '"evaluation_period": {"start": "", "end": ""}, "min_days": 2})\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(patterns_consumer))
    coworkers_request = json.loads((ROOT / "examples/coworkers.json").read_text(encoding="utf-8"))
    coworkers_solution = solve(coworkers_request)["solution"]
    run(
        str(python),
        "-I",
        "-c",
        "import importlib.util, json, sys; "
        "from shift_schedula import solve, verify, make_baseline; "
        "assert importlib.util.find_spec('ortools') is None; "
        "request, solution = map(json.loads, sys.argv[1:]); "
        "assert verify(request, solution)['status'] == 'PARTIAL'; "
        "assert make_baseline(request, solution, 'saved')['source_request']['constraints'] "
        "== request['constraints']; "
        "solution['shifts'] = [s for s in solution['shifts'] if s['employee_id'] != 'mentor_b']; "
        "checked = verify(request, solution); "
        "assert checked['status'] == 'INVALID_PLAN'; "
        "assert any(v['code']=='REQUIRED_COWORKERS_VIOLATION' for v in checked['diagnostics']); "
        "assert solve(request)['status'] == 'BACKEND_UNAVAILABLE'",
        json.dumps(coworkers_request),
        json.dumps(coworkers_solution),
    )
    coworkers_consumer = tmp_path / "coworkers_consumer.py"
    coworkers_consumer.write_text(
        patterns_consumer.read_text(encoding="utf-8")
        .replace("Request013", "Request014")
        .replace('"0.13"', '"0.14"')
        + '        request["constraints"].append({"id": "training", '
        '"type": "required_coworkers", "employee_ids": ["alice"], '
        '"coworker_ids": ["bob"], "minimum_people": 1, '
        '"interval": {"start": "", "end": ""}})\n'
        + '        request["constraints"].append({"id": "separate", '
        '"type": "incompatible_employees", "employee_ids": ["alice", "bob"], '
        '"interval": {"start": "", "end": ""}})\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(coworkers_consumer))
    count_request = json.loads((ROOT / "examples/shift_count_balance.json").read_text())
    count_solution = solve(count_request)["solution"]
    run(
        str(python),
        "-I",
        "-c",
        "import importlib.util, json, sys; from shift_schedula import verify, make_baseline; "
        "assert importlib.util.find_spec('ortools') is None; "
        "request, solution = map(json.loads, sys.argv[1:]); "
        "result = verify(request, solution); assert result['status'] == 'VALID'; "
        "assert result['shift_count_balance_summary'][0]['total_deviation_count'] == 0; "
        "assert all(not o['proven_optimal'] for o in result['objectives']); "
        "assert make_baseline(request, solution, 'saved')['source_request']['shift_count_balance'] "
        "== request['shift_count_balance']",
        json.dumps(count_request),
        json.dumps(count_solution),
    )
    count_consumer = tmp_path / "count_consumer.py"
    count_consumer.write_text(
        coworkers_consumer.read_text()
        .replace("Request014", "Request015")
        .replace('"0.14"', '"0.15"')
        + '        request["shift_count_balance"] = [{"id": "nights", "label": "夜勤回数", '
        '"evaluation_period": {"start": "", "end": ""}, "category_id": "night", '
        '"employee_targets": [{"employee_id": "alice", "target_count": 1}]}]\n'
        + '        request["objectives"].append({"id": "count", '
        '"metric": "shift_count_deviation", "balance_id": "nights"})\n',
        encoding="utf-8",
    )
    run(str(python), "-m", "mypy", "--strict", str(count_consumer))
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
