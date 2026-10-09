import copy
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shift_schedula import InvalidInput, cp_sat, get_schema, make_baseline, solve, validate, verify
from shift_schedula.contract import SCHEMA_VERSIONS, parse_datetime, schema_errors
from shift_schedula.engine import validate_response
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "examples/continuity_replan.json").read_text(encoding="utf-8"))


def interval(day, start="09:00", end="10:00"):
    return {
        "start": f"2026-10-{day:02d}T{start}:00+09:00",
        "end": f"2026-10-{day:02d}T{end}:00+09:00",
    }


def rebuild(data):
    data["replan_mode"] = "rebuild"
    data["objectives"] = [{"id": "work", "metric": "scheduled_minutes"}]
    return data


def test_slide_solve_verify_and_snapshot_roundtrip(monkeypatch):
    data = example()
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [o["value"] for o in result["objectives"]] == [0, 180]
    assert result["change_summary"] == {
        "plan_id": "original",
        "unit": "slot_components",
        "work_changes": 0,
        "role_changes": 0,
        "total_changes": 0,
        "comparison_interval": {
            "start": "2026-10-06T00:00:00+09:00",
            "end": "2026-10-08T00:00:00+09:00",
        },
        "slot_minutes": 30,
    }
    alice = result["continuity_summary"]["employees"][0]
    assert (alice["historical_minutes"], alice["planned_minutes"]) == (60, 180)
    shifts = [data["continuity"]["employees"][0]["actual_shifts"][0], *result["solution"]["shifts"]]
    shifts.sort(key=lambda s: s["segments"][0]["interval"]["start"])
    assert all(
        (
            parse_datetime(b["segments"][0]["interval"]["start"])
            - parse_datetime(a["segments"][-1]["interval"]["end"])
        ).total_seconds()
        / 60
        == 1380
        for a, b in zip(shifts, shifts[1:], strict=False)
    )
    assert len(shifts) == 4
    snapshot = make_baseline(data, result["solution"], "second")
    assert snapshot["source_request"]["continuity"] == data["continuity"]
    assert snapshot["source_request"]["constraints"] == data["constraints"]
    assert snapshot["source_request"]["planning_window"] == data["planning_window"]
    assert "baseline" not in snapshot["source_request"]
    assert snapshot["source_fixed_states"]
    assert data == original
    again = copy.deepcopy(data)
    again["baseline"] = json.loads(json.dumps(snapshot))
    repeated = solve(again)
    assert_response(repeated, "OPTIMAL")
    assert repeated["change_summary"]["total_changes"] == 0
    assert len(make_baseline(again, repeated["solution"], "third")["source_fixed_states"]) == 3

    def forbidden(*args):
        raise AssertionError("独立検証で探索しない")

    monkeypatch.setattr(cp_sat, "load_backend", forbidden)
    checked = verify(data, result["solution"])
    assert checked["status"] == "VALID"
    assert checked["change_summary"] == result["change_summary"]
    assert all(not o["proven_optimal"] for o in checked["objectives"])
    assert not checked["shortage_summary"]["proven_minimal"]


@pytest.mark.parametrize("slots,expected", [(1, 4), (2, 8)])
def test_alice_bob_handover_counts_both_components(slots, expected):
    data = rebuild(example())
    day = 6 if slots == 1 else 7
    data["shift_candidates"] = [
        c
        for c in data["shift_candidates"]
        if c["employee_id"] == "alice" and c["id"] != f"alice_{day}"
    ]
    candidate = {
        "id": f"bob_{day}",
        "employee_id": "bob",
        "segments": [{"interval": interval(day), "breaks": []}],
    }
    if slots == 1:
        candidate["segments"][0]["interval"] = interval(day, end="09:30")
        data["shift_candidates"].append(
            {
                "id": f"alice_{day}",
                "employee_id": "alice",
                "segments": [{"interval": interval(day, start="09:30"), "breaks": []}],
            }
        )
    data["shift_candidates"].append(candidate)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 180
    assert result["change_summary"]["work_changes"] == expected // 2
    assert result["change_summary"]["role_changes"] == expected // 2
    assert result["change_summary"]["total_changes"] == expected
    assert verify(data, result["solution"])["change_summary"] == result["change_summary"]


@pytest.mark.parametrize("mutation", ["slot_minutes", "timezone", "no_overlap"])
def test_mismatched_grid_or_no_overlap_rejected(mutation):
    data = example()
    if mutation == "slot_minutes":
        data["planning_window"]["slot_minutes"] = 15
    elif mutation == "timezone":
        data["planning_window"]["timezone"] = "Japan"
    else:
        source = data["baseline"]["source_request"]
        source["planning_window"]["end"] = data["planning_window"]["start"]
        source["demand"] = source["demand"][:1]
        source["shift_candidates"] = source["shift_candidates"][:1]
        data["baseline"]["source_solution"]["assignments"] = data["baseline"]["source_solution"][
            "assignments"
        ][:1]
        data["baseline"]["source_solution"]["shifts"] = data["baseline"]["source_solution"][
            "shifts"
        ][:1]
    checked = validate(data)
    assert checked["status"] == "INVALID_INPUT"
    assert checked["diagnostics"][0]["code"] == "BASELINE_WINDOW_MISMATCH"


@pytest.mark.parametrize("version", ["0.4", "0.5", "0.6"])
def test_old_contracts_keep_same_window_requirement(version):
    data = example()
    # 旧版0.4にも表現できる業務条件で期間だけを変更する。
    for request in (data, data["baseline"]["source_request"]):
        request["schema_version"] = version
        request.pop("continuity")
        request["constraints"] = request["constraints"][:2]
        for demand in request["demand"]:
            if version == "0.4":
                demand.pop("priority")
        for employee in request["employees"]:
            employee["availability"] = [
                {k: request["planning_window"][k] for k in ("start", "end")}
            ]
            employee["history"] = {
                "last_shift_end": None,
                "last_work_day": None,
                "consecutive_work_days_before_window": 0,
            }
    assert solve(data)["diagnostics"][0]["code"] == "SCHEMA_VIOLATION"


@pytest.mark.parametrize("day", [5, 8])
def test_fixed_parts_only_in_overlap(day):
    data = example()
    data["fixed_parts"] = [
        {
            "id": "explicit",
            "employee_id": "alice",
            "interval": interval(day),
            "components": ["work", "role"],
        }
    ]
    assert solve(data)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize("conflict", ["removed_employee", "skills", "availability", "removed_role"])
def test_fixed_conflicts_are_infeasible_and_never_unfixed(conflict):
    data = example()
    if conflict == "removed_employee":
        data["employees"] = data["employees"][1:]
        data["continuity"]["employees"] = data["continuity"]["employees"][1:]
        data["constraints"] = []
        data["shift_candidates"] = [
            c for c in data["shift_candidates"] if c["employee_id"] == "bob"
        ]
    elif conflict == "skills":
        data["skills"] = [{"id": "skill", "label": "技能"}]
        data["roles"][0]["required_skills"] = [{"skill_id": "skill", "min_level": 1}]
        data["employees"][1]["skills"] = [{"skill_id": "skill", "level": 1}]
    elif conflict == "availability":
        data["employees"][0]["availability"] = []
        data["shift_candidates"] = [
            c for c in data["shift_candidates"] if c["employee_id"] == "bob"
        ]
    else:
        data["roles"][0]["id"] = "hall"
        for demand in data["demand"]:
            demand["role_id"] = "hall"
    assert_response(solve(data), "INFEASIBLE")
    assert_response(solve(rebuild(data)), "OPTIMAL" if conflict == "removed_role" else "PARTIAL")


def test_even_empty_fixed_state_requires_employee_to_exist():
    data = rebuild(example())
    data["replan_mode"] = "preserve_assigned"
    data["baseline"]["source_solution"]["assignments"] = []
    data["baseline"]["source_solution"]["shifts"] = []
    data["fixed_parts"] = [
        {
            "id": "off",
            "employee_id": "alice",
            "interval": interval(6),
            "components": ["work", "role"],
        }
    ]
    data["employees"] = data["employees"][1:]
    data["continuity"]["employees"] = data["continuity"]["employees"][1:]
    data["shift_candidates"] = [c for c in data["shift_candidates"] if c["employee_id"] == "bob"]
    data["constraints"] = []
    assert_response(solve(data), "INFEASIBLE")
    plan = solve(rebuild(copy.deepcopy(data)) | {"fixed_parts": []})["solution"]
    assert verify(data, plan)["status"] == "INVALID_PLAN"


@pytest.mark.parametrize(
    "tamper", ["solution", "fixed_states", "origin", "summary", "comparison", "slot_minutes"]
)
def test_forged_baseline_or_response_is_detected(tamper):
    data = example()
    result = solve(data)
    if tamper in ("summary", "comparison", "slot_minutes"):
        if tamper == "summary":
            result["change_summary"]["total_changes"] = 4
        elif tamper == "comparison":
            result["change_summary"]["comparison_interval"]["start"] = interval(5)["start"]
        else:
            result["change_summary"]["slot_minutes"] = 15
        with pytest.raises(InvalidInput):
            validate_response(result, data)
        return
    snapshot = make_baseline(data, result["solution"], "second")
    if tamper == "solution":
        snapshot["source_solution"]["shifts"][0]["segments"][0]["interval"]["end"] = interval(
            6, end="10:30"
        )["end"]
    elif tamper == "fixed_states":
        snapshot["source_fixed_states"][0]["work"] = "off"
    else:
        snapshot["snapshot_origin"]["request_id"] = "forged"
    data["baseline"] = snapshot
    assert solve(data)["status"] == "INVALID_INPUT"


def test_source_fixed_states_outside_new_window_are_still_revalidated():
    data = example()
    data["baseline"]["source_fixed_states"] = [
        {"employee_id": "alice", "interval": interval(5), "work": "off"}
    ]
    assert solve(data)["diagnostics"][0]["code"] == "FIXED_PART_VIOLATION"


@pytest.mark.parametrize("same_id", [True, False])
def test_commitment_record_conflict_vs_valid_fixed_condition_conflict(same_id):
    data = example()
    old = data["baseline"]["source_request"]
    old["shift_candidates"] = [c for c in old["shift_candidates"] if c["id"] != "alice_6"]
    old["continuity"]["employees"][0]["committed_shifts"] = [
        {"id": "committed", "segments": [{"interval": interval(6), "breaks": []}]}
    ]
    old_result = solve(old)
    data["baseline"] = make_baseline(old, old_result["solution"], "committed_plan")
    data["shift_candidates"] = [c for c in data["shift_candidates"] if c["id"] != "alice_6"]
    data["continuity"]["employees"][0]["committed_shifts"] = [
        {
            "id": "committed" if same_id else "different",
            "segments": [{"interval": interval(6, "10:00", "11:00"), "breaks": []}],
        }
    ]
    result = solve(data)
    assert_response(result, "INVALID_INPUT" if same_id else "INFEASIBLE")
    if same_id:
        assert result["diagnostics"][0]["code"] == "CONFLICTING_CONTINUITY"
    else:
        result = solve(rebuild(data))
        assert_response(result, "OPTIMAL")
        assert any(s.get("committed_shift_id") == "different" for s in result["solution"]["shifts"])
        assert verify(data, result["solution"])["status"] == "VALID"


def test_small_rebuild_and_fixed_problems_match_exhaustive_enumeration():
    for mode in ("preserve_assigned", "rebuild"):
        data = example()
        data["replan_mode"] = mode
        if mode == "rebuild":
            rebuild(data)
        # 3日の担当者を列挙。元需要を満たし、過去実績込みで全選択が条件内。
        plans = [(*p, "alice") for p in itertools.product(("alice", "bob"), repeat=2)]
        if mode == "preserve_assigned":
            plans = [p for p in plans if p[:2] == ("alice", "alice")]
        result = solve(data)
        assert result["shortage_summary"]["total_person_minutes"] == 0
        assert result["objectives"][-1]["value"] == min(len(p) * 60 for p in plans)
        if mode == "preserve_assigned":
            assert result["objectives"][0]["value"] == min(
                sum(e != "alice" for e in p[:2]) * 8 for p in plans
            )


@pytest.mark.parametrize("version", ["0.15"])
@pytest.mark.parametrize("kind", ["request", "response", "solution", "verification"])
def test_new_schema_and_cli(kind, version):
    result = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", version],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == get_schema(kind, version)
    assert get_schema(kind, version)["$id"].endswith(f":{version}")


def test_cli_solve_verify(tmp_path):
    request = ROOT / "examples/continuity_replan.json"
    result = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "solve", str(request)],
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    path = tmp_path / "solution.json"
    path.write_text(json.dumps(output["solution"]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "shift_schedula", "verify", str(request), str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    checked = json.loads(result.stdout)
    assert checked["status"] == "VALID"
    assert checked["change_summary"] == output["change_summary"]
    assert not schema_errors("verification", checked)
    assert SCHEMA_VERSIONS == ("0.15",)


@pytest.mark.parametrize("working", [False, True])
def test_off_break_work_and_role_null_are_distinct(working):
    data = example()
    old = data["baseline"]["source_request"]
    old["constraints"] = []
    old["shift_candidates"] = [
        {
            "id": "break_shift",
            "employee_id": "alice",
            "segments": [
                {"interval": interval(6, end="10:30"), "breaks": [interval(6, "09:30", "10:00")]}
            ],
        }
    ]
    old["demand"] = [
        {"id": f"old_{i}", "role_id": "kitchen", "interval": span, "required_people": 1}
        for i, span in enumerate([interval(6, end="09:30"), interval(6, "10:00", "10:30")])
    ]
    old_plan = solve(old)
    assert_response(old_plan, "OPTIMAL")
    data["baseline"] = make_baseline(old, old_plan["solution"], "break_plan")
    rebuild(data)
    data["constraints"] = []
    data["demand"] = (
        [
            {
                "id": "middle",
                "role_id": "kitchen",
                "interval": interval(6, "09:30", "10:00"),
                "required_people": 1,
            }
        ]
        if working
        else []
    )
    data["shift_candidates"] = (
        [
            {
                "id": "without_break",
                "employee_id": "alice",
                "segments": [{"interval": interval(6, end="10:30"), "breaks": []}],
            }
        ]
        if working
        else []
    )
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert (result["change_summary"]["work_changes"], result["change_summary"]["role_changes"]) == (
        (1, 3) if working else (3, 2)
    )
    assert verify(data, result["solution"])["change_summary"] == result["change_summary"]


@pytest.mark.parametrize("employee", ["added", "deleted"])
def test_employee_union_counts_nonfixed_changes(employee):
    data = rebuild(example())
    if employee == "deleted":
        data["employees"] = data["employees"][1:]
        data["continuity"]["employees"] = data["continuity"]["employees"][1:]
        data["constraints"] = []
        data["shift_candidates"] = [
            c for c in data["shift_candidates"] if c["employee_id"] == "bob"
        ]
    else:
        data["employees"][1]["id"] = "new_bob"
        data["continuity"]["employees"][1]["employee_id"] = "new_bob"
        data["constraints"] = []
        data["shift_candidates"] = [
            c for c in data["shift_candidates"] if c["employee_id"] == "bob"
        ]
        for candidate in data["shift_candidates"]:
            candidate["employee_id"] = "new_bob"
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["change_summary"]["total_changes"] == 16
    assert verify(data, result["solution"])["change_summary"]["total_changes"] == 16


def test_shifted_snapshot_can_slide_again_without_mutating_source():
    data = example()
    plan = solve(data)
    snapshot = make_baseline(data, plan["solution"], "second")
    original = copy.deepcopy(snapshot)
    # 新Wは7〜9日、6日の勤務は利用側で確認済み実績として入力する。
    data["planning_window"]["start"] = "2026-10-07T00:00:00+09:00"
    data["continuity"]["employees"][0]["actual_shifts"].append(
        {"id": "actual_6", "segments": [{"interval": interval(6), "breaks": []}]}
    )
    data["demand"] = data["demand"][1:]
    data["shift_candidates"] = [c for c in data["shift_candidates"] if not c["id"].endswith("_6")]
    data["baseline"] = snapshot
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["change_summary"]["total_changes"] == 0
    assert (
        result["change_summary"]["comparison_interval"]["start"] == data["planning_window"]["start"]
    )
    assert snapshot == original
    assert verify(data, result["solution"])["status"] == "VALID"


def test_backward_slide_projects_absolute_slots():
    data = example()
    source = copy.deepcopy(data)
    source.pop("baseline")
    source.pop("replan_mode")
    source["objectives"] = source["objectives"][1:]
    old_result = solve(source)
    data["baseline"] = make_baseline(source, old_result["solution"], "later")
    data["planning_window"]["start"] = "2026-10-05T00:00:00+09:00"
    data["planning_window"]["end"] = "2026-10-08T00:00:00+09:00"
    data["continuity"]["employees"][0]["actual_shifts"] = []
    data["demand"] = data["demand"][:2] + [
        {"id": "need_5", "role_id": "kitchen", "interval": interval(5), "required_people": 1}
    ]
    data["shift_candidates"] = [c for c in data["shift_candidates"] if not c["id"].endswith("_8")]
    data["shift_candidates"].append(
        {
            "id": "alice_5",
            "employee_id": "alice",
            "segments": [{"interval": interval(5), "breaks": []}],
        }
    )
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["change_summary"]["total_changes"] == 0
    assert result["change_summary"]["comparison_interval"] == {
        "start": "2026-10-06T00:00:00+09:00",
        "end": "2026-10-08T00:00:00+09:00",
    }
    assert verify(data, result["solution"])["status"] == "VALID"


def test_commitment_becomes_confirmed_actual_with_same_id():
    data = example()
    old = data["baseline"]["source_request"]
    old["shift_candidates"] = [c for c in old["shift_candidates"] if c["id"] != "alice_5"]
    old["continuity"]["employees"][0]["committed_shifts"] = [
        {"id": "actual_5", "segments": [{"interval": interval(5), "breaks": []}]}
    ]
    result = solve(old)
    data["baseline"] = make_baseline(old, result["solution"], "committed")
    assert_response(solve(data), "OPTIMAL")
    data["continuity"]["employees"][0]["actual_shifts"][0]["segments"][0]["interval"]["end"] = (
        interval(5, end="10:30")["end"]
    )
    assert solve(data)["diagnostics"][0]["code"] == "CONFLICTING_CONTINUITY"


@pytest.mark.parametrize("mode", ["preserve_assigned", "rebuild"])
def test_mandatory_demand_in_new_window_does_not_rewrite_original_baseline(mode):
    data = example()
    original = copy.deepcopy(data["baseline"])
    data["demand"][-1]["minimum_people"] = 1
    data["shift_candidates"] = [c for c in data["shift_candidates"] if not c["id"].endswith("_8")]
    data["replan_mode"] = mode
    if mode == "rebuild":
        rebuild(data)
    saved = copy.deepcopy(data)
    assert_response(solve(data), "INFEASIBLE")
    assert data == saved
    assert data["baseline"] == original
    assert "minimum_people" not in original["source_request"]["demand"][-1]
    data["demand"][-1]["minimum_people"] = 0
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 60
    assert result["change_summary"]["total_changes"] == 0
    assert verify(data, result["solution"])["status"] == "PARTIAL"
