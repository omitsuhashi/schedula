import copy
import itertools
import json
import random
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shift_schedula import InvalidInput, get_schema, make_baseline, solve, validate, verify
from shift_schedula.engine import validate_response
from shift_schedula.model import normalize
from shift_schedula.verify import verify_plan
from tests.roster_support import rule
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def example(name="month"):
    return json.loads((ROOT / f"examples/continuity_{name}.json").read_text(encoding="utf-8"))


def stamp(day, clock="00:00"):
    return f"2026-{day}T{clock}:00+09:00"


def segment(a, b, rests=()):
    return {
        "interval": {"start": a, "end": b},
        "breaks": [{"start": x, "end": y} for x, y in rests],
    }


def row(data):
    return data["continuity"]["employees"][0]


def solution(data):
    result = solve(data)
    assert result["solution"] is not None, result
    return result["solution"]


def test_month_and_week_examples_preserve_intervals_and_recompute():
    for name, status, totals, shortage in (
        ("month", "OPTIMAL", (120, 300, 60), 0),
        ("week", "PARTIAL", (960, 1440, 0), 480),
    ):
        data = example(name)
        saved = copy.deepcopy(data)
        assert validate(data)["status"] == "VALID"
        result = solve(data)
        assert_response(result, status)
        assert data == saved
        summary = result["continuity_summary"]["employees"][0]
        assert (
            tuple(
                summary[k]
                for k in ("historical_minutes", "planned_minutes", "outside_planning_minutes")
            )
            == totals
        )
        assert result["shortage_summary"]["total_person_minutes"] == shortage
        assert result["objectives"][0]["value"] == totals[1]
        checked = verify(data, result["solution"])
        assert checked["status"] == ("VALID" if not shortage else "PARTIAL")
        assert checked["continuity_summary"] == result["continuity_summary"]
        assert not checked["shortage_summary"]["proven_minimal"]
        assert all(not o["proven_optimal"] for o in checked["objectives"])
        snapshot = make_baseline(data, result["solution"], "saved")
        assert snapshot["source_request"] == data
        assert validate({**data, "baseline": snapshot})["status"] == "VALID"
    duty = next(s for s in solution(example())["shifts"] if s["committed_shift_id"] == "night")
    assert duty["segments"] == row(example())["committed_shifts"][0]["segments"]
    assert duty["work_day"] == "2026-10-31"
    assert len(solution(example())["shifts"]) == 1


@pytest.mark.parametrize(
    "field",
    [
        "before_context",
        "past_complete",
        "actual_shifts",
        "commitments_complete",
        "committed_shifts",
    ],
)
def test_missing_history_is_not_zero_filled(field):
    data = example()
    del row(data)[field]
    assert solve(data)["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("duplicate_id", "CONFLICTING_CONTINUITY"),
        ("duplicate_day", "CONFLICTING_CONTINUITY"),
        ("overlap", "CONFLICTING_CONTINUITY"),
        ("actual_after_start", "INVALID_CONTINUITY_INTERVAL"),
        ("outside_context", "INVALID_CONTINUITY_INTERVAL"),
        ("anchor", "INVALID_CONTINUITY_INTERVAL"),
        ("history", "CONFLICTING_CONTINUITY"),
        ("missing_employee", "INCOMPLETE_HISTORY"),
    ],
)
def test_contradictory_facts_are_input_errors(mutation, code):
    data = example("week")
    r = row(data)
    if mutation == "duplicate_id":
        r["committed_shifts"] = [
            {
                "id": r["actual_shifts"][0]["id"],
                "segments": [segment(stamp("10-07", "09:00"), stamp("10-07", "10:00"))],
            }
        ]
    elif mutation == "duplicate_day":
        r["actual_shifts"].append(
            {"id": "other", "segments": [segment(stamp("10-05", "18:00"), stamp("10-05", "19:00"))]}
        )
    elif mutation == "overlap":
        r["actual_shifts"][0]["segments"][0]["interval"]["end"] = stamp("10-06", "10:00")
    elif mutation == "actual_after_start":
        r["actual_shifts"][-1]["segments"][0]["interval"]["end"] = stamp("10-07", "01:00")
    elif mutation == "outside_context":
        r["committed_shifts"] = [
            {"id": "outside", "segments": [segment(stamp("10-12"), stamp("10-12", "01:00"))]}
        ]
    elif mutation == "anchor":
        r["before_context"] = {
            "last_shift_end": stamp("10-05", "10:00"),
            "last_work_day": "2026-10-04",
            "consecutive_work_days_before_window": 1,
        }
    elif mutation == "history":
        data["employees"][0]["history"] = r["before_context"]
    else:
        data["continuity"]["employees"] = []
    assert_response(solve(data), "INVALID_INPUT")
    assert validate(data)["diagnostics"][0]["code"] == code


@pytest.mark.parametrize(
    "ending,limit,chosen", [("21:00", 3, True), ("21:30", 3, False), ("21:00", 2, False)]
)
def test_rest_to_future_commitment_and_future_consecutive_days(ending, limit, chosen):
    data = example()
    data["shift_candidates"] = [
        {
            "id": "evening",
            "employee_id": "alice",
            "segments": [segment(stamp("11-01", "17:00"), stamp("11-01", ending))],
        }
    ]
    data["demand"].append(
        {
            "id": "evening_need",
            "role_id": "kitchen",
            "interval": {"start": stamp("11-01", "17:00"), "end": stamp("11-01", "21:00")},
            "required_people": 1,
        }
    )
    data["constraints"][1]["limit_days"] = limit
    result = solve(data)
    assert_response(result, "OPTIMAL" if chosen else "PARTIAL")
    assert any("candidate_id" in s for s in result["solution"]["shifts"]) == chosen
    if not chosen:
        forced = copy.deepcopy(result["solution"])
        forced["shifts"].append(
            {
                "candidate_id": "evening",
                "employee_id": "alice",
                "work_day": "2026-11-01",
                "segments": data["shift_candidates"][0]["segments"],
            }
        )
        assert verify(data, forced)["status"] == "INVALID_PLAN"


def test_valid_rules_conflicting_with_facts_are_infeasible():
    data = example()
    data["employees"][0]["availability"] = []
    assert validate(data)["status"] == "VALID"
    assert_response(solve(data), "INFEASIBLE")
    data = example("week")
    data["constraints"][0]["max_minutes"] = 900
    assert_response(solve(data), "INFEASIBLE")
    data["diagnosis"] = {"time_limit_seconds": 5, "max_suggestions": 0, "allowed_changes": []}
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conditions = result["diagnosis_result"]["conflict"]["conditions"]
    assert any(c["code"] == "ACTUAL_SHIFT_BACKGROUND" for c in conditions)


def test_past_rules_are_not_retroactive_and_anchor_connects_to_new_work():
    data = example("week")
    data["constraints"] = [
        rule("max_consecutive_days", 1),
        rule("min_rest_minutes", 2000, identifier="rest"),
    ]
    data["demand"] = []
    assert_response(solve(data), "OPTIMAL")
    data["constraints"] = [rule("min_rest_minutes", 660)]
    row(data)["actual_shifts"] = []
    row(data)["before_context"] = {
        "last_shift_end": stamp("10-05"),
        "last_work_day": "2026-10-04",
        "consecutive_work_days_before_window": 1,
    }
    row(data)["committed_shifts"] = [
        {"id": "cross", "segments": [segment(stamp("10-05", "10:30"), stamp("10-07", "01:00"))]}
    ]
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "id", "day", "break", "segment"])
def test_tampering_is_detected_without_solver_tables(mutation):
    data = example()
    out = solution(data)
    if mutation == "missing":
        out["shifts"] = []
    elif mutation == "duplicate":
        out["shifts"].append(copy.deepcopy(out["shifts"][0]))
    elif mutation == "id":
        out["shifts"][0]["committed_shift_id"] = "unknown"
    elif mutation == "day":
        out["shifts"][0]["work_day"] = "2026-11-01"
    elif mutation == "break":
        out["shifts"][0]["segments"][0]["breaks"] = []
    else:
        out["shifts"][0]["segments"][0]["interval"]["end"] = stamp("11-01", "07:00")
    problem = normalize(data)
    problem.candidates.clear()
    problem.continuity.clear()
    assert verify_plan(problem, out)[0]
    assert verify(data, out)["status"] == "INVALID_PLAN"


def test_split_shift_gap_only_overlap_and_dst_minutes():
    data = example()
    data["constraints"] = []
    data["demand"] = []
    row(data)["committed_shifts"] = [
        {
            "id": "split",
            "segments": [
                segment(stamp("10-31", "23:00"), stamp("11-01", "01:00")),
                segment(stamp("11-01", "03:00"), stamp("11-01", "05:00")),
            ],
        }
    ]
    result = solve(data)
    s = result["continuity_summary"]["employees"][0]
    assert (s["historical_minutes"], s["planned_minutes"]) == (60, 180)
    row(data)["committed_shifts"][0]["segments"] = [
        segment(stamp("10-31", "22:00"), stamp("10-31", "23:00")),
        segment(stamp("11-02", "01:00"), stamp("11-02", "02:00")),
    ]
    result = solve(data)
    assert len(result["solution"]["shifts"]) == 1
    assert result["objectives"][0]["value"] == 0
    assert_response(result, "OPTIMAL")
    data["planning_window"] = {
        "start": "2026-10-25T00:00:00+02:00",
        "end": "2026-10-26T00:00:00+01:00",
        "timezone": "Europe/Berlin",
        "slot_minutes": 30,
    }
    data["continuity"]["context_window"] = {
        "start": "2026-10-24T00:00:00+02:00",
        "end": "2026-10-27T00:00:00+01:00",
    }
    data["employees"][0]["availability"] = [
        {k: data["continuity"]["context_window"][k] for k in ("start", "end")}
    ]
    row(data)["committed_shifts"] = [
        {
            "id": "dst",
            "segments": [
                segment(
                    "2026-10-25T01:00:00+02:00",
                    "2026-10-25T04:00:00+01:00",
                    [("2026-10-25T02:00:00+02:00", "2026-10-25T02:30:00+02:00")],
                )
            ],
        }
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 210
    assert verify(data, result["solution"])["status"] == "VALID"


def test_new_candidate_crosses_end_without_rounding_outside_minutes():
    data = example()
    row(data)["committed_shifts"] = []
    data["constraints"] = []
    data["demand"] = [
        {
            "id": "late",
            "role_id": "kitchen",
            "interval": {"start": stamp("11-01", "23:00"), "end": stamp("11-02")},
            "required_people": 1,
        }
    ]
    data["shift_candidates"] = [
        {
            "id": "late",
            "employee_id": "alice",
            "segments": [
                segment(
                    stamp("11-01", "23:00"),
                    stamp("11-02", "01:17"),
                    [(stamp("11-02", "00:11"), stamp("11-02", "00:23"))],
                )
            ],
        }
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["solution"]["shifts"][0]["segments"] == data["shift_candidates"][0]["segments"]
    assert result["continuity_summary"]["employees"][0]["outside_planning_minutes"] == 65
    assert result["objectives"][0]["value"] == 60
    old = copy.deepcopy(data)
    old["schema_version"] = "0.4"
    del old["continuity"]
    old["employees"][0]["history"] = {
        "last_shift_end": None,
        "last_work_day": None,
        "consecutive_work_days_before_window": 0,
    }
    old["employees"][0]["availability"] = [{k: old["planning_window"][k] for k in ("start", "end")}]
    assert_response(solve(old), "INVALID_INPUT")
    for version in ("0.1", "0.2", "0.3", "0.4"):
        assert_response(solve({**data, "schema_version": version}), "INVALID_INPUT")


def test_fairness_preferences_and_fixed_states_include_committed_work():
    data = example()
    data["fairness"] = {
        "evaluation_period": {k: data["planning_window"][k] for k in ("start", "end")},
        "employee_targets": [{"employee_id": "alice", "target_minutes": 300}],
    }
    data["preferences"] = [
        {
            "id": "avoid",
            "type": "avoid_work",
            "employee_ids": ["alice"],
            "interval": {"start": stamp("11-01"), "end": stamp("11-01", "02:00")},
            "penalty_per_minute": 2,
        }
    ]
    data["objectives"] = [
        {"id": "pref", "metric": "preference_penalty"},
        {"id": "fair", "metric": "fairness_deviation_minutes"},
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [o["value"] for o in result["objectives"]] == [240, 0]
    data["baseline"] = make_baseline(data, result["solution"], "saved")
    data["replan_mode"] = "preserve_assigned"
    assert_response(solve(data), "OPTIMAL")
    row(data)["committed_shifts"][0]["segments"][0]["breaks"] = []
    assert_response(solve(data), "OPTIMAL")  # 固定は担当済み枠だけで休憩枠を固定しない。
    data["fixed_parts"] = [
        {
            "id": "rest",
            "employee_id": "alice",
            "interval": {"start": stamp("11-01", "02:00"), "end": stamp("11-01", "03:00")},
            "components": ["work"],
        }
    ]
    assert_response(solve(data), "INFEASIBLE")


def test_cli_schemas_and_summary_tampering(tmp_path):
    data = example()
    result = solve(data)
    broken = copy.deepcopy(result)
    broken["continuity_summary"]["employees"][0]["historical_minutes"] += 1
    with pytest.raises(InvalidInput):
        validate_response(broken, data)
    path = tmp_path / "solution.json"
    path.write_text(json.dumps(result["solution"]), encoding="utf-8")
    for command, args in [
        ("solve", [str(ROOT / "examples/continuity_month.json")]),
        ("verify", [str(ROOT / "examples/continuity_month.json"), str(path)]),
    ]:
        p = subprocess.run(
            [sys.executable, "-m", "shift_schedula", command, *args], capture_output=True, text=True
        )
        assert p.returncode == 0, p.stdout + p.stderr
        assert json.loads(p.stdout)["continuity_summary"] == result["continuity_summary"]
    for kind in ("request", "response", "solution", "verification"):
        assert get_schema(kind, "0.6")["$id"] == f"urn:schedula:{kind}:0.6"


@pytest.mark.parametrize("seed", range(12))
def test_small_enumeration_matches_shortage_then_work(seed):
    # 元JSONの時刻と休憩だけから全列挙する。モデル・候補投影・検証器を使わない。
    rng = random.Random(seed)
    data = example()
    data["constraints"] = [
        rule("min_rest_minutes", rng.choice([0, 660])),
        rule("max_consecutive_days", rng.choice([2, 3]), identifier="days"),
    ]
    data["shift_candidates"] = [
        {
            "id": f"choice_{i}",
            "employee_id": "alice",
            "segments": [segment(stamp("11-01", a), stamp("11-01", b))],
        }
        for i, (a, b) in enumerate([("16:30", "21:00"), ("17:00", "21:00"), ("17:00", "21:30")])
    ]
    data["demand"].append(
        {
            "id": "evening",
            "role_id": "kitchen",
            "interval": {"start": stamp("11-01", "17:00"), "end": stamp("11-01", "21:00")},
            "required_people": 1,
        }
    )

    def parse(value):
        return datetime.fromisoformat(value).astimezone(UTC)

    start = parse(data["planning_window"]["start"])
    needs = {start + timedelta(minutes=i * 30): 0 for i in range(48)}
    for d in data["demand"]:
        a, b = map(parse, (d["interval"]["start"], d["interval"]["end"]))
        for slot in needs:
            if a <= slot < b:
                needs[slot] += d["required_people"]
    best = None
    for flags in itertools.product((False, True), repeat=3):
        duties = row(data)["committed_shifts"] + [
            c for c, flag in zip(data["shift_candidates"], flags, strict=True) if flag
        ]
        spans = sorted(
            (
                parse(d["segments"][0]["interval"]["start"]),
                parse(d["segments"][-1]["interval"]["end"]),
            )
            for d in duties
        )
        days = sorted(
            a.astimezone(datetime.fromisoformat(stamp("11-01")).tzinfo).date() for a, _ in spans
        )
        if len(set(days)) != len(days):
            continue
        if any(
            (b[0] - a[1]).total_seconds() < data["constraints"][0]["limit_minutes"] * 60
            for a, b in zip(spans, spans[1:], strict=False)
        ):
            continue
        count, longest, previous = 0, 0, None
        for day in days:
            count = count + 1 if previous is not None and day == previous + timedelta(days=1) else 1
            longest, previous = max(longest, count), day
        if longest > data["constraints"][1]["limit_days"]:
            continue
        coverage, work = set(), 0
        for d in duties:
            for s in d["segments"]:
                a, b = map(parse, (s["interval"]["start"], s["interval"]["end"]))
                rest = [(parse(r["start"]), parse(r["end"])) for r in s["breaks"]]
                for slot in needs:
                    if a <= slot < b and not any(x <= slot < y for x, y in rest):
                        coverage.add(slot)
                        work += 30
        shortage = sum(max(0, need - (slot in coverage)) * 30 for slot, need in needs.items())
        value = shortage, work
        best = min(best, value) if best is not None else value
    result = solve(data)
    assert (
        result["shortage_summary"]["total_person_minutes"],
        result["objectives"][0]["value"],
    ) == best
    assert result["shortage_summary"]["proven_minimal"]
    assert verify(data, result["solution"])["status"] in {"VALID", "PARTIAL"}


def test_same_fixed_timeline_matches_full_and_split_verification():
    second = example("week")
    selected = solution(second)["shifts"]
    duties = copy.deepcopy(row(second)["actual_shifts"]) + [
        {"id": s["candidate_id"], "segments": s["segments"]} for s in selected
    ]
    full = copy.deepcopy(second)
    full["planning_window"]["start"] = stamp("10-05")
    full["employees"][0]["availability"][0]["start"] = stamp("10-05")
    row(full)["actual_shifts"] = []
    row(full)["committed_shifts"] = duties
    full["shift_candidates"] = []
    full["demand"] += [
        {
            "id": f"past_{day}",
            "role_id": "kitchen",
            "interval": {"start": stamp(day, "09:00"), "end": stamp(day, "17:00")},
            "required_people": 1,
        }
        for day in ("10-05", "10-06")
    ]
    first = copy.deepcopy(full)
    first["planning_window"]["end"] = stamp("10-07")
    first["demand"] = [d for d in first["demand"] if d["id"].startswith("past_")]
    second["shift_candidates"] = []
    row(second)["committed_shifts"] = duties[2:]
    results = [verify(d, solution(d)) for d in (full, first, second)]
    assert all(r["status"] in {"VALID", "PARTIAL"} for r in results)
    assert results[0]["continuity_summary"]["employees"][0]["planned_minutes"] == sum(
        r["continuity_summary"]["employees"][0]["planned_minutes"] for r in results[1:]
    )
    assert results[0]["shortage_summary"]["total_person_minutes"] == sum(
        r["shortage_summary"]["total_person_minutes"] for r in results[1:]
    )
    for kind, limit, code in [
        ("min_rest_minutes", 961, "MIN_REST_MINUTES_VIOLATION"),
        ("max_consecutive_days", 1, "MAX_CONSECUTIVE_DAYS_VIOLATION"),
    ]:
        # 求解済みの同じ列を境界を変えて再検証する。未来を解放した別問題ではない。
        for data in (full, first, second):
            out = solution(data)
            data["constraints"].append(rule(kind, limit, identifier=f"tight_{kind}"))
            checked = verify(data, out)
            assert checked["status"] == "INVALID_PLAN"
            assert code in {v["code"] for v in checked["verification"]["violations"]}
            data["constraints"].pop()


def test_template_expansion_starts_only_in_planning_window():
    data = example()
    data["demand"] = []
    data["constraints"] = []
    row(data)["committed_shifts"] = []
    data["shift_templates"] = [
        {
            "id": "night_template",
            "employee_ids": ["alice"],
            "dates": ["2026-10-31", "2026-11-01", "2026-11-02"],
            "start_times": ["23:00"],
            "segment_options": [[{"offset_minutes": 0, "duration_minutes": 180, "breaks": []}]],
        }
    ]
    candidates = normalize(data).candidates
    assert len(candidates) == 1
    assert candidates[0].day.isoformat() == "2026-11-01"
    assert candidates[0].output(normalize(data).grid)["segments"][0]["interval"]["end"] == stamp(
        "11-02", "02:00"
    )


@pytest.mark.parametrize("backend", ["auto", "cp_sat"])
def test_continuity_priority_precedes_preference_and_uses_total_shortage_first(backend):
    data = example()
    data["solver"]["backend"] = backend
    data["demand"] = [
        {
            "id": "high",
            "role_id": "kitchen",
            "interval": {"start": stamp("11-01"), "end": stamp("11-01", "00:30")},
            "required_people": 1,
            "priority": 100,
        },
        {
            "id": "low",
            "role_id": "hall",
            "interval": {"start": stamp("11-01"), "end": stamp("11-01", "00:30")},
            "required_people": 1,
            "priority": 0,
        },
    ]
    data["roles"].append({"id": "hall", "label": "ホール", "required_skills": []})
    data["preferences"] = [
        {
            "id": "avoid",
            "type": "avoid_role",
            "employee_ids": ["alice"],
            "role_id": "kitchen",
            "penalty_per_minute": 10,
        }
    ]
    data["objectives"] = [{"id": "pref", "metric": "preference_penalty"}]
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 30
    assert [g["total_person_minutes"] for g in result["priority_summary"]["groups"]] == [0, 30]
    assert all(g["proven_minimal"] for g in result["priority_summary"]["groups"])
    assert result["objectives"][0]["value"] == 300
    assert result["continuity_summary"]["employees"][0]["planned_minutes"] == 300
    checked = verify(data, result["solution"])
    assert all(not g["proven_minimal"] for g in checked["priority_summary"]["groups"])
    # 完全に供給できる低priorityの長い需要を高priorityの短い需要より先に置く総量評価。
    row(data)["committed_shifts"] = []
    data["shift_candidates"] = [
        {
            "id": "high_shift",
            "employee_id": "alice",
            "segments": [segment(stamp("11-01"), stamp("11-01", "00:30"))],
        },
        {
            "id": "low_shift",
            "employee_id": "alice",
            "segments": [segment(stamp("11-01", "01:00"), stamp("11-01", "02:00"))],
        },
    ]
    data["demand"][1]["interval"] = {
        "start": stamp("11-01", "01:00"),
        "end": stamp("11-01", "02:00"),
    }
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 30
    assert [g["total_person_minutes"] for g in result["priority_summary"]["groups"]] == [30, 0]


def test_verification_rejects_committed_reference_without_continuity():
    data = example()
    out = solution(data)
    del data["continuity"]
    data["employees"][0]["availability"][0]["end"] = stamp("11-02")
    data["employees"][0]["history"] = {
        "last_shift_end": None,
        "last_work_day": None,
        "consecutive_work_days_before_window": 0,
    }
    assert verify(data, out)["status"] == "INVALID_PLAN"


@pytest.mark.parametrize("out", [None, {}, {"shifts": [42], "assignments": []}])
def test_malformed_solution_is_invalid_plan(out):
    assert verify(example(), out)["status"] == "INVALID_PLAN"


def test_missing_anchor_fields_and_pre_context_aggregation_are_rejected():
    data = example("week")
    row(data)["before_context"] = {}
    assert validate(data)["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"
    data = example("week")
    data["constraints"][0]["interval"]["start"] = stamp("10-04")
    assert validate(data)["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"
    # 過去の11分休憩と終了端を現在の30分粒度に丸めない。
    data = example("week")
    row(data)["actual_shifts"][0]["segments"] = [
        segment(
            stamp("10-05", "09:01"),
            stamp("10-05", "17:17"),
            [(stamp("10-05", "12:02"), stamp("10-05", "12:13"))],
        )
    ]
    checked = solve(data)
    assert checked["continuity_summary"]["employees"][0]["historical_minutes"] == 965
