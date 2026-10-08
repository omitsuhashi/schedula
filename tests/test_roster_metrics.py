import copy
import itertools
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shift_schedula import InvalidInput, get_schema, make_baseline, solve, validate, verify
from shift_schedula.contract import SCHEMA_VERSIONS, schema_errors
from shift_schedula.engine import validate_response
from shift_schedula.extensions import evaluate
from shift_schedula.model import normalize
from tests.roster_support import candidate, demand, interval, request, rule, stamp
from tests.support import assert_response
from tests.test_continuity import example as continuity_example
from tests.test_extensions import extended, fairness, selected
from tests.test_objectives import control_search

ROOT = Path(__file__).resolve().parents[1]


def cost_request():
    data = request(employees=("alice", "bob"))
    data["shift_candidates"] = [candidate(e, end=660) for e in ("alice", "bob")]
    data["demand"] = [demand(end=660)]
    data = extended(data)
    data["schema_version"] = "0.9"
    data["costs"] = {
        "currency": "JPY",
        "units_per_currency": 60,
        "employee_rates": [
            {"employee_id": "alice", "units_per_minute": 1800},
            {"employee_id": "bob", "units_per_minute": 2400},
        ],
    }
    data["objectives"] = [{"id": "cost", "metric": "scheduled_cost"}]
    return data


def add_duty(data, targets, intervals=None, identifier="night"):
    data.setdefault("duty_balance", []).append(
        {
            "id": identifier,
            "label": "夜勤",
            "evaluation_period": {k: data["planning_window"][k] for k in ("start", "end")},
            "intervals": intervals or [interval(end=660)],
            "employee_targets": [
                {"employee_id": e, "target_minutes": m} for e, m in targets.items()
            ],
        }
    )
    data["objectives"].append(
        {"id": f"balance_{identifier}", "metric": "duty_deviation_minutes", "duty_id": identifier}
    )


def night_request():
    data = request(days=2, employees=("alice", "bob"))
    data["shift_candidates"] = [
        candidate(e, d, a, b)
        for e in ("alice", "bob")
        for d in range(2)
        for a, b in ((600, 840), (1200, 1440))
    ]
    for employee in data["employees"]:
        employee["availability"] = [interval(d, 600, 1440) for d in range(2)]
    data["demand"] = [demand(d, a, b) for d in range(2) for a, b in ((600, 840), (1200, 1440))]
    data["constraints"] = [rule("min_rest_minutes", 600, ("alice", "bob"))]
    data = extended(data)
    data["schema_version"] = "0.9"
    data["objectives"] = []
    add_duty(data, {"alice": 240, "bob": 240}, [interval(d, 1200, 1440) for d in range(2)])
    return data


@pytest.mark.parametrize("reverse", [False, True])
def test_cost_and_preferences_match_exhaustive_choices(reverse):
    data = cost_request()
    data["preferences"] = [
        {
            "id": "avoid",
            "type": "avoid_role",
            "employee_ids": ["alice"],
            "role_id": "kitchen",
            "penalty_per_minute": 1,
        }
    ]
    data["objectives"].append({"id": "wishes", "metric": "preference_penalty"})
    if reverse:
        data["objectives"].reverse()
    result = solve(data)
    assert_response(result, "OPTIMAL")
    expected = min((0, 144000), (60, 108000)) if reverse else min((144000, 0), (108000, 60))
    assert tuple(o["value"] for o in result["objectives"]) == expected
    assert result["solution"]["shifts"][0]["employee_id"] == ("bob" if reverse else "alice")
    summary = result["cost_summary"]
    assert summary["total_units"] == (144000 if reverse else 108000)
    assert Fraction(summary["total_units"], summary["units_per_currency"]) == (
        2400 if reverse else 1800
    )
    assert verify(data, result["solution"])["cost_summary"] == summary


@pytest.mark.parametrize("minutes,rate,total", [(17, 1800, 30600), (1, 1001, 1001), (60, 0, 0)])
def test_exact_minutes_without_rounding(minutes, rate, total):
    data = cost_request()
    data["planning_window"]["slot_minutes"] = 1
    data["shift_candidates"] = [
        extended({**request(), "shift_candidates": [candidate(end=600 + minutes)]})[
            "shift_candidates"
        ][0]
    ]
    data["demand"] = [demand(end=600 + minutes)]
    data["costs"]["employee_rates"][0]["units_per_minute"] = rate
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["cost_summary"]["total_units"] == total
    assert result["cost_summary"]["employees"][0]["scheduled_minutes"] == minutes
    assert Fraction(total, 60) == Fraction(rate * minutes, 60)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_costs",
        "missing_objective",
        "missing_employee",
        "unknown",
        "duplicate",
        "mixed",
        "currency",
        "multiplier",
    ],
)
def test_costs_require_complete_explicit_rates(mutation):
    data = cost_request()
    rates = data["costs"]["employee_rates"]
    if mutation == "missing_costs":
        data.pop("costs")
    elif mutation == "missing_objective":
        data["objectives"] = []
    elif mutation == "missing_employee":
        rates.pop()
    elif mutation == "unknown":
        rates[0]["employee_id"] = "missing"
    elif mutation == "duplicate":
        rates.append(copy.deepcopy(rates[0]))
    elif mutation == "mixed":
        rates[0]["currency"] = "USD"
    elif mutation == "currency":
        data["costs"]["currency"] = "JPY\n"
    else:
        data["costs"]["units_per_currency"] = 1000001
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("value", [-1, True, None, 1.0, 1.5, 1000000001])
def test_rate_integers_are_strict(value):
    data = cost_request()
    data["costs"]["employee_rates"][0]["units_per_minute"] = value
    assert validate(data)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize("value", [0, -1, True, None, 1.0, 1000001])
def test_multiplier_integers_are_strict(value):
    data = cost_request()
    data["costs"]["units_per_currency"] = value
    assert validate(data)["status"] == "INVALID_INPUT"


def test_conservative_cost_overflow_is_rejected_before_backend(monkeypatch):
    data = extended(request(days=7))
    data["schema_version"] = "0.9"
    data["employees"][0]["availability"] = [{"start": stamp(), "end": stamp(7)}]
    data["shift_candidates"] = [
        {
            "id": f"long_{i}",
            "employee_id": "alice",
            "segments": [{"interval": {"start": stamp(), "end": stamp(7)}, "breaks": []}],
        }
        for i in range(1000)
    ]
    data["costs"] = {
        "currency": "JPY",
        "units_per_currency": 1000000,
        "employee_rates": [{"employee_id": "alice", "units_per_minute": 1000000000}],
    }
    data["objectives"] = [{"id": "cost", "metric": "scheduled_cost"}]
    from shift_schedula import cp_sat

    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("モデル構築前に拒否する"))
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "INTEGER_EXPRESSION_LIMIT"
    assert result["diagnostics"][0]["json_pointer"] == "/costs"


def test_break_split_standby_template_and_changed_rate_baseline():
    data = cost_request()
    c = data["shift_candidates"][0]
    c["segments"] = [
        {"interval": interval(end=690), "breaks": [interval(start=630, end=660)]},
        {"interval": interval(start=720, end=780), "breaks": []},
    ]
    data["employees"][0]["availability"] = [interval(end=780)]
    data["shift_candidates"] = [c]
    data["demand"] = [demand()]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["cost_summary"]["total_units"] == 216000
    baseline = make_baseline(data, result["solution"], "saved")
    new = copy.deepcopy(data)
    new["baseline"] = baseline
    new["costs"]["employee_rates"][0]["units_per_minute"] = 2000
    new["objectives"].insert(0, {"id": "changes", "metric": "plan_changes"})
    again = solve(new)
    assert_response(again, "OPTIMAL")
    assert [o["value"] for o in again["objectives"]] == [0, 240000]
    assert baseline["source_request"]["costs"]["employee_rates"][0]["units_per_minute"] == 1800
    data = cost_request()
    data["shift_candidates"] = []
    data["shift_templates"] = [
        {
            "id": "template",
            "employee_ids": ["alice", "bob"],
            "dates": ["2026-10-05"],
            "start_times": ["10:00"],
            "segment_options": [[{"offset_minutes": 0, "duration_minutes": 60, "breaks": []}]],
        }
    ]
    assert solve(data)["cost_summary"]["total_units"] == 108000


def test_cost_and_duty_do_not_increase_shortage_or_ignore_priority():
    data = cost_request()
    data["shift_candidates"] = data["shift_candidates"][1:]
    add_duty(data, {"alice": 0, "bob": 0})
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [o["value"] for o in result["objectives"]] == [144000, 60]
    data["demand"].append({**demand(end=660, role="hall"), "priority": 1})
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 60
    assert [g["total_person_minutes"] for g in result["priority_summary"]["groups"]] == [0, 60]
    data["shift_candidates"] = []
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["cost_summary"]["total_units"] == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_night_balance_and_wishes_keep_fixed_first_day_and_equal_cost(reverse):
    data = night_request()
    fairness(data, {"alice": 480, "bob": 480})
    data["objectives"].append(
        {"id": "night", "metric": "duty_deviation_minutes", "duty_id": "night"}
    )
    data["costs"] = cost_request()["costs"]
    data["objectives"].append({"id": "cost", "metric": "scheduled_cost"})
    forced = {
        "assignments": [
            {"employee_id": e, "role_id": "kitchen", "interval": interval(0, a, b)}
            for e, a, b in (("alice", 1200, 1440), ("bob", 600, 840))
        ],
        "shifts": [
            selected(c)
            for c in data["shift_candidates"]
            if c["employee_id"] == "alice"
            and c["segments"][0]["interval"] == interval(0, 1200, 1440)
            or c["employee_id"] == "bob"
            and c["segments"][0]["interval"] == interval(0, 600, 840)
        ],
    }
    data["baseline"] = make_baseline(data, forced, "first_day")
    data["fixed_parts"] = [
        {
            "id": "first_night",
            "employee_id": "alice",
            "interval": interval(0, 1200, 1440),
            "components": ["work", "role"],
        }
    ]
    data["preferences"] = [
        {
            "id": "avoid_day",
            "type": "avoid_work",
            "employee_ids": ["alice"],
            "interval": interval(1, 600, 840),
            "penalty_per_minute": 1,
        }
    ]
    wishes = {"id": "wishes", "metric": "preference_penalty"}
    if reverse:
        data["objectives"].insert(1, wishes)
    else:
        data["objectives"].append(wishes)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    # 2日目の全候補を列挙。固定した1日目に加え、一人一勤務・両需要充足を満たす2案。
    choices = [(0, 240, 480 * 1800 + 480 * 2400), (480, 0, 480 * 1800 + 480 * 2400)]
    expected = min((w, d, c) if reverse else (d, c, w) for d, w, c in choices)
    assert tuple(o["value"] for o in result["objectives"])[1:] == expected
    assert result["objectives"][0]["value"] == 0
    assert result["duty_balance_summary"][0]["total_deviation_minutes"] == (480 if reverse else 0)


@pytest.mark.parametrize(
    "order",
    list(
        itertools.permutations(("scheduled_cost", "duty_deviation_minutes", "preference_penalty"))
    ),
)
def test_three_objectives_match_exhaustive_choices(order):
    data = cost_request()
    add_duty(data, {"alice": 0, "bob": 60})
    data["preferences"] = [
        {
            "id": "avoid",
            "type": "avoid_work",
            "employee_ids": ["bob"],
            "interval": interval(end=660),
            "penalty_per_minute": 1,
        }
    ]
    data["objectives"].append({"id": "wishes", "metric": "preference_penalty"})
    by_metric = {o["metric"]: o for o in data["objectives"]}
    data["objectives"] = [by_metric[m] for m in order]
    choices = []
    for a, b in itertools.product((0, 1), repeat=2):
        if a + b == 0:
            continue
        metrics = {
            "scheduled_cost": a * 108000 + b * 144000,
            "duty_deviation_minutes": a * 60 + abs(b * 60 - 60),
            "preference_penalty": b * 60,
        }
        choices.append(tuple(metrics[m] for m in order))
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert tuple(o["value"] for o in result["objectives"]) == min(choices)


@pytest.mark.parametrize("value", [-1, True, None, 1.0, 10000001])
def test_duty_target_integers_are_strict(value):
    data = cost_request()
    add_duty(data, {"alice": value})
    assert validate(data)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_duty",
        "missing_objective",
        "duplicate_duty",
        "duplicate_objective",
        "unknown_duty",
        "other_metric",
        "unknown_employee",
        "duplicate_employee",
        "empty_targets",
        "outside_period",
        "misaligned",
        "past_period",
        "too_many",
        "too_many_intervals",
    ],
)
def test_duty_pairing_references_intervals_and_limits(mutation):
    data = cost_request()
    add_duty(data, {"alice": 30})
    duty = data["duty_balance"][0]
    if mutation == "missing_duty":
        data.pop("duty_balance")
    elif mutation == "missing_objective":
        data["objectives"].pop()
    elif mutation == "duplicate_duty":
        data["duty_balance"].append(copy.deepcopy(duty))
    elif mutation == "duplicate_objective":
        data["objectives"].append({**data["objectives"][-1], "id": "another"})
    elif mutation == "unknown_duty":
        data["objectives"][-1]["duty_id"] = "missing"
    elif mutation == "other_metric":
        data["objectives"][0]["duty_id"] = "night"
    elif mutation == "unknown_employee":
        duty["employee_targets"][0]["employee_id"] = "missing"
    elif mutation == "duplicate_employee":
        duty["employee_targets"] *= 2
    elif mutation == "empty_targets":
        duty["employee_targets"] = []
    elif mutation == "outside_period":
        duty["evaluation_period"] = interval(start=630, end=690)
    elif mutation == "misaligned":
        duty["intervals"][0]["start"] = stamp(minute=601)
    elif mutation == "past_period":
        duty["evaluation_period"]["start"] = stamp(-1)
    elif mutation == "too_many":
        data["duty_balance"] *= 21
    else:
        duty["intervals"] *= 1001
    assert validate(data)["status"] == "INVALID_INPUT"
    assert_response(solve(data), "INVALID_INPUT")


def test_union_split_break_zero_and_unreachable_targets_are_independent():
    data = cost_request()
    data["planning_window"]["end"] = stamp(2)
    data["shift_candidates"] = [
        {
            "id": "night",
            "employee_id": "alice",
            "segments": [{"interval": interval(0, 1320, 1680), "breaks": [interval(1, 120, 150)]}],
        }
    ]
    data["employees"][0]["availability"] = [interval(0, 1320, 1680)]
    data["demand"] = [demand(0, 1320, 1440)]
    add_duty(
        data,
        {"alice": 0, "bob": 240},
        [interval(0, 1320, 1560), interval(1, 0, 240), interval(1, 0, 240)],
    )
    add_duty(data, {"alice": 330}, [interval(0, 1320, 1680)], "holiday")
    result = solve(data)
    assert_response(result, "OPTIMAL")
    summary = result["duty_balance_summary"]
    assert summary[0]["intervals"] == [interval(0, 1320, 1680)]
    assert summary[0]["employees"] == [
        {
            "employee_id": "alice",
            "target_minutes": 0,
            "actual_minutes": 330,
            "deviation_minutes": 330,
        },
        {
            "employee_id": "bob",
            "target_minutes": 240,
            "actual_minutes": 0,
            "deviation_minutes": 240,
        },
    ]
    assert summary[1]["total_deviation_minutes"] == 0
    problem = normalize(data)
    problem.candidates = []
    assert evaluate(problem, result["solution"])[2]["duty_balance_summary"] == summary
    checked = verify(data, result["solution"])
    assert checked["duty_balance_summary"] == summary
    assert all(not o["proven_optimal"] for o in checked["objectives"])
    data["shift_candidates"][0]["segments"] = [
        {"interval": interval(0, 1320, 1440), "breaks": []},
        {"interval": interval(1, 120, 240), "breaks": []},
    ]
    result = solve(data)
    assert result["duty_balance_summary"][0]["employees"][0]["actual_minutes"] == 240


def test_continuity_costs_are_projected_and_duty_remains_in_planning_window():
    data = continuity_example()
    data["schema_version"] = "0.9"
    data["costs"] = {
        "currency": "JPY",
        "units_per_currency": 60,
        "employee_rates": [{"employee_id": "alice", "units_per_minute": 1800}],
    }
    data["objectives"] = [{"id": "cost", "metric": "scheduled_cost"}]
    period = {k: data["planning_window"][k] for k in ("start", "end")}
    add_duty(data, {"alice": 300}, [period])
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["cost_summary"]["total_units"] == 540000
    assert result["duty_balance_summary"][0]["employees"][0]["actual_minutes"] == 300
    assert verify(data, result["solution"])["cost_summary"] == result["cost_summary"]
    snapshot = make_baseline(data, result["solution"], "saved")
    assert validate({**data, "baseline": snapshot})["status"] == "VALID"


@pytest.mark.parametrize(
    "field", ["cost_summary", "duty_balance_summary", "objectives", "duty_id", "shift"]
)
def test_tampered_summaries_objectives_and_shifts_are_rejected(field):
    data = cost_request()
    add_duty(data, {"alice": 60})
    result = solve(data)
    if field == "cost_summary":
        result[field]["employees"][0]["units_per_minute"] += 1
    elif field == "duty_balance_summary":
        result[field][0]["employees"][0]["actual_minutes"] += 1
    elif field == "objectives":
        result[field][-1]["value"] += 1
    elif field == "duty_id":
        result["objectives"][-1]["duty_id"] = "wrong"
    else:
        result["solution"]["shifts"][0]["segments"][0]["interval"]["end"] = stamp(minute=690)
    with pytest.raises(InvalidInput):
        validate_response(result, data)


@pytest.mark.parametrize(
    "statuses",
    [
        ("FEASIBLE",),
        ("OPTIMAL", "FEASIBLE"),
        ("OPTIMAL", "UNKNOWN"),
        ("OPTIMAL", "OPTIMAL", "FEASIBLE"),
    ],
)
def test_unproven_higher_objectives_do_not_claim_cost_or_duty_optimality(monkeypatch, statuses):
    data = cost_request()
    add_duty(data, {"alice": 60})
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "FEASIBLE")
    assert len(calls) == len(statuses)
    proofs = [o["proven_optimal"] for o in result["objectives"]]
    assert proofs == ([True, False] if len(statuses) == 3 else [False, False])


@pytest.mark.parametrize(
    "version", [v for v in SCHEMA_VERSIONS if v not in {"0.9", "0.10", "0.11", "0.12"}]
)
def test_old_versions_reject_new_fields_and_objectives(version):
    data = cost_request()
    add_duty(data, {"alice": 60})
    data["schema_version"] = version
    assert_response(solve(data), "INVALID_INPUT")
    result = solve(cost_request())
    result["schema_version"] = version
    assert schema_errors("response", result, version)


def test_schema_cli_success_verify_and_solution_read_error(tmp_path):
    data = cost_request()
    add_duty(data, {"alice": 60})
    path = tmp_path / "request.json"
    path.write_text(json.dumps(data))

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "shift_schedula", *args], capture_output=True, text=True
        )

    output = cli("solve", str(path))
    assert output.returncode == 0, output.stderr
    result = json.loads(output.stdout)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(result["solution"]))
    checked = cli("verify", str(path), str(plan))
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["duty_balance_summary"] == result["duty_balance_summary"]
    broken = cli("verify", str(path), str(tmp_path / "missing.json"))
    assert broken.returncode == 2, broken.stderr
    assert not schema_errors("verification", json.loads(broken.stdout), "0.9")
    for kind in ("request", "response", "solution", "verification"):
        schema = get_schema(kind, "0.9")
        Draft202012Validator.check_schema(schema)
        fetched = cli("schema", kind, "--schema-version", "0.9")
        assert fetched.returncode == 0
        assert json.loads(fetched.stdout) == schema


@pytest.mark.parametrize("rest", [False, True])
def test_dst_uses_elapsed_minutes_for_cost_and_duty(rest):
    data = cost_request()
    window = {"start": "2026-10-25T00:00:00+02:00", "end": "2026-10-26T00:00:00+01:00"}
    span = {"start": "2026-10-25T01:00:00+02:00", "end": "2026-10-25T04:00:00+01:00"}
    breaks = (
        [{"start": "2026-10-25T02:00:00+02:00", "end": "2026-10-25T02:30:00+02:00"}] if rest else []
    )
    data["planning_window"].update(window, timezone="Europe/Berlin")
    for e in data["employees"]:
        e["availability"] = [span]
    data["shift_candidates"] = [
        {"id": "berlin", "employee_id": "alice", "segments": [{"interval": span, "breaks": breaks}]}
    ]
    data["demand"] = [
        {**demand(), "interval": {"start": span["start"], "end": "2026-10-25T02:00:00+02:00"}}
    ]
    add_duty(data, {"alice": 210 if rest else 240}, [span])
    result = solve(data)
    assert_response(result, "OPTIMAL")
    actual = 210 if rest else 240
    assert result["cost_summary"]["total_units"] == actual * 1800
    assert result["duty_balance_summary"][0]["employees"][0]["actual_minutes"] == actual
    assert (
        verify(data, result["solution"])["duty_balance_summary"] == result["duty_balance_summary"]
    )


@pytest.mark.parametrize("mode", ["preserve_assigned", "rebuild", "changes_first"])
def test_duty_keeps_fixed_baseline_and_change_priority(mode):
    data = night_request()
    old = copy.deepcopy(data)
    old["objectives"] = []
    old.pop("duty_balance")
    old["shift_candidates"] = [
        c
        for c in old["shift_candidates"]
        if c["employee_id"] == "alice"
        and c["segments"][0]["interval"]["start"][11:16] == "20:00"
        or c["employee_id"] == "bob"
        and c["segments"][0]["interval"]["start"][11:16] == "10:00"
    ]
    result = solve(old)
    assert_response(result, "OPTIMAL")
    data["baseline"] = make_baseline(old, result["solution"], "both_nights")
    if mode == "changes_first":
        data["objectives"].insert(0, {"id": "changes", "metric": "plan_changes"})
    else:
        data["replan_mode"] = mode
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["duty_balance_summary"][0]["total_deviation_minutes"] == (
        0 if mode == "rebuild" else 480
    )
    if mode == "changes_first":
        assert result["change_summary"]["total_changes"] == 0


def test_all_twenty_duties_and_six_normal_objectives_are_supported():
    data = cost_request()
    result = solve(data)
    data["baseline"] = make_baseline(data, result["solution"], "saved")
    fairness(data, {"alice": 60, "bob": 0})
    data["objectives"] += [
        {"id": m, "metric": m}
        for m in (
            "scheduled_cost",
            "scheduled_minutes",
            "role_switches",
            "plan_changes",
            "preference_penalty",
        )
    ]
    for i in range(20):
        add_duty(data, {"alice": 60}, identifier=f"duty{i}")
    assert len(data["objectives"]) == 26
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(result["duty_balance_summary"]) == 20
    assert all(o["value"] == 0 for o in result["objectives"][-20:])
    data["objectives"].append({"id": "extra", "metric": "scheduled_minutes"})
    assert validate(data)["status"] == "INVALID_INPUT"


def test_assignment_rejects_roster_metrics_and_unknown_normal_fields():
    data = cost_request()
    add_duty(data, {"alice": 60})
    data["problem_type"] = "assignment"
    data["shift_candidates"] = []
    for e in data["employees"]:
        e.pop("history")
    assert_response(solve(data), "INVALID_INPUT")
    data = cost_request()
    data["objectives"].append({"id": "duplicate_cost", "metric": "scheduled_cost"})
    assert_response(solve(data), "INVALID_INPUT")


def test_interval_union_is_360_minutes_and_independent_of_input_order():
    data = cost_request()
    data["planning_window"]["end"] = stamp(2)
    span = interval(0, 1320, 1680)
    data["employees"][0]["availability"] = [span]
    data["shift_candidates"] = [
        {"id": "overnight", "employee_id": "alice", "segments": [{"interval": span, "breaks": []}]}
    ]
    data["demand"] = [demand(0, 1320, 1440)]
    add_duty(data, {"alice": 360}, [interval(0, 1320, 1560), interval(1, 0, 240)], "scheduled_cost")
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["duty_balance_summary"][0]["employees"][0]["actual_minutes"] == 360
    data["duty_balance"][0]["intervals"].reverse()
    again = solve(data)
    assert again["duty_balance_summary"] == result["duty_balance_summary"]


def test_cost_partition_matches_original_night_and_verification_needs_no_backend(monkeypatch):
    data = continuity_example()
    data["schema_version"] = "0.9"
    data["employees"][0]["availability"][0]["start"] = "2026-10-31T00:00:00+09:00"
    data["costs"] = {
        "currency": "JPY",
        "units_per_currency": 60,
        "employee_rates": [{"employee_id": "alice", "units_per_minute": 1800}],
    }
    data["objectives"] = [{"id": "cost", "metric": "scheduled_cost"}]
    costs = []
    for start, end in (
        ("2026-10-31", "2026-11-01"),
        ("2026-11-01", "2026-11-02"),
        ("2026-10-31", "2026-11-02"),
    ):
        new = copy.deepcopy(data)
        new["planning_window"].update(start=start + "T00:00:00+09:00", end=end + "T00:00:00+09:00")
        new["demand"] = []
        result = solve(new)
        assert_response(result, "OPTIMAL")
        costs.append(result["cost_summary"]["total_units"])
    assert costs == [216000, 540000, 756000]
    from shift_schedula import cp_sat

    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("独立検証は探索しない"))
    assert verify(new, result["solution"])["cost_summary"] == result["cost_summary"]


def test_new_request_rates_exclude_employees_only_in_old_baseline():
    data = cost_request()
    result = solve(data)
    baseline = make_baseline(data, result["solution"], "old")
    new = copy.deepcopy(data)
    new["baseline"] = baseline
    new["employees"] = new["employees"][1:]
    new["shift_candidates"] = new["shift_candidates"][1:]
    new["costs"]["employee_rates"] = new["costs"]["employee_rates"][1:]
    result = solve(new)
    assert_response(result, "OPTIMAL")
    assert result["cost_summary"]["employees"] == [
        {
            "employee_id": "bob",
            "units_per_minute": 2400,
            "scheduled_minutes": 60,
            "cost_units": 144000,
        }
    ]


def test_conflict_refinement_ignores_soft_cost_and_duty_objectives():
    data = json.loads((ROOT / "examples/conflict_refinement.json").read_text())
    data["schema_version"] = "0.9"
    data["costs"] = {
        "currency": "JPY",
        "units_per_currency": 60,
        "employee_rates": [
            {"employee_id": e["id"], "units_per_minute": 1800} for e in data["employees"]
        ],
    }
    data["objectives"].append({"id": "cost", "metric": "scheduled_cost"})
    add_duty(data, {e["id"]: 30 for e in data["employees"]}, [data["constraints"][0]["interval"]])
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    assert detail["status"] == "COMPLETE", detail
    assert detail["conflict"]["minimality"] == "inclusion_minimal"
    assert all(
        c["json_pointer"].startswith("/constraints/") for c in detail["conflict"]["conditions"]
    )
