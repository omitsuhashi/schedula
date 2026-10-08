"""契約0.10の原勤務・確認済み履歴・目的順を公開入口で照合する。"""

import copy
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shift_schedula import InvalidInput, cp_sat, get_schema, make_baseline, solve, validate, verify
from shift_schedula.contract import SCHEMA_VERSIONS, schema_errors
from shift_schedula.engine import validate_response
from shift_schedula.extensions import evaluate
from shift_schedula.model import normalize
from tests.roster_support import interval, rule, stamp
from tests.support import assert_response
from tests.test_continuity import example as month_example
from tests.test_continuity import segment
from tests.test_extensions import fairness
from tests.test_objectives import control_search
from tests.test_roster_metrics import cost_request

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "examples/continuity_duty_balance.json").read_text())


def test_history_changes_choice_and_fairness_stays_in_window(monkeypatch):
    data = example()
    objectives = data["objectives"]
    fairness(data, {"alice": 0, "bob": 240})
    data["objectives"] = objectives + data["objectives"]
    saved = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert data == saved
    assert [s["employee_id"] for s in result["solution"]["shifts"]] == ["bob"]
    assert [o["value"] for o in result["objectives"]] == [0, 432000, 240, 0]
    assert [e["actual_minutes"] for e in result["duty_balance_summary"][0]["employees"]] == [
        240,
        240,
    ]
    assert result["continuity_summary"]["context_window"] == data["continuity"]["context_window"]
    assert [e["scheduled_minutes"] for e in result["fairness_summary"]["employees"]] == [0, 240]
    # モデルの候補・事実表や探索バックエンドを消しても元JSONと解だけで同じ値になる。
    problem = normalize(data)
    problem.candidates = []
    problem.continuity = []
    assert (
        evaluate(problem, result["solution"])[2]["duty_balance_summary"]
        == result["duty_balance_summary"]
    )
    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("独立検証は探索しない"))
    checked = verify(data, result["solution"])
    assert checked["status"] == "VALID"
    assert checked["duty_balance_summary"] == result["duty_balance_summary"]
    assert all(not o["proven_optimal"] for o in checked["objectives"])
    assert not checked["shortage_summary"]["proven_minimal"]


@pytest.mark.parametrize(
    "mutation",
    [
        "past",
        "commitments",
        "anchor",
        "actual",
        "rows",
        "no_context",
        "no_continuity",
        "before_context",
        "after_context",
        "outside_evaluation",
        "precision",
        "alignment",
    ],
)
def test_unconfirmed_history_and_invalid_ranges_are_rejected(mutation):
    data = example()
    duty = data["duty_balance"][0]
    row = data["continuity"]["employees"][1]
    if mutation == "past":
        row["past_complete"] = False
    elif mutation == "commitments":
        row["commitments_complete"] = False
    elif mutation == "anchor":
        row.pop("before_context")
    elif mutation == "actual":
        row.pop("actual_shifts")
    elif mutation == "rows":
        data["continuity"]["employees"].pop()
    elif mutation == "no_context":
        data["continuity"].pop("context_window")
    elif mutation == "no_continuity":
        data.pop("continuity")
        data["constraints"] = []
        for employee in data["employees"]:
            employee["availability"] = [interval(1, 0, 1440)]
            employee["history"] = {
                "last_shift_end": None,
                "last_work_day": None,
                "consecutive_work_days_before_window": 0,
            }
    elif mutation == "before_context":
        duty["evaluation_period"]["start"] = stamp(-1)
    elif mutation == "after_context":
        duty["evaluation_period"]["end"] = stamp(4)
    elif mutation == "outside_evaluation":
        duty["evaluation_period"] = interval(1, 0, 1440)
    elif mutation == "precision":
        duty["intervals"][0]["start"] = stamp(0, 1200).replace(":00+", ":01+")
    else:
        duty["intervals"][1]["start"] = stamp(1, 1201)
    result = validate(data)
    assert result["status"] == "INVALID_INPUT", result
    if mutation in {
        "past",
        "commitments",
        "anchor",
        "actual",
        "rows",
        "no_context",
        "no_continuity",
    }:
        assert result["diagnostics"][0]["code"] == "INCOMPLETE_HISTORY"
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("mode", ["preserve_assigned", "rebuild", "changes_first", "explicit"])
def test_baseline_roundtrip_preserves_history_and_hard_fixed_parts(mode):
    data = example()
    old = copy.deepcopy(data)
    old["shift_candidates"] = old["shift_candidates"][:1]
    original = solve(old)
    assert_response(original, "OPTIMAL")
    assert original["objectives"][0]["value"] == 480
    baseline = make_baseline(old, original["solution"], "alice_night")
    assert baseline["source_request"]["duty_balance"] == old["duty_balance"]
    assert baseline["source_request"]["continuity"] == old["continuity"]
    data["baseline"] = baseline
    if mode == "changes_first":
        data["objectives"].insert(0, {"id": "changes", "metric": "plan_changes"})
    elif mode == "explicit":
        data["fixed_parts"] = [
            {
                "id": "alice_fixed",
                "employee_id": "alice",
                "interval": interval(1, 1200, 1440),
                "components": ["work", "role"],
            }
        ]
    else:
        data["replan_mode"] = mode
    result = solve(data)
    assert_response(result, "OPTIMAL")
    # 固定は保持し、偏差を減らす待機勤務は許す。変更優先は待機の追加も避ける。
    assert result["duty_balance_summary"][0]["total_deviation_minutes"] == (
        0 if mode == "rebuild" else 480 if mode == "changes_first" else 240
    )
    if mode != "rebuild":
        assert any(s["employee_id"] == "alice" for s in result["solution"]["shifts"])
    if mode == "changes_first":
        assert result["change_summary"]["total_changes"] == 0
    again = make_baseline(data, result["solution"], "again")
    assert validate({**data, "baseline": again})["status"] == "VALID"
    assert again["source_request"]["duty_balance"] == data["duty_balance"]


def test_version_order_accepts_old_baselines_and_rejects_new_in_old():
    data = example()
    old = copy.deepcopy(data)
    old["schema_version"] = "0.9"
    old["duty_balance"][0]["evaluation_period"] = interval(1, 0, 1440)
    old["duty_balance"][0]["intervals"] = [interval(1, 1200, 1440)]
    baseline = make_baseline(old, solve(old)["solution"], "old")
    assert validate({**data, "baseline": baseline})["status"] == "VALID"
    old["baseline"] = make_baseline(data, solve(data)["solution"], "new")
    result = validate(old)
    assert result["status"] == "INVALID_INPUT"
    assert result["diagnostics"][0]["code"] == "UNSUPPORTED_BASELINE_VERSION"


def test_sliding_fixed_replan_keeps_original_evaluation_and_explicit_history():
    data = example()
    data["planning_window"]["end"] = stamp(3)
    data["shift_candidates"].append(
        {"id": "bob_second", "employee_id": "bob", "segments": [segment(stamp(2, 1200), stamp(3))]}
    )
    data["demand"].append(
        {**data["demand"][0], "id": "second_need", "interval": interval(2, 1200, 1440)}
    )
    data["duty_balance"][0]["intervals"].append(interval(2, 1200, 1440))
    data["duty_balance"][0]["employee_targets"][1]["target_minutes"] = 480
    old = solve(data)
    assert_response(old, "OPTIMAL")
    data["baseline"] = make_baseline(data, old["solution"], "two_days")
    data["planning_window"]["start"] = stamp(2)
    data["shift_candidates"] = data["shift_candidates"][2:]
    data["demand"] = data["demand"][1:]
    # 実績は利用側が確認して入力する。基準計画からの自動変換ではない。
    data["continuity"]["employees"][1]["actual_shifts"] = [
        {"id": "confirmed_bob", "segments": [segment(stamp(1, 1200), stamp(2))]}
    ]
    data["replan_mode"] = "preserve_assigned"
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["duty_balance_summary"][0]["total_deviation_minutes"] == 0
    assert result["change_summary"]["total_changes"] == 0
    assert result["continuity_summary"]["employees"][1]["historical_minutes"] == 240
    assert (
        validate({**data, "baseline": make_baseline(data, result["solution"], "slid")})["status"]
        == "VALID"
    )


def test_without_continuity_preserves_plan_only_metrics():
    data = cost_request()
    old = solve(data)
    data["schema_version"] = "0.10"
    new = solve(data)
    assert_response(new, "OPTIMAL")
    assert old["solution"] == new["solution"]
    assert old["cost_summary"] == new["cost_summary"]
    assert new["continuity_summary"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "summary",
        "period",
        "target",
        "continuity_summary",
        "objective",
        "baseline_history",
        "baseline_segments",
    ],
)
def test_tampering_is_detected(mutation):
    data = example()
    result = solve(data)
    if mutation.startswith("baseline"):
        data["baseline"] = make_baseline(data, result["solution"], "saved")
        if mutation == "baseline_history":
            data["baseline"]["source_request"]["continuity"]["employees"][0]["past_complete"] = (
                False
            )
        else:
            data["baseline"]["source_solution"]["shifts"][0]["segments"][0]["interval"]["end"] = (
                stamp(2, 30)
            )
        assert validate(data)["status"] == "INVALID_INPUT"
        return
    if mutation == "summary":
        result["duty_balance_summary"][0]["employees"][0]["actual_minutes"] += 1
    elif mutation == "period":
        result["duty_balance_summary"][0]["evaluation_period"] = interval(1, 0, 1440)
    elif mutation == "target":
        result["duty_balance_summary"][0]["employees"][0]["target_minutes"] += 1
    elif mutation == "continuity_summary":
        result["continuity_summary"]["employees"][0]["historical_minutes"] += 1
    else:
        result["objectives"][0]["value"] += 1
    with pytest.raises(InvalidInput):
        validate_response(result, data)


@pytest.mark.parametrize("split", [False, True])
def test_boundary_original_segments_are_counted_once_and_costs_stay_in_window(split):
    data = month_example()
    data["schema_version"] = "0.10"
    data["costs"] = {
        "currency": "JPY",
        "units_per_currency": 60,
        "employee_rates": [{"employee_id": "alice", "units_per_minute": 1800}],
    }
    data["objectives"] = [{"id": "cost", "metric": "scheduled_cost"}]
    row = data["continuity"]["employees"][0]
    if split:
        row["committed_shifts"][0]["segments"] = [
            segment("2026-10-31T22:00:00+09:00", "2026-11-01T00:00:00+09:00"),
            segment("2026-11-01T03:00:00+09:00", "2026-11-01T06:00:00+09:00"),
        ]
        data["demand"] = data["demand"][1:]
    duty = {
        "id": "night",
        "label": "夜勤",
        "evaluation_period": data["continuity"]["context_window"],
        "intervals": [{"start": "2026-10-31T22:00:00+09:00", "end": "2026-11-01T06:00:00+09:00"}],
        "employee_targets": [{"employee_id": "alice", "target_minutes": 0}],
    }
    data["duty_balance"] = [duty]
    data["objectives"].insert(
        0, {"id": "night", "metric": "duty_deviation_minutes", "duty_id": "night"}
    )
    totals, costs, planned = [], [], []
    for a, b in (
        ("2026-10-31", "2026-11-01"),
        ("2026-11-01", "2026-11-02"),
        ("2026-10-31", "2026-11-02"),
    ):
        new = copy.deepcopy(data)
        new["employees"][0]["availability"][0]["start"] = "2026-10-31T00:00:00+09:00"
        new["planning_window"].update(start=a + "T00:00:00+09:00", end=b + "T00:00:00+09:00")
        new["demand"] = []
        result = solve(new)
        assert_response(result, "OPTIMAL")
        totals.append(result["duty_balance_summary"][0]["employees"][0]["actual_minutes"])
        costs.append(result["cost_summary"]["total_units"])
        planned.append(result["cost_summary"]["employees"][0]["scheduled_minutes"])
        assert (
            verify(new, result["solution"])["duty_balance_summary"]
            == result["duty_balance_summary"]
        )
        projection = copy.deepcopy(new)
        period = {k: new["planning_window"][k] for k in ("start", "end")}
        projection["duty_balance"][0].update(evaluation_period=period, intervals=[period])
        projected = verify(projection, result["solution"])
        assert projected["duty_balance_summary"][0]["employees"][0]["actual_minutes"] == planned[-1]
    assert totals == ([300] * 3 if split else [420] * 3)
    assert planned == ([120, 180, 300] if split else [120, 300, 420])
    assert costs[0] + costs[1] == costs[2] == planned[2] * 1800
    if not split:
        assert costs == [216000, 540000, 756000]


def test_selected_night_extends_after_window_and_future_commitment_is_included():
    data = example()
    data["continuity"]["employees"][0]["actual_shifts"] = []
    data["shift_candidates"] = [
        {
            "id": "cross_end",
            "employee_id": "bob",
            "segments": [segment(stamp(1, 1320), stamp(2, 240))],
        }
    ]
    data["demand"][0]["interval"] = interval(1, 1320, 1440)
    data["continuity"]["employees"][0]["committed_shifts"] = [
        {"id": "future_alice", "segments": [segment(stamp(2, 1200), stamp(3))]}
    ]
    duty = data["duty_balance"][0]
    duty["intervals"] = [interval(1, 1320, 1680), interval(2, 1200, 1440), interval(2, 0, 180)]
    duty["employee_targets"] = [
        {"employee_id": "alice", "target_minutes": 240},
        {"employee_id": "bob", "target_minutes": 360},
    ]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [e["actual_minutes"] for e in result["duty_balance_summary"][0]["employees"]] == [
        240,
        360,
    ]
    assert result["objectives"][0]["value"] == 0
    assert result["cost_summary"]["total_units"] == 216000
    assert len(result["solution"]["shifts"]) == 1
    assert result["continuity_summary"]["employees"][0]["committed_shift_ids"] == ["future_alice"]


def test_dst_and_unaligned_outside_window_minutes_are_not_rounded():
    data = example()
    data["planning_window"].update(
        start="2026-10-25T00:00:00+02:00", end="2026-10-26T00:00:00+01:00", timezone="Europe/Berlin"
    )
    period = {"start": "2026-10-24T00:00:00+02:00", "end": "2026-10-27T00:00:00+01:00"}
    data["continuity"]["context_window"] = period
    for e, row in zip(data["employees"], data["continuity"]["employees"], strict=True):
        e["availability"] = [period]
        row["actual_shifts"] = []
        row["committed_shifts"] = []
    span = {"start": "2026-10-24T23:43:00+02:00", "end": "2026-10-25T04:00:00+01:00"}
    rest = {"start": "2026-10-25T02:00:00+02:00", "end": "2026-10-25T02:30:00+02:00"}
    data["continuity"]["employees"][0]["committed_shifts"] = [
        {"id": "dst", "segments": [{"interval": span, "breaks": [rest]}]}
    ]
    data["shift_candidates"] = []
    data["demand"] = []
    data["constraints"] = []
    duty = data["duty_balance"][0]
    duty.update(evaluation_period=period, intervals=[span, span])
    duty["employee_targets"] = [{"employee_id": "alice", "target_minutes": 287}]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 0
    assert result["duty_balance_summary"][0]["employees"][0]["actual_minutes"] == 287
    assert result["cost_summary"]["total_units"] == 270 * 1800
    assert result["continuity_summary"]["employees"][0]["historical_minutes"] == 17
    assert (
        verify(data, result["solution"])["duty_balance_summary"] == result["duty_balance_summary"]
    )


@pytest.mark.parametrize(
    "order",
    list(
        itertools.permutations(("duty_deviation_minutes", "scheduled_cost", "preference_penalty"))
    ),
)
def test_combined_priority_and_user_objectives_match_exhaustive_choices(order):
    data = example()
    data["demand"].append(
        {**data["demand"][0], "id": "hall_need", "role_id": "hall", "priority": 0}
    )
    data["shift_candidates"] = data["shift_candidates"][1:]
    data["roles"][0]["required_skills"] = []
    data["preferences"] = [
        {
            "id": "avoid_kitchen",
            "type": "avoid_role",
            "employee_ids": ["bob"],
            "role_id": "kitchen",
            "penalty_per_minute": 1,
        }
    ]
    by_metric = {o["metric"]: o for o in data["objectives"]}
    by_metric["preference_penalty"] = {"id": "wishes", "metric": "preference_penalty"}
    data["objectives"] = [by_metric[m] for m in order]
    # 各30分枠はoff/kitchen/hall。勤務なしの場合も列挙し、巨大な重みを使わない。
    choices = []
    for assignment in itertools.product((None, "kitchen", "hall"), repeat=8):
        high = assignment.count("kitchen")
        low = assignment.count("hall")
        metrics = {
            "duty_deviation_minutes": 0,
            "scheduled_cost": 432000,
            "preference_penalty": high * 30,
        }
        choices.append(
            (480 - (high + low) * 30, (8 - high) * 30, (8 - low) * 30, *(metrics[m] for m in order))
        )
    metrics = {"duty_deviation_minutes": 240, "scheduled_cost": 0, "preference_penalty": 0}
    choices.append((480, 240, 240, *(metrics[m] for m in order)))
    result = solve(data)
    assert_response(result, "PARTIAL")
    actual = (
        result["shortage_summary"]["total_person_minutes"],
        *(g["total_person_minutes"] for g in result["priority_summary"]["groups"]),
        *(o["value"] for o in result["objectives"]),
    )
    assert actual == min(choices)
    assert verify(data, result["solution"])["status"] == "PARTIAL"


@pytest.mark.parametrize("constraint", ["upper", "lower", "rest", "days"])
def test_unreachable_targets_do_not_relax_hard_constraints(constraint):
    data = example()
    if constraint == "upper":
        data["constraints"].append(rule("max_scheduled_minutes", 0, ("bob",), "bob_cap"))
    elif constraint == "lower":
        data["constraints"].append(
            {
                "id": "alice_min",
                "type": "scheduled_minutes_bounds",
                "employee_ids": ["alice"],
                "interval": interval(1, 0, 1440),
                "min_minutes": 240,
            }
        )
    else:
        data["shift_candidates"] = data["shift_candidates"][1:]
        row = data["continuity"]["employees"][1]
        row["actual_shifts"] = [{"id": "bob_past", "segments": [segment(stamp(0, 1200), stamp(1))]}]
        data["constraints"].append(
            rule("min_rest_minutes", 1500, ("bob",), "rest_long")
            if constraint == "rest"
            else rule("max_consecutive_days", 1, ("bob",), "days_short")
        )
    result = solve(data)
    assert_response(result, "OPTIMAL" if constraint in {"upper", "lower"} else "PARTIAL")
    assert result["duty_balance_summary"][0]["total_deviation_minutes"] == (
        480 if constraint == "upper" else 240 if constraint == "lower" else 0
    )
    assert result["shortage_summary"]["total_person_minutes"] == (
        0 if constraint in {"upper", "lower"} else 240
    )


@pytest.mark.parametrize(
    "statuses",
    [
        ("UNKNOWN",),
        ("FEASIBLE",),
        ("OPTIMAL", "UNKNOWN"),
        ("OPTIMAL", "OPTIMAL", "FEASIBLE"),
        ("OPTIMAL", "OPTIMAL", "OPTIMAL", "UNKNOWN"),
    ],
)
def test_unknown_and_time_limited_prefix_do_not_claim_lower_optimality(monkeypatch, statuses):
    data = example()
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "UNKNOWN" if statuses == ("UNKNOWN",) else "FEASIBLE")
    assert len(calls) == len(statuses)
    if result["solution"]:
        # 総不足・priority群の二段の後だけ利用者の目的を証明する。
        assert [o["proven_optimal"] for o in result["objectives"]] == (
            [True, False, False] if len(statuses) == 4 else [False] * 3
        )
        assert result["duty_balance_summary"] is not None
    else:
        assert result["duty_balance_summary"] is None


def test_conflict_refinement_preserves_history_and_commitment_background():
    data = example()
    data["continuity"]["employees"][1]["committed_shifts"] = [
        {"id": "bob_fixed", "segments": data["shift_candidates"][1]["segments"]}
    ]
    data["shift_candidates"] = data["shift_candidates"][:1]
    data["constraints"].append(rule("max_scheduled_minutes", 0, ("bob",), "bob_cap"))
    data["diagnosis"] = {
        "time_limit_seconds": 10,
        "max_suggestions": 0,
        "allowed_changes": [],
        "conflict_refinement": {"time_limit_seconds": 5},
    }
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert result["diagnosis_result"]["status"] == "COMPLETE"
    assert conflict["minimality"] == "inclusion_minimal"
    assert any(
        c["json_pointer"].endswith("/actual_shifts/0") for c in conflict["background_conditions"]
    )
    assert any(
        c["json_pointer"].endswith("/committed_shifts/0") for c in conflict["background_conditions"]
    )
    assert [c["related_ids"][0] for c in conflict["conditions"]] == ["bob_cap"]
    validate_response(result, data)


@pytest.mark.parametrize("version", [v for v in SCHEMA_VERSIONS if v != "0.10"])
def test_older_versions_reject_history_evaluation(version):
    data = example()
    data["schema_version"] = version
    assert_response(solve(data), "INVALID_INPUT")


def test_cli_schema_and_verification_failures(tmp_path):
    data = example()
    request = tmp_path / "request.json"
    request.write_text(json.dumps(data))
    result = solve(data)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(result["solution"]))
    for args, code in (
        (["solve", str(request)], 0),
        (["verify", str(request), str(plan)], 0),
        (["verify", str(request), str(tmp_path / "missing")], 2),
    ):
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", *args], capture_output=True, text=True
        )
        assert completed.returncode == code, completed.stderr
        response = json.loads(completed.stdout)
        assert not schema_errors(
            "response" if args[0] == "solve" else "verification", response, "0.10"
        )
    for kind in ("request", "response", "solution", "verification"):
        schema = get_schema(kind, "0.10")
        Draft202012Validator.check_schema(schema)
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.10"],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == schema
