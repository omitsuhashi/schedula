"""契約0.15の同時勤務を原区間・小規模全探索と公開入口で照合する。"""

import copy
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shift_schedula import get_schema, make_baseline, solve, validate, verify
from shift_schedula.contract import SCHEMA_VERSIONS, parse_datetime
from shift_schedula.diagnosis import condition_groups
from shift_schedula.model import normalize
from shift_schedula.verify import verify_plan
from tests.roster_support import demand, interval, stamp
from tests.support import assert_response
from tests.test_continuity import segment
from tests.test_day_counts import continuity, selected
from tests.test_day_counts import example as days_example
from tests.test_objectives import control_search


def example():
    data = days_example(1, ("trainee", "mentor_a", "mentor_b"))
    data["request_id"] = "coworkers_example"
    data["skills"] = [{"id": "service", "label": "担当技能"}]
    data["employees"][0]["skills"] = [{"skill_id": "service", "level": 1}]
    data["roles"][0]["required_skills"] = [{"skill_id": "service", "min_level": 1}]
    data["shift_candidates"] = [
        {"id": e, "employee_id": e, "segments": [segment(stamp(0, a), stamp(0, b))]}
        for e, a, b in (("trainee", 540, 660), ("mentor_a", 540, 600), ("mentor_b", 600, 660))
    ]
    data["constraints"] = [required(), incompatible(("mentor_a", "mentor_b"))]
    data["demand"] = [dict(demand(0, 540, 660, people=2), minimum_people=1)]
    return data


def required(minimum=1, employees=("trainee",), coworkers=("mentor_a", "mentor_b")):
    return {
        "id": "training_cover",
        "type": "required_coworkers",
        "employee_ids": list(employees),
        "coworker_ids": list(coworkers),
        "minimum_people": minimum,
        "interval": interval(0, 540, 660),
    }


def incompatible(employees=("trainee", "mentor_a", "mentor_b")):
    return {
        "id": "separate",
        "type": "incompatible_employees",
        "employee_ids": list(employees),
        "interval": interval(0, 540, 660),
    }


def plan(data, ids=None):
    return {
        "assignments": [],
        "shifts": [selected(c) for c in data["shift_candidates"] if ids is None or c["id"] in ids],
    }


def violation(data, solution, code):
    checked = verify(data, solution)
    assert checked["status"] == "INVALID_PLAN", checked
    assert checked["objectives"] == []
    assert checked["shortage_summary"] is None
    return next(d for d in checked["diagnostics"] if d["code"] == code)


def test_handoff_exact_boundary_standby_and_one_way_condition():
    data = example()
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 120
    assert result["shortage_summary"]["proven_minimal"] is True
    assert result["objectives"][0]["value"] == 240
    assert {s["candidate_id"] for s in result["solution"]["shifts"]} == {
        "trainee",
        "mentor_a",
        "mentor_b",
    }
    assert {a["employee_id"] for a in result["solution"]["assignments"]} == {"trainee"}
    assert verify(data, result["solution"])["status"] == "PARTIAL"
    assert verify(data, plan(data, {"mentor_a"}))["status"] == "INVALID_PLAN"  # 必須需要
    data["demand"] = []
    assert verify(data, plan(data, {"mentor_a"}))["status"] == "VALID"
    assert verify(data, plan(data, set()))["status"] == "VALID"
    broken = plan(data, {"trainee", "mentor_a"})
    d = violation(data, broken, "REQUIRED_COWORKERS_VIOLATION")
    assert d["json_pointer"] == "/constraints/0"
    assert d["related_ids"] == ["training_cover", "trainee", "mentor_a", "mentor_b"]
    facts = {f["name"]: f["value"] for f in d["facts"]}
    assert facts == {
        "interval_start": stamp(0, 600),
        "interval_end": stamp(0, 630),
        "actual_people": 0,
        "minimum_people": 1,
    }
    problem = normalize(data)
    problem.candidates = []
    problem.continuity = []
    assert any(d["code"] == "REQUIRED_COWORKERS_VIOLATION" for d in verify_plan(problem, broken)[0])


def test_breaks_and_split_gaps_are_nonwork_and_interval_is_local():
    data = example()
    data["constraints"] = [required()]
    for c in data["shift_candidates"][1:]:
        c["segments"] = [segment(stamp(0, 540), stamp(0, 660), [(stamp(0, 600), stamp(0, 630))])]
    assert_response(solve(data), "INFEASIBLE")
    violation(data, plan(data), "REQUIRED_COWORKERS_VIOLATION")
    data["shift_candidates"][0]["segments"][0]["breaks"] = [interval(0, 600, 630)]
    data["demand"] = [
        dict(demand(0, 540, 600), minimum_people=1),
        dict(demand(0, 630, 660), minimum_people=1),
    ]
    assert_response(solve(data), "OPTIMAL")
    data["demand"] = []
    assert verify(data, plan(data))["status"] == "VALID"
    data["shift_candidates"][0]["segments"][0]["breaks"] = []
    data["shift_candidates"][1]["segments"] = [
        segment(stamp(0, 540), stamp(0, 600)),
        segment(stamp(0, 630), stamp(0, 660)),
    ]
    data["shift_candidates"] = data["shift_candidates"][:2]
    violation(data, plan(data), "REQUIRED_COWORKERS_VIOLATION")
    data["constraints"][0]["interval"] = interval(0, 540, 600)
    assert_response(solve(data), "OPTIMAL")


def test_minimum_two_mutual_conditions_and_shared_mentor():
    data = example()
    data["constraints"] = [required(2)]
    for c in data["shift_candidates"][1:]:
        c["segments"] = copy.deepcopy(data["shift_candidates"][0]["segments"])
    assert_response(solve(data), "PARTIAL")
    data["demand"] = []
    violation(data, plan(data, {"trainee", "mentor_a"}), "REQUIRED_COWORKERS_VIOLATION")
    # 同じ指導者は二人を同時に支えられる。逆方向の条件も別に指定する。
    data["constraints"] = [
        required(employees=("trainee", "mentor_b"), coworkers=("mentor_a",)),
        dict(required(employees=("mentor_a",), coworkers=("trainee",)), id="reverse"),
    ]
    assert verify(data, plan(data))["status"] == "VALID"
    data["demand"] = [dict(demand(0, 540, 660), minimum_people=1)]
    assert_response(solve(data), "OPTIMAL")


@pytest.mark.parametrize(
    "pair", list(itertools.combinations(("trainee", "mentor_a", "mentor_b"), 2))
)
def test_incompatible_sets_disallow_every_pair_and_count_standby(pair):
    data = example()
    data["demand"] = []
    data["constraints"] = [incompatible()]
    for c in data["shift_candidates"]:
        c["segments"] = copy.deepcopy(data["shift_candidates"][0]["segments"])
    d = violation(data, plan(data, set(pair)), "INCOMPATIBLE_EMPLOYEES_VIOLATION")
    assert set(d["related_ids"][1:]) == set(pair)
    assert verify(data, plan(data, {pair[0]}))["status"] == "VALID"
    data["constraints"][0]["interval"] = interval(0, 660, 690)
    assert verify(data, plan(data, set(pair)))["status"] == "VALID"


@pytest.mark.parametrize(
    "mutation",
    [
        "self",
        "intersection",
        "empty_employee",
        "empty_coworker",
        "duplicate_employee",
        "duplicate_coworker",
        "unknown_employee",
        "unknown_coworker",
        "bool",
        "null",
        "float",
        "zero",
        "too_many",
        "huge",
        "unknown_field",
        "missing_interval",
        "reversed",
        "outside",
        "misaligned",
        "seconds",
        "single_incompatible",
        "assignment",
        "duplicate_id",
    ],
)
def test_invalid_input_is_rejected_by_all_public_entries(mutation):
    data = example()
    r = data["constraints"][0]
    if mutation in {"bool", "null", "float", "zero", "too_many", "huge"}:
        r["minimum_people"] = {
            "bool": True,
            "null": None,
            "float": 1.0,
            "zero": 0,
            "too_many": 3,
            "huge": 10000001,
        }[mutation]
    elif mutation == "self":
        r["coworker_ids"] = ["trainee"]
    elif mutation == "intersection":
        r["employee_ids"].append("mentor_a")
    elif mutation.startswith("empty_"):
        r[mutation.removeprefix("empty_") + "_ids"] = []
    elif mutation.startswith("duplicate_") and mutation != "duplicate_id":
        r[mutation.removeprefix("duplicate_") + "_ids"] *= 2
    elif mutation.startswith("unknown_") and mutation != "unknown_field":
        r[mutation.removeprefix("unknown_") + "_ids"] = ["ghost"]
    elif mutation == "unknown_field":
        r["role_id"] = "kitchen"
    elif mutation == "missing_interval":
        r.pop("interval")
    elif mutation == "reversed":
        r["interval"]["end"] = stamp(0, 510)
    elif mutation == "outside":
        r["interval"]["start"] = stamp(-1)
    elif mutation == "misaligned":
        r["interval"]["start"] = stamp(0, 541)
    elif mutation == "seconds":
        r["interval"]["start"] = stamp(0, 540).replace(":00+", ":01+")
    elif mutation == "single_incompatible":
        data["constraints"] = [incompatible(("trainee",))]
    elif mutation == "assignment":
        data["problem_type"] = "assignment"
    elif mutation == "duplicate_id":
        data["constraints"][1]["id"] = r["id"]
    assert validate(data)["status"] == "INVALID_INPUT"
    assert_response(solve(data), "INVALID_INPUT")
    assert verify(data, {"assignments": [], "shifts": []})["status"] == "INVALID_INPUT"


@pytest.mark.parametrize("version", [v for v in SCHEMA_VERSIONS if v not in {"0.14", "0.15"}])
def test_old_versions_reject_both_new_conditions(version):
    for rule in (required(), incompatible()):
        data = example()
        data.update(schema_version=version, constraints=[rule])
        assert validate(data)["status"] == "INVALID_INPUT"


def test_committed_boundary_shifts_and_breaks_remain_fixed():
    data = example()
    continuity(data, first_day=-1)
    data["shift_candidates"] = data["shift_candidates"][:1]
    row = data["continuity"]["employees"][1]
    row["committed_shifts"] = [
        {"id": "mentor_fixed", "segments": [segment(stamp(-1, 1380), stamp(0, 660))]}
    ]
    data["constraints"] = [required(coworkers=("mentor_a",))]
    assert_response(solve(data), "PARTIAL")
    row["committed_shifts"][0]["segments"][0]["breaks"] = [interval(0, 600, 630)]
    assert_response(solve(data), "INFEASIBLE")
    data["demand"][0]["minimum_people"] = 0
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["shortage_summary"]["total_person_minutes"] == 240
    assert result["solution"]["shifts"][0]["committed_shift_id"] == "mentor_fixed"
    data["constraints"] = [incompatible(("trainee", "mentor_a"))]
    data["demand"][0]["minimum_people"] = 1
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize("mode", ["preserve_assigned", "rebuild"])
def test_baseline_roundtrip_keeps_relations_and_conflicting_fixed_states(mode):
    data = example()
    original = solve(data)
    baseline = make_baseline(data, original["solution"], "saved")
    assert baseline["source_request"]["constraints"] == data["constraints"]
    data.update(baseline=baseline, replan_mode=mode)
    assert_response(solve(data), "PARTIAL")
    data["constraints"].append(dict(incompatible(("trainee", "mentor_a")), id="new_separation"))
    assert_response(solve(data), "INFEASIBLE")
    data["demand"][0]["minimum_people"] = 0
    assert_response(solve(data), "INFEASIBLE" if mode == "preserve_assigned" else "PARTIAL")
    data.pop("replan_mode")
    data["fixed_parts"] = [
        {
            "id": "fixed",
            "employee_id": "trainee",
            "interval": interval(0, 540, 660),
            "components": ["work"],
        }
    ]
    assert_response(solve(data), "INFEASIBLE")


def test_day_off_conflict_diagnosis_keeps_background_and_rechecks_witnesses():
    data = example()
    data["constraints"].append(
        {
            "id": "mentor_off",
            "type": "days_off_bounds",
            "employee_ids": ["mentor_a"],
            "interval": interval(0, 0, 1440),
            "min_days": 1,
        }
    )
    data["diagnosis"] = {
        "time_limit_seconds": 5,
        "max_suggestions": 0,
        "allowed_changes": [],
        "conflict_refinement": {"time_limit_seconds": 4},
    }
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert conflict["minimality"] == "inclusion_minimal"
    assert {c["group_id"] for c in conflict["conditions"]} == {
        "/constraints/0",
        "/constraints/2",
        "/demand/0",
    }
    assert any(c["code"] == "CANDIDATE_SET" for c in conflict["background_conditions"])
    problem = normalize(data)
    assert all(c["completed_in_budget"] for c in conflict["checks"])
    groups_in_conflict = {c["group_id"] for c in conflict["conditions"]}

    # 十分集合と各単独除去を公開検証で全列挙する。診断の内部証拠は流用しない。
    def possible(active):
        for flags in itertools.product((False, True), repeat=3):
            chosen = {
                c["id"] for c, flag in zip(data["shift_candidates"], flags, strict=True) if flag
            }
            solution = plan(data, chosen)
            if "trainee" in chosen:
                solution["assignments"] = [
                    {
                        "employee_id": "trainee",
                        "role_id": "kitchen",
                        "interval": interval(0, 540, 660),
                    }
                ]
            if not verify_plan(problem, solution, active_groups=active)[0]:
                return True
        return False

    assert not possible(groups_in_conflict)
    assert all(possible(groups_in_conflict - {g}) for g in groups_in_conflict)
    groups, _ = condition_groups(data)
    assert groups[0]["related_ids"] == ["training_cover", "trainee", "mentor_a", "mentor_b"]
    data["diagnosis"]["allowed_changes"] = [
        {"id": "edit", "edits": [{"json_pointer": "/constraints/0/minimum_people", "value": 0}]}
    ]
    assert validate(data)["status"] == "INVALID_INPUT"


@pytest.mark.parametrize(
    "kind,minimum",
    [("required_coworkers", 1), ("required_coworkers", 2), ("incompatible_employees", 1)],
)
def test_all_subsets_match_independent_work_spans_and_solver(kind, minimum):
    data = example()
    data["shift_candidates"][1]["segments"] = [
        segment(stamp(0, 540), stamp(0, 660), [(stamp(0, 570), stamp(0, 600))])
    ]
    data["demand"] = []
    data["constraints"] = [required(minimum) if kind == "required_coworkers" else incompatible()]
    candidates = data["shift_candidates"]
    best = []
    for flags in itertools.product((False, True), repeat=3):
        chosen = [c for c, f in zip(candidates, flags, strict=True) if f]
        # 元JSONだけを読む期待値。モデル・分類・coverageの計算を流用しない。
        work = {}
        for c in chosen:
            work[c["employee_id"]] = {
                minute
                for minute in range(540, 660, 30)
                if any(
                    parse_datetime(s["interval"]["start"])
                    <= parse_datetime(stamp(0, minute))
                    < parse_datetime(s["interval"]["end"])
                    and not any(
                        parse_datetime(b["start"])
                        <= parse_datetime(stamp(0, minute))
                        < parse_datetime(b["end"])
                        for b in s["breaks"]
                    )
                    for s in c["segments"]
                )
            }
        valid = (
            all(
                sum(minute in work.get(e, set()) for e in ("mentor_a", "mentor_b")) >= minimum
                for minute in work.get("trainee", set())
            )
            if kind == "required_coworkers"
            else all(
                sum(minute in spans for spans in work.values()) <= 1
                for minute in range(540, 660, 30)
            )
        )
        assert (verify(data, plan(data, {c["id"] for c in chosen}))["status"] == "VALID") == valid
        forced = copy.deepcopy(data)
        forced["constraints"] += [
            {
                "id": f"force_{e['id']}",
                "type": "work_days_bounds",
                "employee_ids": [e["id"]],
                "interval": interval(0, 0, 1440),
                "min_days": int(f),
                "max_days": int(f),
            }
            for e, f in zip(data["employees"], flags, strict=True)
        ]
        assert_response(solve(forced), "OPTIMAL" if valid else "INFEASIBLE")
        if valid:
            best.append(sum(map(len, work.values())) * 30)
    assert solve(data)["objectives"][0]["value"] == min(best)


@pytest.mark.parametrize("statuses", [("UNKNOWN",), ("FEASIBLE",), ("OPTIMAL", "UNKNOWN")])
def test_shared_search_budget_proof_prefix_and_unknown(monkeypatch, statuses):
    data = example()
    calls, _ = control_search(monkeypatch, statuses)
    result = solve(data)
    assert_response(result, "UNKNOWN" if statuses == ("UNKNOWN",) else "PARTIAL")
    assert len(calls) == len(statuses)
    if result["solution"]:
        assert result["verification"]["valid"]
        assert not result["objectives"][0]["proven_optimal"]


def test_schemas_cli_and_saved_json_sample(tmp_path):
    data = json.loads((Path(__file__).resolve().parents[1] / "examples/coworkers.json").read_text())
    result = solve(data)
    assert_response(result, "PARTIAL")
    source, solution = tmp_path / "request.json", tmp_path / "solution.json"
    source.write_text(json.dumps(data))
    solution.write_text(json.dumps(result["solution"]))
    for args in (["solve", str(source)], ["verify", str(source), str(solution)]):
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", *args], capture_output=True, text=True
        )
        assert completed.returncode == 2, completed.stdout
        assert json.loads(completed.stdout)["schema_version"] == "0.15"
    for kind in ("request", "response", "solution", "verification"):
        schema = get_schema(kind, "0.15")
        Draft202012Validator.check_schema(schema)
        completed = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.15"],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == schema


def test_fall_dst_handoff_counts_actual_time_and_preserves_offsets():
    data = example()
    data["planning_window"].update(
        start="2026-11-01T00:00:00-04:00",
        end="2026-11-02T00:00:00-05:00",
        timezone="America/New_York",
    )
    span = {"start": "2026-11-01T00:30:00-04:00", "end": "2026-11-01T02:30:00-05:00"}
    for employee in data["employees"]:
        employee["availability"] = [span]
    handoff = "2026-11-01T01:30:00-04:00"
    for c, a, b in zip(
        data["shift_candidates"],
        (span["start"], span["start"], handoff),
        (span["end"], handoff, span["end"]),
        strict=True,
    ):
        c["segments"] = [segment(a, b)]
    for rule in data["constraints"]:
        rule["interval"] = span
    data["demand"][0].update(interval=span, required_people=1)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 360
    assert verify(data, result["solution"])["status"] == "VALID"


def test_incompatible_relation_is_one_refined_condition_group():
    data = example()
    data["constraints"][0]["minimum_people"] = 2
    for c in data["shift_candidates"][1:]:
        c["segments"] = copy.deepcopy(data["shift_candidates"][0]["segments"])
    data["diagnosis"] = {
        "time_limit_seconds": 5,
        "max_suggestions": 0,
        "allowed_changes": [],
        "conflict_refinement": {"time_limit_seconds": 4},
    }
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert conflict["minimality"] == "inclusion_minimal"
    assert {c["group_id"] for c in conflict["conditions"]} == {
        "/constraints/0",
        "/constraints/1",
        "/demand/0",
    }
    for index in range(2):
        trial = copy.deepcopy(data)
        trial["constraints"].pop(index)
        assert_response(solve(trial), "PARTIAL")
