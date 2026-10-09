"""契約0.15の勤務開始日・完全休日・確定事実を公開境界で照合する。"""

import copy
import itertools
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import get_args, get_type_hints
from zoneinfo import ZoneInfo

import pytest
from jsonschema import Draft202012Validator

from shift_schedula import (
    InvalidInput,
    cp_sat,
    get_schema,
    make_baseline,
    solve,
    types,
    validate,
    verify,
)
from shift_schedula.contract import SCHEMA_VERSIONS, parse_datetime, schema_errors
from shift_schedula.engine import validate_response
from shift_schedula.extensions import evaluate
from shift_schedula.model import normalize
from tests.roster_support import demand, interval, request, stamp, template
from tests.support import assert_response
from tests.test_continuity import segment
from tests.test_objectives import control_search

ROOT = Path(__file__).resolve().parents[1]


def example(days=7, employees=("alice",)):
    data = request(days, employees)
    for employee in data["employees"]:
        employee["availability"] = [interval(0, 0, days * 1440)]
    return data


def bounds(data, kind="work_days_bounds", **limits):
    return {
        "id": kind,
        "type": kind,
        "employee_ids": [e["id"] for e in data["employees"]],
        "interval": {k: data["planning_window"][k] for k in ("start", "end")},
        **limits,
    }


def selected(candidate):
    return {
        "candidate_id": candidate["id"],
        "employee_id": candidate["employee_id"],
        "work_day": parse_datetime(candidate["segments"][0]["interval"]["start"])
        .astimezone(ZoneInfo("Asia/Tokyo"))
        .date()
        .isoformat(),
        "segments": copy.deepcopy(candidate["segments"]),
    }


def counts(result, index=0):
    return result["day_count_summary"][index]["employees"][0]


def continuity(data, first_day=0):
    data["continuity"] = {
        "context_window": {"start": stamp(first_day), "end": data["planning_window"]["end"]},
        "employees": [
            {
                "employee_id": e["id"],
                "before_context": e.pop("history"),
                "past_complete": True,
                "actual_shifts": [],
                "commitments_complete": True,
                "committed_shifts": [],
            }
            for e in data["employees"]
        ],
    }
    return data["continuity"]["employees"][0]


def test_same_minutes_can_require_two_work_days_and_legacy_stays_valid():
    data = example(2)
    data["shift_candidates"][0]["segments"] = [segment(stamp(0, 600), stamp(0, 840))]
    data["shift_candidates"][1]["segments"] = [segment(stamp(1, 600), stamp(1, 720))]
    data["shift_candidates"].append(
        {
            "id": "short_first",
            "employee_id": "alice",
            "segments": [segment(stamp(0, 600), stamp(0, 720))],
        }
    )
    data["constraints"] = [
        {
            "id": "minutes",
            "type": "scheduled_minutes_bounds",
            "employee_ids": ["alice"],
            "interval": interval(0, 0, 2880),
            "min_minutes": 240,
            "max_minutes": 240,
        },
        bounds(data, min_days=2, max_days=2),
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 240
    assert counts(result) == {
        "employee_id": "alice",
        "work_days": 2,
        "occupied_days": 2,
        "days_off": 0,
    }
    one_day = {"assignments": [], "shifts": [selected(data["shift_candidates"][0])]}
    checked = verify(data, one_day)
    assert checked["status"] == "INVALID_PLAN" and checked["day_count_summary"] is None
    violation = checked["diagnostics"][0]
    assert violation["json_pointer"] == "/constraints/1"
    assert violation["related_ids"] == ["work_days_bounds", "alice"]
    assert {f["name"]: f["value"] for f in violation["facts"]} == {
        "actual_value": 1,
        "min_days": 2,
        "max_days": 2,
    }
    data["schema_version"] = "0.10"
    data["constraints"].pop()
    assert verify(data, one_day)["status"] == "VALID"
    assert verify(data, result["solution"])["status"] == "VALID"


@pytest.mark.parametrize(
    "number,expected", [(2, "INVALID_PLAN"), (3, "VALID"), (4, "VALID"), (5, "INVALID_PLAN")]
)
def test_seven_day_bounds_validate_edited_plans(number, expected):
    data = example()
    data["constraints"] = [bounds(data, min_days=3, max_days=4)]
    checked = verify(
        data,
        {"assignments": [], "shifts": [selected(c) for c in data["shift_candidates"][:number]]},
    )
    assert checked["status"] == expected
    if expected == "VALID":
        assert counts(checked)["work_days"] == number
        assert counts(checked)["days_off"] == 7 - number
    else:
        assert checked["day_count_summary"] is None


@pytest.mark.parametrize("end,occupied", [(stamp(1, 360), 2), (stamp(1), 1)])
def test_night_end_at_midnight_does_not_occupy_next_day(end, occupied):
    data = example(3)
    data["shift_candidates"] = [
        {"id": "night", "employee_id": "alice", "segments": [segment(stamp(0, 1320), end)]}
    ]
    data["constraints"] = [
        bounds(data, min_days=1),
        bounds(data, "days_off_bounds", min_days=3 - occupied, max_days=3 - occupied),
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert counts(result) == {
        "employee_id": "alice",
        "work_days": 1,
        "occupied_days": occupied,
        "days_off": 3 - occupied,
    }
    assert verify(data, result["solution"])["day_count_summary"] == result["day_count_summary"]


@pytest.mark.parametrize("split", [False, True])
def test_year_end_split_gap_is_off_but_full_day_break_is_occupied(split):
    data = example(4)
    start, end = "2026-12-30T00:00:00+09:00", "2027-01-03T00:00:00+09:00"
    data["planning_window"].update(start=start, end=end)
    data["employees"][0]["availability"] = [{"start": start, "end": end}]
    a, b = "2026-12-31T00:00:00+09:00", "2027-01-01T00:00:00+09:00"
    spans = [segment(start, a), segment(b, end)] if split else [segment(start, end, [(a, b)])]
    data["shift_candidates"] = [{"id": "long", "employee_id": "alice", "segments": spans}]
    data["constraints"] = [
        bounds(data, min_days=1),
        bounds(data, "days_off_bounds", min_days=int(split), max_days=int(split)),
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert counts(result)["work_days"] == 1
    assert counts(result)["occupied_days"] == 4 - int(split)
    assert counts(result)["days_off"] == int(split)


def test_confirmed_past_and_selected_days_count_once_with_independent_verification(monkeypatch):
    data = example()
    row = continuity(data)
    data["planning_window"]["start"] = stamp(2)
    row["actual_shifts"] = [
        {"id": f"past{d}", "segments": [segment(stamp(d, 600), stamp(d, 690))]} for d in (0, 1)
    ]
    data["shift_candidates"] = data["shift_candidates"][2:]
    rule = bounds(data, min_days=3, max_days=3)
    rule["interval"]["start"] = stamp()
    data["constraints"] = [rule]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(result["solution"]["shifts"]) == 1
    assert counts(result)["work_days"] == 3
    problem = normalize(data)
    problem.candidates = []
    problem.continuity = []
    assert (
        evaluate(problem, result["solution"])[2]["day_count_summary"] == result["day_count_summary"]
    )
    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("独立検証は探索しない"))
    checked = verify(data, result["solution"])
    assert checked["status"] == "VALID" and counts(checked)["work_days"] == 3
    assert not checked["shortage_summary"]["proven_minimal"]
    changed = copy.deepcopy(result["solution"])
    used = {s["candidate_id"] for s in changed["shifts"]}
    changed["shifts"].append(
        selected(next(c for c in data["shift_candidates"] if c["id"] not in used))
    )
    assert verify(data, changed)["status"] == "INVALID_PLAN"


@pytest.mark.parametrize(
    "start,end,work,occupied",
    [(stamp(0, 1320), stamp(1, 360), 0, 1), (stamp(1, 1320), stamp(2, 360), 1, 2)],
)
def test_boundary_commitment_start_day_and_occupancy_are_distinct(start, end, work, occupied):
    data = example(4)
    row = continuity(data)
    data["planning_window"]["start"] = stamp(1)
    row["committed_shifts"] = [{"id": "fixed", "segments": [segment(start, end)]}]
    data["shift_candidates"] = []
    data["constraints"] = [
        bounds(data, min_days=work, max_days=work),
        bounds(data, "days_off_bounds", min_days=3 - occupied),
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(result["solution"]["shifts"]) == 1
    assert counts(result)["work_days"] == work
    assert counts(result)["occupied_days"] == occupied
    assert verify(data, result["solution"])["day_count_summary"] == result["day_count_summary"]


@pytest.mark.parametrize("kind", ["work_days_bounds", "days_off_bounds"])
def test_hard_conflict_refinement_keeps_commitment_and_does_not_return_partial(kind):
    data = example(2)
    row = continuity(data)
    row["committed_shifts"] = [{"id": "fixed", "segments": [segment(stamp(0, 600), stamp(0, 690))]}]
    data["constraints"] = [
        bounds(data, kind, **({"max_days": 0} if kind == "work_days_bounds" else {"min_days": 2}))
    ]
    data["diagnosis"] = {
        "time_limit_seconds": 10,
        "max_suggestions": 0,
        "allowed_changes": [],
        "conflict_refinement": {"time_limit_seconds": 5},
    }
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    assert result["day_count_summary"] is None
    conflict = result["diagnosis_result"]["conflict"]
    assert conflict["minimality"] == "inclusion_minimal"
    assert [c["json_pointer"] for c in conflict["conditions"]] == ["/constraints/0"]
    assert any(
        c["json_pointer"].endswith("/committed_shifts/0") for c in conflict["background_conditions"]
    )


@pytest.mark.parametrize("kind", ["work_days_bounds", "days_off_bounds"])
def test_unreachable_valid_lower_bound_is_infeasible(kind):
    data = example(2)
    data["constraints"] = [bounds(data, kind, min_days=10000000)]
    assert validate(data)["status"] == "VALID"
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize(
    "first,last,shift_start,shift_end",
    [
        (
            "2026-03-23T00:00:00+01:00",
            "2026-03-30T00:00:00+02:00",
            "2026-03-29T00:00:00+01:00",
            "2026-03-30T00:00:00+02:00",
        ),
        (
            "2026-10-19T00:00:00+02:00",
            "2026-10-26T00:00:00+01:00",
            "2026-10-25T00:00:00+02:00",
            "2026-10-26T00:00:00+01:00",
        ),
    ],
)
def test_dst_week_counts_local_dates_not_elapsed_24_hours(first, last, shift_start, shift_end):
    data = example()
    data["planning_window"].update(start=first, end=last, timezone="Europe/Berlin", slot_minutes=60)
    data["employees"][0]["availability"] = [{"start": first, "end": last}]
    data["shift_candidates"] = [
        {"id": "dst", "employee_id": "alice", "segments": [segment(shift_start, shift_end)]}
    ]
    data["constraints"] = [
        bounds(data, min_days=1),
        bounds(data, "days_off_bounds", min_days=6, max_days=6),
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert counts(result) == {
        "employee_id": "alice",
        "work_days": 1,
        "occupied_days": 1,
        "days_off": 6,
    }


@pytest.mark.parametrize(
    "field,value",
    [("min_days", v) for v in (None, True, False, 1.0, 1.5, -1, 10000001)]
    + [("max_days", None), ("max_days", True)],
)
def test_day_integer_boundaries_reject_invalid_types(field, value):
    data = example()
    data["constraints"] = [bounds(data, **{field: value})]
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "empty_ids",
        "duplicate_ids",
        "unknown_id",
        "duplicate_rule",
        "missing_bound",
        "reversed_bounds",
        "non_midnight",
        "reversed_interval",
        "precision",
        "past",
        "future",
        "past_unconfirmed",
        "missing_actual",
        "before_context",
    ],
)
def test_invalid_rules_and_unconfirmed_ranges_are_rejected(mutation):
    data = example()
    rule = bounds(data, min_days=1)
    data["constraints"] = [rule]
    if mutation == "unknown_field":
        rule["label"] = "不明"
    elif mutation == "empty_ids":
        rule["employee_ids"] = []
    elif mutation == "duplicate_ids":
        rule["employee_ids"] *= 2
    elif mutation == "unknown_id":
        rule["employee_ids"] = ["ghost"]
    elif mutation == "duplicate_rule":
        data["constraints"].append(copy.deepcopy(rule))
    elif mutation == "missing_bound":
        rule.pop("min_days")
    elif mutation == "reversed_bounds":
        rule.update(min_days=2, max_days=1)
    elif mutation == "non_midnight":
        rule["interval"]["start"] = stamp(0, 30)
    elif mutation == "reversed_interval":
        rule["interval"]["end"] = rule["interval"]["start"]
    elif mutation == "precision":
        rule["interval"]["start"] = "2026-10-05T00:00:00.0000001+09:00"
    elif mutation == "past":
        rule["interval"]["start"] = stamp(-1)
    elif mutation == "future":
        continuity(data)
        data["continuity"]["context_window"]["end"] = stamp(8)
        rule["interval"]["end"] = stamp(8)
    else:
        row = continuity(data)
        if mutation == "past_unconfirmed":
            row["past_complete"] = False
        elif mutation == "missing_actual":
            row.pop("actual_shifts")
        else:
            rule["interval"]["start"] = stamp(-1)
    assert_response(solve(data), "INVALID_INPUT")
    if mutation in {"past", "past_unconfirmed", "missing_actual", "before_context"}:
        assert validate(data)["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"


@pytest.mark.parametrize("mode", ["preserve_assigned", "explicit", "rebuild"])
def test_baseline_roundtrip_keeps_rules_and_fixed_work(mode):
    data = example(2)
    data["demand"] = [demand()]
    data["constraints"] = [bounds(data, min_days=1, max_days=1)]
    original = solve(data)
    assert_response(original, "OPTIMAL")
    baseline = make_baseline(data, original["solution"], "saved")
    assert baseline["source_request"]["constraints"] == data["constraints"]
    data["baseline"] = baseline
    data["constraints"] = [bounds(data, "days_off_bounds", min_days=2)]
    if mode == "explicit":
        data["fixed_parts"] = [
            {
                "id": "fixed",
                "employee_id": "alice",
                "interval": interval(),
                "components": ["work", "role"],
            }
        ]
    else:
        data["replan_mode"] = mode
    result = solve(data)
    assert_response(result, "PARTIAL" if mode == "rebuild" else "INFEASIBLE")
    if mode == "rebuild":
        assert counts(result)["days_off"] == 2
    broken = copy.deepcopy(baseline)
    broken["source_solution"]["shifts"] = []
    assert validate({**data, "baseline": broken})["status"] == "INVALID_INPUT"
    old = example(2)
    old["schema_version"] = "0.10"
    assert (
        validate({**old, "baseline": baseline})["diagnostics"][0]["code"]
        == "UNSUPPORTED_BASELINE_VERSION"
    )
    old_result = solve(old)
    assert (
        validate({**example(2), "baseline": make_baseline(old, old_result["solution"], "old")})[
            "status"
        ]
        == "VALID"
    )


@pytest.mark.parametrize(
    "min_work,max_work,min_off,max_off",
    [(0, 3, 0, 3), (1, 2, 1, 2), (2, 2, 1, 1), (0, 0, 3, 3), (3, 3, 0, 0), (4, 4, 0, 3)],
)
def test_small_candidate_subsets_match_independent_exhaustive_counts(
    min_work, max_work, min_off, max_off
):
    data = example(3)
    data["shift_candidates"][0]["segments"] = [segment(stamp(0, 1320), stamp(1, 360))]
    data["shift_candidates"].append(
        {
            "id": "split",
            "employee_id": "alice",
            "segments": [
                segment(stamp(0, 600), stamp(0, 660)),
                segment(stamp(2, 600), stamp(2, 660)),
            ],
        }
    )
    data["constraints"] = [
        bounds(data, min_days=min_work, max_days=max_work),
        bounds(data, "days_off_bounds", min_days=min_off, max_days=max_off),
    ]
    data["demand"] = [demand(1), demand(2)]
    zone = ZoneInfo("Asia/Tokyo")
    possible = []
    for flags in itertools.product((False, True), repeat=4):
        chosen = [c for c, flag in zip(data["shift_candidates"], flags, strict=True) if flag]
        spans = [
            (
                parse_datetime(c["segments"][0]["interval"]["start"]),
                parse_datetime(c["segments"][-1]["interval"]["end"]),
            )
            for c in chosen
        ]
        work = {a.astimezone(zone).date() for a, _ in spans}
        valid = len(work) == len(chosen) and all(
            b <= x or y <= a for (a, b), (x, y) in itertools.combinations(spans, 2)
        )
        occupied = set()
        for d in range(3):
            a, b = parse_datetime(stamp(d)), parse_datetime(stamp(d + 1))
            if any(
                parse_datetime(s["interval"]["start"]) < b
                and a < parse_datetime(s["interval"]["end"])
                for c in chosen
                for s in c["segments"]
            ):
                occupied.add(d)
        valid &= min_work <= len(work) <= max_work and min_off <= 3 - len(occupied) <= max_off
        plan = {"assignments": [], "shifts": [selected(c) for c in chosen]}
        if valid:
            for d in (1, 2):
                if any(
                    parse_datetime(s["interval"]["start"]) <= parse_datetime(stamp(d, 600))
                    and parse_datetime(stamp(d, 630)) <= parse_datetime(s["interval"]["end"])
                    for c in chosen
                    for s in c["segments"]
                ):
                    plan["assignments"].append(
                        {
                            "employee_id": "alice",
                            "role_id": "kitchen",
                            "interval": interval(d, 600, 630),
                        }
                    )
        checked = verify(data, plan)
        assert (checked["status"] in {"VALID", "PARTIAL"}) == valid
        if valid:
            assert counts(checked)["work_days"] == len(work)
            assert counts(checked)["occupied_days"] == len(occupied)
            possible.append(
                (
                    checked["shortage_summary"]["total_person_minutes"],
                    checked["objectives"][0]["value"],
                )
            )
    result = solve(data)
    if not possible:
        assert_response(result, "INFEASIBLE")
    else:
        assert result["verification"]["valid"]
        assert (
            result["shortage_summary"]["total_person_minutes"],
            result["objectives"][0]["value"],
        ) == min(possible)


def test_template_generation_and_summary_tampering():
    data = example()
    data["shift_candidates"] = []
    data["shift_templates"] = [template(dates=tuple(stamp(d)[:10] for d in range(7)))]
    data["constraints"] = [bounds(data, min_days=3, max_days=4)]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert counts(result)["work_days"] == 3
    counts(result)["occupied_days"] += 1
    with pytest.raises(InvalidInput):
        validate_response(result, data)


@pytest.mark.parametrize("statuses", [("UNKNOWN",), ("FEASIBLE",), ("OPTIMAL", "UNKNOWN")])
def test_shared_budget_and_unproven_prefix_are_preserved(monkeypatch, statuses):
    data = example()
    data["constraints"] = [bounds(data, min_days=3)]
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "UNKNOWN" if statuses == ("UNKNOWN",) else "FEASIBLE")
    assert len(calls) == len(statuses)
    assert (
        result["day_count_summary"] is None
        if statuses == ("UNKNOWN",)
        else counts(result)["work_days"] == 3
    )
    assert all(not o["proven_optimal"] for o in result["objectives"])


@pytest.mark.parametrize(
    "version", [v for v in SCHEMA_VERSIONS if v not in {"0.11", "0.12", "0.13", "0.14", "0.15"}]
)
def test_legacy_rejects_new_fields(version):
    data = example()
    data["schema_version"] = version
    data["constraints"] = [bounds(data, min_days=1)]
    assert_response(solve(data), "INVALID_INPUT")


def test_diagnosis_edits_and_assignment_do_not_accept_day_conditions():
    data = example()
    data["constraints"] = [bounds(data, min_days=1)]
    data["diagnosis"] = {
        "time_limit_seconds": 1,
        "max_suggestions": 1,
        "allowed_changes": [
            {"id": "edit", "edits": [{"json_pointer": "/constraints/0/min_days", "value": 0}]}
        ],
    }
    assert validate(data)["diagnostics"][0]["code"] == "UNSUPPORTED_DIAGNOSIS_EDIT"
    data.pop("diagnosis")
    data["problem_type"] = "assignment"
    data["shift_candidates"] = []
    for e in data["employees"]:
        e.pop("history")
    data["objectives"] = [{"id": "wishes", "metric": "preference_penalty"}]
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("version", ["0.11", "0.15"])
def test_cli_and_schemas_cover_success_and_missing_plan(tmp_path, version):
    data = example()
    data["schema_version"] = version
    data["constraints"] = [
        bounds(data, min_days=3, max_days=4),
        bounds(data, "days_off_bounds", min_days=3),
    ]
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(data))
    result = solve(data)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(result["solution"]))
    for args, code in [
        (["solve", str(request_path)], 0),
        (["verify", str(request_path), str(plan)], 0),
        (["verify", str(request_path), str(tmp_path / "missing")], 2),
    ]:
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", *args], capture_output=True, text=True
        )
        assert completed.returncode == code, completed.stderr
        response = json.loads(completed.stdout)
        assert not schema_errors(
            "response" if args[0] == "solve" else "verification", response, version
        )
        if code == 0:
            assert response["day_count_summary"] == result["day_count_summary"]
        else:
            assert response["day_count_summary"] is None
    for kind in ("request", "response", "solution", "verification"):
        schema = get_schema(kind, version)
        Draft202012Validator.check_schema(schema)
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", version],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == schema
    request_type = types.Request011 if version == "0.11" else types.Request015
    assert request_type.__required_keys__ == set(get_schema("request", version)["required"])
    assert set(get_type_hints(request_type)) == set(get_schema("request", version)["properties"])
    assert get_args(get_type_hints(request_type)["schema_version"]) == (version,)


def test_month_eight_days_off_and_untouched_employee_zero_work():
    data = example(31, ("alice", "bob"))
    data["shift_candidates"] = [c for c in data["shift_candidates"] if c["employee_id"] == "alice"]

    # 既存のfixtureを月初へ4日戻す。月末の00:00も半開境界として保持する。
    def moved(value):
        return (datetime.fromisoformat(value) - timedelta(days=4)).isoformat()

    for key in ("start", "end"):
        data["planning_window"][key] = moved(data["planning_window"][key])
    for employee in data["employees"]:
        for value in employee["availability"]:
            for key in ("start", "end"):
                value[key] = moved(value[key])
    for candidate in data["shift_candidates"]:
        for value in candidate["segments"]:
            for key in ("start", "end"):
                value["interval"][key] = moved(value["interval"][key])
    work = bounds(data, min_days=23)
    work["employee_ids"] = ["alice"]
    data["constraints"] = [work, bounds(data, "days_off_bounds", min_days=8)]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert counts(result)["work_days"] == 23
    assert counts(result)["days_off"] == 8
    assert result["day_count_summary"][1]["employees"][1] == {
        "employee_id": "bob",
        "work_days": 0,
        "occupied_days": 0,
        "days_off": 31,
    }


def test_work_start_after_evaluation_and_overlapping_occupied_days_count_once():
    data = example(3)
    data["shift_candidates"] = [
        {
            "id": "night",
            "employee_id": "alice",
            "segments": [segment(stamp(0, 1320), stamp(1, 360))],
        },
        {"id": "next", "employee_id": "alice", "segments": [segment(stamp(1, 600), stamp(1, 660))]},
        {
            "id": "after",
            "employee_id": "alice",
            "segments": [segment(stamp(2, 600), stamp(2, 660))],
        },
    ]
    data["constraints"] = [bounds(data, min_days=3), bounds(data, "days_off_bounds", max_days=0)]
    data["constraints"][1]["interval"]["end"] = stamp(2)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert counts(result, 1) == {
        "employee_id": "alice",
        "work_days": 2,
        "occupied_days": 2,
        "days_off": 0,
    }
    assert verify(data, result["solution"])["day_count_summary"] == result["day_count_summary"]


def test_day_counts_inherit_history_duty_costs_and_priority_objectives():
    from tests.test_continuity_duty_balance import example as history_example

    data = history_example()
    data["constraints"].append(bounds(data, max_days=1))
    data["constraints"].append(bounds(data, "days_off_bounds", max_days=1))
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["duty_balance_summary"][0]["total_deviation_minutes"] == 0
    assert result["cost_summary"]["total_units"] == 432000
    assert result["priority_summary"]["groups"][0]["proven_minimal"]
    assert verify(data, result["solution"])["day_count_summary"] == result["day_count_summary"]


@pytest.mark.parametrize("minimum", [0, 1, 2])
def test_day_bounds_keep_mandatory_demand_and_independent_verification(monkeypatch, minimum):
    data = example(2)
    data["demand"] = [demand(people=2) | {"minimum_people": minimum}]
    data["constraints"] = [bounds(data, min_days=1, max_days=1)]
    saved = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE" if minimum == 2 else "PARTIAL")
    if minimum < 2:
        assert result["shortage_summary"]["total_person_minutes"] == 30
        assert counts(result)["work_days"] == 1
        monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("独立検証は探索しない"))
        checked = verify(data, result["solution"])
        assert checked["day_count_summary"] == result["day_count_summary"]
        assert not checked["shortage_summary"]["proven_minimal"]
        damaged = copy.deepcopy(result["solution"])
        damaged["assignments"] = []
        assert verify(data, damaged)["status"] == ("INVALID_PLAN" if minimum else "PARTIAL")
    assert data == saved
