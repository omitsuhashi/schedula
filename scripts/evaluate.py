"""架空の評価入力を別プロセスで測定し、環境・条件・結果を JSON に保存する。"""

import argparse
import hashlib
import json
import platform
import resource
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path


def measure(path, backend):
    from schedula import solve
    from schedula.contract import load_json
    from schedula.model import normalize

    raw = path.read_bytes()
    request = load_json(raw.decode("utf-8"))
    if backend:
        request["solver"]["backend"] = backend
    start = time.perf_counter()
    response = solve(request)
    elapsed = time.perf_counter() - start
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # 条件の集計は測定後。検証・候補展開を含む solve 全体だけを時間測定する。
    problem = normalize(request)
    window = request["planning_window"]
    return {
        "input_file": str(path),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "problem_type": request["problem_type"],
        "employees": len(request["employees"]),
        "roles": len(request["roles"]),
        "days": (problem.grid.end - problem.grid.start).total_seconds() / 86400,
        "slot_minutes": window["slot_minutes"],
        "slots": problem.grid.slots,
        "candidates": len(problem.candidates),
        "objective_order": [o["metric"] for o in request["objectives"]],
        "solver_request": request["solver"],
        "solver_response": response["solver"],
        "status": response["status"],
        "verification": response["verification"],
        "objectives": response["objectives"],
        "diagnostics": response["diagnostics"],
        "assignments": len(response["solution"]["assignments"]) if response["solution"] else 0,
        "shifts": len(response["solution"]["shifts"]) if response["solution"] else 0,
        "elapsed_seconds": elapsed,
        "engine_elapsed_seconds": response["stats"]["elapsed_seconds"],
        "peak_rss_mib": peak_rss / (1024**2 if sys.platform == "darwin" else 1024),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend", choices=["auto", "min_cost_flow", "cp_sat"])
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(measure(args.inputs[0], args.backend), allow_nan=False))
        return
    if args.output is None:
        parser.error("--output に測定結果の保存先を指定します。")
    measurements = []
    for path in args.inputs:
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(path)]
        if args.backend:
            command += ["--backend", args.backend]
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
        measurements.append(json.loads(result.stdout))
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
            "uv": subprocess.check_output(["uv", "--version"], text=True).strip(),
            "packages": dict(sorted((d.metadata["Name"], d.version) for d in distributions())),
        },
        "measurements": measurements,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
