from collections import Counter, defaultdict

from .contract import InvalidInput, check_json, diagnostic, parse_datetime, schema_errors


def verify_solution(problem, solution):
    """元入力と共通の解を照合し、違反と単一目的の再計算値を返す。"""
    try:
        check_json(solution)
    except InvalidInput as error:
        return error.diagnostics, 0
    violations = schema_errors("solution", solution)
    if violations:
        return violations, 0

    def fail(code, message, path, related_ids=(), **facts):
        if len(violations) < 1000:
            violations.append(diagnostic(code, message, path, related_ids, **facts))

    request, grid = problem.request, problem.grid
    if solution["shifts"]:
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
            if employee_id in preference["employee_ids"] and role_id == preference["role_id"]:
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
    for index, demand in enumerate(request["demand"]):
        start, end = grid.interval(demand["interval"], f"/demand/{index}/interval")
        for slot in range(start, end):
            expected[slot, demand["role_id"]] = int(demand["required_people"])
    for slot, role_id in sorted(expected.keys() | actual.keys()):
        required, assigned = expected[slot, role_id], actual[slot, role_id]
        if assigned != required:
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
    # 現在は目的を最大1件に限定する。評価はソルバーの変数・費用から独立して再計算する。
    value = (
        sum(switches.values())
        if request["objectives"] and request["objectives"][0]["metric"] == "role_switches"
        else penalty
    )
    return violations[:1000], value
