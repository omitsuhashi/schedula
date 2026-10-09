import copy
from datetime import datetime, timedelta

import pytest

from shift_schedula import cp_sat, solve
from shift_schedula.model import normalize
from tests.roster_support import candidate, demand, interval, request, stamp, template
from tests.support import assert_response


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing_history", "MISSING_HISTORY"),
        ("null_with_days", "INVALID_HISTORY"),
        ("recent_with_zero", "INVALID_HISTORY"),
        ("old_with_days", "INVALID_HISTORY"),
        ("future", "INVALID_HISTORY"),
        ("history_seconds", "INVALID_TIME_PRECISION"),
        ("window_start", "INVALID_ROSTER_WINDOW"),
        ("window_end", "INVALID_ROSTER_WINDOW"),
        ("unknown_employee", "UNKNOWN_REFERENCE"),
        ("duplicate_candidate", "DUPLICATE_ID"),
        ("outside_window", "INVALID_CANDIDATE_AVAILABILITY"),
        ("outside_availability", "INVALID_CANDIDATE_AVAILABILITY"),
        ("break_availability_gap", "INVALID_CANDIDATE_AVAILABILITY"),
        ("misaligned", "MISALIGNED_INTERVAL"),
        ("seconds", "INVALID_TIME_PRECISION"),
        ("break_at_start", "INVALID_BREAK"),
        ("break_at_end", "INVALID_BREAK"),
        ("break_outside", "INVALID_BREAK"),
        ("break_reversed", "INVALID_BREAK"),
        ("break_overlap", "OVERLAPPING_INTERVALS"),
        ("break_misaligned", "MISALIGNED_INTERVAL"),
        ("min_cost_flow", "UNSUPPORTED_BACKEND"),
        ("unknown_template_employee", "UNKNOWN_REFERENCE"),
        ("duplicate_template", "DUPLICATE_ID"),
        ("template_break_too_long", "INVALID_BREAK"),
        ("template_minutes", "MISALIGNED_INTERVAL"),
        ("template_start", "MISALIGNED_INTERVAL"),
    ],
)
def test_invalid_roster_rejected_before_dependency_load(monkeypatch, mutation, code):
    data = request()
    candidate_row = data["shift_candidates"][0]
    c = candidate_row["segments"][0]
    e = data["employees"][0]
    if mutation == "missing_history":
        del e["history"]
    elif mutation in {
        "null_with_days",
        "recent_with_zero",
        "old_with_days",
        "future",
        "history_seconds",
    }:
        e["history"] = {
            "last_shift_end": {
                "null_with_days": None,
                "recent_with_zero": stamp(-1, 780),
                "old_with_days": stamp(-2, 780),
                "future": stamp(0, 30),
                "history_seconds": "2026-10-04T13:00:01+09:00",
            }[mutation],
            "last_work_day": None
            if mutation == "null_with_days"
            else stamp(-2 if mutation == "old_with_days" else -1)[:10],
            "consecutive_work_days_before_window": 0 if mutation == "recent_with_zero" else 1,
        }
    elif mutation.startswith("window_"):
        data["planning_window"]["start" if mutation == "window_start" else "end"] = stamp(
            0 if mutation == "window_start" else 1, 30
        )
    elif mutation == "unknown_employee":
        candidate_row["employee_id"] = "missing"
    elif mutation == "duplicate_candidate":
        data["shift_candidates"] *= 2
    elif mutation == "outside_window":
        c["interval"] = interval(-1)
    elif mutation == "outside_availability":
        e["availability"] = []
    elif mutation == "break_availability_gap":
        e["availability"] = [interval(end=630), interval(start=660)]
        c["breaks"] = [interval(start=630, end=660)]
    elif mutation == "overnight":
        c["interval"] = {"start": stamp(0, 1380), "end": stamp(1, 60)}
    elif mutation in {"misaligned", "seconds"}:
        c["interval"]["start"] = (
            stamp(0, 615) if mutation == "misaligned" else "2026-10-05T10:00:01+09:00"
        )
    elif mutation.startswith("break_"):
        c["breaks"] = {
            "break_at_start": [interval(end=630)],
            "break_at_end": [interval(start=660)],
            "break_outside": [interval(start=570, end=630)],
            "break_reversed": [interval(start=660, end=630)],
            "break_overlap": [interval(start=630, end=660)] * 2,
            "break_misaligned": [interval(start=615, end=660)],
        }[mutation]
    elif mutation == "min_cost_flow":
        data["solver"]["backend"] = "min_cost_flow"
    else:
        t = template()
        data["shift_templates"] = [t]
        if mutation == "unknown_template_employee":
            t["employee_ids"] = ["missing"]
        elif mutation == "duplicate_template":
            data["shift_templates"] *= 2
        elif mutation == "template_break_too_long":
            t["segment_options"][0][0]["breaks"] = [{"offset_minutes": 60, "duration_minutes": 30}]
        elif mutation == "template_overnight":
            t["start_times"] = ["23:30"]
        elif mutation == "template_minutes":
            t["segment_options"][0][0]["duration_minutes"] = 91
        else:
            t["start_times"] = ["10:15"]
    monkeypatch.setattr(
        cp_sat, "load_backend", lambda: pytest.fail("invalid roster loaded backend")
    )
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == code


@pytest.mark.parametrize(
    "last,count", [(None, 0), (stamp(-2, 780), 0), (stamp(-1, 780), 1), (stamp(0), 1)]
)
def test_history_empty_old_recent_and_exclusive_midnight(last, count):
    data = request()
    data["employees"][0]["history"] = {
        "last_shift_end": last,
        "last_work_day": (datetime.fromisoformat(last) - timedelta(microseconds=1))
        .date()
        .isoformat()
        if last is not None
        else None,
        "consecutive_work_days_before_window": count,
    }
    assert_response(solve(data), "OPTIMAL")


def test_adjacent_availability_and_multiple_breaks_are_supported():
    data = request()
    data["employees"][0]["availability"] = [interval(end=630), interval(start=630)]
    data["shift_candidates"] = [candidate(breaks=[(630, 660)])]
    assert len(normalize(data).candidates) == 1
    data["employees"][0]["availability"] = [interval(end=750)]
    data["shift_candidates"] = [candidate(end=750, breaks=[(690, 720), (630, 660)])]
    data["demand"] = [demand()]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 90
    assert result["solution"]["shifts"][0]["segments"][0]["breaks"] == [
        interval(start=630, end=660),
        interval(start=690, end=720),
    ]


def test_shift_ending_at_midnight_is_one_local_day():
    data = request()
    data["employees"][0]["availability"] = [interval(start=1380, end=1440)]
    data["shift_candidates"] = [candidate(start=1380, end=1440)]
    data["demand"] = [demand(start=1380, end=1440)]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 60


def test_template_composition_determinism_and_scope():
    data = request(days=2, employees=("alice", "bob"))
    data["shift_candidates"] = [candidate("alice", end=630)]
    data["shift_templates"] = [
        template(
            ("bob", "alice"),
            ("2026-10-06", "2026-10-05"),
            starts=("10:00", "10:30"),
            durations=(60, 90),
        )
    ]
    original = copy.deepcopy(data)
    candidates = normalize(data).candidates
    assert len(candidates) == 13  # 明示1 + 各日・人の有効な開始/勤務長3通り。
    assert all(
        c.id.startswith("tmpl.") and len(c.id) == 69
        for c in candidates
        if c.id != data["shift_candidates"][0]["id"]
    )
    for field in ("employee_ids", "dates", "start_times", "segment_options"):
        data["shift_templates"][0][field].reverse()
    assert normalize(data).candidates == candidates
    assert original["shift_templates"][0]["employee_ids"] == ["bob", "alice"]
    assert len({c.id for c in candidates}) == len(candidates)


def test_template_break_options_are_alternatives():
    data = request()
    data["shift_candidates"] = []
    data["employees"][0]["availability"] = [interval(end=720)]
    data["shift_templates"] = [template(durations=(120,), breaks=((30, 30), (60, 30)))]
    candidates = normalize(data).candidates
    assert len(candidates) == 2
    assert [c.breaks for c in sorted(candidates, key=lambda c: c.breaks)] == [
        ((21, 22),),
        ((22, 23),),
    ]
    assert all(len(c.work_slots) == 3 for c in candidates)


def test_template_filters_unavailable_and_outside_dates_without_widening():
    data = request()
    data["shift_candidates"] = []
    data["shift_templates"] = [
        template(
            dates=("2026-10-04", "2026-10-05", "2026-10-06"), starts=("09:00", "10:00", "11:00")
        )
    ]
    candidates = normalize(data).candidates
    assert len(candidates) == 1
    assert candidates[0].start == 20 and candidates[0].end == 23
    data["employees"][0]["availability"] = []
    assert normalize(data).candidates == []
    data["demand"] = [{**demand(), "minimum_people": 1}]
    assert_response(solve(data), "INFEASIBLE")


def test_generated_candidate_collision_with_explicit_id_rejected():
    data = request()
    data["shift_templates"] = [template()]
    generated = next(c for c in normalize(data).candidates if c.id.startswith("tmpl."))
    data["shift_candidates"][0]["id"] = generated.id
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "DUPLICATE_ID"


def test_template_time_cannot_end_in_newline():
    data = request()
    data["shift_templates"] = [template(starts=("10:00\n",))]
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "INVALID_TEMPLATE_TIME"


@pytest.mark.parametrize(
    "day,clock,zone",
    [("0001-01-01", "00:00", "Asia/Tokyo"), ("9999-12-31", "23:30", "America/New_York")],
)
def test_template_timezone_overflow_is_invalid_input(day, clock, zone):
    data = request()
    data["planning_window"].update(
        timezone=zone,
        start="2026-10-05T00:00:00-04:00" if zone == "America/New_York" else stamp(),
        end="2026-10-06T00:00:00-04:00" if zone == "America/New_York" else stamp(1),
    )
    data["employees"][0]["availability"] = []
    data["shift_candidates"] = []
    data["shift_templates"] = [template(dates=(day,), starts=(clock,))]
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "INVALID_TEMPLATE_TIME"
    assert result["diagnostics"][0]["json_pointer"] == "/shift_templates/0/start_times"
    assert result["solver"]["backend"] == "none"


@pytest.mark.parametrize("days", [100, 101])
def test_preexpansion_accepts_discarded_candidates_without_count_limit(days):
    data = request(employees=tuple(f"worker_{i}" for i in range(50)))
    data["shift_candidates"] = []
    dates = tuple(
        (datetime(2026, 10, 5) + timedelta(days=d)).date().isoformat() for d in range(days)
    )
    data["shift_templates"] = [template(tuple(e["id"] for e in data["employees"]), dates)]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(normalize(data).candidates) == 50


@pytest.mark.parametrize(
    "day,clock,code",
    [
        ("2026-03-08", "02:30", "NONEXISTENT_LOCAL_TIME"),
        ("2026-11-01", "01:30", "AMBIGUOUS_LOCAL_TIME"),
    ],
)
def test_template_clock_changes_rejected(day, clock, code):
    data = request()
    start = f"{day}T00:00:00" + ("-05:00" if "03-08" in day else "-04:00")
    next_day = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    end = f"{next_day}T00:00:00" + ("-04:00" if "03-08" in day else "-05:00")
    data["planning_window"].update(start=start, end=end, timezone="America/New_York")
    data["employees"][0]["availability"] = [{"start": start, "end": end}]
    data["shift_candidates"] = []
    data["shift_templates"] = [template(dates=(day,), starts=(clock,), durations=(60,))]
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == code


@pytest.mark.parametrize(
    "start,end,minutes",
    [
        ("2026-03-08T01:30:00-05:00", "2026-03-08T03:30:00-04:00", 60),
        ("2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00", 60),
    ],
)
def test_explicit_offsets_resolve_clock_change(start, end, minutes):
    data = request()
    date = start[:10]
    spring = "03-08" in date
    data["planning_window"].update(
        start=date + "T00:00:00" + ("-05:00" if spring else "-04:00"),
        end=(datetime.fromisoformat(date) + timedelta(days=1)).date().isoformat()
        + "T00:00:00"
        + ("-04:00" if spring else "-05:00"),
        timezone="America/New_York",
    )
    data["employees"][0]["availability"] = [{"start": start, "end": end}]
    data["shift_candidates"] = [
        {
            "id": "clock_change",
            "employee_id": "alice",
            "segments": [{"interval": {"start": start, "end": end}, "breaks": []}],
        }
    ]
    data["demand"] = [
        {
            "id": "need",
            "role_id": "kitchen",
            "interval": {"start": start, "end": end},
            "required_people": 1,
        }
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == minutes
