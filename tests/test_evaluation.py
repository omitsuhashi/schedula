import hashlib
import json
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
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    measurement, roster = report["measurements"]
    assert (
        measurement["solver_response"]["engine_version"]
        == report["environment"]["packages"]["schedula"]
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
