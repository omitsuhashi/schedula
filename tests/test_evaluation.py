import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_evaluation_records_verified_result_and_process_measurements(tmp_path):
    source = ROOT / "examples/assignment.json"
    output = tmp_path / "results.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/evaluate.py"),
            str(source),
            str(ROOT / "examples/roster.json"),
            "--backend",
            "cp_sat",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert (
        report["source"]["commit"]
        == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    )
    assert report["source"]["dirty"] == bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    )
    assert (
        report["source"]["uv_lock_sha256"]
        == hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    )
    measurement, roster = report["measurements"]
    assert (
        measurement["solver_response"]["engine_version"]
        == report["environment"]["packages"]["shift-schedula"]
    )
    assert measurement["solver_request"]["backend"] == "cp_sat"
    assert measurement["solver_response"]["backend"] == "cp_sat"
    assert measurement["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert measurement["status"] == "OPTIMAL"
    assert measurement["verification"]["valid"] is True
    assert measurement["objectives"][0]["value"] == 0
    assert measurement["elapsed_seconds"] >= measurement["engine_elapsed_seconds"] > 0
    assert measurement["peak_rss_mib"] > 0
    assert (measurement["employees"], measurement["roles"], measurement["slots"]) == (3, 3, 4)
    assert measurement["candidates"] == 0
    assert roster["status"] == "OPTIMAL" and roster["verification"]["valid"] is True
    assert roster["candidates"] == 32
    assert [o["value"] for o in roster["objectives"]] == [60, 2640, 0]


def run_evaluation(tmp_path, *arguments):
    output = tmp_path / "results.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/evaluate.py"),
            *map(str, arguments),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(output.read_text())


def test_repeated_cold_parallel_and_warm_first_call_are_distinguished(tmp_path):
    source = ROOT / "examples/assignment.json"
    cold = run_evaluation(tmp_path, source, "--repeat", 2, "--processes", 2, "--source-ref", "HEAD")
    assert cold["source"]["snapshot"] == "git_archive"
    assert cold["source"]["dirty"] is False
    assert len(cold["source"]["source_tree_sha256"]) == 64
    assert len(cold["workers"]) == 2
    assert cold["summaries"][0]["solution_rate"] == 1
    assert cold["summaries"][0]["first_request_elapsed_seconds"]["samples"] == 2
    assert cold["summaries"][0]["continued_request_elapsed_seconds"]["samples"] == 0
    warm = run_evaluation(tmp_path, source, "--repeat", 3, "--mode", "warm")
    assert len(warm["workers"]) == 1
    assert [item["iteration"] for item in warm["measurements"]] == [1, 2, 3]
    assert warm["summaries"][0]["first_request_elapsed_seconds"]["samples"] == 1
    assert warm["summaries"][0]["continued_request_elapsed_seconds"]["samples"] == 2


def test_archived_legacy_package_runs_in_its_own_environment(tmp_path):
    legacy = tmp_path / "legacy"
    shutil.copytree(
        ROOT / "src/shift_schedula",
        legacy / "src/schedula",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in (
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        ".gitignore",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        (legacy / name).write_text(
            text.replace("shift-schedula", "schedula").replace("shift_schedula =", "schedula ="),
            encoding="utf-8",
        )
    for name in ("contract.py", "engine.py"):
        path = legacy / "src/schedula" / name
        path.write_text(
            path.read_text()
            .replace('files("shift_schedula")', 'files("schedula")')
            .replace('version("shift-schedula")', 'version("schedula")')
        )
    (legacy / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/evaluate.py", legacy / "scripts/evaluate.py")
    (legacy / "examples").mkdir()
    shutil.copyfile(ROOT / "examples/assignment.json", legacy / "examples/assignment.json")
    for command in (
        ["git", "init"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Evaluation Test",
            "-c",
            "user.email=evaluation@example.invalid",
            "commit",
            "-m",
            "legacy package",
        ],
        ["uv", "sync", "--locked", "--no-dev", "--python", sys.executable],
    ):
        result = subprocess.run(command, cwd=legacy, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    output = tmp_path / "legacy-results.json"
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "python",
            "scripts/evaluate.py",
            "examples/assignment.json",
            "--source-ref",
            "HEAD",
            "--repeat",
            "2",
            "--mode",
            "warm",
            "--output",
            str(output),
        ],
        cwd=legacy,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert "shift-schedula" not in report["environment"]["packages"]
    assert report["source"]["snapshot"] == "git_archive"
    assert report["source"]["dirty"] is False
    for row in report["measurements"]:
        assert row["status"] == "OPTIMAL" and row["verification"]["valid"] is True
        assert (
            row["solver_response"]["engine_version"]
            == report["environment"]["packages"]["schedula"]
        )
    assert report["summaries"][0]["solution_rate"] == 1


def test_invalid_input_failures_and_external_timeout_remain_in_denominator(tmp_path):
    report = run_evaluation(
        tmp_path,
        ROOT / "examples/invalid-input.json",
        tmp_path / "missing.json",
        "--repeat",
        2,
        "--mode",
        "warm",
    )
    invalid, missing = report["summaries"]
    assert invalid["statuses"] == {"INVALID_INPUT": 2}
    assert missing["statuses"] == {"WORKER_ERROR": 1, "WORKER_NOT_RUN": 1}
    assert missing["attempts"] == 2 and missing["solution_rate"] == 0
    assert missing["statistics"]["elapsed_seconds"]["samples"] == 0
    timeout = run_evaluation(
        tmp_path, ROOT / "examples/assignment.json", "--repeat", 2, "--timeout-seconds", 0.000001
    )
    assert timeout["summaries"][0]["statuses"] == {"WORKER_TIMEOUT": 2}
    assert timeout["summaries"][0]["process_elapsed_seconds"]["samples"] == 2
    assert all(item["input_sha256"] for item in timeout["measurements"])
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"employees":null}')
    invalid_shape = run_evaluation(tmp_path, malformed)["measurements"][0]
    assert invalid_shape["status"] == "INVALID_INPUT"
    assert invalid_shape["employees"] is None
    assert invalid_shape["diagnostics"]


def test_objective_bound_scope_zero_denominator_and_nearest_rank():
    import runpy

    functions = runpy.run_path(str(ROOT / "scripts/evaluate.py"))
    response = {
        "objectives": [
            {"id": "first", "metric": "preference_penalty", "value": 10, "proven_optimal": False},
            {"id": "second", "metric": "role_switches", "value": 2, "proven_optimal": False},
        ],
        "diagnostics": [
            {
                "code": "OBJECTIVE_BOUND",
                "json_pointer": f"/objectives/{index}",
                "facts": [{"name": "best_bound", "value": value}],
            }
            for index, value in enumerate([8, 1])
        ],
    }
    first, second = functions["objective_quality"](response)
    assert first["absolute_gap"] == 2 and first["relative_gap"] == 0.2
    assert second["best_bound"] is None and second["relative_gap"] is None
    response["objectives"][0].update(value=10, proven_optimal=True)
    response["objectives"][1].update(value=100, proven_optimal=False)
    response["diagnostics"][0]["facts"][0]["value"] = 10
    response["diagnostics"][1]["facts"][0]["value"] = 40
    first, second = functions["objective_quality"](response)
    assert first["absolute_gap"] == 0
    assert second["best_bound"] == 40
    assert second["absolute_gap"] == 60 and second["relative_gap"] == 0.6
    response["diagnostics"].pop()
    second = functions["objective_quality"](response)[1]
    assert second["best_bound"] is None
    assert second["absolute_gap"] is None and second["relative_gap"] is None
    response["objectives"] = [
        {"id": "zero", "metric": "preference_penalty", "value": 0, "proven_optimal": True}
    ]
    response["diagnostics"] = []
    assert functions["objective_quality"](response)[0]["relative_gap"] == 0
    assert functions["distribution"](range(1, 21)) == {
        "samples": 20,
        "mean": 10.5,
        "median": 10.5,
        "p95": 19,
        "maximum": 20,
    }
    assert functions["distribution"]([])["p95"] is None


def test_time_limit_override_is_forwarded_without_changing_input(tmp_path):
    source = ROOT / "examples/assignment.json"
    original = json.loads(source.read_text())
    report = run_evaluation(tmp_path, source, "--time-limit-seconds", 30, "--source-ref", "HEAD")
    row = report["measurements"][0]
    assert row["status"] == "OPTIMAL"
    assert report["conditions"]["time_limit_seconds_override"] == 30
    assert row["input_solver_request"] == original["solver"]
    assert row["solver_request"]["time_limit_seconds"] == 30
    assert row["search_stats"]["time_limit_seconds"] == 30
    assert row["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    for invalid in ["nan", "0", "301"]:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/evaluate.py"),
                str(source),
                "--time-limit-seconds",
                invalid,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "探索予算" in result.stderr


def test_external_source_directory_is_used_and_identified(tmp_path):
    variant = tmp_path / "variant"
    shutil.copytree(ROOT / "src", variant / "src")
    for name in ["uv.lock", "pyproject.toml"]:
        shutil.copyfile(ROOT / name, variant / name)
    with (variant / "src/shift_schedula/__init__.py").open("a") as file:
        file.write('\nraise RuntimeError("external tree test")\n')
    report = run_evaluation(
        tmp_path,
        ROOT / "examples/assignment.json",
        "--source-ref",
        "HEAD",
        "--source-directory",
        variant,
    )
    assert report["source"]["snapshot"] == "external_tree_copy"
    assert report["source"]["dirty"] is True
    assert report["source"]["source_directory"] == str(variant)
    assert report["measurements"][0]["status"] == "WORKER_ERROR"
    assert "external tree test" in report["measurements"][0]["error"]


def test_evaluation_keeps_original_infeasibility_and_verified_suggestions(tmp_path):
    report = run_evaluation(tmp_path, ROOT / "docs/evaluations/inputs/roster-extended.json")
    row = report["measurements"][0]
    assert row["schema_version"] == "0.2" and row["status"] == "INFEASIBLE"
    suggestion = row["diagnosis_result"]["suggestions"][0]
    assert suggestion["option_id"] == "restore_one_person"
    assert suggestion["response"]["verification"]["valid"] is True
    assert [item["value"] for item in suggestion["response"]["objectives"]] == [16, 0, 240]
    assert suggestion["response"]["fairness_summary"]
    assert suggestion["response"]["change_summary"]
    assert report["summaries"][0]["solution_rate"] == 0
    assert report["summaries"][0]["verified_suggestions"] == 1


def test_partial_evaluation_preserves_shortage_and_verified_rate(tmp_path):
    report = run_evaluation(tmp_path, ROOT / "examples/partial_roster.json")
    row = report["measurements"][0]
    assert row["status"] == "PARTIAL"
    assert row["shortage_summary"]["total_person_minutes"] == 30
    assert row["shortage_summary"]["proven_minimal"]
    assert report["summaries"][0]["verified_solutions"] == 1
    import runpy

    functions = runpy.run_path(str(ROOT / "scripts/evaluate.py"))
    row["shortage_summary"]["proven_minimal"] = False
    for objective in row["objectives"]:
        objective["proven_optimal"] = False
    assert all(q["best_bound"] is None for q in functions["objective_quality"](row))
