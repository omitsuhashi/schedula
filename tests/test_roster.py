import copy
import itertools
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from schedula import cp_sat, flow, solve
from schedula.model import normalize
from schedula.verify import verify_solution
from tests.roster_support import candidate, demand, interval, request, rule, stamp
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("backend", ["auto", "cp_sat"])
def test_reference_roster_with_one_objective(backend):
    # 原本を変更せず、業務入力だけを読み取り今回の対応目的を指定する。
    data = json.loads(
        (ROOT / "docs/reference/skillshift-starter-0.1/examples/roster.json").read_text()
    )
    data["objectives"] = data["objectives"][:1]
    data["solver"]["backend"] = backend
    original = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["solver"]["backend"] == "cp_sat"
    assert result["solver"]["selection_reason"] == (
        "JOINT_ROSTER" if backend == "auto" else "EXPLICIT_BACKEND"
    )
    assert len(normalize(data).candidates) == 32
    assert len(result["solution"]["shifts"]) == 8
    assert result["objectives"][0]["value"] == 60
    assert verify_solution(normalize(data), result["solution"]) == ([], (60,))
    assert data == original


def test_original_multiple_objectives():
    data = json.loads(
        (ROOT / "docs/reference/skillshift-starter-0.1/examples/roster.json").read_text()
    )
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert [o["value"] for o in result["objectives"]] == [60, 2640, 0]
    assert verify_solution(normalize(data), result["solution"]) == ([], (60, 2640, 0))


def test_scheduled_minutes_exclude_breaks_include_waiting():
    data = request()
    data["shift_candidates"] = [candidate(breaks=[(630, 660)])]
    data["demand"] = [demand()]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 60
    assert len(result["solution"]["assignments"]) == 1
    assert result["solution"]["assignments"][0]["interval"] == interval(end=630)


@pytest.mark.parametrize("minutes", [0, 29, 30, 59, 60, 61])
def test_scheduled_minutes_limit(minutes):
    data = request()
    data["shift_candidates"] = [candidate(breaks=[(630, 660)])]
    data["demand"] = [demand()]
    data["constraints"] = [rule("max_scheduled_minutes", minutes)]
    assert_response(solve(data), "OPTIMAL" if minutes >= 60 else "INFEASIBLE")


@pytest.mark.parametrize("minutes", [29, 30, 31])
def test_assigned_minutes_exclude_waiting(minutes):
    data = request()
    data["demand"] = [demand()]
    data["constraints"] = [rule("max_assigned_minutes", minutes)]
    assert_response(solve(data), "OPTIMAL" if minutes >= 30 else "INFEASIBLE")


@pytest.mark.parametrize("break_gap", [False, True])
def test_role_switches_ignore_waiting_and_break_gaps(break_gap):
    data = request()
    data["shift_candidates"] = [candidate(breaks=[(630, 660)] if break_gap else [])]
    data["demand"] = [demand(), demand(start=660, end=690, role="hall")]
    data["objectives"] = [{"id": "changes", "metric": "role_switches"}]
    data["constraints"] = [rule("max_role_switches", 0)]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 0
    data["demand"][1]["interval"]["start"] = stamp(minute=630)
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize("minutes", [1259, 1260, 1261])
@pytest.mark.parametrize("history", [False, True])
def test_rest_boundary_with_history(minutes, history):
    data = request(days=2)
    data["demand"] = [demand(0), demand(1)]
    if history:
        data["demand"] = [demand(0)]
        data["employees"][0]["history"] = {
            "last_shift_end": stamp(-1, 780),
            "consecutive_work_days_before_window": 1,
        }
    else:
        data["employees"][0]["availability"][0] = interval(end=780)
        data["shift_candidates"][0] = candidate(end=780)
    data["constraints"] = [rule("min_rest_minutes", minutes)]
    assert_response(solve(data), "OPTIMAL" if minutes <= 1260 else "INFEASIBLE")


def test_rest_model_stays_linear_with_5000_distinct_candidates():
    data = request(days=2)
    data["employees"][0]["availability"] = [interval(day, 540, 1020) for day in range(2)]
    masks = list(itertools.islice((i for i in range(1, 1 << 14) if i.bit_count() <= 10), 2500))
    data["shift_candidates"] = [
        candidate(
            day=day,
            start=540,
            end=1020,
            breaks=[(540 + 30 * (i + 1), 570 + 30 * (i + 1)) for i in range(14) if mask & (1 << i)],
            identifier=f"shift_{day}_{mask}",
        )
        for day in range(2)
        for mask in masks
    ]
    data["constraints"] = [rule("min_rest_minutes", 1020)]
    model, *_ = cp_sat.prepare(normalize(data), cp_model)
    # 翌朝まで16時間、必要休息17時間。ペア制約なら625万件になる入力。
    assert sum(c.has_interval() for c in model.proto.constraints) == 5000
    assert sum(c.has_no_overlap() for c in model.proto.constraints) == 1
    assert len(model.proto.constraints) < 10000


@pytest.mark.parametrize("limit", [0, 1, 2, 3, 4])
def test_consecutive_days_inherit_history(limit):
    data = request(days=2)
    data["employees"][0]["history"] = {
        "last_shift_end": stamp(-1, 780),
        "consecutive_work_days_before_window": 1,
    }
    data["demand"] = [demand(0), demand(1)]
    data["constraints"] = [rule("max_consecutive_days", limit)]
    assert_response(solve(data), "OPTIMAL" if limit >= 3 else "INFEASIBLE")


def test_day_off_resets_history_even_when_history_exceeds_limit():
    data = request(days=3)
    data["employees"][0]["history"] = {
        "last_shift_end": stamp(-1, 780),
        "consecutive_work_days_before_window": 5,
    }
    data["demand"] = [demand(1), demand(2)]
    data["constraints"] = [rule("max_consecutive_days", 2)]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert len(result["solution"]["shifts"]) == 2


def test_disjoint_candidates_are_alternatives_not_split_shifts():
    data = request()
    data["shift_candidates"] = [candidate(end=630), candidate(start=660)]
    data["demand"] = [demand(), demand(start=660, end=690)]
    assert_response(solve(data), "INFEASIBLE")


def test_breaks_and_unselected_shifts_cannot_cover_demand():
    data = request()
    data["shift_candidates"] = [candidate(breaks=[(630, 660)])]
    data["demand"] = [demand(start=630, end=660)]
    assert_response(solve(data), "INFEASIBLE")
    data["shift_candidates"] = []
    assert_response(solve(data), "INFEASIBLE")


def test_employee_selection_requires_skill_combination():
    data = request(employees=("alice", "bob", "carol"))
    data["skills"] = [{"id": "cook", "label": "調理"}, {"id": "serve", "label": "接客"}]
    data["roles"][0]["required_skills"] = [{"skill_id": "cook", "min_level": 1}]
    data["roles"][1]["required_skills"] = [{"skill_id": "serve", "min_level": 1}]
    data["employees"][0]["skills"] = [{"skill_id": "cook", "level": 1}]
    data["employees"][1]["skills"] = [{"skill_id": "serve", "level": 1}]
    data["demand"] = [demand(), demand(role="hall")]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert {s["employee_id"] for s in result["solution"]["shifts"]} == {"alice", "bob"}
    data["shift_candidates"] = [data["shift_candidates"][0], data["shift_candidates"][2]]
    assert_response(solve(data), "INFEASIBLE")


def test_empty_demand_selects_no_work_under_scheduled_objective():
    data = request()
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["solution"] == {"assignments": [], "shifts": []}
    assert result["objectives"][0]["value"] == 0
    data["employees"][0]["availability"] = []
    data["shift_candidates"] = []
    assert_response(solve(data), "OPTIMAL")


def test_missing_backend_never_falls_back(monkeypatch):
    def unavailable():
        raise cp_sat.BackendUnavailable

    monkeypatch.setattr(cp_sat, "load_backend", unavailable)
    monkeypatch.setattr(flow, "run", lambda _: pytest.fail("unexpected flow"))
    result = solve(request())
    assert_response(result, "BACKEND_UNAVAILABLE")
    assert result["solver"]["selection_reason"] == "JOINT_ROSTER"


def test_scheduled_limits_apply_individually_and_all_rules_apply():
    data = request(employees=("alice", "bob"))
    data["demand"] = [demand(people=2)]
    data["constraints"] = [rule("max_scheduled_minutes", 90, ("alice", "bob"))]
    result = solve(data)
    assert_response(result, "OPTIMAL")
    assert result["objectives"][0]["value"] == 180
    data["constraints"].append(rule("max_scheduled_minutes", 60, identifier="stricter"))
    assert_response(solve(data), "INFEASIBLE")


@pytest.mark.parametrize("status", ["FEASIBLE", "UNKNOWN", "INFEASIBLE", "MODEL_INVALID"])
def test_roster_native_statuses(monkeypatch, status):
    data = request()
    data["demand"] = [demand()]
    original = cp_model.CpSolver.solve

    def controlled(solver, model):
        if status == "FEASIBLE":
            assert original(solver, model) == cp_model.OPTIMAL
        elif status == "UNKNOWN":
            solver.parameters.max_time_in_seconds = 1e-12
            assert original(solver, model) == cp_model.UNKNOWN
        return getattr(cp_model, status)

    monkeypatch.setattr(cp_model.CpSolver, "solve", controlled)
    result = solve(data)
    assert_response(result, "INTERNAL_ERROR" if status == "MODEL_INVALID" else status)
    if status == "FEASIBLE":
        assert result["objectives"][0]["value"] == 90
        assert result["objectives"][0]["proven_optimal"] is False


def test_real_roster_search_timeout_is_unknown():
    data = request()
    data["demand"] = [demand()]
    data["solver"]["time_limit_seconds"] = 1e-9
    assert_response(solve(data), "UNKNOWN")


def exhaustive_value(data):
    # 元 JSON の勤務候補の全部分集合と、需要枠への担当配置を列挙する。
    # normalize・候補展開・独立検証器・ソルバーの表は使用しない。
    parse = datetime.fromisoformat
    candidates = data["shift_candidates"]
    employees = {e["id"]: e for e in data["employees"]}
    role_skills = {r["id"]: r["required_skills"] for r in data["roles"]}
    first = parse(data["planning_window"]["start"])
    last = parse(data["planning_window"]["end"])
    needs = []
    for item in data["demand"]:
        a, b = parse(item["interval"]["start"]), parse(item["interval"]["end"])
        while a < b:
            needs.extend([(a, item["role_id"])] * item["required_people"])
            a += timedelta(minutes=30)
    best = None
    for bits in itertools.product((False, True), repeat=len(candidates)):
        selected = [c for c, bit in zip(candidates, bits, strict=True) if bit]
        by_employee = defaultdict(list)
        dates = set()
        valid = True
        scheduled = Counter()
        for c in selected:
            e, a, b = c["employee_id"], parse(c["interval"]["start"]), parse(c["interval"]["end"])
            key = e, a.date()
            if key in dates:
                valid = False
            dates.add(key)
            by_employee[e].append((a, b))
            scheduled[e] += int((b - a).total_seconds() // 60) - sum(
                int((parse(i["end"]) - parse(i["start"])).total_seconds() // 60)
                for i in c["breaks"]
            )
        for c in data["constraints"]:
            for e in c["employee_ids"]:
                if c["type"] == "max_scheduled_minutes" and scheduled[e] > c["limit_minutes"]:
                    valid = False
                if c["type"] == "min_rest_minutes":
                    previous = employees[e]["history"]["last_shift_end"]
                    previous = parse(previous) if previous else None
                    for a, b in sorted(by_employee[e]):
                        if previous and (a - previous).total_seconds() < c["limit_minutes"] * 60:
                            valid = False
                        previous = b
                if c["type"] == "max_consecutive_days":
                    count = employees[e]["history"]["consecutive_work_days_before_window"]
                    day = first.date()
                    while day < last.date():
                        count = count + 1 if (e, day) in dates else 0
                        if count > c["limit_days"]:
                            valid = False
                        day += timedelta(days=1)
        if not valid:
            continue
        options = []
        for a, role in needs:
            eligible = []
            for e, employee in employees.items():
                levels = {s["skill_id"]: s["level"] for s in employee["skills"]}
                if any(
                    s["skill_id"] not in levels or levels[s["skill_id"]] < s["min_level"]
                    for s in role_skills[role]
                ):
                    continue
                if any(
                    c["employee_id"] == e
                    and parse(c["interval"]["start"]) <= a
                    and a + timedelta(minutes=30) <= parse(c["interval"]["end"])
                    and not any(parse(b["start"]) <= a < parse(b["end"]) for b in c["breaks"])
                    for c in selected
                ):
                    eligible.append(e)
            options.append(eligible)
        for assigned in itertools.product(*options):
            roles = defaultdict(dict)
            minutes = Counter()
            penalty = 0
            valid = True
            for (a, role), e in zip(needs, assigned, strict=True):
                if a in roles[e]:
                    valid = False
                roles[e][a] = role
                minutes[e] += 30
                penalty += sum(
                    30 * p["penalty_per_minute"]
                    for p in data["preferences"]
                    if e in p["employee_ids"] and role == p["role_id"]
                )
            switches = {
                e: sum(
                    a + timedelta(minutes=30) in row and role != row[a + timedelta(minutes=30)]
                    for a, role in row.items()
                )
                for e, row in roles.items()
            }
            for c in data["constraints"]:
                for e in c["employee_ids"]:
                    if c["type"] == "max_assigned_minutes" and minutes[e] > c["limit_minutes"]:
                        valid = False
                    if c["type"] == "max_role_switches" and switches.get(e, 0) > c["limit_count"]:
                        valid = False
            if valid:
                metrics = {
                    "scheduled_minutes": sum(scheduled.values()),
                    "role_switches": sum(switches.values()),
                    "preference_penalty": penalty,
                }
                value = tuple(metrics[o["metric"]] for o in data["objectives"])
                best = value if best is None else min(best, value)
    return best


@pytest.mark.parametrize("seed", range(60))
def test_optimum_matches_independent_enumeration(seed):
    rng = random.Random(seed)
    data = request(days=2, employees=("alice", "bob"))
    data["shift_candidates"] = []
    for e in ("alice", "bob"):
        for day in range(2):
            data["shift_candidates"].extend(
                [
                    candidate(e, day, breaks=[(630, 660)] if rng.randrange(2) else []),
                    candidate(e, day, end=630),
                ]
            )
    data["demand"] = [
        demand(day, minute, minute + 30, rng.choice(["kitchen", "hall"]))
        for day in range(2)
        for minute in (600, 630, 660)
        if rng.randrange(3)
    ]
    data["constraints"] = [
        rule("max_scheduled_minutes", rng.choice([30, 90, 180]), ("alice", "bob")),
        rule("min_rest_minutes", rng.choice([0, 1320, 1440]), ("alice", "bob"), "rest"),
        rule("max_consecutive_days", rng.choice([0, 1, 2, 3]), ("alice", "bob"), "days"),
        rule("max_assigned_minutes", rng.choice([30, 90, 180]), ("alice", "bob"), "assigned"),
        rule("max_role_switches", rng.randrange(3), ("alice", "bob"), "changes"),
    ]
    if rng.randrange(2):
        data["employees"][0]["history"] = {
            "last_shift_end": stamp(-1, 690),
            "consecutive_work_days_before_window": 1,
        }
    metrics = rng.sample(
        ["scheduled_minutes", "preference_penalty", "role_switches"], rng.randrange(4)
    )
    data["objectives"] = [{"id": metric, "metric": metric} for metric in metrics]
    if "preference_penalty" in metrics:
        data["preferences"] = [
            {
                "id": "avoid",
                "type": "avoid_role",
                "employee_ids": ["alice"],
                "role_id": "kitchen",
                "penalty_per_minute": 2,
            }
        ]
    expected = exhaustive_value(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE" if expected is None else "OPTIMAL")
    if expected is not None:
        assert tuple(o["value"] for o in result["objectives"]) == expected


def test_roster_cli_json_only():
    result = subprocess.run(
        [sys.executable, "-m", "schedula", "solve", str(ROOT / "examples/roster.json")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert_response(json.loads(result.stdout), "OPTIMAL")
