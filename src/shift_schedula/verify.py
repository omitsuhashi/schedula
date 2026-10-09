import logging
import time
from collections import Counter, defaultdict
from datetime import timedelta

from .contract import (
    InvalidInput,
    check_json,
    diagnostic,
    parse_datetime,
    schema_errors,
    schema_version_of,
    summary_fields,
)

logger = logging.getLogger(__name__)


def priority_summary(request, shortage):
    """元需要と独立検証の不足一覧から再計算する。探索の証明は付与しない。"""
    from .model import priority_levels

    levels = {d["id"]: d.get("priority", 0) for d in request["demand"]}
    totals = Counter()
    for item in shortage["shortages"]:
        minutes = (
            parse_datetime(item["interval"]["end"]) - parse_datetime(item["interval"]["start"])
        ).total_seconds() // 60
        totals[levels[item["demand_id"]]] += int(minutes) * item["missing_people"]
    return {
        "groups": [
            {"priority": level, "total_person_minutes": totals[level], "proven_minimal": False}
            for level in priority_levels(request)
        ]
    }


def verification_response(request, diagnostics=()):
    """入力を補完・検証せず、独立検証の未実施応答を作る。"""
    result = {
        "schema_version": schema_version_of(request),
        "request_id": request.get("request_id")
        if isinstance(request, dict) and isinstance(request.get("request_id"), str)
        else None,
        "status": "INVALID_INPUT",
        "verification": {"performed": False, "valid": None, "violations": []},
        "demand_satisfied": None,
        "objectives": [],
        "shortage_summary": None,
        "fairness_summary": None,
        "change_summary": None,
        "diagnostics": list(diagnostics),
        "stats": {"elapsed_seconds": 0.0},
    }
    result.update(dict.fromkeys(summary_fields(result["schema_version"])))
    return result


def verify(request: dict, solution: dict) -> dict:
    """JSON 型の編集解を検証する。探索と最適性の認定は行わない。"""
    from .extensions import evaluate
    from .model import TimezoneDataError, normalize

    started = time.perf_counter()
    result = verification_response(request)
    try:
        problem = normalize(request)
        violations, values, shortage = verify_plan(problem, solution)
        result["verification"] = {
            "performed": True,
            "valid": not violations,
            "violations": violations,
        }
        if violations:
            result["status"] = "INVALID_PLAN"
            result["diagnostics"] = violations
        else:
            complete = shortage["total_person_minutes"] == 0
            result.update(
                status="VALID" if complete else "PARTIAL",
                demand_satisfied=complete,
                shortage_summary={**shortage, "proven_minimal": False},
            )
            result["objectives"] = [
                {**objective, "value": value, "proven_optimal": False}
                for objective, value in zip(request["objectives"], values, strict=True)
            ]
            _, _, summaries = evaluate(problem, solution)
            result.update(summaries)
            result["priority_summary"] = priority_summary(request, shortage)
    except InvalidInput as error:
        result["diagnostics"] = error.diagnostics
    except TimezoneDataError:
        logger.debug("独立検証で時刻データを読み取れませんでした。", exc_info=True)
        result.update(
            status="INTERNAL_ERROR",
            diagnostics=[
                diagnostic("TIMEZONE_DATA_UNAVAILABLE", "OSのTZDBまたはtzdataの導入を確認します。")
            ],
        )
    except Exception:
        logger.debug("独立検証で内部例外が発生しました。", exc_info=True)
        result.update(
            status="INTERNAL_ERROR",
            demand_satisfied=None,
            objectives=[],
            shortage_summary=None,
            fairness_summary=None,
            change_summary=None,
            verification={"performed": False, "valid": None, "violations": []},
            diagnostics=[diagnostic("INTERNAL_ERROR", "独立検証の処理に失敗しました。")],
        )
    if result["status"] not in {"VALID", "PARTIAL"}:
        for name in result:
            if name.endswith("_summary"):
                result[name] = None
    result["stats"]["elapsed_seconds"] = time.perf_counter() - started
    errors = schema_errors("verification", result)
    if errors:
        raise InvalidInput(errors)
    return result


def verify_shifts(request, grid, shifts, fail, active_groups=None):
    if request.get("continuity"):
        from .continuity import verify_shifts as verify_continuity_shifts

        return verify_continuity_shifts(request, grid, shifts, fail, active_groups)
    from .roster import expand_candidates

    # 元入力から再展開し、CP-SAT の候補表・選択変数を使わず照合する。
    candidates = {c.id: c for c in expand_candidates(request, grid)}
    seen, dates = set(), set()
    coverage, breaks = defaultdict(set), defaultdict(set)
    selected = defaultdict(list)
    scheduled = Counter()
    for index, shift in enumerate(shifts):
        path = f"/shifts/{index}"
        identifier, employee = shift["candidate_id"], shift["employee_id"]
        if identifier not in candidates:
            fail("UNKNOWN_CANDIDATE", "結果に存在しない勤務候補があります。", path, [identifier])
            continue
        candidate = candidates[identifier]
        try:
            segments = tuple(
                (
                    *grid.interval(
                        s["interval"],
                        f"{path}/segments/{i}/interval",
                    ),
                    tuple(
                        sorted(
                            grid.interval(
                                b,
                                f"{path}/segments/{i}/breaks/{j}",
                            )
                            for j, b in enumerate(s["breaks"])
                        )
                    ),
                )
                for i, s in enumerate(shift["segments"])
            )
            interval = segments[0][0], segments[-1][1]
            rest = tuple(b for _, _, rests in segments for b in rests)
        except InvalidInput as error:
            for d in error.diagnostics:
                fail(d["code"], d["message"], d["json_pointer"])
            continue
        if (
            employee != candidate.employee_id
            or interval != (candidate.start, candidate.end)
            or rest != candidate.breaks
            or (segments != candidate.segments or shift["work_day"] != candidate.day.isoformat())
        ):
            fail(
                "CANDIDATE_MISMATCH",
                "従業員・勤務区間・休憩が元の候補と一致しません。",
                path,
                [identifier],
            )
            continue
        if identifier in seen:
            fail("DUPLICATE_SHIFT", "同じ勤務候補を複数回選択しています。", path, [identifier])
            continue
        seen.add(identifier)
        key = employee, candidate.day
        if key in dates:
            fail(
                "MULTIPLE_DAILY_SHIFTS", "1人・ローカル日付につき最大1勤務です。", path, [employee]
            )
        dates.add(key)
        start, end = interval
        blocked = {slot for a, b in rest for slot in range(a, b)}
        work = {slot for a, b, _ in segments for slot in range(a, b)} - blocked
        coverage[employee].update(work)
        breaks[employee].update(blocked)
        scheduled[employee] += len(work) * grid.slot_minutes
        selected[employee].append((start, end, candidate.day.toordinal()))
    for employee, intervals in selected.items():
        ordered = sorted(intervals)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
            fail(
                "OVERLAPPING_SHIFTS",
                "開始日が異なる勤務の外側区間が重複しています。",
                "/shifts",
                [employee],
            )
    first_day = grid.start.astimezone(grid.timezone).date().toordinal()
    end_day = grid.end.astimezone(grid.timezone).date().toordinal()
    histories = {e["id"]: e["history"] for e in request["employees"]}
    for index, constraint in enumerate(request["constraints"]):
        if active_groups is not None and f"/constraints/{index}" not in active_groups:
            continue
        kind = constraint["type"]
        path = f"/constraints/{index}"
        for employee in constraint["employee_ids"]:
            related = [constraint["id"], employee]
            if (
                kind == "max_scheduled_minutes"
                and scheduled[employee] > constraint["limit_minutes"]
            ):
                fail(
                    "MAX_SCHEDULED_MINUTES_VIOLATION",
                    "勤務量が上限を超えています。",
                    path,
                    related,
                    actual_value=scheduled[employee],
                    limit=constraint["limit_minutes"],
                )
            elif kind == "scheduled_minutes_bounds":
                start, end = grid.interval(constraint["interval"], path + "/interval")
                minutes = len(coverage[employee] & set(range(start, end))) * grid.slot_minutes
                for field, code, invalid in (
                    (
                        "min_minutes",
                        "MIN_SCHEDULED_MINUTES_VIOLATION",
                        minutes < constraint.get("min_minutes", 0),
                    ),
                    (
                        "max_minutes",
                        "MAX_SCHEDULED_MINUTES_VIOLATION",
                        minutes > constraint.get("max_minutes", 10000000),
                    ),
                ):
                    if invalid:
                        fail(
                            code,
                            "評価区間の勤務量が必須の上下限に違反しています。",
                            path,
                            related,
                            actual_value=minutes,
                            limit=constraint[field],
                        )
            elif kind == "min_rest_minutes":
                previous = histories[employee]["last_shift_end"]
                previous = parse_datetime(previous) if previous is not None else None
                for start, end, _ in sorted(selected[employee]):
                    a = grid.start + timedelta(minutes=start * grid.slot_minutes)
                    if previous is not None and a - previous < timedelta(
                        minutes=int(constraint["limit_minutes"])
                    ):
                        fail(
                            "MIN_REST_MINUTES_VIOLATION",
                            "勤務間の休息が不足しています。",
                            path,
                            related,
                            actual_value=(a - previous).total_seconds() / 60,
                            limit=constraint["limit_minutes"],
                        )
                    previous = grid.start + timedelta(minutes=end * grid.slot_minutes)
            elif kind == "max_consecutive_days":
                count = int(histories[employee]["consecutive_work_days_before_window"])
                working = {day for _, _, day in selected[employee]}
                for day in range(first_day, end_day):
                    count = count + 1 if day in working else 0
                    if count > constraint["limit_days"]:
                        fail(
                            "MAX_CONSECUTIVE_DAYS_VIOLATION",
                            "連勤日数が上限を超えています。",
                            path,
                            related,
                            actual_value=count,
                            limit=constraint["limit_days"],
                        )
            elif kind == "min_split_gap_minutes":
                for identifier in seen:
                    candidate = candidates[identifier]
                    if candidate.employee_id == employee and any(
                        (b[0] - a[1]) * grid.slot_minutes < constraint["limit_minutes"]
                        for a, b in zip(candidate.segments, candidate.segments[1:], strict=False)
                    ):
                        fail(
                            "MIN_SPLIT_GAP_VIOLATION",
                            "分割勤務の区間間隔が不足しています。",
                            path,
                            [*related, identifier],
                        )
    return coverage, breaks, scheduled


def verify_solution(problem, solution, *, require_complete=False):
    """従来の呼び出し向けに、違反と目的順の再計算値を返す。"""
    return verify_plan(problem, solution, require_complete=require_complete)[:2]


def verify_plan(problem, solution, *, require_complete=False, active_groups=None):
    """元入力と解を照合し、違反・目的値・不足を独立に再計算する。"""
    try:
        check_json(solution)
    except InvalidInput as error:
        return error.diagnostics, (), None
    except RecursionError:
        return [diagnostic("NON_JSON_VALUE", "解の階層が深すぎます。")], (), None
    violations = schema_errors("solution", solution, problem.request["schema_version"])
    if violations:
        return violations, (), None
    if not problem.request.get("continuity") and any(
        "committed_shift_id" in s for s in solution["shifts"]
    ):
        violations.append(
            diagnostic(
                "UNEXPECTED_COMMITTED_SHIFT",
                "確定勤務の参照には continuity が必要です。",
                "/shifts",
            )
        )
    if violations:
        return violations, (), None

    def fail(code, message, path, related_ids=(), **facts):
        if len(violations) < 1000:
            violations.append(diagnostic(code, message, path, related_ids, **facts))

    request, grid = problem.request, problem.grid
    roster = request["problem_type"] == "roster"
    coverage, breaks, scheduled = (
        verify_shifts(request, grid, solution["shifts"], fail, active_groups)
        if roster
        else ({}, {}, {})
    )
    if roster and (not violations):
        from .day_counts import evaluate as evaluate_day_counts

        evaluate_day_counts(request, grid, solution, fail, active_groups)
    if roster and (not violations):
        from .shift_patterns import evaluate as evaluate_patterns

        evaluate_patterns(request, grid, solution, fail, active_groups)
    if roster and (not violations):
        from .coworkers import evaluate as evaluate_coworkers

        evaluate_coworkers(request, grid, coverage, fail, active_groups)
    if not roster and solution["shifts"]:
        fail("UNEXPECTED_SHIFTS", "assignment の勤務結果は空にします。", "/shifts")
    employees = {employee["id"]: employee for employee in request["employees"]}
    roles = {role["id"]: role for role in request["roles"]}
    actual, occupied = Counter(), set()
    intervals = defaultdict(list)
    assigned_roles = defaultdict(dict)
    penalty = 0
    for index, assignment in enumerate(solution["assignments"]):
        path = f"/assignments/{index}"
        employee_id, role_id = assignment["employee_id"], assignment["role_id"]
        if employee_id not in employees or role_id not in roles:
            fail(
                "UNKNOWN_REFERENCE",
                "結果の従業員または役割が未登録です。",
                path,
                [employee_id, role_id],
            )
            continue
        try:
            start, end = grid.interval(assignment["interval"], path + "/interval")
        except InvalidInput as error:
            violations.extend(error.diagnostics)
            continue
        intervals[employee_id, role_id].append((start, end, index))
        employee, role = employees[employee_id], roles[role_id]
        levels = {skill["skill_id"]: skill["level"] for skill in employee["skills"]}
        if any(
            skill["skill_id"] not in levels or levels[skill["skill_id"]] < skill["min_level"]
            for skill in role["required_skills"]
        ):
            fail("SKILL_VIOLATION", "担当資格を満たしていません。", path, [employee_id, role_id])
        availability = [
            (parse_datetime(value["start"]), parse_datetime(value["end"]))
            for value in employee["availability"]
        ]
        for slot in range(start, end):
            if roster and slot not in coverage.get(employee_id, set()):
                on_break = slot in breaks.get(employee_id, set())
                fail(
                    "BREAK_ASSIGNMENT" if on_break else "UNSELECTED_SHIFT_ASSIGNMENT",
                    "休憩中または選択した勤務以外に配置されています。",
                    path,
                    [employee_id],
                    slot=slot,
                )
            interval = grid.output_interval(slot, slot + 1)
            a, b = parse_datetime(interval["start"]), parse_datetime(interval["end"])
            if not any(left <= a and b <= right for left, right in availability):
                fail(
                    "AVAILABILITY_VIOLATION",
                    "勤務可能時間外の配置です。",
                    path,
                    [employee_id],
                    slot=slot,
                )
            if (employee_id, slot) in occupied:
                fail(
                    "DOUBLE_ASSIGNMENT",
                    "同じ従業員を同じ時間に二重配置しています。",
                    path,
                    [employee_id],
                    slot=slot,
                )
            occupied.add((employee_id, slot))
            assigned_roles[employee_id][slot] = role_id
            actual[slot, role_id] += 1
        minutes = (end - start) * grid.slot_minutes
        for preference in request["preferences"]:
            if (
                preference["type"] == "avoid_role"
                and employee_id in preference["employee_ids"]
                and role_id == preference["role_id"]
            ):
                penalty += minutes * int(preference["penalty_per_minute"])
    for index, preference in enumerate(request["preferences"]):
        if preference["type"] == "avoid_role":
            continue
        start, end = grid.interval(preference["interval"], f"/preferences/{index}/interval")
        slots = set(range(start, end))
        minutes = sum(
            len(coverage.get(e, set()) & slots) * grid.slot_minutes
            for e in preference["employee_ids"]
        )
        if preference["type"] == "prefer_work":
            minutes = (end - start) * grid.slot_minutes * len(preference["employee_ids"]) - minutes
        penalty += minutes * int(preference["penalty_per_minute"])
    for (employee_id, role_id), values in intervals.items():
        ordered = sorted(values)
        for (_, previous_end, previous_index), (start, _, index) in zip(
            ordered, ordered[1:], strict=False
        ):
            if previous_end == start:
                fail(
                    "UNMERGED_ASSIGNMENTS",
                    "隣接した同じ従業員・役割の担当をまとめてください。",
                    f"/assignments/{index}/interval",
                    [employee_id, role_id],
                    previous_assignment_index=previous_index,
                    slot=start,
                )
    expected = Counter()
    relaxed = set()
    shortages = []
    total = 0
    for index, demand in enumerate(request["demand"]):
        start, end = grid.interval(demand["interval"], f"/demand/{index}/interval")
        runs = []
        for slot in range(start, end):
            required = int(demand["required_people"])
            expected[slot, demand["role_id"]] = required
            if required and active_groups is not None and f"/demand/{index}" not in active_groups:
                relaxed.add((slot, demand["role_id"]))
            assigned = actual[slot, demand["role_id"]]
            minimum = int(demand.get("minimum_people", 0))
            if assigned < minimum and (slot, demand["role_id"]) not in relaxed:
                fail(
                    "MINIMUM_DEMAND_VIOLATION",
                    "配置人数が必須の最低人数を満たしていません。",
                    f"/demand/{index}",
                    [demand["id"], demand["role_id"]],
                    interval_start=grid.output_interval(slot, slot + 1)["start"],
                    interval_end=grid.output_interval(slot, slot + 1)["end"],
                    minimum_people=minimum,
                    assigned_people=assigned,
                )
            if assigned < required:
                total += (required - assigned) * grid.slot_minutes
                if runs and runs[-1][1] == slot and runs[-1][2] == assigned:
                    runs[-1][1] = slot + 1
                else:
                    runs.append([slot, slot + 1, assigned])
        shortages.extend(
            {
                "demand_id": demand["id"],
                "role_id": demand["role_id"],
                "interval": grid.output_interval(a, b),
                "required_people": required,
                "assigned_people": assigned,
                "missing_people": required - assigned,
                **({"minimum_people": minimum}),
            }
            for a, b, assigned in runs
        )
    for slot, role_id in sorted(expected.keys() | actual.keys()):
        if (slot, role_id) in relaxed:
            continue
        required, assigned = expected[slot, role_id], actual[slot, role_id]
        if assigned > required or (assigned < required and (require_complete)):
            code = "DEMAND_SHORTAGE" if assigned < required else "DEMAND_EXCESS"
            fail(
                code,
                "配置人数が厳密な需要と一致しません。",
                "/assignments",
                [role_id],
                slot=slot,
                required_people=required,
                assigned_people=assigned,
            )
    assigned_minutes = Counter(employee_id for employee_id, _ in occupied)
    switches = {
        employee_id: sum(
            slot + 1 in values and role_id != values[slot + 1] for slot, role_id in values.items()
        )
        for employee_id, values in assigned_roles.items()
    }
    for index, constraint in enumerate(request["constraints"]):
        if active_groups is not None and f"/constraints/{index}" not in active_groups:
            continue
        if constraint["type"] not in {"max_assigned_minutes", "max_role_switches"}:
            continue
        minutes_limit = constraint["type"] == "max_assigned_minutes"
        field = "limit_minutes" if minutes_limit else "limit_count"
        for employee_id in constraint["employee_ids"]:
            value = (
                assigned_minutes[employee_id] * grid.slot_minutes
                if minutes_limit
                else switches.get(employee_id, 0)
            )
            if value > constraint[field]:
                fail(
                    "MAX_ASSIGNED_MINUTES_VIOLATION"
                    if minutes_limit
                    else "MAX_ROLE_SWITCHES_VIOLATION",
                    "担当時間または担当切替の上限を超えています。",
                    f"/constraints/{index}",
                    [constraint["id"], employee_id],
                    actual_value=value,
                    limit=constraint[field],
                )
    if active_groups is not None:
        from .extensions import check_fixed_states, fixed_requirements, states

        work, roles = states(grid, solution, continuity=bool(request.get("continuity")))
        violations.extend(
            check_fixed_states(
                fixed_requirements(problem, active_groups), work, roles, employee_ids=employees
            )
        )
        # 診断証拠の有効性だけを調べ、公開verifyの条件と目的評価は変えない。
        return violations[:1000], (), None
    # ソルバーの変数・費用から独立して、未探索の目的も同じ解から再計算する。
    metrics = {
        "preference_penalty": penalty,
        "role_switches": sum(switches.values()),
        "scheduled_minutes": sum(scheduled.values()),
    }
    from .extensions import evaluate

    extension_violations, extension_metrics, _ = evaluate(problem, solution)
    violations.extend(extension_violations)
    metrics.update(extension_metrics)
    from .model import objective_key

    return (
        violations[:1000],
        tuple(metrics[objective_key(o)] for o in request["objectives"]),
        {"total_person_minutes": total, "shortages": shortages},
    )
