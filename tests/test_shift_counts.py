"""回数の尺度・履歴・開始日・目的順を元JSONと公開入口で確認する。"""

import copy
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shift_schedula import InvalidInput, cp_sat, get_schema, make_baseline, solve, validate, verify
from shift_schedula.contract import SCHEMA_VERSIONS, schema_errors
from shift_schedula.engine import validate_response
from shift_schedula.extensions import evaluate
from shift_schedula.model import normalize
from tests.roster_support import demand, interval, stamp
from tests.support import assert_response
from tests.test_continuity import segment
from tests.test_day_counts import example as days_example
from tests.test_day_counts import selected
from tests.test_extensions import fairness
from tests.test_objectives import control_search
from tests.test_roster_metrics import add_duty

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "examples/shift_count_balance.json").read_text())


def balance(data, targets, identifier="all", category=None, period=None):
    data.setdefault("shift_count_balance", []).append(
        {
            "id": identifier,
            "label": identifier,
            "evaluation_period": period
            or {k: data["planning_window"][k] for k in ("start", "end")},
            **({"category_id": category} if category else {}),
            "employee_targets": [{"employee_id": e, "target_count": t} for e, t in targets.items()],
        }
    )
    data["objectives"].append(
        {"id": f"balance_{identifier}", "metric": "shift_count_deviation", "balance_id": identifier}
    )


def test_history_changes_choice_and_verify_does_not_read_model_coefficients(monkeypatch):
    data = example()
    saved = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert data == saved
    assert [s["employee_id"] for s in result["solution"]["shifts"]] == ["bob"]
    summary = result["shift_count_balance_summary"]
    assert [e["actual_count"] for e in summary[0]["employees"]] == [1, 1]
    assert summary[0]["total_deviation_count"] == 0
    problem = normalize(data)
    problem.candidates = []
    problem.continuity = []
    assert evaluate(problem, result["solution"])[2]["shift_count_balance_summary"] == summary
    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("独立検証は探索しない"))
    checked = verify(data, result["solution"])
    assert checked["status"] == "VALID"
    assert checked["shift_count_balance_summary"] == summary
    assert all(not o["proven_optimal"] for o in checked["objectives"])


def test_equal_minutes_different_counts_split_shift_and_zero_target():
    data = days_example(3, ("alice", "bob", "excluded"))
    data["schema_version"] = "0.15"
    data["shift_candidates"] = [
        {
            "id": "long",
            "employee_id": "alice",
            "segments": [segment(stamp(0, 1200), stamp(1, 240))],
        },
        {"id": "short", "employee_id": "bob", "segments": [segment(stamp(0, 1200), stamp(1))]},
        {
            "id": "split",
            "employee_id": "bob",
            "segments": [
                segment(stamp(1, 1200), stamp(1, 1320)),
                segment(stamp(1, 1380), stamp(2, 60)),
            ],
        },
    ]
    data["shift_categories"] = [
        {
            "id": "night",
            "label": "夜勤",
            "intervals": [interval(0, 0, 4320)],
            "min_overlap_minutes": 60,
        }
    ]
    balance(data, {"alice": 1, "bob": 1}, "night", "night")
    balance(data, {"alice": 0}, "zero")
    solution = {"assignments": [], "shifts": [selected(c) for c in data["shift_candidates"]]}
    checked = verify(data, solution)
    assert checked["status"] == "VALID", checked
    assert [e["actual_count"] for e in checked["shift_count_balance_summary"][0]["employees"]] == [
        1,
        2,
    ]
    assert checked["shift_count_balance_summary"][0]["total_deviation_count"] == 1
    assert checked["shift_count_balance_summary"][1]["total_deviation_count"] == 1
    assert checked["objectives"][0]["value"] == 960


@pytest.mark.parametrize("overlap,expected", [(59, 0), (60, 1)])
def test_classification_union_breaks_and_threshold(overlap, expected):
    data = days_example(1)
    data["schema_version"] = "0.15"
    data["planning_window"]["slot_minutes"] = 1
    span = interval(0, 600, 600 + overlap + 30)
    data["shift_candidates"] = [
        {
            "id": "shift",
            "employee_id": "alice",
            "segments": [{"interval": span, "breaks": [interval(0, 620, 650)]}],
        }
    ]
    data["shift_categories"] = [
        {
            "id": "night",
            "label": "表示名は推測に使わない",
            "intervals": [span, span],
            "min_overlap_minutes": 60,
        }
    ]
    balance(data, {"alice": 1}, "night", "night")
    solution = {"assignments": [], "shifts": [selected(data["shift_candidates"][0])]}
    checked = verify(data, solution)
    assert checked["status"] == "VALID", checked
    assert checked["shift_count_balance_summary"][0]["employees"][0]["actual_count"] == expected
    data["objectives"] = data["objectives"][1:]
    solved = solve(data)
    assert_response(solved, "OPTIMAL")
    assert solved["objectives"][0]["value"] == 1 - expected


def test_committed_original_start_partitions_counts_before_classification_cut():
    data = example()
    data["shift_candidates"] = []
    data["demand"] = []
    data["constraints"] = []
    data.pop("costs")
    data.pop("duty_balance")
    data["objectives"] = []
    data.pop("shift_count_balance")
    data["continuity"]["employees"][0]["actual_shifts"] = []
    fact = {"id": "cross_boundary", "segments": [segment(stamp(0, 1320), stamp(1, 360))]}
    data["continuity"]["employees"][0]["committed_shifts"] = [fact]
    data["shift_categories"][0]["intervals"] = [interval(1, 0, 360)]
    for first, last, identifier in ((0, 1, "before"), (1, 3, "after"), (0, 3, "whole")):
        balance(data, {"alice": 0}, identifier, "night", interval(first, 0, (last - first) * 1440))
    result = solve(data)
    assert_response(result, "OPTIMAL")
    counts = [s["employees"][0]["actual_count"] for s in result["shift_count_balance_summary"]]
    assert counts == [1, 0, 1]
    assert len(result["solution"]["shifts"]) == 1
    assert (
        verify(data, result["solution"])["shift_count_balance_summary"]
        == result["shift_count_balance_summary"]
    )
    # W外のみの確定勤務も評価する。
    data["continuity"]["employees"][1]["committed_shifts"] = [
        {"id": "future", "segments": [segment(stamp(2, 1200), stamp(3))]}
    ]
    data["shift_categories"][0]["intervals"].append(interval(2, 1200, 1440))
    balance(data, {"bob": 1}, "future", "night")
    data["shift_count_balance"][-1]["evaluation_period"] = interval(0, 0, 4320)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["shift_count_balance_summary"][-1]["employees"][0]["actual_count"] == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_small_exhaustive_objective_order_and_shortage_are_independent(reverse):
    data = days_example(3, ("alice", "bob"))
    data["schema_version"] = "0.15"
    data["shift_candidates"] = [
        {
            "id": f"{e}_{d}",
            "employee_id": e,
            "segments": [segment(stamp(d, 600), stamp(d, 630 if e == "alice" else 660))],
        }
        for e in ("alice", "bob")
        for d in range(3)
    ]
    data["demand"] = [dict(demand(d), minimum_people=1, priority=d % 2) for d in range(3)]
    balance(data, {"alice": 0, "bob": 3})
    if reverse:
        data["objectives"].reverse()
    values = []
    # 元JSONの全64候補部分集合。ソルバー・候補係数・verifyから期待値を取らない。
    for bits in itertools.product((0, 1), repeat=6):
        rows = [c for c, bit in zip(data["shift_candidates"], bits, strict=True) if bit]
        if any(
            not any(c["segments"][0]["interval"]["start"][:10] == stamp(d)[:10] for c in rows)
            for d in range(3)
        ):
            continue
        actual = {e: sum(c["employee_id"] == e for c in rows) for e in ("alice", "bob")}
        count_value = actual["alice"] + abs(actual["bob"] - 3)
        minutes_value = actual["alice"] * 30 + actual["bob"] * 60
        values.append((count_value, minutes_value) if reverse else (minutes_value, count_value))
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert tuple(o["value"] for o in result["objectives"]) == min(values)
    assert result["shortage_summary"]["total_person_minutes"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "empty",
        "null_category",
        "unknown_category",
        "duplicate",
        "duplicate_employee",
        "unknown_employee",
        "no_definition",
        "no_objective",
        "duplicate_objective",
        "wrong_metric",
        "midday",
        "outside",
        "reverse",
        "unknown_field",
        "missing_target",
        "empty_targets",
        "past_unconfirmed",
        "future_unconfirmed",
    ],
)
def test_invalid_count_inputs(mutation):
    data = example()
    definition = data["shift_count_balance"][0]
    if mutation == "unknown":
        data["unexpected"] = 1
    elif mutation == "empty":
        data["shift_count_balance"] = []
    elif mutation == "null_category":
        definition["category_id"] = None
    elif mutation == "unknown_category":
        definition["category_id"] = "missing"
    elif mutation == "duplicate":
        data["shift_count_balance"] *= 2
    elif mutation == "duplicate_employee":
        definition["employee_targets"] *= 2
    elif mutation == "unknown_employee":
        definition["employee_targets"][0]["employee_id"] = "missing"
    elif mutation == "no_definition":
        data.pop("shift_count_balance")
    elif mutation == "no_objective":
        data["objectives"].pop(0)
    elif mutation == "duplicate_objective":
        data["objectives"].append({**data["objectives"][0], "id": "again"})
    elif mutation == "wrong_metric":
        data["objectives"][1]["balance_id"] = "night_count"
    elif mutation == "midday":
        definition["evaluation_period"]["start"] = stamp(0, 30)
    elif mutation == "outside":
        definition["evaluation_period"]["start"] = stamp(-1)
    elif mutation == "reverse":
        definition["evaluation_period"]["end"] = definition["evaluation_period"]["start"]
    elif mutation == "unknown_field":
        definition["formula"] = "count()"
    elif mutation == "missing_target":
        definition["employee_targets"][0].pop("target_count")
    elif mutation == "empty_targets":
        definition["employee_targets"] = []
    elif mutation == "past_unconfirmed":
        data["continuity"]["employees"][0]["past_complete"] = False
    else:
        data["continuity"]["employees"][0]["commitments_complete"] = False
    assert validate(data)["status"] == "INVALID_INPUT"
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("target", [True, False, 1.0, -1, 10_000_001, None])
def test_invalid_targets(target):
    data = example()
    data["shift_count_balance"][0]["employee_targets"][0]["target_count"] = target
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize("mode", ["preserve_assigned", "rebuild", "changes_first"])
def test_baseline_retains_classification_targets_and_fixed_state(mode):
    data = example()
    old = copy.deepcopy(data)
    old["shift_candidates"] = old["shift_candidates"][:1]
    original = solve(old)
    data["baseline"] = make_baseline(old, original["solution"], "old")
    assert data["baseline"]["source_request"]["shift_count_balance"] == old["shift_count_balance"]
    if mode == "changes_first":
        data["objectives"].insert(0, {"id": "changes", "metric": "plan_changes"})
    else:
        data["replan_mode"] = mode
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert any(s["employee_id"] == "alice" for s in result["solution"]["shifts"]) == (
        mode != "rebuild"
    )
    if mode == "changes_first":
        assert result["change_summary"]["total_changes"] == 0
    data["baseline"] = make_baseline(data, result["solution"], "again")
    assert validate(data)["status"] == "VALID"
    data["shift_categories"][0]["min_overlap_minutes"] = 300
    assert data["baseline"]["source_request"]["shift_categories"][0]["min_overlap_minutes"] == 60


def test_summary_and_objective_tampering_are_rejected():
    data = example()
    for field in ("summary", "objective", "reference"):
        result = solve(data)
        if field == "summary":
            result["shift_count_balance_summary"][0]["employees"][0]["actual_count"] += 1
        elif field == "objective":
            result["objectives"][0]["value"] += 1
        else:
            result["objectives"][0]["balance_id"] = "wrong"
        with pytest.raises(InvalidInput):
            validate_response(result, data)


@pytest.mark.parametrize("statuses", [("FEASIBLE",), ("OPTIMAL", "UNKNOWN"), ("UNKNOWN",)])
def test_shared_budget_proof_prefix_and_null_on_no_plan(monkeypatch, statuses):
    data = example()
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "UNKNOWN" if statuses[0] == "UNKNOWN" else "FEASIBLE")
    assert len(calls) == len(statuses)
    if result["solution"] is None:
        assert result["shift_count_balance_summary"] is None
    else:
        assert all(not o["proven_optimal"] for o in result["objectives"])


def test_twenty_counts_twenty_duties_and_six_normal_objectives():
    data = days_example(1, ("alice", "bob"))
    data["schema_version"] = "0.15"
    data["baseline"] = make_baseline(data, solve(data)["solution"], "empty")
    fairness(data, {"alice": 0})
    data["costs"] = {
        "currency": "JPY",
        "units_per_currency": 1,
        "employee_rates": [
            {"employee_id": e["id"], "units_per_minute": 0} for e in data["employees"]
        ],
    }
    data["objectives"] += [
        {"id": m, "metric": m}
        for m in (
            "scheduled_minutes",
            "scheduled_cost",
            "role_switches",
            "plan_changes",
            "preference_penalty",
        )
    ]
    for i in range(20):
        balance(data, {"alice": 10_000_000}, f"count{i}")
        add_duty(data, {"alice": 0}, identifier=f"duty{i}")
    assert len(data["objectives"]) == 46
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(result["shift_count_balance_summary"]) == 20
    assert all(
        s["total_deviation_count"] == 10_000_000 for s in result["shift_count_balance_summary"]
    )
    data["objectives"].append({"id": "extra", "metric": "role_switches"})
    assert validate(data)["status"] == "INVALID_INPUT"


def test_versions_schemas_and_cli_failure_shapes(tmp_path):
    data = example()
    for version in SCHEMA_VERSIONS[:-1]:
        assert schema_errors("request", {**data, "schema_version": version})
    result = solve(data)
    for kind, value in (
        ("request", data),
        ("response", result),
        ("solution", result["solution"]),
        ("verification", verify(data, result["solution"])),
    ):
        assert get_schema(kind, "0.15")["$id"].endswith(":0.15")
        assert not schema_errors(kind, value, "0.15")
    path = tmp_path / "request.json"
    path.write_text(json.dumps(data))
    missing = subprocess.run(
        [
            sys.executable,
            "-m",
            "shift_schedula",
            "verify",
            str(path),
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2
    checked = json.loads(missing.stdout)
    assert checked["shift_count_balance_summary"] is None
    assert not schema_errors("verification", checked, "0.15")


def test_dst_elapsed_minutes_differ_but_each_original_duty_counts_once():
    data = days_example(3)
    data["schema_version"] = "0.15"
    period = {"start": "2026-10-31T00:00:00-04:00", "end": "2026-11-03T00:00:00-05:00"}
    data["planning_window"].update(**period, timezone="America/New_York")
    data["employees"][0]["availability"] = [period]
    data["shift_candidates"] = [
        {
            "id": "fall_back",
            "employee_id": "alice",
            "segments": [segment("2026-10-31T22:00:00-04:00", "2026-11-01T06:00:00-05:00")],
        },
        {
            "id": "ordinary",
            "employee_id": "alice",
            "segments": [segment("2026-11-01T22:00:00-05:00", "2026-11-02T06:00:00-05:00")],
        },
    ]
    balance(data, {"alice": 2})
    data["objectives"].reverse()
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [o["value"] for o in result["objectives"]] == [0, 1020]
    assert result["shift_count_balance_summary"][0]["employees"][0]["actual_count"] == 2
    assert (
        verify(data, result["solution"])["shift_count_balance_summary"]
        == result["shift_count_balance_summary"]
    )


def test_assignment_rejects_counts_and_newer_baseline_is_rejected_by_old_version():
    data = days_example(1)
    data["schema_version"] = "0.15"
    balance(data, {"alice": 1})
    result = solve(data)
    baseline = make_baseline(data, result["solution"], "new")
    old = copy.deepcopy(data)
    old["schema_version"] = "0.14"
    old.pop("shift_count_balance")
    old["objectives"] = old["objectives"][:1]
    old["baseline"] = baseline
    assert validate(old)["diagnostics"][0]["code"] == "UNSUPPORTED_BASELINE_VERSION"
    data["problem_type"] = "assignment"
    data["shift_candidates"] = []
    for employee in data["employees"]:
        employee.pop("history")
    assert_response(solve(data), "INVALID_INPUT")
