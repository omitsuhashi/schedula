import copy
import importlib.util
import json
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from examples import controlled_solve
from shift_schedula import cp_sat, solve


def stalled_worker(request, path, num_workers):
    # 正規の入口の各段階で停止を注入し、spawnでも親が復帰することを確認する。
    from shift_schedula import engine, roster

    def stall(*args, **kwargs):
        Path(path).write_text("{", encoding="utf-8")
        Path(path + ".started").touch()
        time.sleep(30)

    match request.pop("test_stage"):
        case "validation":
            engine.normalize = stall
        case "expansion":
            roster.expand_candidates = stall
        case "search":
            engine.cp_sat.run = stall
        case "ipc":
            stall()
    controlled_solve._worker(request, path, num_workers)


def crashed_worker(request, path, num_workers):
    Path(path).write_text("{", encoding="utf-8")
    os._exit(7)


def test_worker_count_validation_and_backend_application(assignment_request, monkeypatch):
    saved = copy.deepcopy(assignment_request)
    for value in (False, True, 0, -1, 1.5, "2", None, 2**31):
        response = solve(assignment_request, num_workers=value)
        assert response["status"] == "INVALID_INPUT"
        assert response["diagnostics"][0]["code"] == "INVALID_EXECUTION_OPTION"
    response = solve(assignment_request, num_workers=3)
    stats = {
        f["name"]: f["value"]
        for d in response["diagnostics"]
        if d["code"] == "SEARCH_STATS"
        for f in d["facts"]
    }
    assert response["status"] == "OPTIMAL"
    assert stats["num_workers"] is None and stats["workers_applied"] is False
    if importlib.util.find_spec("ortools") is not None:
        module, _ = cp_sat.load_backend()
        original = module.CpSolver.solve
        observed = []

        def search(self, model, *args, **kwargs):
            observed.append(self.parameters.num_search_workers)
            return original(self, model, *args, **kwargs)

        monkeypatch.setattr(module.CpSolver, "solve", search)
        request = {
            **assignment_request,
            "solver": {**assignment_request["solver"], "backend": "cp_sat"},
        }
        for count in (2, 1, 3):
            offset = len(observed)
            response = solve(request) if count == 2 else solve(request, num_workers=count)
            assert response["status"] == "OPTIMAL"
            stats = {
                f["name"]: f["value"]
                for d in response["diagnostics"]
                if d["code"] == "SEARCH_STATS"
                for f in d["facts"]
            }
            assert stats["num_workers"] == count and stats["workers_applied"] is True
            assert observed[offset:] and set(observed[offset:]) == {count}
    assert assignment_request == saved


def test_spawn_deadline_cancel_failure_and_independent_calls(assignment_request, monkeypatch):
    before = {p.pid for p in multiprocessing.active_children()}
    response = controlled_solve.run_controlled(assignment_request, total_seconds=20)
    assert response["status"] == "COMPLETED"
    assert response["response"]["status"] == "OPTIMAL"
    assert (
        controlled_solve.run_controlled({}, total_seconds=20)["response"]["status"]
        == "INVALID_INPUT"
    )
    assert (
        controlled_solve.run_controlled(assignment_request, total_seconds=0.001)["status"]
        == "DEADLINE_EXCEEDED"
    )
    monkeypatch.setattr(controlled_solve, "_worker", crashed_worker)
    result = controlled_solve.run_controlled(assignment_request, total_seconds=20)
    assert result["status"] == "WORKER_ERROR" and result["response"] is None
    monkeypatch.setattr(controlled_solve, "_worker", stalled_worker)
    roster_request = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/roster.json").read_text(encoding="utf-8")
    )
    stages = ["validation", "expansion", "ipc"]
    if importlib.util.find_spec("ortools") is not None:
        stages.append("search")
    for stage in stages:
        request = {**roster_request, "test_stage": stage}
        for cancellation in (False, True):
            cancel = threading.Event()
            # TemporaryDirectoryのパスを観測して、実際に段階へ到達してから止める。
            original = controlled_solve.tempfile.TemporaryDirectory
            directory = []

            def temporary(*args, original=original, directory=directory, **kwargs):
                value = original(*args, **kwargs)
                directory.append(value.name)
                return value

            with monkeypatch.context() as patch:
                patch.setattr(controlled_solve.tempfile, "TemporaryDirectory", temporary)
                with ThreadPoolExecutor() as pool:
                    task = pool.submit(
                        controlled_solve.run_controlled, request, total_seconds=5, cancel=cancel
                    )
                    wait_until = time.monotonic() + 4
                    while (
                        not directory or not (Path(directory[0]) / "response.json.started").exists()
                    ):
                        assert time.monotonic() < wait_until
                        time.sleep(0.01)
                    if cancellation:
                        cancel.set()
                    result = task.result(timeout=8)
            assert result["status"] == ("CANCELLED" if cancellation else "DEADLINE_EXCEEDED")
            assert result["response"] is None and result["elapsed_seconds"] < 8
            assert not Path(directory[0]).exists()
    cancel = threading.Event()
    directory = []

    def temporary(*args, original=original, directory=directory, **kwargs):
        value = original(*args, **kwargs)
        directory.append(value.name)
        return value

    monkeypatch.setattr(controlled_solve.tempfile, "TemporaryDirectory", temporary)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(
            controlled_solve.run_controlled,
            {**roster_request, "test_stage": "ipc"},
            total_seconds=20,
            cancel=cancel,
        )
        wait_until = time.monotonic() + 4
        while not directory or not (Path(directory[0]) / "response.json.started").exists():
            assert time.monotonic() < wait_until
            time.sleep(0.01)
        # 他の呼び出しを通常のworkerに戻し、取消と同時に走らせる。
        monkeypatch.undo()
        second = pool.submit(controlled_solve.run_controlled, assignment_request, total_seconds=20)
        time.sleep(0.3)
        cancel.set()
        assert first.result(timeout=5)["status"] == "CANCELLED"
        assert second.result(timeout=20)["response"]["status"] == "OPTIMAL"
    assert {p.pid for p in multiprocessing.active_children()} == before
