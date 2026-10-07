"""spawnで起動・IPC・求解・独立検証を含む総期限と取消を管理する例。"""

import argparse
import json
import math
import multiprocessing
import tempfile
import threading
import time
from pathlib import Path

from shift_schedula import load_json, solve
from shift_schedula.engine import validate_response


def _worker(request, path, num_workers):
    result = solve(request, num_workers=num_workers)
    Path(path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def run_controlled(request, *, total_seconds=30.0, cancel=None, num_workers=2):
    if (
        isinstance(total_seconds, bool)
        or not isinstance(total_seconds, (int, float))
        or not math.isfinite(total_seconds)
        or total_seconds <= 0
    ):
        raise ValueError("total_seconds は有限の正数で指定します。")
    started = time.monotonic()
    deadline = started + total_seconds
    cancel = cancel if cancel is not None else threading.Event()
    result = {"status": "WORKER_ERROR", "response": None}
    cleanup_seconds = 0.0

    def interrupted():
        if cancel.is_set():
            return "CANCELLED"
        if time.monotonic() >= deadline:
            return "DEADLINE_EXCEEDED"
        return None

    with tempfile.TemporaryDirectory(prefix="shift-schedula-") as directory:
        path = Path(directory) / "response.json"
        process = multiprocessing.get_context("spawn").Process(
            target=_worker, args=(request, str(path), num_workers)
        )
        try:
            status = interrupted()
            if status is None:
                process.start()
                while process.is_alive() and (status := interrupted()) is None:
                    process.join(min(0.05, max(0, deadline - time.monotonic())))
                status = interrupted()
                if status is None and process.exitcode == 0:
                    # 子の終了後にだけ読む。停止中の部分書き込みは返却しない。
                    response = load_json(path.read_text(encoding="utf-8"))
                    validate_response(
                        response, request if response["solution"] is not None else None
                    )
                    status = interrupted()
                    if status is None:
                        result.update(status="COMPLETED", response=response)
            if status is not None:
                result["status"] = status
        except Exception:
            result.update(status=interrupted() or "WORKER_ERROR", response=None)
        finally:
            cleanup_started = time.monotonic()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                    process.join(1.0)
                    if process.is_alive():
                        process.kill()
                process.join()
            process.close()
            cleanup_seconds = time.monotonic() - cleanup_started
    if result["status"] == "COMPLETED" and (status := interrupted()) is not None:
        result.update(status=status, response=None)
    result["elapsed_seconds"] = time.monotonic() - started
    result["cleanup_seconds"] = cleanup_seconds
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--total-seconds", type=float, default=30.0)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--cancel-after", type=float)
    options = parser.parse_args()
    cancel = threading.Event()
    timer = None
    if options.cancel_after is not None:
        timer = threading.Timer(options.cancel_after, cancel.set)
        timer.start()
    try:
        request = load_json(options.request.read_text(encoding="utf-8"))
        print(
            json.dumps(
                run_controlled(
                    request,
                    total_seconds=options.total_seconds,
                    cancel=cancel,
                    num_workers=options.num_workers,
                ),
                ensure_ascii=False,
            )
        )
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
