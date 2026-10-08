"""契約0.13の分類・休日・並び・日群を原区間と全探索で確認する。"""

import copy
import itertools
import json
import subprocess
import sys
from datetime import datetime, timedelta
from typing import get_args, get_type_hints

import pytest
from jsonschema import Draft202012Validator

from shift_schedula import get_schema, make_baseline, solve, types, validate, verify
from shift_schedula.contract import SCHEMA_VERSIONS, parse_datetime
from shift_schedula.model import normalize
from shift_schedula.shift_patterns import category_ranges, classify
from shift_schedula.verify import verify_plan
from tests.roster_support import demand, interval, stamp
from tests.support import assert_response
from tests.test_continuity import segment
from tests.test_day_counts import continuity, selected
from tests.test_day_counts import example as days_example
from tests.test_objectives import control_search


def example(days=9, employees=("alice",)):
    data = days_example(days, employees)
    data["schema_version"] = "0.13"
    return data


def pattern(kind, first=2, last=5, **fields):
    return {
        "id": "pattern",
        "type": kind,
        "employee_ids": ["alice"],
        "evaluation_period": {"start": stamp(first), "end": stamp(last)},
        **fields,
    }


def category(identifier, first=0, last=9, start=0, end=1440, minimum=1):
    return {
        "id": identifier,
        "label": identifier,
        "intervals": [interval(d, start, end) for d in range(first, last)],
        "min_overlap_minutes": minimum,
    }


def plan(data, days):
    return {
        "assignments": [],
        "shifts": [selected(c) for c in data["shift_candidates"] if c["id"] in days],
    }


def ids(data, days):
    return [c["id"] for c in data["shift_candidates"] if selected(c)["work_day"] in days]


def by_days(data, *days):
    return plan(data, ids(data, {stamp(d)[:10] for d in days}))


def assert_pattern_violation(data, solution):
    checked = verify(data, solution)
    assert checked["status"] == "INVALID_PLAN", checked
    violation = next(d for d in checked["diagnostics"] if d["code"] == "SHIFT_PATTERN_VIOLATION")
    assert violation["json_pointer"] == "/constraints/0"
    assert violation["related_ids"][:2] == ["pattern", "alice"]
    assert checked["objectives"] == []


def test_minimum_consecutive_days_off_checks_maximal_runs_and_no_days_off():
    data = example()
    data["constraints"] = [pattern("min_consecutive_days_off", min_days=2)]
    assert_pattern_violation(data, by_days(data, 2, 4))
    assert verify(data, by_days(data, 2, 5))["status"] == "VALID"
    assert verify(data, by_days(data, *range(9)))["status"] == "VALID"
    assert verify(data, by_days(data))["status"] == "VALID"
    # 左・右余白に続く休み、評価期間と交差しない短い休日を区別する。
    assert verify(data, by_days(data, 0, 2, 3, 4, 5, 6, 7))["status"] == "VALID"
    assert_pattern_violation(data, by_days(data, 1, 3))
    assert_pattern_violation(data, by_days(data, 3, 5))
    data["preferences"] = [
        {
            "id": "off",
            "type": "avoid_work",
            "employee_ids": ["alice"],
            "interval": interval(3),
            "penalty_per_minute": 1,
        }
    ]
    data["objectives"].insert(0, {"id": "wish", "metric": "preference_penalty"})
    assert_pattern_violation(data, by_days(data, 2, 4))


@pytest.mark.parametrize("end_minute,next_day", [(1800, 4), (1440, 3)])
def test_days_off_after_night_has_exact_midnight_boundary(end_minute, next_day):
    data = example(7)
    data["shift_candidates"] = [
        {
            "id": "night",
            "employee_id": "alice",
            "segments": [segment(stamp(0, 1320), stamp(0, end_minute))],
        },
        {
            "id": "early",
            "employee_id": "alice",
            "segments": [segment(stamp(next_day, -30), stamp(next_day, 30))],
        },
        {
            "id": "allowed",
            "employee_id": "alice",
            "segments": [segment(stamp(next_day), stamp(next_day, 60))],
        },
    ]
    data["shift_categories"] = [category("night", last=2, start=1320)]
    data["constraints"] = [
        pattern("days_off_after_shift", first=0, last=1, category_id="night", min_days=2)
    ]
    assert verify(data, plan(data, ["night", "allowed"]))["status"] == "VALID"
    assert_pattern_violation(data, plan(data, ["night", "early"]))
    data["demand"] = [
        dict(demand(0, 1320, 1350), minimum_people=1),
        demand(next_day - 1, 1410, 1440),
    ]
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert [s["candidate_id"] for s in result["solution"]["shifts"]] == ["night"]
    assert result["shortage_summary"]["total_person_minutes"] == 30


def test_forbidden_start_day_offset_is_not_next_chosen_shift_and_is_employee_specific():
    data = example(employees=("alice", "bob"))
    data["shift_categories"] = [
        category("late", start=600, end=630),
        category("early", start=660, end=690),
    ]
    data["constraints"] = [
        pattern(
            "forbidden_shift_successions",
            from_category_id="late",
            to_category_id="early",
            day_offset=1,
        )
    ]
    assert_pattern_violation(data, by_days(data, 2, 3))
    assert verify(data, by_days(data, 2, 4))["status"] == "VALID"
    other = plan(data, ids(data, {stamp(2)[:10]}))
    other["shifts"].append(
        selected(
            next(
                c
                for c in data["shift_candidates"]
                if c["employee_id"] == "bob" and selected(c)["work_day"] == stamp(3)[:10]
            )
        )
    )
    assert verify(data, other)["status"] == "VALID"
    data["constraints"][0]["day_offset"] = 2
    data["constraints"][0]["evaluation_period"]["end"] = stamp(4)
    assert_pattern_violation(data, by_days(data, 2, 3, 4))


def test_weekend_groups_count_each_group_once_and_include_night_occupancy():
    data = example(14)
    data["constraints"] = [
        pattern(
            "worked_date_groups_limit",
            first=0,
            last=14,
            max_groups=1,
            date_groups=[
                {"id": "week1", "dates": [stamp(5)[:10], stamp(6)[:10]]},
                {"id": "week2", "dates": [stamp(12)[:10], stamp(13)[:10]]},
            ],
        )
    ]
    assert verify(data, by_days(data, 5, 6))["status"] == "VALID"
    assert_pattern_violation(data, by_days(data, 5, 13))
    data["shift_candidates"][4]["segments"] = [segment(stamp(4, 1320), stamp(5, 360))]
    assert_pattern_violation(data, by_days(data, 4, 13))
    data["shift_candidates"][4]["segments"] = [segment(stamp(4, 1320), stamp(5))]
    assert verify(data, by_days(data, 4, 13))["status"] == "VALID"
    # 休憩は占有日を消さず、分割間の非勤務は占有日を増やさない。
    data["shift_candidates"][4]["segments"] = [
        segment(stamp(4, 1320), stamp(5, 60), [(stamp(4, 1410), stamp(5, 30))])
    ]
    assert_pattern_violation(data, by_days(data, 4, 13))
    data["shift_candidates"][4]["segments"] = [
        segment(stamp(4, 600), stamp(4, 660)),
        segment(stamp(7, 600), stamp(7, 660)),
    ]
    assert verify(data, by_days(data, 4, 13))["status"] == "VALID"


@pytest.mark.parametrize("minimum,matched", [(59, True), (60, True), (61, False)])
def test_categories_union_breaks_split_standby_threshold_and_multiple_matches(minimum, matched):
    data = example()
    data["shift_categories"] = [
        category("night", first=2, last=3, start=600, end=660, minimum=minimum)
    ]
    c = data["shift_categories"][0]
    c["intervals"].append(interval(2, 630, 690))
    data["shift_categories"].append({**copy.deepcopy(c), "id": "also"})
    spans = [segment(stamp(2, 600), stamp(2, 690), [(stamp(2, 630), stamp(2, 660))])]
    assert classify(spans, category_ranges(data)) == ({"night", "also"} if matched else set())
    spans = [segment(stamp(2, 600), stamp(2, 630)), segment(stamp(2, 660), stamp(2, 690))]
    assert classify(spans, category_ranges(data)) == ({"night", "also"} if matched else set())
    data["shift_candidates"] = [{"id": "standby", "employee_id": "alice", "segments": spans}]
    assert validate(data)["status"] == "VALID"  # 未参照の分類を保持できる。


@pytest.mark.parametrize("kind", ["forbidden_shift_successions", "days_off_after_shift"])
def test_previous_actual_trigger_and_future_commitment_are_preserved_in_diagnosis(kind):
    data = example(8)
    row = continuity(data)
    data["planning_window"]["start"] = stamp(2)
    data["shift_candidates"] = [
        c for c in data["shift_candidates"] if selected(c)["work_day"] >= stamp(2)[:10]
    ]
    row["actual_shifts"] = [{"id": "past", "segments": [segment(stamp(1, 1320), stamp(2))]}]
    row["committed_shifts"] = [{"id": "fixed", "segments": [segment(stamp(2, 600), stamp(2, 690))]}]
    data["shift_categories"] = [
        category("night", last=2, start=1320),
        category("day", last=8, start=600, end=690),
    ]
    fields = (
        {"from_category_id": "night", "to_category_id": "day", "day_offset": 1}
        if kind == "forbidden_shift_successions"
        else {"category_id": "night", "min_days": 2}
    )
    data["constraints"] = [pattern(kind, **fields)]
    data["diagnosis"] = {
        "time_limit_seconds": 10,
        "max_suggestions": 0,
        "allowed_changes": [],
        "conflict_refinement": {"time_limit_seconds": 5},
    }
    assert validate(data)["status"] == "VALID"
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert conflict["minimality"] == "inclusion_minimal"
    assert [c["json_pointer"] for c in conflict["conditions"]] == ["/constraints/0"]
    assert any(c["code"] == "SHIFT_CATEGORY_BACKGROUND" for c in conflict["background_conditions"])
    bare = copy.deepcopy(data)
    bare["constraints"] = []
    fixed = solve(bare)
    assert_response(fixed, "OPTIMAL")
    assert_pattern_violation(data, fixed["solution"])


@pytest.mark.parametrize(
    "kind,fields",
    [
        (
            "forbidden_shift_successions",
            {"from_category_id": "all", "to_category_id": "all", "day_offset": 2},
        ),
        ("days_off_after_shift", {"category_id": "all", "min_days": 2}),
        ("min_consecutive_days_off", {"min_days": 2}),
    ],
)
def test_missing_margin_is_incomplete_history_with_required_interval(kind, fields):
    data = example(3)
    data["shift_categories"] = [category("all", last=3)]
    data["constraints"] = [pattern(kind, first=0, last=3, **fields)]
    result = validate(data)
    assert result["status"] == "INVALID_INPUT"
    assert result["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"
    assert any(f["name"] == "required_start" for f in result["diagnostics"][0]["facts"])


def test_history_summary_cannot_prove_classification_and_future_context_is_not_days_off():
    data = example(8)
    data["employees"][0]["history"].update(
        last_shift_end=stamp(-1, 1380),
        last_work_day=stamp(-1)[:10],
        consecutive_work_days_before_window=1,
    )
    data["shift_categories"] = [category("night", last=8)]
    data["constraints"] = [
        pattern("days_off_after_shift", first=0, last=1, category_id="night", min_days=2)
    ]
    assert validate(data)["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"
    data = example(5)
    continuity(data)
    data["continuity"]["context_window"]["end"] = stamp(9)
    data["constraints"] = [pattern("min_consecutive_days_off", first=2, last=4, min_days=2)]
    assert validate(data)["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"


@pytest.mark.parametrize("min_days", [1, 2, 3])
def test_every_small_subset_matches_independent_holiday_runs_and_optimum(min_days):
    data = example(7)
    data["constraints"] = [pattern("min_consecutive_days_off", first=3, last=4, min_days=min_days)]
    data["demand"] = [demand(d) for d in (2, 3, 4)]
    best = []
    for flags in itertools.product((False, True), repeat=7):
        chosen = [d for d, flag in enumerate(flags) if flag]
        off = [d for d, flag in enumerate(flags) if not flag]
        runs = [
            [day for _, day in g]
            for _, g in itertools.groupby(enumerate(off), key=lambda pair: pair[1] - pair[0])
        ]
        valid = all(len(r) >= min_days for r in runs if 3 in r)
        solution = by_days(data, *chosen)
        for d in chosen:
            if d in (2, 3, 4):
                solution["assignments"].append(
                    {
                        "employee_id": "alice",
                        "role_id": "kitchen",
                        "interval": interval(d, 600, 630),
                    }
                )
        checked = verify(data, solution)
        assert (checked["status"] in {"VALID", "PARTIAL"}) == valid, (flags, checked)
        if valid:
            best.append(((3 - len(set(chosen) & {2, 3, 4})) * 30, len(chosen) * 90))
    result = solve(data)
    assert result["verification"]["valid"]
    assert (
        result["shortage_summary"]["total_person_minutes"],
        result["objectives"][0]["value"],
    ) == min(best)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_category",
        "unknown_category",
        "float",
        "bool",
        "zero",
        "oversized",
        "unknown_field",
        "empty_ids",
        "unknown_employee",
        "non_midnight",
        "reversed_period",
        "misaligned_category",
        "duplicate_group_id",
        "overlapping_group_dates",
        "outside_group_date",
    ],
)
def test_invalid_classifications_rules_dates_and_integer_types(mutation):
    data = example()
    data["shift_categories"] = [category("night")]
    rule = pattern("days_off_after_shift", category_id="night", min_days=2)
    data["constraints"] = [rule]
    if mutation == "duplicate_category":
        data["shift_categories"] *= 2
    elif mutation == "unknown_category":
        rule["category_id"] = "missing"
    elif mutation in {"float", "bool", "zero", "oversized"}:
        rule["min_days"] = {"float": 2.0, "bool": True, "zero": 0, "oversized": 367}[mutation]
    elif mutation == "unknown_field":
        rule["expression"] = "anything"
    elif mutation == "empty_ids":
        rule["employee_ids"] = []
    elif mutation == "unknown_employee":
        rule["employee_ids"] = ["ghost"]
    elif mutation == "non_midnight":
        rule["evaluation_period"]["start"] = stamp(2, 30)
    elif mutation == "reversed_period":
        rule["evaluation_period"]["end"] = stamp(1)
    elif mutation == "misaligned_category":
        data["shift_categories"][0]["intervals"][0]["start"] = stamp(0, 1)
    else:
        rule = pattern(
            "worked_date_groups_limit",
            date_groups=[
                {"id": "one", "dates": [stamp(2)[:10]]},
                {"id": "two", "dates": [stamp(3)[:10]]},
            ],
            max_groups=1,
        )
        data["constraints"] = [rule]
        if mutation == "duplicate_group_id":
            rule["date_groups"][1]["id"] = "one"
        elif mutation == "overlapping_group_dates":
            rule["date_groups"][1]["dates"] = [stamp(2)[:10]]
        else:
            rule["date_groups"][1]["dates"] = [stamp(8)[:10]]
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("version", [v for v in SCHEMA_VERSIONS if v not in {"0.13", "0.14"}])
def test_old_contracts_reject_categories_and_patterns(version):
    data = example()
    data["schema_version"] = version
    data["shift_categories"] = [category("all")]
    assert validate(data)["status"] == "INVALID_INPUT"
    data.pop("shift_categories")
    data["constraints"] = [pattern("min_consecutive_days_off", min_days=2)]
    assert validate(data)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize("mode", ["preserve_assigned", "rebuild"])
def test_baseline_keeps_categories_and_rules_without_automatically_setting_next_rules(mode):
    data = example()
    data["shift_categories"] = [category("all")]
    data["demand"] = [demand(2), demand(4)]
    original = solve(data)
    assert_response(original, "OPTIMAL")
    baseline = make_baseline(data, original["solution"], "saved")
    assert baseline["source_request"]["shift_categories"] == data["shift_categories"]
    data["baseline"] = baseline
    data["replan_mode"] = mode
    data["constraints"] = [pattern("min_consecutive_days_off", min_days=2)]
    result = solve(data)
    assert result["verification"]["valid"]
    assert verify(data, result["solution"])["status"] == "VALID"
    saved = make_baseline(data, result["solution"], "again")
    assert saved["source_request"]["constraints"] == data["constraints"]
    assert saved["source_request"]["shift_categories"] == data["shift_categories"]


@pytest.mark.parametrize("statuses", [("UNKNOWN",), ("FEASIBLE",), ("OPTIMAL", "UNKNOWN")])
def test_shared_search_budget_and_proofs_with_pattern_conditions(monkeypatch, statuses):
    data = example()
    data["constraints"] = [pattern("min_consecutive_days_off", min_days=2)]
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "UNKNOWN" if statuses == ("UNKNOWN",) else "FEASIBLE")
    assert len(calls) == len(statuses)
    assert all(not o["proven_optimal"] for o in result["objectives"])


def test_public_schemas_types_cli_and_diagnosis_edits(tmp_path):
    data = example()
    data["constraints"] = [pattern("min_consecutive_days_off", min_days=2)]
    data["shift_categories"] = [category("all")]
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(data))
    solution = tmp_path / "solution.json"
    solution.write_text(json.dumps(solve(data)["solution"]))
    for args in (["solve", str(request_path)], ["verify", str(request_path), str(solution)]):
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", *args], capture_output=True, text=True
        )
        assert completed.returncode == 0, completed.stdout
        assert json.loads(completed.stdout)["schema_version"] == "0.13"
    for kind in ("request", "response", "solution", "verification"):
        schema = get_schema(kind, "0.13")
        Draft202012Validator.check_schema(schema)
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.13"],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == schema
    assert types.Request013.__required_keys__ == set(get_schema("request", "0.13")["required"])
    assert set(get_type_hints(types.Request013)) == set(get_schema("request", "0.13")["properties"])
    assert get_args(get_type_hints(types.Request013)["schema_version"]) == ("0.13",)
    data["diagnosis"] = {
        "time_limit_seconds": 1,
        "max_suggestions": 1,
        "allowed_changes": [
            {"id": "edit", "edits": [{"json_pointer": "/constraints/0/min_days", "value": 1}]}
        ],
    }
    assert validate(data)["diagnostics"][0]["code"] == "UNSUPPORTED_DIAGNOSIS_EDIT"


@pytest.mark.parametrize(
    "kind", ["forbidden_shift_successions", "days_off_after_shift", "worked_date_groups_limit"]
)
def test_all_small_subsets_match_independent_pairs_groups_and_solver(kind):
    source = example(7)
    source["shift_candidates"] = source["shift_candidates"][1:5]
    source["shift_categories"] = [category("all", last=7)]
    fields = {
        "forbidden_shift_successions": {
            "from_category_id": "all",
            "to_category_id": "all",
            "day_offset": 2,
        },
        "days_off_after_shift": {"category_id": "all", "min_days": 1},
        "worked_date_groups_limit": {
            "max_groups": 1,
            "date_groups": [
                {"id": "one", "dates": [stamp(1)[:10], stamp(2)[:10]]},
                {"id": "two", "dates": [stamp(3)[:10], stamp(4)[:10]]},
            ],
        },
    }[kind]
    source["constraints"] = [
        pattern(kind, first=2 if kind == "forbidden_shift_successions" else 1, last=5, **fields)
    ]
    source["demand"] = [demand(d) for d in range(1, 5)]
    possible = []
    for flags in itertools.product((False, True), repeat=4):
        chosen = [d for d, flag in zip(range(1, 5), flags, strict=True) if flag]
        valid = (
            all(b - a != 2 for a, b in itertools.combinations(chosen, 2))
            if kind == "forbidden_shift_successions"
            else all(b - a >= 2 for a, b in itertools.combinations(chosen, 2))
            if kind == "days_off_after_shift"
            else not (set(chosen) & {1, 2} and set(chosen) & {3, 4})
        )
        solution = by_days(source, *chosen)
        solution["assignments"] = [
            {"employee_id": "alice", "role_id": "kitchen", "interval": interval(d, 600, 630)}
            for d in chosen
        ]
        assert (verify(source, solution)["status"] in {"VALID", "PARTIAL"}) == valid
        forced = copy.deepcopy(source)
        forced["shift_candidates"] = [
            c for c, flag in zip(source["shift_candidates"], flags, strict=True) if flag
        ]
        forced["demand"] = [dict(demand(d), minimum_people=1) for d in chosen]
        assert_response(solve(forced), "OPTIMAL" if valid else "INFEASIBLE")
        if valid:
            possible.append(((4 - len(chosen)) * 30, len(chosen) * 90))
    best = solve(source)
    assert (
        best["shortage_summary"]["total_person_minutes"],
        best["objectives"][0]["value"],
    ) == min(possible)


def test_independent_verification_and_explicit_fixed_conflict():
    data = example()
    original = by_days(data, 2, 4)
    data["baseline"] = make_baseline(data, original, "saved")
    data["fixed_parts"] = [
        {
            "id": "fixed",
            "employee_id": "alice",
            "interval": {"start": stamp(2), "end": stamp(5)},
            "components": ["work"],
        }
    ]
    data["constraints"] = [pattern("min_consecutive_days_off", min_days=2)]
    assert_response(solve(data), "INFEASIBLE")
    bare = copy.deepcopy(data)
    bare.pop("baseline")
    bare.pop("fixed_parts")
    problem = normalize(bare)
    problem.candidates = []
    problem.continuity = []
    violations, _, _ = verify_plan(problem, original)
    assert any(v["code"] == "SHIFT_PATTERN_VIOLATION" for v in violations)


def test_pattern_diagnostics_only_reference_shifts_related_to_the_violation():
    data = example()
    row = continuity(data, first_day=-5)
    row["actual_shifts"] = [
        {"id": "unrelated", "segments": [segment(stamp(-4, 600), stamp(-4, 690))]}
    ]
    data["constraints"] = [pattern("min_consecutive_days_off", min_days=2)]
    checked = verify(data, by_days(data, 2, 4))
    assert checked["status"] == "INVALID_PLAN"
    assert "unrelated" not in checked["diagnostics"][0]["related_ids"]


def test_previous_facts_only_are_not_retroactively_rejected_and_outside_period_is_ignored():
    data = example(9)
    row = continuity(data)
    data["planning_window"]["start"] = stamp(3)
    data["shift_candidates"] = data["shift_candidates"][3:]
    row["actual_shifts"] = [
        {"id": f"past{d}", "segments": [segment(stamp(d, 600), stamp(d, 690))]} for d in (1, 2)
    ]
    data["shift_categories"] = [category("all")]
    data["constraints"] = [
        pattern(
            "forbidden_shift_successions",
            first=4,
            last=5,
            from_category_id="all",
            to_category_id="all",
            day_offset=2,
        )
    ]
    assert_response(solve(data), "OPTIMAL")
    # 過去の起点2→対象4は期間内なので拒否。起点3→対象5は評価外なので義務を作らない。
    assert_pattern_violation(data, by_days(data, 4))
    assert verify(data, by_days(data, 3, 5))["status"] == "VALID"


@pytest.mark.parametrize("value", [True, None, 0, 1.0, 10000001])
def test_category_threshold_rejects_invalid_values(value):
    data = example()
    data["shift_categories"] = [category("all", minimum=value)]
    assert validate(data)["status"] == "INVALID_INPUT"


def test_month_boundary_and_one_minute_below_category_threshold():
    data = example(9)
    # 全時刻を10月末へ移し、開始日基準の並びを月境界で確認する。
    text = json.dumps(data)
    for d in range(9, -1, -1):
        text = text.replace(
            stamp(d)[:10], (datetime(2026, 10, 29) + timedelta(days=d)).date().isoformat()
        )
    data = json.loads(text)
    data["planning_window"]["slot_minutes"] = 30
    data["constraints"] = [
        {
            **pattern(
                "forbidden_shift_successions",
                from_category_id="all",
                to_category_id="all",
                day_offset=1,
            ),
            "evaluation_period": {
                "start": "2026-10-31T00:00:00+09:00",
                "end": "2026-11-03T00:00:00+09:00",
            },
        }
    ]
    data["shift_categories"] = [
        {
            "id": "all",
            "label": "全勤務",
            "intervals": [{k: data["planning_window"][k] for k in ("start", "end")}],
            "min_overlap_minutes": 60,
        }
    ]
    assert_pattern_violation(
        data, plan(data, [data["shift_candidates"][2]["id"], data["shift_candidates"][3]["id"]])
    )
    categories = {"night": ([(parse_datetime(stamp(0, 600)), parse_datetime(stamp(0, 660)))], 60)}
    assert classify([segment(stamp(0, 600), stamp(0, 659))], categories) == set()
    assert classify([segment(stamp(0, 600), stamp(0, 660))], categories) == {"night"}


@pytest.mark.parametrize(
    "first,last",
    [
        ("2026-03-23T00:00:00+01:00", "2026-03-30T00:00:00+02:00"),
        ("2026-10-19T00:00:00+02:00", "2026-10-26T00:00:00+01:00"),
    ],
)
def test_dst_groups_and_local_days_do_not_use_elapsed_24_hours(first, last):
    data = example(7)
    data["planning_window"].update(start=first, end=last, timezone="Europe/Berlin", slot_minutes=60)
    data["employees"][0]["availability"] = [{"start": first, "end": last}]
    zone = data["planning_window"]["timezone"]
    from zoneinfo import ZoneInfo

    sunday = datetime.fromisoformat(last).astimezone(ZoneInfo(zone)) - timedelta(days=1)
    data["shift_candidates"] = [
        {"id": "dst", "employee_id": "alice", "segments": [segment(sunday.isoformat(), last)]}
    ]
    data["constraints"] = [
        {
            **pattern(
                "worked_date_groups_limit",
                max_groups=0,
                date_groups=[{"id": "sun", "dates": [sunday.date().isoformat()]}],
            ),
            "evaluation_period": {"start": first, "end": last},
        }
    ]
    bare = copy.deepcopy(data)
    bare["constraints"] = []
    data["constraints"].append(
        {
            "id": "force",
            "type": "work_days_bounds",
            "employee_ids": ["alice"],
            "interval": {"start": first, "end": last},
            "min_days": 1,
        }
    )
    assert_response(solve(data), "INFEASIBLE")
    chosen = {
        "assignments": [],
        "shifts": [
            {
                "candidate_id": "dst",
                "employee_id": "alice",
                "work_day": sunday.date().isoformat(),
                "segments": data["shift_candidates"][0]["segments"],
            }
        ],
    }
    assert verify(bare, chosen)["status"] == "VALID"
    assert_pattern_violation(data, chosen)
