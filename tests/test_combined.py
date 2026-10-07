import copy
import itertools
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from shift_schedula import solve
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def parse(value):
    return datetime.fromisoformat(value).astimezone(UTC)


def slots(interval, step):
    start, end = parse(interval["start"]), parse(interval["end"])
    while start < end:
        yield start
        start += step


def states(shifts, assignments, step):
    work, roles = {}, {}
    for duty in shifts:
        for segment in duty["segments"]:
            for slot in slots(segment["interval"], step):
                work[duty["employee_id"], slot] = "work"
            for rest in segment["breaks"]:
                for slot in slots(rest, step):
                    work[duty["employee_id"], slot] = "break"
    for assignment in assignments:
        for slot in slots(assignment["interval"], step):
            roles[assignment["employee_id"], slot] = assignment["role_id"]
    return work, roles


def enumerate_plans(data):
    # 元JSONの候補部分集合と、全需要枠への担当組合せを列挙する。
    # normalize・候補展開・目的計算・独立検証器・ソルバーの内部表は使わない。
    step = timedelta(minutes=data["planning_window"]["slot_minutes"])
    slot_minutes = data["planning_window"]["slot_minutes"]
    zone = ZoneInfo(data["planning_window"]["timezone"])
    first_day = parse(data["planning_window"]["start"]).astimezone(zone).date()
    end_day = parse(data["planning_window"]["end"]).astimezone(zone).date()
    employees = {employee["id"]: employee for employee in data["employees"]}
    available = {
        identifier: set().union(*(set(slots(value, step)) for value in employee["availability"]))
        for identifier, employee in employees.items()
    }
    qualified = {
        (employee["id"], role["id"])
        for employee in employees.values()
        for role in data["roles"]
        if all(
            any(
                s["skill_id"] == r["skill_id"] and s["level"] >= r["min_level"]
                for s in employee["skills"]
            )
            for r in role["required_skills"]
        )
    }
    needs = [
        (slot, demand["role_id"], demand["required_people"])
        for demand in data["demand"]
        for slot in slots(demand["interval"], step)
    ]
    previous = data["baseline"]["source_solution"]
    old_work, old_roles = states(previous["shifts"], previous["assignments"], step)
    for bits in itertools.product((False, True), repeat=len(data["shift_candidates"])):
        selected = [c for c, bit in zip(data["shift_candidates"], bits, strict=True) if bit]
        work, _ = states(selected, [], step)
        scheduled = Counter(employee for (employee, _), state in work.items() if state == "work")
        spans, work_days = defaultdict(list), defaultdict(set)
        valid = True
        for candidate in selected:
            employee, segments = candidate["employee_id"], candidate["segments"]
            start, end = (
                parse(segments[0]["interval"]["start"]),
                parse(segments[-1]["interval"]["end"]),
            )
            day = start.astimezone(zone).date()
            valid &= day not in work_days[employee]
            work_days[employee].add(day)
            spans[employee].append((start, end))
            valid &= all(set(slots(s["interval"], step)) <= available[employee] for s in segments)
            for rule in data["constraints"]:
                if employee in rule["employee_ids"] and rule["type"] == "min_split_gap_minutes":
                    valid &= all(
                        (
                            parse(b["interval"]["start"]) - parse(a["interval"]["end"])
                        ).total_seconds()
                        >= 60 * rule["limit_minutes"]
                        for a, b in zip(segments, segments[1:], strict=False)
                    )
        for employee, person in employees.items():
            duties = sorted(spans[employee])
            valid &= all(a[1] <= b[0] for a, b in zip(duties, duties[1:], strict=False))
            for rule in data["constraints"]:
                if employee not in rule["employee_ids"]:
                    continue
                if rule["type"] == "max_scheduled_minutes":
                    valid &= scheduled[employee] * slot_minutes <= rule["limit_minutes"]
                elif rule["type"] == "min_rest_minutes":
                    last = person["history"]["last_shift_end"]
                    last = parse(last) if last is not None else None
                    for start, end in duties:
                        valid &= (
                            last is None
                            or (start - last).total_seconds() >= 60 * rule["limit_minutes"]
                        )
                        last = end
                elif rule["type"] == "max_consecutive_days":
                    count = person["history"]["consecutive_work_days_before_window"]
                    day = first_day
                    while day < end_day:
                        count = count + 1 if day in work_days[employee] else 0
                        valid &= count <= rule["limit_days"]
                        day += timedelta(days=1)
        if not valid:
            continue
        choices = [
            list(
                itertools.combinations(
                    [
                        employee
                        for employee in sorted(employees)
                        if work.get((employee, slot)) == "work" and (employee, role) in qualified
                    ],
                    count,
                )
            )
            for slot, role, count in needs
        ]
        for combination in itertools.product(*choices):
            roles = {}
            valid = True
            for (slot, role, _), people in zip(needs, combination, strict=True):
                for employee in people:
                    valid &= (employee, slot) not in roles
                    roles[employee, slot] = role
            for part in data["fixed_parts"]:
                for slot in slots(part["interval"], step):
                    key = part["employee_id"], slot
                    if "work" in part["components"]:
                        valid &= work.get(key, "off") == old_work.get(key, "off")
                    if "role" in part["components"]:
                        valid &= roles.get(key) == old_roles.get(key)
            switches = Counter(
                employee
                for (employee, slot), role in roles.items()
                if (employee, slot + step) in roles and roles[employee, slot + step] != role
            )
            assigned = Counter(employee for employee, _ in roles)
            for rule in data["constraints"]:
                for employee in rule["employee_ids"]:
                    if rule["type"] == "max_assigned_minutes":
                        valid &= assigned[employee] * slot_minutes <= rule["limit_minutes"]
                    elif rule["type"] == "max_role_switches":
                        valid &= switches[employee] <= rule["limit_count"]
            if not valid:
                continue
            metrics = {
                "plan_changes": sum(
                    work.get(k, "off") != old_work.get(k, "off")
                    for k in work.keys() | old_work.keys()
                )
                + sum(roles.get(k) != old_roles.get(k) for k in roles.keys() | old_roles.keys()),
                "fairness_deviation_minutes": sum(
                    abs(scheduled[t["employee_id"]] * slot_minutes - t["target_minutes"])
                    for t in data["fairness"]["employee_targets"]
                ),
                "scheduled_minutes": sum(scheduled.values()) * slot_minutes,
                "role_switches": sum(switches.values()),
                "preference_penalty": sum(
                    slot_minutes * p["penalty_per_minute"]
                    for (employee, _), role in roles.items()
                    for p in data["preferences"]
                    if employee in p["employee_ids"] and role == p["role_id"]
                ),
            }
            yield tuple(metrics[o["metric"]] for o in data["objectives"]), work, roles


def assert_enumerated_result(data, result):
    plans = list(enumerate_plans(data))
    if not plans:
        assert_response(result, "INFEASIBLE")
        return None
    assert_response(result, "OPTIMAL")
    optimum = min(p[0] for p in plans)
    assert tuple(o["value"] for o in result["objectives"]) == optimum
    work, roles = states(
        result["solution"]["shifts"],
        result["solution"]["assignments"],
        timedelta(minutes=data["planning_window"]["slot_minutes"]),
    )
    assert any(
        value == optimum and actual_work == work and actual_roles == roles
        for value, actual_work, actual_roles in plans
    )
    return optimum


def test_combined_old_night_split_fixed_fairness_changes_and_diagnosis():
    data = json.loads((ROOT / "examples/replan.json").read_text())
    original = copy.deepcopy(data)
    assert assert_enumerated_result(data, solve(data)) == (16, 0, 240)
    # 同じ固定部分を保持し、旧分割勤務も選べる場合は目的順序によって計画が変わる。
    choices = copy.deepcopy(data)
    choices["employees"][0]["availability"].append(copy.deepcopy(data["demand"][1]["interval"]))
    old_shift = copy.deepcopy(data["baseline"]["source_request"]["shift_candidates"][0])
    old_shift["id"] = "alice_split_alternative"
    choices["shift_candidates"].append(old_shift)
    objectives = choices["objectives"]
    for order in itertools.permutations(objectives):
        choices["objectives"] = list(order)
        metrics = [o["metric"] for o in order]
        expected = {"scheduled_minutes": 240}
        if metrics.index("plan_changes") < metrics.index("fairness_deviation_minutes"):
            expected.update(plan_changes=0, fairness_deviation_minutes=240)
        else:
            expected.update(plan_changes=16, fairness_deviation_minutes=0)
        assert assert_enumerated_result(choices, solve(choices)) == tuple(
            expected[m] for m in metrics
        )
    # 欠勤したAliceの後半を固定すると、需要を下げる許可だけでは解除できない。
    fixed_conflict = copy.deepcopy(data)
    fixed_conflict["fixed_parts"].append(
        {
            "id": "preserve_unavailable_second",
            "employee_id": "alice",
            "interval": copy.deepcopy(data["demand"][1]["interval"]),
            "components": ["work", "role"],
        }
    )
    fixed_conflict["diagnosis"] = {
        "time_limit_seconds": 10,
        "max_suggestions": 1,
        "allowed_changes": [
            {
                "id": "drop_second_need",
                "edits": [{"json_pointer": "/demand/1/required_people", "value": 0}],
            }
        ],
    }
    result = solve(fixed_conflict)
    assert assert_enumerated_result(fixed_conflict, result) is None
    detail = result["diagnosis_result"]
    assert detail["status"] == "COMPLETE"
    assert detail["conflict"]["infeasibility_proven"] is True
    assert detail["conflict"]["minimality"] == "not_proven"
    assert "/fixed_parts/1" in {c["json_pointer"] for c in detail["conflict"]["conditions"]}
    assert detail["suggestions"] == []
    lowered = copy.deepcopy(fixed_conflict)
    lowered["demand"][1]["required_people"] = 0
    assert list(enumerate_plans(lowered)) == []
    forbidden = copy.deepcopy(fixed_conflict)
    forbidden["diagnosis"]["allowed_changes"][0]["edits"] = [
        {"json_pointer": "/fixed_parts/1/components", "value": 0}
    ]
    assert_response(solve(forbidden), "INVALID_INPUT")
    assert data == original


def test_combined_performance_input_checks_original_and_allowed_changed_plan():
    data = json.loads((ROOT / "docs/evaluations/inputs/roster-extended.json").read_text())
    original = copy.deepcopy(data)
    result = solve(data)
    assert assert_enumerated_result(data, result) is None
    detail = result["diagnosis_result"]
    assert detail["status"] == "COMPLETE" and detail["conflict"]["infeasibility_proven"] is True
    assert len(detail["suggestions"]) == 1
    suggestion = detail["suggestions"][0]
    assert suggestion["option_id"] == "restore_one_person"
    changed = suggestion["modified_request"]
    expected = copy.deepcopy(data)
    expected.pop("diagnosis")
    expected["demand"][1]["required_people"] = 1
    expected["solver"]["time_limit_seconds"] = changed["solver"]["time_limit_seconds"]
    assert changed == expected
    assert changed["fixed_parts"] == data["fixed_parts"]
    assert assert_enumerated_result(changed, suggestion["response"]) == (16, 0, 240)
    assert data == original
