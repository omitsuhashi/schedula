import copy
import errno
import math

import pytest

from shift_schedula import model, solve
from shift_schedula.contract import InvalidInput, load_json, schema_errors
from shift_schedula.model import normalize
from tests.support import assert_response


def replace(request, path, value):
    target = request
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


@pytest.mark.parametrize("assignment_request", ["0.15"], indirect=True)
@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["unexpected"], 1),
        (["schema_version"], "99.0"),
        (["planning_window", "unexpected"], True),
        (["planning_window", "timezone"], "unknown/zone"),
        (["planning_window", "timezone"], "/etc/passwd"),
        (["planning_window", "slot_minutes"], 7),
        (["planning_window", "slot_minutes"], True),
        (["planning_window", "start"], "2026-10-05T11:00:00"),
        (["planning_window", "start"], "2026-02-30T11:00:00+09:00"),
        (["planning_window", "start"], "2026-10-05T11:00:00-00:00"),
        (["planning_window", "end"], "2026-10-05T11:00:00+09:00"),
        (["planning_window", "end"], "2026-10-05T10:00:00+09:00"),
        (["planning_window", "end"], "2026-10-05T13:01:00+09:00"),
        (["planning_window", "end"], "2026-10-05T13:00:01+09:00"),
        (["planning_window", "end"], "2026-10-05T13:00:00.0000001+09:00"),
        (["employees", 0, "skills", 0, "skill_id"], "unregistered"),
        (["roles", 0, "required_skills", 0, "skill_id"], "unregistered"),
        (["roles", 0, "required_skills", 0, "min_level"], -1),
        (["roles", 0, "required_skills", 0, "min_level"], 0.5),
        (["demand", 0, "role_id"], "unregistered"),
        (["demand", 0, "required_people"], -1),
        (["demand", 0, "required_people"], 1.5),
        (["demand", 0, "required_people"], True),
        (["demand", 0, "interval", "start"], "2026-10-05T10:30:00+09:00"),
        (["demand", 0, "interval", "end"], "2026-10-05T13:30:00+09:00"),
        (["demand", 0, "interval", "end"], "2026-10-05T11:00:00+09:00"),
        (["demand", 0, "interval", "start"], "2026-10-05T11:15:00+09:00"),
        (["preferences", 0, "employee_ids"], ["unregistered"]),
        (["preferences", 0, "employee_ids"], ["alice", "alice"]),
        (["preferences", 0, "role_id"], "unregistered"),
        (["preferences", 0, "type"], "arbitrary_code"),
        (["preferences", 0, "penalty_per_minute"], 0),
        (["objectives"], []),
        (["solver", "backend"], "unknown"),
        (["solver", "time_limit_seconds"], 0),
        (["solver", "time_limit_seconds"], math.inf),
        (["solver", "time_limit_seconds"], -math.inf),
        (["solver", "time_limit_seconds"], math.nan),
        (["employees", 0, "label"], math.nan),
        (["solver", "seed"], -1),
        (["solver", "seed"], 2147483648),
        (["employees", 0, "skills", 0, "unexpected"], 1),
    ],
)
def test_invalid_structure_references_and_intervals(assignment_request, path, value):
    replace(assignment_request, path, value)
    result = solve(assignment_request)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"]
    assert result["solver"]["backend"] == "none"


@pytest.mark.parametrize("value", [None, [], "text", {}, 42])
def test_non_request_objects(value):
    assert_response(solve(value), "INVALID_INPUT")


@pytest.mark.parametrize("assignment_request", ["0.15"], indirect=True)
@pytest.mark.parametrize(
    "field", ["skills", "roles", "employees", "demand", "preferences", "objectives"]
)
def test_duplicate_ids(assignment_request, field):
    assignment_request[field].append(copy.deepcopy(assignment_request[field][0]))
    assert_response(solve(assignment_request), "INVALID_INPUT")


@pytest.mark.parametrize("assignment_request", ["0.15"], indirect=True)
@pytest.mark.parametrize("path", [["employees", 0, "skills"], ["roles", 0, "required_skills"]])
def test_duplicate_skill_entries(assignment_request, path):
    target = assignment_request
    for part in path:
        target = target[part]
    target.append(copy.deepcopy(target[0]))
    assert_response(solve(assignment_request), "INVALID_INPUT")


def test_duplicate_metrics_with_different_ids(assignment_request):
    assignment_request["objectives"].append({**assignment_request["objectives"][0], "id": "second"})
    assert_response(solve(assignment_request), "INVALID_INPUT")


@pytest.mark.parametrize("assignment_request", ["0.15"], indirect=True)
@pytest.mark.parametrize("field", ["demand", "availability"])
def test_overlap_rejected_even_for_zero_demand(assignment_request, field):
    if field == "demand":
        assignment_request["demand"].append(
            {**assignment_request["demand"][0], "id": "overlap", "required_people": 0}
        )
    else:
        assignment_request["employees"][0]["availability"] *= 2
    assert_response(solve(assignment_request), "INVALID_INPUT")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["problem_type"], "roster"),
        (["objectives", 0, "metric"], "scheduled_minutes"),
        (
            ["employees", 0, "history"],
            {"last_shift_end": None, "consecutive_work_days_before_window": 0},
        ),
        (
            ["constraints"],
            [
                {
                    "id": "limit",
                    "type": "max_scheduled_minutes",
                    "employee_ids": ["alice"],
                    "limit_minutes": 0,
                }
            ],
        ),
        (["constraints"], [{"id": "unknown", "type": "ignore_me", "employee_ids": ["alice"]}]),
        (
            ["shift_candidates"],
            [
                {
                    "id": "shift",
                    "employee_id": "alice",
                    "interval": {
                        "start": "2026-10-05T11:00:00+09:00",
                        "end": "2026-10-05T13:00:00+09:00",
                    },
                    "breaks": [],
                }
            ],
        ),
        (
            ["shift_templates"],
            [
                {
                    "id": "template",
                    "employee_ids": ["alice"],
                    "dates": ["2026-10-05"],
                    "start_times": ["11:00"],
                    "duration_minutes_options": [120],
                    "break_options": [],
                }
            ],
        ),
    ],
)
def test_unsupported_conditions_are_not_dropped(assignment_request, path, value):
    replace(assignment_request, path, value)
    assert_response(solve(assignment_request), "INVALID_INPUT")


@pytest.mark.parametrize(
    "text",
    [
        '{"a":1,"a":2}',
        '{"nested":{"a":1,"a":2}}',
        '{"items":[{"a":1,"a":2}]}',
        '{"n":NaN}',
        '{"n":Infinity}',
        '{"n":-Infinity}',
        '{"n":1e10000}',
        "{",
    ],
)
def test_strict_json_reader(text):
    with pytest.raises(InvalidInput):
        load_json(text)


def test_non_json_and_cyclic_library_input(assignment_request):
    assignment_request["employees"][0]["skills"] = ()
    assert_response(solve(assignment_request), "INVALID_INPUT")
    assignment_request["cycle"] = assignment_request
    assert_response(solve(assignment_request), "INVALID_INPUT")


@pytest.mark.parametrize(
    ("start", "end", "slots"),
    [
        ("2026-03-08T01:30:00-05:00", "2026-03-08T03:30:00-04:00", 2),
        ("2026-11-01T01:00:00-04:00", "2026-11-01T02:00:00-05:00", 4),
    ],
)
def test_time_grid_uses_elapsed_time_across_clock_changes(assignment_request, start, end, slots):
    assignment_request["planning_window"].update(start=start, end=end, timezone="America/New_York")
    for employee in assignment_request["employees"]:
        employee["availability"] = [{"start": start, "end": end}]
    for demand in assignment_request["demand"]:
        demand["interval"] = {"start": start, "end": end}
    problem = normalize(assignment_request)
    assert problem.grid.slots == slots
    result = solve(assignment_request)
    assert_response(result, "OPTIMAL")
    assert result["solution"]["assignments"][0]["interval"] == {"start": start, "end": end}


def test_equivalent_offsets_are_same_instants(assignment_request):
    assignment_request["employees"][0]["availability"] = [
        {"start": "2026-10-05T02:00:00Z", "end": "2026-10-05T04:00:00Z"}
    ]
    assert_response(solve(assignment_request), "OPTIMAL")


def test_integer_valued_json_numbers(assignment_request):
    assignment_request["planning_window"]["slot_minutes"] = 30.0
    assignment_request["demand"][0]["required_people"] = 1.0
    assignment_request["preferences"][0]["penalty_per_minute"] = 1.0
    assert_response(solve(assignment_request), "OPTIMAL")


def test_missing_explicit_array(assignment_request):
    del assignment_request["shift_candidates"]
    assert_response(solve(assignment_request), "INVALID_INPUT")


def test_resource_limits(assignment_request):
    assignment_request["planning_window"]["end"] = "2027-01-01T00:00:00+09:00"
    assert_response(solve(assignment_request), "INVALID_INPUT")
    assignment_request["planning_window"]["end"] = "2026-12-01T11:00:00+09:00"
    assignment_request["planning_window"]["slot_minutes"] = 60
    assignment_request["employees"] = [
        {
            **copy.deepcopy(assignment_request["employees"][0]),
            "id": f"employee_{i}",
            "availability": [],
        }
        for i in range(250)
    ]
    assert_response(solve(assignment_request), "INVALID_INPUT")


def test_identifier_cannot_end_in_newline(assignment_request):
    assignment_request["request_id"] = "valid_id\n"
    assert_response(solve(assignment_request), "INVALID_INPUT")


def test_timezone_length_is_rejected_before_zoneinfo(assignment_request, monkeypatch):
    assignment_request["planning_window"]["timezone"] = "A" * 256
    assert schema_errors("request", assignment_request)

    def unexpected_zoneinfo(_):
        raise AssertionError("Schema validation must reject the name before ZoneInfo")

    monkeypatch.setattr(model, "ZoneInfo", unexpected_zoneinfo)
    result = solve(assignment_request)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["json_pointer"] == "/planning_window/timezone"


@pytest.mark.parametrize(
    ("error_number", "status"),
    [(errno.ENAMETOOLONG, "INVALID_INPUT"), (errno.EIO, "INTERNAL_ERROR")],
)
def test_timezone_path_error_is_distinct_from_io_failure(
    assignment_request, monkeypatch, error_number, status
):
    def failing_zoneinfo(_):
        raise OSError(error_number, "Injected zoneinfo error")

    monkeypatch.setattr(model, "ZoneInfo", failing_zoneinfo)
    result = solve(assignment_request)
    assert_response(result, status)
    if status == "INVALID_INPUT":
        assert result["diagnostics"][0]["code"] == "INVALID_TIMEZONE"
        assert result["diagnostics"][0]["json_pointer"] == "/planning_window/timezone"
