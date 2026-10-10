import copy
import json
import socket
import subprocess
import sys
from http.client import HTTPConnection
from threading import Event, Thread

import pytest

from demo import server
from shift_schedula import solve
from tests.support import assert_response
from tests.test_playground_scenarios import BASELINE, SCENARIOS, scenario_requests


@pytest.fixture
def http_server():
    with server.DemoServer(0) as instance:
        thread = Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        try:
            yield instance
        finally:
            instance.shutdown()
            thread.join(timeout=5)


def call(
    instance, request=None, *, method="POST", path="/solve", body=None, headers=None, timeout=10
):
    connection = HTTPConnection("127.0.0.1", instance.server_port, timeout=timeout)
    if body is None and request is not None:
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
    connection.request(method, path, body, headers or {"Content-Type": "application/json"})
    response = connection.getresponse()
    content = response.read()
    status = response.status
    connection.close()
    return status, json.loads(content) if content else None


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_http_scenarios_match_library(http_server, scenario):
    for step, request in scenario_requests(scenario):
        status, result = call(http_server, request)
        assert status == 200
        assert_response(result, step["expected"]["status"])
        direct = solve(request)
        for key in (
            "request_id",
            "status",
            "solution",
            "objectives",
            "verification",
            "shortage_summary",
        ):
            assert result[key] == direct[key]


def test_http_matches_cli_and_only_serves_allowlist(http_server):
    status, result = call(http_server, BASELINE)
    cli = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "solve", str(server.SAMPLES / "lunch.json")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert status == 200
    assert json.loads(cli.stdout)["solution"] == result["solution"]
    for path in (
        "/samples/lunch.json",
        "/samples/scenarios.json",
        "/samples/roster.json",
        "/samples/coworkers.json",
        "/samples/roster-100-30.json",
        "/samples/catalog.json",
        "/samples/lessons.json",
        "/samples/demand-adjustment.json",
        "/samples/consecutive-days.json",
        "/samples/night-count.json",
        "/samples/manual-verify.json",
        "/samples/manual-verify.solution.json",
        "/samples/skills.json",
        "/samples/availability.json",
        "/samples/shift-candidates.json",
        "/samples/breaks.json",
        "/samples/overnight.json",
        "/samples/split-shift.json",
        "/samples/coverage-24h.json",
        "/samples/coverage-48h.json",
    ):
        assert call(http_server, method="GET", path=path)[0] == 200
    for path in ("/../pyproject.toml", "/.git/config", "/samples/", "/solve"):
        assert call(http_server, method="GET", path=path)[0] == 404
    assert call(http_server, BASELINE, method="PUT")[0] == 405
    assert call(http_server, BASELINE, method="CUSTOM")[1]["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert call(http_server, BASELINE, path="/elsewhere")[0] == 404


def test_partial_http_cli_and_library_agree(http_server):
    _, request = list(scenario_requests(SCENARIOS[1]))[1]
    status, result = call(http_server, request)
    cli = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "solve", "-"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
    )
    assert status == 200 and cli.returncode == 2 and cli.stderr == ""
    assert_response(result, "PARTIAL")
    for other in (solve(request), json.loads(cli.stdout)):
        for key in (
            "request_id",
            "status",
            "solution",
            "objectives",
            "verification",
            "shortage_summary",
        ):
            assert result[key] == other[key]


@pytest.mark.parametrize(
    ("body", "headers", "status", "code"),
    [
        (b"{", None, 400, "INVALID_JSON"),
        (b'{"a":1,"a":2}', None, 400, "DUPLICATE_JSON_KEY"),
        (b'{"a":NaN}', None, 400, "NON_FINITE_NUMBER"),
        (b"\xff", None, 400, "INVALID_JSON"),
        (b" " * (server.MAX_BODY + 1), None, 413, "BODY_TOO_LARGE"),
        (b"{}", {"Content-Type": "text/plain"}, 415, "UNSUPPORTED_MEDIA_TYPE"),
        (
            b"{}",
            {"Content-Type": "application/json; charset=latin-1"},
            415,
            "UNSUPPORTED_MEDIA_TYPE",
        ),
        (b"{}", {"Origin": "https://example.com"}, 403, "FORBIDDEN_ORIGIN"),
        (b"{}", {"Host": "example.com"}, 403, "FORBIDDEN_ORIGIN"),
        (b"{}", {"Transfer-Encoding": "chunked"}, 400, "INVALID_BODY"),
        (b"{}", {"Content-Length": "-1"}, 400, "INVALID_BODY"),
        (b"{}", {"Content-Length": "99999999999999999999"}, 400, "INVALID_BODY"),
    ],
    ids=[
        "syntax",
        "duplicate-key",
        "non-finite",
        "utf8",
        "body-limit",
        "media-type",
        "charset",
        "origin",
        "host",
        "encoding",
        "negative-length",
        "large-length",
    ],
)
@pytest.mark.parametrize("path", ["/solve", "/solve-json", "/verify-json"])
def test_http_rejects_invalid_transport(http_server, body, headers, status, code, path):
    if code == "BODY_TOO_LARGE" and path != "/solve":
        body = b"{}"
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(server.MAX_JSON_BODY + 1),
        }
    actual, result = call(http_server, body=body, headers=headers, path=path)
    assert (actual, result["error"]["code"]) == (status, code)
    assert "status" not in result


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("employees", 0, "label"), " "),
        (("employees", 0, "label"), "あ" * 21),
        (("employees", 0, "id"), "ren"),
        (("employees", 0, "skills"), [{"skill_id": "unknown", "level": 1}]),
        (("employees", 0, "skills"), [{"skill_id": "cooking", "level": True}]),
        (("employees", 0, "skills"), [{"skill_id": "cooking", "level": 2}]),
        (("employees", 0, "availability", 0, "start"), "2026-10-06T11:15:00+09:00"),
        (("employees", 0, "availability", 0, "end"), "2026-10-06T11:00:00+09:00"),
        (("demand", 0, "required_people"), True),
        (("demand", 0, "required_people"), 1.5),
        (("demand", 0, "required_people"), 7),
        (("demand", 0, "role_id"), "hall"),
        (("solver", "seed"), 1),
        (("schema_version",), "0.2"),
        (("constraints",), [{"id": "custom"}]),
        (("employees",), []),
        (("demand",), []),
        (("extra",), "unknown"),
    ],
)
def test_http_rejects_out_of_range_without_mutation(http_server, path, value):
    request = copy.deepcopy(BASELINE)
    target = request
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    before = copy.deepcopy(request)
    status, result = call(http_server, request)
    assert status == 400
    assert result["error"]["code"] == "DEMO_INPUT_OUT_OF_RANGE"
    assert result["error"]["json_pointer"] is not None
    assert request == before


def test_editable_limits_and_ids_independent_of_order(http_server):
    request = copy.deepcopy(BASELINE)
    request["employees"].reverse()
    request["demand"].reverse()
    request["employees"][0]["label"] = "😀" * 20
    request["employees"][0]["skills"] = []
    for item in request["demand"]:
        item["required_people"] = 0
    status, result = call(
        http_server,
        request,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Origin": f"http://127.0.0.1:{http_server.server_port}",
        },
    )
    assert status == 200
    assert_response(result, "OPTIMAL")
    assert result["solution"]["assignments"] == []


def test_engine_states_and_entrance_failure_are_distinct(http_server, monkeypatch):
    from shift_schedula.engine import response

    send_json = server.Handler.send_json

    def after_unlock(handler, status, value):
        assert not handler.server.solve_lock.locked()
        send_json(handler, status, value)

    monkeypatch.setattr(server.Handler, "send_json", after_unlock)
    for state in ("INVALID_INPUT", "BACKEND_UNAVAILABLE", "INTERNAL_ERROR", "UNKNOWN"):
        result = response(BASELINE["request_id"], state)
        monkeypatch.setattr(server, "solve", lambda _, result=result: result)
        assert call(http_server, BASELINE) == (200, result)

    def fail(_):
        raise RuntimeError("本文や内部情報を返さない")

    monkeypatch.setattr(server, "solve", fail)
    status, result = call(http_server, BASELINE)
    assert (status, result["error"]["code"]) == (500, "SERVER_ERROR")
    monkeypatch.setattr(server, "solve", solve)
    assert call(http_server, BASELINE)[1]["status"] == "OPTIMAL"


def test_concurrent_solve_is_busy_then_recovers(http_server, monkeypatch):
    entered, release = Event(), Event()

    def slow(request):
        entered.set()
        assert release.wait(timeout=5)
        return solve(request)

    monkeypatch.setattr(server, "solve", slow)
    results = []
    thread = Thread(target=lambda: results.append(call(http_server, BASELINE)))
    thread.start()
    try:
        assert entered.wait(timeout=5)
        for path in ("/solve", "/solve-json"):
            status, result = call(http_server, BASELINE, path=path)
            assert (status, result["error"]["code"]) == (503, "BUSY")
    finally:
        release.set()
        thread.join(timeout=5)
    assert results[0][1]["status"] == "OPTIMAL"
    assert call(http_server, BASELINE)[1]["status"] == "OPTIMAL"


def test_missing_duplicate_headers_and_read_deadline(http_server, monkeypatch):
    host = f"127.0.0.1:{http_server.server_port}"
    monkeypatch.setattr(server, "READ_TIMEOUT", 0.1)
    for headers, code in [
        ("", "INVALID_BODY"),
        ("Content-Length: 2\r\nContent-Length: 2\r\n", "INVALID_BODY"),
        (f"Host: {host}\r\nContent-Length: 2\r\n", "FORBIDDEN_ORIGIN"),
        ("Content-Length: 2\r\n", "READ_TIMEOUT"),
    ]:
        with socket.create_connection(("127.0.0.1", http_server.server_port), timeout=5) as client:
            client.sendall(
                f"POST /solve HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
                f"{headers}\r\n".encode()
            )
            content = b""
            while block := client.recv(65536):
                content += block
            assert json.loads(content.split(b"\r\n\r\n", 1)[1])["error"]["code"] == code


@pytest.mark.parametrize("name", ["assignment", "roster", "overnight", "split_roster"])
def test_json_input_uses_engine_contract(http_server, name):
    request = json.loads((server.ROOT / "examples" / f"{name}.json").read_text())
    before = copy.deepcopy(request)
    status, result = call(http_server, request, path="/solve-json")
    assert status == 200
    assert_response(result, "OPTIMAL")
    assert result["schema_version"] == request["schema_version"]
    assert result["request_id"] == request["request_id"]
    assert request == before


def test_json_input_reports_engine_validation(http_server):
    request = json.loads((server.ROOT / "examples" / "invalid-input.json").read_text())
    status, result = call(http_server, request, path="/solve-json")
    assert status == 200
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "UNKNOWN_REFERENCE"
    assert call(http_server, body=b"null", path="/solve-json")[1]["status"] == "INVALID_INPUT"


@pytest.mark.parametrize("standby", [False, True], ids=["solver", "feasible-standby"])
def test_json_sample_100_people_30_days(http_server, monkeypatch, standby):
    from shift_schedula.engine import response
    from shift_schedula.flow import make_solution
    from shift_schedula.model import normalize
    from shift_schedula.verify import verify_solution

    body = (server.SAMPLES / "roster-100-30.json").read_bytes()
    request = json.loads(body)
    problem = normalize(request)
    assert len(request["employees"]) == 100
    assert problem.grid.slots == 30 * 48
    assert problem.grid.slot_minutes == 30
    assert len(problem.candidates) == 3000
    assert len(body) > server.MAX_BODY
    if standby:
        first_day = problem.grid.start.astimezone(problem.grid.timezone).date()
        positions = {employee["id"]: index for index, employee in enumerate(request["employees"])}
        assignments = {employee: [] for employee in positions}
        selected = []
        # 休憩時間ごとの25人から10人を選び、各従業員に5日ごとに2勤務を割り当てる。
        for candidate in problem.candidates:
            day = (candidate.day - first_day).days
            position = positions[candidate.employee_id] % 50 // 2
            if (position - day * 10) % 25 < 10:
                selected.append(candidate)
                role = next(iter(problem.qualified[candidate.employee_id]))
                assignments[candidate.employee_id].extend(
                    (slot, role) for slot in candidate.work_slots
                )
        solution = make_solution(problem.grid, assignments)
        extra = next(
            c
            for c in problem.candidates
            if c.employee_id == request["employees"][20]["id"] and c.day == first_day
        )
        assert extra not in selected
        solution["shifts"] = [c.output(problem.grid) for c in [*selected, extra]]
        violations, values = verify_solution(problem, solution)
        assert violations == []
        assert len(solution["shifts"]) == 1201
        assert values == (540450,)
        replay = response(
            request["request_id"],
            "FEASIBLE",
            backend="cp_sat",
            selection_reason="JOINT_ROSTER",
            verification={"performed": True, "valid": True, "violations": []},
        )
        replay.update(
            schema_version=request["schema_version"],
            fairness_summary=None,
            change_summary=None,
            diagnosis_result=None,
            continuity_summary=None,
            cost_summary=None,
            duty_balance_summary=None,
            day_count_summary=None,
            shift_count_balance_summary=None,
            priority_summary={
                "groups": [{"priority": 0, "total_person_minutes": 0, "proven_minimal": True}]
            },
            shortage_summary={"total_person_minutes": 0, "proven_minimal": True, "shortages": []},
            solution=solution,
            objectives=[
                {
                    "id": "work",
                    "metric": "scheduled_minutes",
                    "value": values[0],
                    "proven_optimal": False,
                }
            ],
        )
        monkeypatch.setattr(server, "solve", lambda _: replay)
    status, result = call(http_server, body=body, path="/solve-json", timeout=120)
    assert status == 200
    assert result["status"] in {"OPTIMAL", "FEASIBLE"}
    assert_response(result, result["status"])
    violations, values = verify_solution(problem, result["solution"])
    assert violations == []
    assert values == tuple(item["value"] for item in result["objectives"])


def test_adapter_http_is_inline_and_reverify_preserves_record(http_server):
    from shift_schedula import check_record, confirm_source, split_request

    draft = split_request(BASELINE)
    status, result = call(http_server, draft, path="/adapter/check")
    assert status == 200 and result["status"] == "INVALID_INPUT"
    for source in draft["sources"]:
        draft = confirm_source(draft, source["id"])
    status, result = call(http_server, draft, path="/adapter/run")
    assert status == 200
    record = check_record(result["record"])
    assert result["view"]["current_status"] == "VALID"
    assert all(not o["proven_optimal"] for o in result["view"]["metrics"]["objectives"])
    status, restored = call(http_server, record, path="/adapter/verify")
    assert status == 200 and restored["record"] == record
    assert restored["view"]["run_id"] == record["run_id"]
    assert restored["draft"] == draft
    status, result = call(
        http_server, {"manifest_version": "1.0", "files": ["/etc/passwd"]}, path="/adapter/run"
    )
    assert status == 200 and result["status"] == "INVALID_INPUT"
    assert call(http_server, body=b'{"a":1,"a":2}', path="/adapter/check")[0] == 400
    assert call(http_server, method="GET", path="/samples/assignment.draft.json")[0] == 200


@pytest.mark.parametrize("version", [*(f"0.{i}" for i in range(1, 15)), "0.16", None])
def test_json_http_rejects_versions_with_current_failure_contract(http_server, version):
    request = copy.deepcopy(BASELINE)
    request["schema_version"] = version
    original = copy.deepcopy(request)
    status, result = call(http_server, request, path="/solve-json")
    assert status == 200
    assert_response(result, "INVALID_INPUT")
    assert result["schema_version"] == "0.15"
    assert result["request_id"] == request["request_id"]
    assert result["solution"] is None
    assert result["verification"]["performed"] is False
    assert request == original


def test_public_verify_http_without_solver_and_all_states(http_server, monkeypatch):
    from shift_schedula import verify
    from shift_schedula.contract import schema_errors

    request = json.loads((server.SAMPLES / "manual-verify.json").read_text())
    solution = json.loads((server.SAMPLES / "manual-verify.solution.json").read_text())

    def forbidden(*args, **kwargs):
        raise AssertionError("公開verifyではsolveを呼ばない")

    monkeypatch.setattr(server, "solve", forbidden)
    for name in ("VALID", "INVALID_PLAN", "PARTIAL", "INVALID_INPUT"):
        r, s = copy.deepcopy(request), copy.deepcopy(solution)
        if name == "INVALID_PLAN":
            s["assignments"][0]["employee_id"] = "bob"
        elif name == "PARTIAL":
            s["assignments"].pop(0)
        elif name == "INVALID_INPUT":
            r["demand"][0]["required_people"] = -1
        payload = {"request": r, "solution": s}
        saved = copy.deepcopy(payload)
        status, result = call(http_server, payload, path="/verify-json")
        assert status == 200 and result["status"] == name
        assert not schema_errors("verification", result)
        direct = verify(r, s)
        assert {k: v for k, v in result.items() if k != "stats"} == {
            k: v for k, v in direct.items() if k != "stats"
        }
        assert payload == saved
        assert "solution" not in result and "solver" not in result
    for payload in (
        {},
        None,
        [],
        {"request": request},
        {"request": request, "solution": solution, "extra": True},
    ):
        status, result = call(http_server, body=json.dumps(payload).encode(), path="/verify-json")
        assert status == 400 and result["error"]["code"] == "DEMO_INPUT_OUT_OF_RANGE"
    for r in (None, {}):
        status, result = call(
            http_server, {"request": r, "solution": solution}, path="/verify-json"
        )
        assert status == 200 and result["status"] == "INVALID_INPUT"
        assert not schema_errors("verification", result)


def test_verify_http_display_limit_and_shared_busy_lock(http_server):
    request = json.loads((server.SAMPLES / "roster-100-30.json").read_text())
    request["employees"].append({**copy.deepcopy(request["employees"][0]), "id": "extra_employee"})
    status, result = call(http_server, {"request": request, "solution": {}}, path="/verify-json")
    assert status == 400 and result["error"]["code"] == "DEMO_LIMIT"
    payload = {"request": BASELINE, "solution": {}}
    with http_server.solve_lock:
        status, result = call(http_server, payload, path="/verify-json")
    assert status == 503 and result["error"]["code"] == "BUSY"
