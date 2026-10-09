"""契約0.4の業務条件・再計画・公開検証を外部入口から確認する。"""

import copy
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shift_schedula import cp_sat, get_schema, make_baseline, solve, verify
from shift_schedula.contract import SCHEMA_VERSIONS, InvalidInput, schema_errors
from shift_schedula.engine import validate_response
from shift_schedula.model import normalize
from tests.roster_support import demand, interval, request, stamp, template
from tests.support import assert_response
from tests.test_extensions import extended, selected


def current(data=None):
    data = extended(request() if data is None else data)
    data["schema_version"] = "0.4"
    return data


def bounds(
    start=600, end=690, minimum=None, maximum=None, employees=("alice",), identifier="bounds"
):
    result = {
        "id": identifier,
        "type": "scheduled_minutes_bounds",
        "employee_ids": list(employees),
        "interval": interval(start=start, end=end),
    }
    if minimum is not None:
        result["min_minutes"] = minimum
    if maximum is not None:
        result["max_minutes"] = maximum
    return result


def preference(
    kind="avoid_work", start=600, end=690, employees=("alice",), penalty=1, identifier="wish"
):
    return {
        "id": identifier,
        "type": kind,
        "employee_ids": list(employees),
        "interval": interval(start=start, end=end),
        "penalty_per_minute": penalty,
    }


@pytest.mark.parametrize("version", SCHEMA_VERSIONS)
def test_candidate_count_removed_for_explicit_generated_and_selected_shifts(version):
    data = request()
    if version != "0.1":
        data = extended(data)
    data["schema_version"] = version
    data["shift_candidates"] = [
        {**data["shift_candidates"][0], "id": f"choice_{i}"} for i in range(5001)
    ]
    data["demand"] = [demand()]
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(normalize(data).candidates) == 5001
    assert data == original
    data["shift_candidates"][0]["employee_id"] = "missing"
    assert_response(solve(data), "INVALID_INPUT")
    many = request(days=21, employees=tuple(f"e{i}" for i in range(239)))
    if version != "0.1":
        many = extended(many)
    many["schema_version"] = version
    solution = {"assignments": [], "shifts": [selected(c) for c in many["shift_candidates"]]}
    assert len(solution["shifts"]) == 5019
    assert not schema_errors("solution", solution, version)
    assert verify(many, solution)["status"] == "VALID"
    generated = request(days=30, employees=tuple(f"e{i}" for i in range(100)))
    generated["roles"] = generated["roles"][:1]
    generated["shift_candidates"] = []
    generated["shift_templates"] = [
        template(
            tuple(e["id"] for e in generated["employees"]),
            tuple(stamp(d)[:10] for d in range(30)),
            starts=("10:00", "10:30"),
            durations=(60,),
        )
    ]
    if version != "0.1":
        generated = extended(generated)
        t = generated["shift_templates"][0]
        t.pop("duration_minutes_options")
        t.pop("break_options")
        t["segment_options"] = [[{"offset_minutes": 0, "duration_minutes": 60, "breaks": []}]]
    generated["schema_version"] = version
    assert len(normalize(generated).candidates) == 6000


@pytest.mark.parametrize("version", ["0.1", "0.2", "0.3"])
@pytest.mark.parametrize("field", ["replan_mode", "bounds", "preference"])
def test_new_conditions_rejected_by_old_versions(version, field):
    data = request() if version == "0.1" else extended(request())
    data["schema_version"] = version
    if field == "replan_mode":
        data[field] = "rebuild"
    elif field == "bounds":
        data["constraints"] = [bounds(minimum=0)]
    else:
        data["preferences"] = [preference()]
        data["objectives"].insert(0, {"id": "wishes", "metric": "preference_penalty"})
    assert_response(solve(data), "INVALID_INPUT")


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("contradiction", "INVALID_MINUTES_BOUNDS"),
        ("unknown", "UNKNOWN_REFERENCE"),
        ("outside", "INVALID_INTERVAL"),
        ("misaligned", "MISALIGNED_INTERVAL"),
        ("empty", "SCHEMA_VIOLATION"),
        ("null", "SCHEMA_VIOLATION"),
        ("assignment", "UNSUPPORTED_CONDITION"),
    ],
)
def test_bounds_validation(mutation, code):
    data = current()
    item = bounds(minimum=0, maximum=90)
    data["constraints"] = [item]
    if mutation == "contradiction":
        item["min_minutes"] = 91
    elif mutation == "unknown":
        item["employee_ids"] = ["missing"]
    elif mutation == "outside":
        item["interval"]["start"] = stamp(-1)
    elif mutation == "misaligned":
        item["interval"]["start"] = stamp(0, 601)
    elif mutation == "empty":
        item.pop("min_minutes")
        item.pop("max_minutes")
    elif mutation == "null":
        item["min_minutes"] = None
    else:
        data["problem_type"] = "assignment"
        data["shift_candidates"] = []
        for e in data["employees"]:
            e.pop("history")
        data["objectives"] = []
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == code


@pytest.mark.parametrize(
    "minimum,maximum,status",
    [
        (89, None, "OPTIMAL"),
        (90, 90, "OPTIMAL"),
        (91, None, "INFEASIBLE"),
        (None, 89, "PARTIAL"),
        (None, 90, "OPTIMAL"),
        (0, 0, "PARTIAL"),
    ],
)
def test_bounds_boundary_and_standby_are_hard(minimum, maximum, status):
    data = current()
    data["demand"] = [demand()]
    data["constraints"] = [bounds(minimum=minimum, maximum=maximum)]
    result = solve(data)
    assert_response(result, status)
    if status == "OPTIMAL":
        assert result["objectives"][0]["value"] == 90  # 担当30分・待機60分。
        assert verify(data, result["solution"])["status"] == "VALID"
    tampered = {"assignments": [], "shifts": [selected(data["shift_candidates"][0])]}
    if maximum is not None and maximum < 90:
        assert any(
            v["code"] == "MAX_SCHEDULED_MINUTES_VIOLATION"
            for v in verify(data, tampered)["verification"]["violations"]
        )
    if minimum:
        empty = verify(data, {"assignments": [], "shifts": []})
        assert empty["status"] == "INVALID_PLAN"
        assert any(
            v["code"] == "MIN_SCHEDULED_MINUTES_VIOLATION"
            for v in empty["verification"]["violations"]
        )


def test_multiple_periods_month_boundary_and_overlapping_bounds():
    data = current(request(days=30))
    data["constraints"] = [bounds(minimum=180, maximum=180)]
    data["constraints"][0]["interval"] = interval(0, 0, 7 * 1440)
    data["constraints"].append(
        {
            **bounds(minimum=90, maximum=90, identifier="overlap"),
            "interval": interval(0, 0, 2 * 1440),
        }
    )
    data["constraints"].append(
        {**bounds(minimum=90, identifier="month_edge"), "interval": interval(26, 0, 3 * 1440)}
    )
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 270
    assert verify(data, result["solution"])["status"] == "VALID"


def test_preferred_work_uses_standby_but_never_excess_assignment():
    data = current()
    data["preferences"] = [preference("prefer_work")]
    data["objectives"].insert(0, {"id": "wishes", "metric": "preference_penalty"})
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [o["value"] for o in result["objectives"]] == [0, 90]
    assert result["solution"]["assignments"] == []
    data["preferences"] = [preference("avoid_work")]
    result = solve(data)
    assert result["solution"] == {"assignments": [], "shifts": []}
    data["demand"] = [demand()]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 90


def test_avoid_work_selects_alternative_and_shortage_remains_first():
    data = current(request(employees=("alice", "bob")))
    data["demand"] = [demand()]
    data["preferences"] = [preference(penalty=10000)]
    data["objectives"].insert(0, {"id": "wishes", "metric": "preference_penalty"})
    result = solve(data)
    assert result["solution"]["assignments"][0]["employee_id"] == "bob"
    data["shift_candidates"] = data["shift_candidates"][:1]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 900000
    assert result["shortage_summary"]["total_person_minutes"] == 0


def test_break_split_overnight_preferences_and_bounds_use_elapsed_overlap():
    root = Path(__file__).resolve().parents[1]
    for filename in ("overnight.json", "split_roster.json"):
        data = json.loads((root / "examples" / filename).read_text())
        period = {k: data["planning_window"][k] for k in ("start", "end")}
        data["constraints"] = [{**bounds(minimum=420, maximum=420), "interval": period}]
        data["preferences"] = [
            {**preference("prefer_work", penalty=2), "interval": period},
            {**preference("avoid_work", penalty=3, identifier="avoid"), "interval": period},
        ]
        data["objectives"].insert(0, {"id": "wishes", "metric": "preference_penalty"})
        result = solve(data)
        assert_response(result, "OPTIMAL")
        expected = normalize(data).grid.slots * 30 * 2 + 420
        assert result["objectives"][0]["value"] == expected
        assert verify(data, result["solution"])["objectives"][0]["value"] == expected
        result["objectives"][0]["value"] += 1
        with pytest.raises(InvalidInput):
            validate_response(result, data)


def test_clock_change_work_bounds_and_preferences_count_elapsed_minutes():
    data = current()
    window = {"start": "2026-11-01T00:00:00-04:00", "end": "2026-11-02T00:00:00-05:00"}
    work = {"start": "2026-11-01T01:30:00-04:00", "end": "2026-11-01T01:30:00-05:00"}
    data["planning_window"].update(window, timezone="America/New_York")
    data["employees"][0]["availability"] = [work]
    data["shift_candidates"][0]["segments"] = [{"interval": work, "breaks": []}]
    data["constraints"] = [{**bounds(minimum=60, maximum=60), "interval": work}]
    data["preferences"] = [{**preference("prefer_work"), "interval": work}]
    data["objectives"].insert(0, {"id": "wishes", "metric": "preference_penalty"})
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [o["value"] for o in result["objectives"]] == [0, 60]


def test_small_exhaustive_work_conditions_match_solver():
    # 生の区間から候補の勤務枠を列挙し、独立検証器を期待値の計算に使わない。
    for lower, upper, need in itertools.product((0, 60, 90, 120), (60, 90), (0, 1, 2)):
        data = current(request(employees=("alice", "bob")))
        data["demand"] = [demand(end=690, people=need)]
        data["constraints"] = [bounds(minimum=lower, maximum=upper)]
        data["preferences"] = [
            preference("prefer_work", end=660, penalty=2),
            preference("avoid_work", start=630, penalty=3, identifier="avoid"),
        ]
        data["objectives"].insert(0, {"id": "wishes", "metric": "preference_penalty"})
        if lower > upper:
            assert_response(solve(data), "INVALID_INPUT")
            continue
        expected = []
        for alice, bob in itertools.product((0, 1), repeat=2):
            minutes = 90 * alice
            if not lower <= minutes <= upper:
                continue
            shortage = max(0, need - alice - bob) * 90
            penalty = (60 - 60 * alice) * 2 + 60 * alice * 3
            expected.append((shortage, penalty, 90 * (alice + bob)))
        result = solve(data)
        if not expected:
            assert_response(result, "INFEASIBLE")
        else:
            actual = (
                result["shortage_summary"]["total_person_minutes"],
                *(o["value"] for o in result["objectives"]),
            )
            assert actual == min(expected)


def replan_case():
    old = current(request(employees=("alice", "bob")))
    old["employees"][1]["availability"] = []
    old["shift_candidates"] = old["shift_candidates"][:1]
    old["demand"] = [demand(), demand(role="hall")]
    old["objectives"] = []
    solution = {
        "assignments": [
            {"employee_id": "alice", "role_id": "kitchen", "interval": interval(end=630)}
        ],
        "shifts": [selected(old["shift_candidates"][0])],
    }
    data = current(request(employees=("alice", "bob")))
    data["roles"][1]["required_skills"] = [{"skill_id": "hall_skill", "min_level": 1}]
    data["skills"] = [{"id": "hall_skill", "label": "ホール技能"}]
    data["employees"][0]["skills"] = [{"skill_id": "hall_skill", "level": 1}]
    data["demand"] = copy.deepcopy(old["demand"])
    data["baseline"] = make_baseline(old, solution, "partial_plan")
    data["objectives"] = [{"id": "work", "metric": "scheduled_minutes"}]
    return data


def test_preserve_vs_rebuild_comparison_and_repeated_snapshots():
    data = replan_case()
    original = copy.deepcopy(data)
    data["replan_mode"] = "preserve_assigned"
    fixed = solve(data)
    assert_response(fixed, "PARTIAL")
    assert fixed["shortage_summary"]["total_person_minutes"] == 30
    assert fixed["solution"]["assignments"][0]["employee_id"] == "alice"
    assert verify(data, fixed["solution"])["status"] == "PARTIAL"
    snapshot = make_baseline(data, fixed["solution"], "second_plan")
    assert snapshot["source_fixed_states"]
    assert "baseline" not in snapshot["source_request"]
    assert snapshot["snapshot_origin"]["baseline_plan_id"] == "partial_plan"
    data["baseline"] = json.loads(json.dumps(snapshot))
    again = solve(data)
    assert_response(again, "PARTIAL")
    assert again["change_summary"]["total_changes"] == 0
    snapshot2 = make_baseline(data, again["solution"], "third_plan")
    assert len(snapshot2["source_fixed_states"]) == len(snapshot["source_fixed_states"])
    data = {**original, "replan_mode": "rebuild"}
    rebuilt = solve(data)
    assert_response(rebuilt, "OPTIMAL")
    assert rebuilt["shortage_summary"]["total_person_minutes"] == 0
    assert rebuilt["change_summary"]["total_changes"] > 0
    assert [o["metric"] for o in rebuilt["objectives"]] == ["scheduled_minutes"]
    # 1枠2人の全列挙: aliceのみがhall可能。固定kitchenは不足1、自由は不足0。
    for mode, expected in [("preserve_assigned", 30), ("rebuild", 0)]:
        choices = [
            (a, b)
            for a, b in itertools.product((None, "kitchen", "hall"), (None, "kitchen"))
            if not (a is not None and a == b) and (mode != "preserve_assigned" or a == "kitchen")
        ]
        assert min((2 - sum(x is not None for x in pair)) * 30 for pair in choices) == expected


@pytest.mark.parametrize("conflict", ["availability", "removed_employee"])
def test_fixed_new_conditions_are_infeasible_and_never_unfixed(conflict):
    data = replan_case()
    data["replan_mode"] = "preserve_assigned"
    data["shift_candidates"] = data["shift_candidates"][1:]
    if conflict == "availability":
        data["employees"][0]["availability"] = []
    else:
        data["employees"] = data["employees"][1:]
    assert_response(solve(data), "INFEASIBLE")
    data["replan_mode"] = "rebuild"
    assert_response(solve(data), "PARTIAL")


@pytest.mark.parametrize("field", ["fixed_parts", "plan_changes"])
def test_rebuild_rejects_explicit_fixed_and_change_objective(field):
    data = replan_case()
    data["replan_mode"] = "rebuild"
    if field == "fixed_parts":
        data[field] = [
            {
                "id": "fixed",
                "employee_id": "alice",
                "interval": interval(end=630),
                "components": ["role"],
            }
        ]
    else:
        data["objectives"].append({"id": "changes", "metric": field})
    result = solve(data)
    assert_response(result, "INVALID_INPUT")
    assert result["diagnostics"][0]["code"] == "REBUILD_CONFLICT"


def test_partial_baseline_old_versions_and_invalid_snapshot_not_trusted():
    data = replan_case()
    data["schema_version"] = "0.3"
    data["baseline"]["source_request"]["schema_version"] = "0.3"
    data["baseline"].pop("source_fixed_states")
    data["baseline"].pop("snapshot_origin")
    assert_response(solve(data), "INVALID_INPUT")
    data = replan_case()
    data["replan_mode"] = "preserve_assigned"
    result = solve(data)
    snapshot = make_baseline(data, result["solution"], "saved")
    snapshot["source_solution"]["assignments"] = []
    data["baseline"] = snapshot
    invalid = solve(data)
    assert_response(invalid, "INVALID_INPUT")
    assert invalid["diagnostics"][0]["code"] == "FIXED_PART_VIOLATION"


@pytest.mark.parametrize("state", [{"work": "off"}, {"role": None}])
def test_snapshot_states_reject_unknown_employee_even_when_empty(state):
    data = replan_case()
    data["baseline"]["source_fixed_states"].append(
        {"employee_id": "unknown", "interval": interval(end=630), **state}
    )
    with pytest.raises(InvalidInput) as error:
        normalize(data)
    assert error.value.diagnostics[0]["code"] == "UNKNOWN_REFERENCE"
    assert error.value.diagnostics[0]["json_pointer"].endswith("/employee_id")


def test_preserved_assignments_over_1000_do_not_expand_fixed_parts():
    data = current(request(days=5, employees=tuple(f"e{i}" for i in range(201))))
    data["roles"] = data["roles"][:1]
    data["demand"] = [demand(d, people=201) for d in range(5)]
    solution = {
        "shifts": [selected(c) for c in data["shift_candidates"]],
        "assignments": [
            {"employee_id": e["id"], "role_id": "kitchen", "interval": interval(d, end=630)}
            for e in data["employees"]
            for d in range(5)
        ],
    }
    data["baseline"] = make_baseline(data, solution, "many_assigned")
    data["replan_mode"] = "preserve_assigned"
    data["fixed_parts"] = []
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(result["solution"]["assignments"]) == 1005
    assert data["fixed_parts"] == []


@pytest.mark.parametrize("version", SCHEMA_VERSIONS)
def test_verification_has_no_solver_call_or_proofs(version, monkeypatch, assignment_request):
    data = copy.deepcopy(assignment_request)
    data["schema_version"] = version
    result = solve(data)

    def forbidden(*args):
        raise AssertionError("探索を呼んではいけない")

    monkeypatch.setattr(cp_sat, "load_backend", forbidden)
    monkeypatch.setattr(cp_sat, "run", forbidden)
    checked = verify(data, result["solution"])
    assert checked["status"] == "VALID"
    assert checked["demand_satisfied"] is True
    assert not schema_errors("verification", checked)
    assert all(not o["proven_optimal"] for o in checked["objectives"])
    assert checked["shortage_summary"]["proven_minimal"] is False
    data["employees"][0]["skills"] = []
    assert verify(data, result["solution"])["status"] == "INVALID_PLAN"
    checked = verify(data, {"assignments": [], "shifts": []})
    assert checked["status"] == (
        "PARTIAL"
        if version
        in {
            "0.3",
            "0.4",
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }
        else "INVALID_PLAN"
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("employee", "UNKNOWN_REFERENCE"),
        ("candidate", "CANDIDATE_MISMATCH"),
        ("skill", "SKILL_VIOLATION"),
        ("double", "DOUBLE_ASSIGNMENT"),
        ("break", "BREAK_ASSIGNMENT"),
        ("bounds", "MIN_SCHEDULED_MINUTES_VIOLATION"),
        ("fixed", "FIXED_PART_VIOLATION"),
        ("proof", "SCHEMA_VIOLATION"),
    ],
)
def test_public_verifier_rejects_edited_solution(mutation, code):
    data = current()
    data["demand"] = [demand()]
    result = solve(data)
    solution = copy.deepcopy(result["solution"])
    if mutation == "employee":
        solution["assignments"][0]["employee_id"] = "unknown"
    elif mutation == "candidate":
        solution["shifts"][0]["segments"][0]["interval"]["end"] = stamp(0, 660)
    elif mutation == "skill":
        data["skills"] = [{"id": "s", "label": "技能"}]
        data["roles"][0]["required_skills"] = [{"skill_id": "s", "min_level": 1}]
    elif mutation == "double":
        solution["assignments"].append(copy.deepcopy(solution["assignments"][0]))
    elif mutation == "break":
        # 休憩は端に接しない別の候補へ置き換え、担当だけを休憩中に動かす。
        data["shift_candidates"][0]["segments"][0]["breaks"] = [interval(start=630, end=660)]
        solution["shifts"] = [selected(data["shift_candidates"][0])]
        solution["assignments"][0]["interval"] = interval(start=630, end=660)
    elif mutation == "bounds":
        data["constraints"] = [bounds(minimum=90)]
        solution["shifts"] = []
        solution["assignments"] = []
    elif mutation == "fixed":
        data["baseline"] = make_baseline(data, result["solution"], "saved")
        data["replan_mode"] = "preserve_assigned"
        solution["assignments"] = []
    else:
        solution["objectives"] = [{"value": 0, "proven_optimal": True}]
    checked = verify(data, solution)
    assert checked["status"] == "INVALID_PLAN"
    assert checked["demand_satisfied"] is None
    assert checked["objectives"] == []
    assert code in {v["code"] for v in checked["verification"]["violations"]}


def test_verification_invalid_input_and_internal_failure_are_not_valid(monkeypatch):
    assert verify(None, None)["status"] == "INVALID_INPUT"
    cyclic = {}
    cyclic["cycle"] = cyclic
    assert verify(current(), cyclic)["status"] == "INVALID_PLAN"
    import importlib

    module = importlib.import_module("shift_schedula.verify")

    def fail(*args, **kwargs):
        raise RuntimeError("failure")

    monkeypatch.setattr(module, "verify_plan", fail)
    result = verify(current(), {"assignments": [], "shifts": []})
    assert result["status"] == "INTERNAL_ERROR"
    assert result["verification"]["valid"] is not True


def test_public_schema_and_cli_verify(tmp_path):
    data = current()
    data["demand"] = [demand()]
    solution = solve(data)["solution"]
    req, sol = tmp_path / "request.json", tmp_path / "solution.json"
    req.write_text(json.dumps(data))
    sol.write_text(json.dumps(solution))
    for kind in ("request", "response", "solution", "verification"):
        proc = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.4"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert json.loads(proc.stdout) == get_schema(kind, "0.4")
    proc = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "verify", str(req), str(sol)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0 and json.loads(proc.stdout)["status"] == "VALID"
    sol.write_text(json.dumps({"assignments": [], "shifts": []}))
    proc = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "verify", str(req), str(sol)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2 and json.loads(proc.stdout)["status"] == "PARTIAL"


def test_preserve_fills_shortage_and_changes_unassigned_break_and_standby():
    data = replan_case()
    data["roles"][1]["required_skills"] = []
    fixed = solve({**data, "replan_mode": "preserve_assigned"})
    rebuilt = solve({**data, "replan_mode": "rebuild"})
    assert_response(fixed, "OPTIMAL")
    assert_response(rebuilt, "OPTIMAL")
    assert [o["value"] for o in fixed["objectives"]] == [o["value"] for o in rebuilt["objectives"]]
    old = current()
    old["shift_candidates"][0]["segments"][0]["breaks"] = [interval(start=630, end=660)]
    old["demand"] = [demand()]
    solution = {
        "shifts": [selected(old["shift_candidates"][0])],
        "assignments": [
            {"employee_id": "alice", "role_id": "kitchen", "interval": interval(end=630)}
        ],
    }
    new = current()
    new["baseline"] = make_baseline(old, solution, "old_break")
    new["replan_mode"] = "preserve_assigned"
    new["shift_candidates"][0]["segments"][0]["interval"]["end"] = stamp(0, 660)
    new["demand"] = [demand(), demand(start=630, end=660, role="hall")]
    result = solve(new)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 60
    assert result["change_summary"]["work_changes"] == 2


def test_bounds_diagnosis_records_hard_period_and_allowed_edit():
    data = current()
    data["constraints"] = [bounds(minimum=120)]
    data["diagnosis"] = {
        "time_limit_seconds": 10,
        "max_suggestions": 1,
        "allowed_changes": [
            {
                "id": "lower_minimum",
                "edits": [{"json_pointer": "/constraints/0/min_minutes", "value": 90}],
            }
        ],
    }
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    assert result["diagnosis_result"]["status"] == "COMPLETE"
    conditions = result["diagnosis_result"]["conflict"]["conditions"]
    assert any(
        c["code"] == "CONSTRAINT" and c["interval"] == data["constraints"][0]["interval"]
        for c in conditions
    )
    suggestion = result["diagnosis_result"]["suggestions"][0]
    assert suggestion["response"]["status"] == "OPTIMAL"
    assert suggestion["response"]["objectives"][0]["value"] == 90


@pytest.mark.parametrize("filename", ["overnight.json", "split_roster.json"])
def test_combined_night_split_shortage_fairness_wishes_and_repeated_replanning(filename):
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "examples" / filename).read_text())
    period = {k: data["planning_window"][k] for k in ("start", "end")}
    data["constraints"].append({**bounds(minimum=420, maximum=420), "interval": period})
    data["preferences"] = [{**preference("prefer_work"), "interval": period}]
    data["fairness"] = {
        "evaluation_period": period,
        "employee_targets": [{"employee_id": "alice", "target_minutes": 450}],
    }
    data["objectives"] = [
        {"id": "wishes", "metric": "preference_penalty"},
        {"id": "fairness", "metric": "fairness_deviation_minutes"},
        {"id": "work", "metric": "scheduled_minutes"},
    ]
    original = solve(data)
    assert_response(original, "OPTIMAL")
    for d in data["demand"]:
        d["required_people"] = 2
        d["minimum_people"] = 0
    # 不足以外は有効な計画を、新しい条件の基準へ昇格する。
    for mode in ("preserve_assigned", "rebuild"):
        new = copy.deepcopy(data)
        new["baseline"] = make_baseline(data, original["solution"], "partial_source")
        new["replan_mode"] = mode
        result = solve(new)
        assert_response(result, "PARTIAL")
        assert result["fairness_summary"]["employees"][0]["deviation_minutes"] == 30
        checked = verify(new, json.loads(json.dumps(result["solution"])))
        assert checked["status"] == "PARTIAL"
        assert [o["value"] for o in checked["objectives"]] == [
            o["value"] for o in result["objectives"]
        ]
        for i in range(2):
            new["baseline"] = make_baseline(new, result["solution"], f"next_{i}")
            result = solve(new)
            assert_response(result, "PARTIAL")
            assert result["change_summary"]["total_changes"] == 0


def test_verification_schema_rejects_forged_validity_and_optimality():
    data = current()
    result = verify(data, {"assignments": [], "shifts": []})
    result["verification"]["valid"] = False
    assert schema_errors("verification", result)
    result = verify(data, {"assignments": [], "shifts": []})
    result["shortage_summary"]["proven_minimal"] = True
    assert schema_errors("verification", result)


def test_cli_malformed_solution_keeps_request_version_and_identity(tmp_path):
    req, sol = tmp_path / "request.json", tmp_path / "bad.json"
    data = current()
    req.write_text(json.dumps(data))
    sol.write_text("{")
    result = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "verify", str(req), str(sol)],
        capture_output=True,
        text=True,
    )
    checked = json.loads(result.stdout)
    assert result.returncode == 2 and checked["status"] == "INVALID_INPUT"
    assert checked["schema_version"] == "0.4" and checked["request_id"] == data["request_id"]
    assert not schema_errors("verification", checked)
