"""5機能を同じ勤務計画・再計画・独立検証へ接続する結合確認。"""

import copy
import itertools
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from shift_schedula import make_baseline, solve, validate, verify
from tests.roster_support import demand, interval, rule, stamp
from tests.support import assert_response
from tests.test_continuity import segment
from tests.test_coworkers import example as coworkers_example
from tests.test_day_counts import continuity
from tests.test_day_counts import example as days_example
from tests.test_shift_counts import balance, example

ROOT = Path(__file__).resolve().parents[1]


def combined():
    data = coworkers_example()
    data["schema_version"] = "0.15"
    data["request_id"] = "combined_conditions"
    data["shift_candidates"][1]["segments"] = [
        {"interval": interval(0, 540, 630), "breaks": [interval(0, 570, 600)]}
    ]
    data["shift_candidates"][2]["segments"] = [
        {"interval": interval(0, 570, 660), "breaks": [interval(0, 600, 630)]}
    ]
    period = interval(0, 0, 1440)
    employees = [e["id"] for e in data["employees"]]
    data["constraints"] += [
        {
            "id": "work_days",
            "type": "work_days_bounds",
            "employee_ids": employees,
            "interval": period,
            "min_days": 0,
            "max_days": 1,
        },
        {
            "id": "days_off",
            "type": "days_off_bounds",
            "employee_ids": employees,
            "interval": period,
            "min_days": 0,
            "max_days": 1,
        },
        {
            "id": "dates",
            "type": "worked_date_groups_limit",
            "employee_ids": employees,
            "evaluation_period": period,
            "date_groups": [{"id": "training_day", "dates": [stamp()[:10]]}],
            "max_groups": 1,
        },
    ]
    data["shift_categories"] = [
        {"id": "training", "label": "実習勤務", "intervals": [period], "min_overlap_minutes": 30}
    ]
    balance(data, {e: 1 for e in employees}, "training", "training")
    return data


def month():
    data = days_example(31)
    data["schema_version"] = "0.15"
    data["request_id"] = "combined_month"
    data["shift_candidates"] = [
        {
            "id": "night",
            "employee_id": "alice",
            "segments": [segment(stamp(0, 1320), stamp(1, 360))],
        },
        {
            "id": "split",
            "employee_id": "alice",
            "segments": [
                segment(stamp(4, 600), stamp(4, 660)),
                segment(stamp(4, 720), stamp(4, 780)),
            ],
        },
    ]
    row = continuity(data, -7)
    row["actual_shifts"] = [{"id": "past", "segments": [segment(stamp(-2, 600), stamp(-2, 660))]}]
    data["shift_categories"] = [
        {
            "id": "night",
            "label": "夜勤",
            "intervals": [interval(0, 1320, 1800)],
            "min_overlap_minutes": 60,
        }
    ]
    data["constraints"] = [
        rule("min_rest_minutes", 600, identifier="rest"),
        rule("max_consecutive_days", 2, identifier="consecutive"),
        {
            "id": "week_days",
            "type": "work_days_bounds",
            "employee_ids": ["alice"],
            "interval": interval(0, 0, 10080),
            "min_days": 2,
            "max_days": 2,
        },
        {
            "id": "month_off",
            "type": "days_off_bounds",
            "employee_ids": ["alice"],
            "interval": interval(0, 0, 44640),
            "min_days": 28,
            "max_days": 28,
        },
        {
            "id": "minutes",
            "type": "scheduled_minutes_bounds",
            "employee_ids": ["alice"],
            "interval": interval(-7, 0, 54720),
            "min_minutes": 0,
            "max_minutes": 660,
        },
        {
            "id": "after_night",
            "type": "days_off_after_shift",
            "employee_ids": ["alice"],
            "evaluation_period": interval(0, 0, 10080),
            "category_id": "night",
            "min_days": 2,
        },
    ]
    data["demand"] = [
        dict(demand(0, 1320, 1350), minimum_people=1),
        dict(demand(4, 600, 630), minimum_people=1),
    ]
    balance(data, {"alice": 1}, "night", "night")
    return data


def test_week_days_month_off_night_split_history_and_required_margin():
    data = month()
    result = solve(data)
    assert_response(result, "OPTIMAL")
    summaries = {s["constraint_id"]: s["employees"][0] for s in result["day_count_summary"]}
    assert summaries["week_days"] == {
        "employee_id": "alice",
        "work_days": 2,
        "occupied_days": 3,
        "days_off": 4,
    }
    assert summaries["month_off"]["days_off"] == 28
    assert result["shift_count_balance_summary"][0]["employees"][0]["actual_count"] == 1
    assert verify(data, result["solution"])["status"] == "VALID"
    data["planning_window"]["end"] = stamp(3)
    data["continuity"]["context_window"]["end"] = stamp(3)
    data["employees"][0]["availability"] = [interval(0, 0, 4320)]
    data["shift_candidates"] = data["shift_candidates"][:1]
    data["demand"] = data["demand"][:1]
    data["constraints"] = [data["constraints"][-1]]
    data["constraints"][0]["evaluation_period"] = interval(0, 0, 1440)
    data["shift_count_balance"][0]["evaluation_period"] = interval(0, 0, 4320)
    rejected = validate(data)
    assert rejected["status"] == "INVALID_INPUT"
    assert rejected["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"


def test_mandatory_trainee_handoff_breaks_partial_and_all_summaries():
    data = combined()
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 120
    assert result["objectives"][0]["value"] == 240
    assert result["shift_count_balance_summary"][0]["total_deviation_count"] == 0
    assert all(e["work_days"] == 1 for e in result["day_count_summary"][0]["employees"])
    assert verify(data, result["solution"])["status"] == "PARTIAL"
    data["employees"][0]["availability"] = []
    data["shift_candidates"] = data["shift_candidates"][1:]
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize("first", ["shift_count_deviation", "scheduled_cost", "preference_penalty"])
def test_count_minutes_cost_and_wishes_follow_explicit_order(first):
    data = example()
    data.pop("duty_balance")
    data["costs"]["employee_rates"][0]["units_per_minute"] = 0
    data["costs"]["employee_rates"][1]["units_per_minute"] = 1
    data["preferences"] = [
        {
            "id": "wish",
            "type": "avoid_role",
            "employee_ids": ["bob"],
            "role_id": "kitchen",
            "penalty_per_minute": 1,
        }
    ]
    objectives = [
        data["objectives"][0],
        {"id": "cost", "metric": "scheduled_cost"},
        {"id": "wish", "metric": "preference_penalty"},
        {"id": "work", "metric": "scheduled_minutes"},
    ]
    data["objectives"] = sorted(objectives, key=lambda o: o["metric"] != first)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    values = {o["metric"]: o["value"] for o in result["objectives"]}
    assert values == (
        {
            "shift_count_deviation": 0,
            "scheduled_cost": 240,
            "preference_penalty": 240,
            "scheduled_minutes": 240,
        }
        if first == "shift_count_deviation"
        else {
            "shift_count_deviation": 1,
            "scheduled_cost": 240,
            "preference_penalty": 0,
            "scheduled_minutes": 480,
        }
        if first == "preference_penalty"
        else {
            "shift_count_deviation": 2,
            "scheduled_cost": 0,
            "preference_penalty": 0,
            "scheduled_minutes": 240,
        }
    )
    assert verify(data, result["solution"])["status"] == "VALID"


@pytest.mark.parametrize(
    "index,field,value,code",
    [
        (0, "minimum_people", 2, "REQUIRED_COWORKERS_VIOLATION"),
        (2, "max_days", 0, "WORK_DAYS_BOUNDS_VIOLATION"),
        (3, "min_days", 1, "DAYS_OFF_BOUNDS_VIOLATION"),
        (4, "max_groups", 0, "SHIFT_PATTERN_VIOLATION"),
    ],
)
def test_hand_edits_cannot_pass_new_hard_conditions(index, field, value, code):
    data = combined()
    original = solve(data)["solution"]
    data["constraints"][index][field] = value
    checked = verify(data, original)
    assert checked["status"] == "INVALID_PLAN"
    assert any(d["code"] == code for d in checked["diagnostics"]), checked
    assert checked["shift_count_balance_summary"] is None


def test_minimum_and_incompatibility_tampering_are_detected():
    data = combined()
    original = solve(data)["solution"]
    data["demand"][0]["minimum_people"] = 2
    assert verify(data, original)["status"] == "INVALID_PLAN"
    data["demand"][0]["minimum_people"] = 1
    data["constraints"][1]["employee_ids"].append("trainee")
    checked = verify(data, original)
    assert checked["status"] == "INVALID_PLAN"
    assert any(d["code"] == "INCOMPATIBLE_EMPLOYEES_VIOLATION" for d in checked["diagnostics"])


@pytest.mark.parametrize("mode", ["preserve_assigned", "rebuild"])
def test_partial_absence_replan_preserves_all_five_conditions(mode):
    data = combined()
    result = solve(data)
    saved = make_baseline(data, result["solution"], "partial")
    data["baseline"] = saved
    data["replan_mode"] = mode
    # 確定前の指導者を交代し、新人の既存担当を保持して不足を補う。
    replacement = copy.deepcopy(data["employees"][2])
    replacement["id"] = replacement["label"] = "mentor_c"
    data["employees"].append(replacement)
    candidate = copy.deepcopy(data["shift_candidates"][2])
    candidate["id"] = candidate["employee_id"] = "mentor_c"
    data["shift_candidates"][2] = candidate
    data["employees"][2]["availability"] = []
    data["constraints"][0]["coworker_ids"].append("mentor_c")
    data["constraints"][1]["employee_ids"].append("mentor_c")
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shift_count_balance_summary"][0]["total_deviation_count"] == 1
    assert any(s["employee_id"] == "mentor_c" for s in result["solution"]["shifts"])
    assert verify(data, result["solution"])["status"] == "PARTIAL"
    roundtrip = make_baseline(data, result["solution"], "replacement")
    for field in ("constraints", "demand", "shift_categories", "shift_count_balance"):
        assert roundtrip["source_request"][field] == data[field]
    assert saved["source_request"]["shift_count_balance"] == combined()["shift_count_balance"]


def test_sliding_period_preserves_original_count_category_and_baseline():
    data = example()
    data["planning_window"]["end"] = stamp(3)
    data["shift_candidates"].append(
        {"id": "bob_second", "employee_id": "bob", "segments": [segment(stamp(2, 1200), stamp(3))]}
    )
    data["demand"].append(
        {**data["demand"][0], "id": "second", "interval": interval(2, 1200, 1440)}
    )
    data["shift_categories"][0]["intervals"].append(interval(2, 1200, 1440))
    data["duty_balance"][0]["intervals"].append(interval(2, 1200, 1440))
    data["duty_balance"][0]["employee_targets"][1]["target_minutes"] = 480
    data["shift_count_balance"][0]["employee_targets"][1]["target_count"] = 2
    original = solve(data)
    assert_response(original, "OPTIMAL")
    data["baseline"] = make_baseline(data, original["solution"], "two_days")
    data["planning_window"]["start"] = stamp(2)
    data["demand"] = data["demand"][1:]
    data["shift_candidates"] = data["shift_candidates"][2:]
    data["continuity"]["employees"][1]["actual_shifts"] = [
        {"id": "confirmed", "segments": [segment(stamp(1, 1200), stamp(2))]}
    ]
    data["replan_mode"] = "preserve_assigned"
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["shift_count_balance_summary"][0]["total_deviation_count"] == 0
    assert result["change_summary"]["total_changes"] == 0


def test_impossible_groups_keep_facts_and_ignore_soft_count_goal():
    data = combined()
    data["constraints"][0]["minimum_people"] = 2
    data["diagnosis"] = {
        "time_limit_seconds": 5,
        "max_suggestions": 0,
        "allowed_changes": [],
        "conflict_refinement": {"time_limit_seconds": 5},
    }
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert conflict["minimality"] == "inclusion_minimal", result["diagnosis_result"]
    assert not any("shift_count" in c["json_pointer"] for c in conflict["conditions"])
    # 十分集合と、その各要素を一つ除いた入力を公開solveで独立照合する。
    paths = {c["json_pointer"] for c in conflict["conditions"]}
    for removed in [None, *paths]:
        trial = copy.deepcopy(data)
        trial.pop("diagnosis")
        trial["constraints"] = [
            c
            for i, c in enumerate(data["constraints"])
            if f"/constraints/{i}" in paths and f"/constraints/{i}" != removed
        ]
        trial["demand"] = [
            d
            for i, d in enumerate(data["demand"])
            if f"/demand/{i}" in paths and f"/demand/{i}" != removed
        ]
        assert (solve(trial)["status"] == "INFEASIBLE") == (removed is None)


def test_saved_examples_match_combined_conditions():
    for name, data in (("combined_conditions", combined()), ("combined_month", month())):
        assert json.loads((ROOT / f"examples/{name}.json").read_text()) == data


def test_tiny_five_conditions_exhaustive_from_original_json():
    data = combined()
    step = timedelta(minutes=30)

    def work_slots(candidate):
        result = set()
        for part in candidate["segments"]:
            at, end = (datetime.fromisoformat(part["interval"][k]) for k in ("start", "end"))
            while at < end:
                if not any(
                    datetime.fromisoformat(b["start"]) <= at < datetime.fromisoformat(b["end"])
                    for b in part["breaks"]
                ):
                    result.add(at)
                at += step
        return result

    possibilities = []
    for bits in itertools.product((0, 1), repeat=3):
        rows = [c for c, bit in zip(data["shift_candidates"], bits, strict=True) if bit]
        slots = {c["employee_id"]: work_slots(c) for c in rows}
        trainee = slots.get("trainee", set())
        mentors = [slots.get(e, set()) for e in ("mentor_a", "mentor_b")]
        # 必須需要1、各勤務枠の必要同僚1、同時勤務禁止。日数と日群の上限は各1。
        if (
            len(trainee) != 4
            or mentors[0] & mentors[1]
            or any(not any(t in s for s in mentors) for t in trainee)
        ):
            continue
        # 全員の分類閾値30分。原勤務は各人1件、0目標/対象外を混同しない。
        possibilities.append(
            (120, sum(len(s) for s in slots.values()) * 30, sum(abs(bit - 1) for bit in bits))
        )
    result = solve(data)
    assert (
        result["shortage_summary"]["total_person_minutes"],
        *(o["value"] for o in result["objectives"]),
    ) == min(possibilities)
