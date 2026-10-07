import copy
import itertools
import json
import random
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from schedula import cp_sat, solve
from schedula.model import normalize
from schedula.verify import verify_solution
from tests.roster_support import demand, interval, request, rule, stamp
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def segment(day=0, start=600, end=690, breaks=()):
    return {
        "interval": interval(day, start, end),
        "breaks": [interval(day, a, b) for a, b in breaks],
    }


def shift(segments, employee="alice", identifier="extended"):
    return {"id": identifier, "employee_id": employee, "segments": segments}


def extended_request(days=1, employees=("alice",)):
    data = request(days, employees)
    data["schema_version"] = "0.2"
    data["shift_candidates"] = [
        shift([{"interval": c["interval"], "breaks": c["breaks"]}], c["employee_id"], c["id"])
        for c in data["shift_candidates"]
    ]
    for employee in data["employees"]:
        employee["history"]["last_work_day"] = None
    return data


def example(name):
    return json.loads((ROOT / "examples" / name).read_text())


@pytest.mark.parametrize("name", ["overnight.json", "split_roster.json"])
def test_extended_examples_api_and_cli(name):
    data = example(name)
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["schema_version"] == "0.2"
    assert result["objectives"][0]["value"] == 420
    assert result["solution"]["shifts"][0]["work_day"] == "2026-10-06"
    assert len(result["solution"]["assignments"]) == 2
    assert verify_solution(normalize(data), result["solution"]) == ([], (420,))
    assert data == original
    process = subprocess.run(
        [sys.executable, "-m", "schedula", "solve", str(ROOT / "examples" / name)],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert process.stderr == ""
    assert_response(json.loads(process.stdout), "OPTIMAL")


@pytest.mark.parametrize("start,status", [(810, "INFEASIBLE"), (840, "OPTIMAL")])
def test_overnight_rest_uses_last_end_and_next_start(start, status):
    data = example("overnight.json")
    data["employees"][0]["availability"].append(interval(2, start, start + 60))
    data["shift_candidates"].append(shift([segment(2, start, start + 60)], identifier="next"))
    data["demand"].append(demand(2, start, start + 60))
    data["constraints"] = [rule("min_rest_minutes", 480)]
    assert_response(solve(data), status)


def test_overnight_overlap_is_forbidden_without_rest_rule():
    data = example("overnight.json")
    data["employees"][0]["availability"] = [interval(1, 1320, 1920)]
    data["shift_candidates"].append(shift([segment(2, 330, 480)], identifier="overlap"))
    data["demand"].append(demand(2, 360, 480))
    data["constraints"] = []
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize("limit,status", [(2, "INFEASIBLE"), (3, "OPTIMAL")])
def test_overnight_history_and_consecutive_days_use_start_day(limit, status):
    data = example("overnight.json")
    data["employees"][0]["history"] = {
        "last_shift_end": stamp(1),
        "last_work_day": "2026-10-05",
        "consecutive_work_days_before_window": 2,
    }
    data["constraints"] = [rule("max_consecutive_days", limit)]
    assert_response(solve(data), status)


@pytest.mark.parametrize("day,status", [(2, "INFEASIBLE"), (3, "OPTIMAL")])
def test_overnight_end_day_without_new_start_resets_consecutive_days(day, status):
    data = example("overnight.json")
    data["planning_window"]["end"] = stamp(4)
    data["employees"][0]["availability"].append(interval(day, 540, 600))
    data["shift_candidates"].append(shift([segment(day, 540, 600)], identifier="later"))
    data["demand"].append(demand(day, 540, 600))
    data["constraints"] = [rule("max_consecutive_days", 1)]
    assert_response(solve(data), status)


@pytest.mark.parametrize(
    "last,work_day,count",
    [
        (None, "2026-10-04", 0),
        (stamp(-1, 780), None, 1),
        (stamp(0, 30), "2026-10-04", 1),
        (stamp(0), "2026-10-05", 1),
        (stamp(-2, 780), "2026-10-04", 1),
        (stamp(-1, 780), "2026-10-04", 0),
        (stamp(-2, 780), "2026-10-03", 1),
    ],
)
def test_extended_history_inconsistency_is_rejected_before_backend(
    monkeypatch, last, work_day, count
):
    data = extended_request()
    data["employees"][0]["history"] = {
        "last_shift_end": last,
        "last_work_day": work_day,
        "consecutive_work_days_before_window": count,
    }
    monkeypatch.setattr(
        cp_sat, "load_backend", lambda: pytest.fail("invalid history loaded backend")
    )
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "INVALID_HISTORY"


def test_night_history_start_day_is_not_inferred_from_end():
    data = extended_request()
    data["employees"][0]["history"] = {
        "last_shift_end": stamp(-1, 360),
        "last_work_day": "2026-10-03",
        "consecutive_work_days_before_window": 0,
    }
    assert_response(solve(data), "OPTIMAL")


@pytest.mark.parametrize("outside", ["before", "after"])
def test_extended_explicit_candidate_outside_window_is_not_clipped(outside):
    data = extended_request(days=2)
    data["shift_candidates"] = [
        shift([segment(-1, 1320, 1800) if outside == "before" else segment(1, 1320, 1800)])
    ]
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "INVALID_CANDIDATE_AVAILABILITY"


def test_overnight_ending_at_year_boundary_midnight():
    data = extended_request()
    data["planning_window"].update(
        start="2026-12-31T00:00:00+09:00", end="2027-01-01T00:00:00+09:00"
    )
    duty = {"start": "2026-12-31T22:00:00+09:00", "end": "2027-01-01T00:00:00+09:00"}
    data["employees"][0]["availability"] = [duty]
    data["shift_candidates"] = [shift([{"interval": duty, "breaks": []}])]
    data["demand"] = [
        {"id": "year_end", "role_id": "kitchen", "interval": duty, "required_people": 1}
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 120
    assert result["solution"]["shifts"][0]["work_day"] == "2026-12-31"


@pytest.mark.parametrize("gap,status", [(300, "OPTIMAL"), (330, "INFEASIBLE")])
def test_split_gap_rule_is_hard_condition_not_input_invalidity(gap, status):
    data = example("split_roster.json")
    data["constraints"][1]["limit_minutes"] = gap
    assert len(normalize(data).candidates) == 1
    assert_response(solve(data), status)


@pytest.mark.parametrize("start,status", [(450, "INFEASIBLE"), (480, "OPTIMAL")])
def test_split_rest_starts_after_last_segment(start, status):
    data = example("split_roster.json")
    data["planning_window"]["end"] = stamp(3)
    data["employees"][0]["availability"].append(interval(2, start, start + 60))
    data["shift_candidates"].append(shift([segment(2, start, start + 60)], identifier="next"))
    data["demand"].append(demand(2, start, start + 60))
    assert_response(solve(data), status)


def test_different_shift_cannot_be_inserted_into_split_gap():
    data = extended_request(days=2)
    data["employees"][0]["availability"] = [interval(0, 1320, 2160)]
    data["shift_candidates"] = [
        shift([segment(0, 1320, 1380), segment(1, 660, 720)], identifier="split_night"),
        shift([segment(1, 540, 600)], identifier="inside_gap"),
    ]
    data["demand"] = [demand(0, 1320, 1380), demand(1, 540, 600), demand(1, 660, 720)]
    data["constraints"] = []
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize(
    "segments,code",
    [
        ([segment(start=540, end=720), segment(start=690, end=780)], "INVALID_SEGMENT_ORDER"),
        ([segment(start=540, end=720), segment(start=720, end=780)], "INVALID_SEGMENT_ORDER"),
        ([segment(start=720, end=780), segment(start=540, end=720)], "INVALID_SEGMENT_ORDER"),
        ([segment(start=540, end=540)], "INVALID_INTERVAL"),
        ([segment(start=545, end=720)], "MISALIGNED_INTERVAL"),
        ([segment(start=540, end=720, breaks=[(540, 570)])], "INVALID_BREAK"),
        ([segment(start=540, end=720, breaks=[(600, 750)])], "INVALID_BREAK"),
        ([segment(start=540, end=720, breaks=[(600, 660), (630, 690)])], "OVERLAPPING_INTERVALS"),
    ],
)
def test_extended_segment_structure_rejected(segments, code):
    data = extended_request()
    data["employees"][0]["availability"] = [interval(0, 0, 1440)]
    data["shift_candidates"] = [shift(segments)]
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == code


@pytest.mark.parametrize("count,status", [(4, "OPTIMAL"), (5, "INVALID_INPUT")])
def test_split_segment_limit(count, status):
    data = extended_request()
    data["employees"][0]["availability"] = [interval(0, 0, 1440)]
    data["shift_candidates"] = [
        shift([segment(start=60 * i, end=60 * i + 30) for i in range(count)])
    ]
    assert_response(solve(data), status)


def extended_template(employees=("alice",), dates=("2026-10-05",), starts=("09:00",), options=None):
    return {
        "id": "split_template",
        "employee_ids": list(employees),
        "dates": list(dates),
        "start_times": list(starts),
        "segment_options": options
        or [
            [
                {"offset_minutes": 0, "duration_minutes": 180, "breaks": []},
                {"offset_minutes": 480, "duration_minutes": 240, "breaks": []},
            ]
        ],
    }


def test_extended_template_determinism_and_actual_gaps():
    data = extended_request(days=2, employees=("alice", "bob"))
    for employee in data["employees"]:
        employee["availability"] = [interval(0, 0, 2880)]
    data["shift_candidates"] = []
    shape = extended_template()["segment_options"][0]
    data["shift_templates"] = [
        extended_template(
            ("bob", "alice"),
            ("2026-10-06", "2026-10-05"),
            ("09:00", "22:00"),
            [
                shape,
                [
                    {
                        "offset_minutes": 0,
                        "duration_minutes": 480,
                        "breaks": [
                            {"offset_minutes": 90, "duration_minutes": 60},
                            {"offset_minutes": 240, "duration_minutes": 30},
                        ],
                    }
                ],
            ],
        )
    ]
    candidates = normalize(data).candidates
    assert len(candidates) == 12
    split = next(c for c in candidates if len(c.segments) == 2)
    assert len(split.work_slots) * 30 == 420
    assert not set(range(split.segments[0][1], split.segments[1][0])) & split.work_slots
    for field in ("employee_ids", "dates", "start_times", "segment_options"):
        data["shift_templates"][0][field].reverse()
    for option in data["shift_templates"][0]["segment_options"]:
        for s in option:
            s["breaks"].reverse()
    assert normalize(data).candidates == candidates


def test_extended_templates_filter_but_explicit_candidates_reject():
    data = extended_request()
    data["shift_candidates"] = []
    data["shift_templates"] = [extended_template()]
    assert normalize(data).candidates == []
    data["shift_templates"] = []
    data["shift_candidates"] = [shift([segment(start=540, end=720), segment(start=1020, end=1260)])]
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("days", [100, 101])
def test_extended_template_accepts_discarded_shapes_without_count_limit(days):
    employees = tuple(f"worker_{i}" for i in range(50))
    data = extended_request(employees=employees)
    data["shift_candidates"] = []
    dates = [(datetime(2026, 10, 5) + timedelta(days=i)).date().isoformat() for i in range(days)]
    data["shift_templates"] = [
        extended_template(
            employees,
            dates,
            ("10:00",),
            [[{"offset_minutes": 0, "duration_minutes": 90, "breaks": []}]],
        )
    ]
    assert_response(solve(data), "OPTIMAL")


@pytest.mark.parametrize("mutation", ["first_offset", "adjacent", "too_many", "break_outside"])
def test_extended_template_invalid_shape_is_not_discarded(mutation):
    data = extended_request()
    data["employees"][0]["availability"] = []
    t = extended_template(dates=("2026-10-04",))
    shapes = t["segment_options"][0]
    if mutation == "first_offset":
        shapes[0]["offset_minutes"] = 30
    elif mutation == "adjacent":
        shapes[1]["offset_minutes"] = 180
    elif mutation == "too_many":
        t["segment_options"] = [
            [{"offset_minutes": i * 60, "duration_minutes": 30, "breaks": []} for i in range(5)]
        ]
    else:
        shapes[1]["breaks"] = [{"offset_minutes": 210, "duration_minutes": 60}]
    data["shift_candidates"] = []
    data["shift_templates"] = [t]
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize(
    "day,spring,minutes", [("2026-03-08", True, 180), ("2026-11-01", False, 300)]
)
def test_extended_clock_changes_use_elapsed_minutes(day, spring, minutes):
    data = extended_request()
    next_day = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    start = day + "T00:00:00" + ("-05:00" if spring else "-04:00")
    end = next_day + "T00:00:00" + ("-04:00" if spring else "-05:00")
    duty = {"start": start, "end": day + "T04:00:00" + ("-04:00" if spring else "-05:00")}
    data["planning_window"].update(start=start, end=end, timezone="America/New_York")
    data["employees"][0]["availability"] = [duty]
    data["shift_candidates"] = [shift([{"interval": duty, "breaks": []}])]
    data["demand"] = [{"id": "clock", "role_id": "kitchen", "interval": duty, "required_people": 1}]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == minutes
    data["shift_candidates"] = []
    data["shift_templates"] = [
        extended_template(
            dates=(day,),
            starts=("02:30" if spring else "01:30",),
            options=[[{"offset_minutes": 0, "duration_minutes": 30, "breaks": []}]],
        )
    ]
    rejected = solve(data)
    assert_response(rejected, "INVALID_INPUT")
    assert rejected["diagnostics"][0]["code"] == (
        "NONEXISTENT_LOCAL_TIME" if spring else "AMBIGUOUS_LOCAL_TIME"
    )


@pytest.mark.parametrize(
    "name,mutation",
    [
        ("overnight.json", "work_day"),
        ("overnight.json", "break"),
        ("overnight.json", "break_assignment"),
        ("split_roster.json", "gap_assignment"),
        ("split_roster.json", "segment"),
    ],
)
def test_broken_extended_solution_detected_and_blocked(monkeypatch, name, mutation):
    data = example(name)
    solution = copy.deepcopy(solve(data)["solution"])
    duty = solution["shifts"][0]
    if mutation == "work_day":
        duty["work_day"] = "2026-10-07"
    elif mutation == "break":
        duty["segments"][0]["breaks"] = []
    elif mutation == "segment":
        duty["segments"][1]["interval"]["end"] = stamp(1, 1230)
    else:
        solution["assignments"].append(
            {
                "employee_id": "alice",
                "role_id": "kitchen",
                "interval": interval(1, 1410, 1440)
                if mutation == "break_assignment"
                else interval(1, 720, 750),
            }
        )
    problem = normalize(data)
    problem.candidates.clear()
    problem.available.clear()
    violations, _ = verify_solution(problem, solution)
    assert violations
    if mutation == "break_assignment":
        assert "BREAK_ASSIGNMENT" in {v["code"] for v in violations}
    elif mutation == "gap_assignment":
        assert "UNSELECTED_SHIFT_ASSIGNMENT" in {v["code"] for v in violations}
    monkeypatch.setattr(
        cp_sat, "run", lambda *_: cp_sat.SatResult("OPTIMAL", solution, (420,), (True,))
    )
    assert_response(solve(data), "INTERNAL_ERROR")


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("split_gap", "MIN_SPLIT_GAP_VIOLATION"),
        ("scheduled", "MAX_SCHEDULED_MINUTES_VIOLATION"),
        ("overlap", "OVERLAPPING_SHIFTS"),
    ],
)
def test_extended_rule_violations_in_result_are_detected(monkeypatch, mutation, code):
    data = example("overnight.json" if mutation == "overlap" else "split_roster.json")
    solution = copy.deepcopy(solve(data)["solution"])
    if mutation == "split_gap":
        data["constraints"][1]["limit_minutes"] = 330
    elif mutation == "scheduled":
        data["constraints"] = [rule("max_scheduled_minutes", 419)]
    else:
        data["employees"][0]["availability"] = [interval(1, 1320, 1920)]
        data["shift_candidates"].append(shift([segment(2, 330, 480)], identifier="overlap"))
        problem = normalize(data)
        overlapping = next(c for c in problem.candidates if c.id == "overlap")
        solution["shifts"].append(overlapping.output(problem.grid))
    violations, _ = verify_solution(normalize(data), solution)
    assert code in {v["code"] for v in violations}
    monkeypatch.setattr(
        cp_sat, "run", lambda *_: cp_sat.SatResult("OPTIMAL", solution, (420,), (True,))
    )
    assert_response(solve(data), "INTERNAL_ERROR")


def exhaustive_scheduled_value(data):
    # 単一役割の小規模入力を元JSONだけで列挙する。候補展開・検証器・モデルを使わない。
    def parse(value):
        return datetime.fromisoformat(value).astimezone(UTC)

    first = parse(data["planning_window"]["start"])
    end = parse(data["planning_window"]["end"])
    zone = ZoneInfo(data["planning_window"]["timezone"])
    step = timedelta(minutes=data["planning_window"]["slot_minutes"])

    def slots(value):
        return set(
            range((parse(value["start"]) - first) // step, (parse(value["end"]) - first) // step)
        )

    needs = {slot: d["required_people"] for d in data["demand"] for slot in slots(d["interval"])}
    employees = {e["id"]: e for e in data["employees"]}
    best = None
    for bits in itertools.product((False, True), repeat=len(data["shift_candidates"])):
        selected = [c for c, bit in zip(data["shift_candidates"], bits, strict=True) if bit]
        intervals, working_days, coverage, minutes = (
            defaultdict(list),
            defaultdict(set),
            defaultdict(set),
            defaultdict(int),
        )
        valid = True
        for c in selected:
            employee = c["employee_id"]
            start = parse(c["segments"][0]["interval"]["start"])
            last = parse(c["segments"][-1]["interval"]["end"])
            day = start.astimezone(zone).date()
            valid &= day not in working_days[employee]
            working_days[employee].add(day)
            intervals[employee].append((start, last))
            for s in c["segments"]:
                work = slots(s["interval"]) - set().union(*(slots(b) for b in s["breaks"]))
                coverage[employee].update(work)
                minutes[employee] += len(work) * int(step.total_seconds() // 60)
            for constraint in data["constraints"]:
                if (
                    employee in constraint["employee_ids"]
                    and constraint["type"] == "min_split_gap_minutes"
                ):
                    valid &= all(
                        (
                            parse(b["interval"]["start"]) - parse(a["interval"]["end"])
                        ).total_seconds()
                        >= constraint["limit_minutes"] * 60
                        for a, b in zip(c["segments"], c["segments"][1:], strict=False)
                    )
        for employee in employees:
            duties = sorted(intervals[employee])
            valid &= all(a[1] <= b[0] for a, b in zip(duties, duties[1:], strict=False))
            for constraint in data["constraints"]:
                if employee not in constraint["employee_ids"]:
                    continue
                kind = constraint["type"]
                if kind == "max_scheduled_minutes":
                    valid &= minutes[employee] <= constraint["limit_minutes"]
                elif kind == "min_rest_minutes":
                    previous = employees[employee]["history"]["last_shift_end"]
                    previous = parse(previous) if previous else None
                    for start, last in duties:
                        valid &= (
                            previous is None
                            or (start - previous).total_seconds()
                            >= constraint["limit_minutes"] * 60
                        )
                        previous = last
                elif kind == "max_consecutive_days":
                    count = employees[employee]["history"]["consecutive_work_days_before_window"]
                    day = first.astimezone(zone).date()
                    while day < end.astimezone(zone).date():
                        count = count + 1 if day in working_days[employee] else 0
                        valid &= count <= constraint["limit_days"]
                        day += timedelta(days=1)
        valid &= all(
            sum(slot in row for row in coverage.values()) >= count for slot, count in needs.items()
        )
        if valid:
            value = sum(minutes.values())
            best = value if best is None else min(best, value)
    return best


@pytest.mark.parametrize("seed", range(24))
def test_extended_roster_matches_independent_small_enumeration(seed):
    rng = random.Random(seed)
    data = extended_request(days=2, employees=("alice", "bob"))
    data["shift_candidates"] = []
    for employee in data["employees"]:
        employee["availability"] = [interval(0, 0, 2880)]
        for i, segments in enumerate(
            [
                [segment(0, 1320, 1560, [(1380, 1410)] if rng.randrange(2) else [])],
                [segment(0, 1320, 1380)],
                [segment(1, 480, 540), segment(1, 720, 780)],
                [segment(1, 480, 540)],
            ]
        ):
            data["shift_candidates"].append(
                shift(segments, employee["id"], f"{employee['id']}_{i}")
            )
    data["demand"] = [
        demand(0, start, start + 30)
        for start in (1320, 1350, 1380, 1410, 1440, 1470, 1500, 1530, 1920, 1950, 2160, 2190)
        if rng.randrange(3) == 0
    ]
    data["constraints"] = [
        rule("max_scheduled_minutes", rng.choice([120, 240, 360]), ("alice", "bob")),
        rule("min_rest_minutes", rng.choice([0, 300, 660]), ("alice", "bob"), "rest"),
        rule("max_consecutive_days", rng.choice([1, 2]), ("alice", "bob"), "days"),
        rule("min_split_gap_minutes", rng.choice([0, 180, 181]), ("alice", "bob"), "gap"),
    ]
    if rng.randrange(2):
        data["employees"][0]["history"] = {
            "last_shift_end": stamp(),
            "last_work_day": "2026-10-04",
            "consecutive_work_days_before_window": 1,
        }
    expected = exhaustive_scheduled_value(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE" if expected is None else "OPTIMAL")
    if expected is not None:
        assert result["objectives"][0]["value"] == expected
