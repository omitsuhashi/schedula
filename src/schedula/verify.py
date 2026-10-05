from collections import Counter, defaultdict

from .contract import InvalidInput, check_json, diagnostic, parse_datetime, schema_errors


def verify_solution(problem, solution):
    """正規化済みの資格・費用・需要やソルバーの変数を使わず、共通の解を照合する。"""
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
    return violations[:1000], penalty
