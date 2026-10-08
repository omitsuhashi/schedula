"""架空入力の反復・継続・並行測定を、失敗を含めて JSON に保存する。"""

import argparse
import hashlib
import io
import json
import math
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import import_module
from importlib.metadata import distributions, version
from pathlib import Path
from tempfile import TemporaryDirectory


def objective_quality(response):
    bounds = {
        item["json_pointer"]: {fact["name"]: fact["value"] for fact in item["facts"]}
        for item in response["diagnostics"]
        if item["code"] == "OBJECTIVE_BOUND"
    }
    quality = []
    prefix_proven = (response.get("shortage_summary") or {}).get("proven_minimal", True)
    for index, objective in enumerate(response["objectives"]):
        facts = bounds.get(f"/objectives/{index}", {})
        bound = facts.get("best_bound") if prefix_proven else None
        if objective["proven_optimal"] and bound is None:
            bound = objective["value"]
        gap = max(0, objective["value"] - bound) if bound is not None else None
        quality.append(
            {
                **objective,
                "best_bound": bound,
                "absolute_gap": gap,
                "relative_gap": gap / max(abs(objective["value"]), 1) if gap is not None else None,
                "bound_scope": "fixed_optimal_prefix" if bound is not None else None,
            }
        )
        prefix_proven = prefix_proven and objective["proven_optimal"]
    return quality


def measure(path, backend, time_limit_seconds=None):
    start = time.perf_counter()
    package = os.environ.get("SCHEDULA_EVALUATION_PACKAGE", "shift_schedula")
    solve = import_module(package).solve
    contract = import_module(f"{package}.contract")
    InvalidInput, load_json = contract.InvalidInput, contract.load_json
    normalize = import_module(f"{package}.model").normalize

    imported = time.perf_counter()
    raw = path.read_bytes()
    request = load_json(raw.decode("utf-8"))
    input_solver = None
    if isinstance(request, dict) and isinstance(request.get("solver"), dict):
        input_solver = request["solver"].copy()
        if backend:
            request["solver"]["backend"] = backend
        if time_limit_seconds is not None:
            request["solver"]["time_limit_seconds"] = time_limit_seconds
    loaded = time.perf_counter()
    response = solve(request)
    finished = time.perf_counter()
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # 条件集計の再正規化は、時間と RSS の取得後に行う。
    try:
        problem = normalize(request)
    except InvalidInput:
        problem = None
    metadata = request if problem else {}
    search_stats = {
        fact["name"]: fact["value"]
        for item in response["diagnostics"]
        if item["code"] == "SEARCH_STATS"
        for fact in item["facts"]
    }
    return {
        "input_file": str(path),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "problem_type": metadata.get("problem_type"),
        "employees": len(metadata["employees"]) if problem else None,
        "roles": len(metadata["roles"]) if problem else None,
        "days": (problem.grid.end - problem.grid.start).total_seconds() / 86400
        if problem
        else None,
        "slot_minutes": metadata.get("planning_window", {}).get("slot_minutes"),
        "slots": problem.grid.slots if problem else None,
        "candidates": len(problem.candidates) if problem else None,
        "objective_order": [o["metric"] for o in metadata["objectives"]] if problem else None,
        "constraint_types": [c["type"] for c in metadata["constraints"]] if problem else None,
        "shift_category_ids": [c["id"] for c in metadata.get("shift_categories", [])],
        "solver_request": metadata.get("solver"),
        "input_solver_request": input_solver,
        "solver_response": response["solver"],
        "schema_version": response["schema_version"],
        "replan_mode": metadata.get("replan_mode"),
        "baseline_plan_id": (metadata.get("baseline") or {}).get("plan_id"),
        "status": response["status"],
        "verification": response["verification"],
        "objectives": response["objectives"],
        "objective_quality": objective_quality(response),
        "diagnostics": response["diagnostics"],
        "fairness_summary": response.get("fairness_summary"),
        "change_summary": response.get("change_summary"),
        "continuity_summary": response.get("continuity_summary"),
        "day_count_summary": response.get("day_count_summary"),
        "cost_summary": response.get("cost_summary"),
        "duty_balance_summary": response.get("duty_balance_summary"),
        "shift_count_balance_summary": response.get("shift_count_balance_summary"),
        "shortage_summary": response.get("shortage_summary"),
        "priority_summary": response.get("priority_summary"),
        "diagnosis_result": response.get("diagnosis_result"),
        "search_stats": search_stats,
        "assignments": len(response["solution"]["assignments"]) if response["solution"] else 0,
        "shifts": len(response["solution"]["shifts"]) if response["solution"] else 0,
        "import_seconds": imported - start,
        "input_seconds": loaded - imported,
        "elapsed_seconds": finished - loaded,
        "request_elapsed_seconds": finished - start,
        "engine_elapsed_seconds": response["stats"]["elapsed_seconds"],
        "metadata_seconds": time.perf_counter() - finished,
        "peak_rss_mib": peak_rss / (1024**2 if sys.platform == "darwin" else 1024),
    }


def distribution(values):
    values = sorted(values)
    return {
        "samples": len(values),
        "mean": statistics.mean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p95": values[math.ceil(0.95 * len(values)) - 1] if values else None,
        "maximum": max(values) if values else None,
    }


def summarize(measurements, workers):
    summaries = []
    for path in dict.fromkeys(item["input_file"] for item in measurements):
        rows = [item for item in measurements if item["input_file"] == path]
        verified = [
            item
            for item in rows
            if item["status"] in {"OPTIMAL", "FEASIBLE", "PARTIAL"}
            and item["verification"]["performed"]
            and item["verification"]["valid"]
        ]
        summaries.append(
            {
                "input_file": path,
                "attempts": len(rows),
                "statuses": dict(sorted(Counter(item["status"] for item in rows).items())),
                "verified_solutions": len(verified),
                "complete_solutions": sum(
                    item["status"] in {"OPTIMAL", "FEASIBLE"} for item in verified
                ),
                "solution_rate": len(verified) / len(rows),
                "verified_suggestions": sum(
                    suggestion["response"]["status"] in {"OPTIMAL", "FEASIBLE"}
                    and suggestion["response"]["verification"]["performed"]
                    and suggestion["response"]["verification"]["valid"]
                    for item in rows
                    for suggestion in (item.get("diagnosis_result") or {}).get("suggestions", [])
                ),
                "statistics": {
                    key: distribution([item[key] for item in rows if item.get(key) is not None])
                    for key in ("elapsed_seconds", "request_elapsed_seconds", "peak_rss_mib")
                },
                "first_request_elapsed_seconds": distribution(
                    [
                        item["request_elapsed_seconds"]
                        for item in rows
                        if item.get("request_elapsed_seconds") is not None
                        and item["iteration"] == 1
                    ]
                ),
                "continued_request_elapsed_seconds": distribution(
                    [
                        item["request_elapsed_seconds"]
                        for item in rows
                        if item.get("request_elapsed_seconds") is not None and item["iteration"] > 1
                    ]
                ),
                "process_elapsed_seconds": distribution(
                    [item["elapsed_seconds"] for item in workers if item["input_file"] == path]
                ),
                "objective_quality": [
                    {
                        "id": objective["id"],
                        "metric": objective["metric"],
                        "observed_values": distribution(
                            [item["objective_quality"][index]["value"] for item in verified]
                        ),
                        "proven_count": sum(
                            item["objective_quality"][index]["proven_optimal"] for item in verified
                        ),
                        "relative_gap": distribution(
                            [
                                item["objective_quality"][index]["relative_gap"]
                                for item in verified
                                if item["objective_quality"][index]["relative_gap"] is not None
                            ]
                        ),
                    }
                    for index, objective in enumerate(
                        verified[0]["objective_quality"] if verified else []
                    )
                ],
            }
        )
    return summaries


def run_worker(job, args, environment):
    path, group, repeats = job
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(path),
        "--worker",
        "--repeat",
        str(repeats),
    ]
    if args.backend:
        command += ["--backend", args.backend]
    if args.time_limit_seconds is not None:
        command += ["--time-limit-seconds", str(args.time_limit_seconds)]
    start = time.perf_counter()
    failure = None
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, env=environment, timeout=args.timeout_seconds
        )
        stdout, stderr = result.stdout, result.stderr
        if result.returncode:
            failure = "WORKER_ERROR"
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        failure = "WORKER_TIMEOUT"
    elapsed = time.perf_counter() - start
    rows = []
    for line in stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            failure = failure or "WORKER_ERROR"
            break
    failure = failure or ("WORKER_ERROR" if len(rows) != repeats else None)
    completed = len(rows)
    for index in range(completed, repeats):
        rows.append(
            {
                "input_file": str(path),
                "status": failure if index == completed else "WORKER_NOT_RUN",
                "error": stderr[-4000:] or "測定結果を受信できませんでした。",
            }
        )
    for index, row in enumerate(rows):
        row.update(group=group, iteration=index + 1, mode=args.mode)
        row["execution"] = "cold_initial" if index == 0 else "continued"
        if "input_sha256" not in row:
            row["input_sha256"] = (
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            )
    return rows, {
        "input_file": str(path),
        "group": group,
        "elapsed_seconds": elapsed,
        "completed": completed,
        "failure": failure,
        "timeout_seconds": args.timeout_seconds,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend", choices=["auto", "min_cost_flow", "cp_sat"])
    parser.add_argument(
        "--time-limit-seconds", type=float, help="入力の探索予算を上書きする（最大300秒）"
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--mode", choices=["cold", "warm"], default="cold")
    parser.add_argument("--processes", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--source-ref", help="指定 commit の src と uv.lock を固定して測定する")
    parser.add_argument(
        "--source-directory", type=Path, help="基準commitから変更した外部ソースをコピーする"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (
        args.repeat < 1
        or args.processes < 1
        or not math.isfinite(args.timeout_seconds)
        or args.timeout_seconds <= 0
    ):
        parser.error("反復数・プロセス数・計測用の実行上限は正の値にします。")
    if args.time_limit_seconds is not None and (
        not math.isfinite(args.time_limit_seconds) or not 0 < args.time_limit_seconds <= 300
    ):
        parser.error("探索予算は0より大きく300秒以下の有限値にします。")
    if args.worker:
        for _ in range(args.repeat):
            print(
                json.dumps(
                    measure(args.inputs[0], args.backend, args.time_limit_seconds), allow_nan=False
                ),
                flush=True,
            )
        return
    if args.output is None:
        parser.error("--output に測定結果の保存先を指定します。")
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(
        ["git", "rev-parse", args.source_ref or "HEAD"], cwd=root, text=True
    ).strip()
    with TemporaryDirectory(prefix="shift_schedula-evaluation-") as directory:
        snapshot = Path(directory)
        if args.source_ref and args.source_directory is None:
            archive = subprocess.check_output(
                ["git", "archive", commit, "src", "uv.lock", "pyproject.toml"], cwd=root
            )
            with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                bundle.extractall(snapshot, filter="data")
        else:
            source_root = args.source_directory or root
            shutil.copytree(
                source_root / "src", snapshot / "src", ignore=shutil.ignore_patterns("__pycache__")
            )
            shutil.copyfile(source_root / "uv.lock", snapshot / "uv.lock")
            shutil.copyfile(source_root / "pyproject.toml", snapshot / "pyproject.toml")
        digest = hashlib.sha256()
        for path in sorted((snapshot / "src").rglob("*")):
            if path.is_file():
                digest.update(
                    str(path.relative_to(snapshot)).encode() + b"\0" + path.read_bytes() + b"\0"
                )
        project = tomllib.loads((snapshot / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        source = {
            "commit": commit,
            "dirty": True
            if args.source_directory
            else False
            if args.source_ref
            else bool(
                subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
            ),
            "snapshot": "external_tree_copy"
            if args.source_directory
            else "git_archive"
            if args.source_ref
            else "working_tree_copy",
            "source_directory": str(args.source_directory) if args.source_directory else None,
            "source_tree_sha256": digest.hexdigest(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "uv_lock_sha256": hashlib.sha256((snapshot / "uv.lock").read_bytes()).hexdigest(),
            "package_version": project["version"],
        }
        if args.source_ref and (
            source["package_version"] != version(project["name"])
            or source["uv_lock_sha256"]
            != hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
        ):
            parser.error(
                "指定 source の package 版または uv.lock が実行環境と一致しません。"
                "先に同じ依存を同期します。"
            )
        environment = {
            **os.environ,
            "PYTHONPATH": str(snapshot / "src"),
            "SCHEDULA_EVALUATION_PACKAGE": project["name"].replace("-", "_"),
        }
        jobs = [
            (path, group + 1, 1 if args.mode == "cold" else args.repeat)
            for path in args.inputs
            for group in range(args.repeat if args.mode == "cold" else 1)
        ]
        with ThreadPoolExecutor(max_workers=args.processes) as pool:
            results = list(pool.map(lambda job: run_worker(job, args, environment), jobs))
    measurements = [row for rows, _ in results for row in rows]
    workers = [worker for _, worker in results]
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "source": source,
        "conditions": {
            "mode": args.mode,
            "repeat": args.repeat,
            "processes": args.processes,
            "worker_processes_started": len(workers),
            "worker_timeout_seconds": args.timeout_seconds,
            "time_limit_seconds_override": args.time_limit_seconds,
            "quantile_method": "nearest_rank",
            "cold_definition": "新規 Python プロセス。OS のファイルキャッシュは消去しない。",
        },
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "python": sys.version,
            "uv": subprocess.check_output(["uv", "--version"], text=True).strip(),
            "packages": dict(sorted((d.metadata["Name"], d.version) for d in distributions())),
        },
        "measurements": measurements,
        "workers": workers,
        "summaries": summarize(measurements, workers),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
