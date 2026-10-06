"""勤務計画の目標勤務量、基準計画と固定部分を扱う。"""

from collections import Counter, defaultdict
from copy import deepcopy

from .contract import InvalidInput, diagnostic, reject


def states(grid, solution):
    """共通解から勤務・担当状態を再構成し、候補表やソルバー変数を参照しない。"""
    work, roles = {}, {}
    for index, shift in enumerate(solution["shifts"]):
        segments = shift.get("segments", [shift])
        for segment_index, segment in enumerate(segments):
            path = f"/shifts/{index}/segments/{segment_index}"
            start, end = grid.interval(segment["interval"], path + "/interval")
            for slot in range(start, end):
                work[shift["employee_id"], slot] = "work"
            for break_index, interval in enumerate(segment["breaks"]):
                start, end = grid.interval(interval, f"{path}/breaks/{break_index}")
                for slot in range(start, end):
                    work[shift["employee_id"], slot] = "break"
    for index, assignment in enumerate(solution["assignments"]):
        start, end = grid.interval(assignment["interval"], f"/assignments/{index}/interval")
        for slot in range(start, end):
            roles[assignment["employee_id"], slot] = assignment["role_id"]
    return work, roles


def validate(problem):
    from .model import normalize, reference, unique
    from .verify import verify_solution

    request, grid = problem.request, problem.grid
    fairness, baseline = request.get("fairness"), request.get("baseline")
    fixed = request.get("fixed_parts", [])
    metrics = {objective["metric"] for objective in request["objectives"]}
    if request["problem_type"] != "roster" and (
        fairness or baseline or fixed or metrics & {"fairness_deviation_minutes", "plan_changes"}
    ):
        reject("UNSUPPORTED_CONDITION", "勤務量・再計画の拡張は roster で指定します。")
    employees = {employee["id"] for employee in request["employees"]}
    if bool(fairness) != ("fairness_deviation_minutes" in metrics):
        reject(
            "MISSING_FAIRNESS_OBJECTIVE",
            "目標勤務量と公平性目的は対にして指定します。",
            "/fairness",
        )
    if fairness:
        if grid.interval(fairness["evaluation_period"], "/fairness/evaluation_period") != (
            0,
            grid.slots,
        ):
            reject(
                "INVALID_FAIRNESS_PERIOD",
                "評価期間は計画期間と一致させます。",
                "/fairness/evaluation_period",
            )
        unique(fairness["employee_targets"], "employee_id", "/fairness/employee_targets")
        for index, target in enumerate(fairness["employee_targets"]):
            reference(
                target["employee_id"], employees, f"/fairness/employee_targets/{index}/employee_id"
            )
    if not baseline:
        if "plan_changes" in metrics or fixed:
            reject("MISSING_BASELINE", "変更目的と固定部分には基準計画を指定します。", "/baseline")
        return
    source = baseline["source_request"]
    if "baseline" in source or "diagnosis" in source:
        reject(
            "NESTED_BASELINE",
            "基準の旧入力に baseline・diagnosis は指定できません。",
            "/baseline/source_request",
        )
    try:
        old = normalize(source)
        violations, _ = verify_solution(old, baseline["source_solution"])
    except InvalidInput as error:
        raise InvalidInput(
            [
                {**item, "json_pointer": "/baseline/source_request" + item["json_pointer"]}
                for item in error.diagnostics
            ]
        ) from error
    if violations:
        raise InvalidInput(
            [
                {**item, "json_pointer": "/baseline/source_solution" + item["json_pointer"]}
                for item in violations
            ]
        )
    if (
        source["problem_type"] != "roster"
        or old.grid.start != grid.start
        or old.grid.end != grid.end
        or old.grid.timezone.key != grid.timezone.key
        or old.grid.slot_minutes != grid.slot_minutes
    ):
        reject(
            "BASELINE_WINDOW_MISMATCH",
            "基準計画は同じ勤務計画の期間・タイムゾーン・粒度で指定します。",
            "/baseline/source_request",
        )
    old_employees = {employee["id"] for employee in source["employees"]}
    if len(employees | old_employees) > 500:
        reject("INPUT_LIMIT", "比較対象の従業員の和集合は500人以下です。", "/baseline")
    unique(fixed, "id", "/fixed_parts")
    for index, part in enumerate(fixed):
        reference(part["employee_id"], old_employees, f"/fixed_parts/{index}/employee_id")
        grid.interval(part["interval"], f"/fixed_parts/{index}/interval")
    work, roles = states(grid, baseline["source_solution"])
    problem.baseline = {**baseline, "work": work, "roles": roles, "employee_ids": old_employees}


def prepare(model, problem, assignments, shifts, scheduled_by_employee):
    request, grid = problem.request, problem.grid
    expressions = {"fairness_deviation_minutes": 0, "plan_changes": 0}
    fairness = request.get("fairness")
    if fairness:
        deviations = []
        for target in fairness["employee_targets"]:
            employee, minutes = target["employee_id"], int(target["target_minutes"])
            deviation = model.new_int_var(
                0, max(grid.slots * grid.slot_minutes, minutes), f"fairness_{employee}"
            )
            model.add_abs_equality(deviation, scheduled_by_employee.get(employee, 0) - minutes)
            deviations.append(deviation)
        expressions["fairness_deviation_minutes"] = sum(deviations)
    baseline = problem.baseline
    if baseline is None:
        return expressions
    work, breaks, roles = defaultdict(list), defaultdict(list), defaultdict(list)
    for candidate in problem.candidates:
        for slot in candidate.work_slots:
            work[candidate.employee_id, slot].append(shifts[candidate.id])
        for start, end in candidate.breaks:
            for slot in range(start, end):
                breaks[candidate.employee_id, slot].append(shifts[candidate.id])
    for (employee, slot, _), variable in assignments.items():
        roles[employee, slot].append(variable)

    def work_match(key, state):
        working, resting = sum(work.get(key, ())), sum(breaks.get(key, ()))
        return {"off": 1 - working - resting, "work": working, "break": resting}[state]

    def role_match(key, role):
        return 1 - sum(roles.get(key, ())) if role is None else assignments.get((*key, role), 0)

    changed_work = [
        1 - work_match(key, baseline["work"].get(key, "off"))
        for key in sorted(work.keys() | breaks.keys() | baseline["work"].keys())
    ]
    changed_roles = [
        1 - role_match(key, baseline["roles"].get(key))
        for key in sorted(roles.keys() | baseline["roles"].keys())
    ]
    expressions["plan_changes"] = sum(changed_work) + sum(changed_roles)
    for index, part in enumerate(request.get("fixed_parts", [])):
        start, end = grid.interval(part["interval"], f"/fixed_parts/{index}/interval")
        for slot in range(start, end):
            key = part["employee_id"], slot
            if "work" in part["components"]:
                model.add(work_match(key, baseline["work"].get(key, "off")) == 1)
            if "role" in part["components"]:
                model.add(role_match(key, baseline["roles"].get(key)) == 1)
    return expressions


def evaluate(problem, solution):
    metrics = {"fairness_deviation_minutes": 0, "plan_changes": 0}
    summaries = {"fairness_summary": None, "change_summary": None}
    try:
        work, roles = states(problem.grid, solution)
    except InvalidInput as error:
        return error.diagnostics, metrics, summaries
    fairness = problem.request.get("fairness")
    if fairness:
        scheduled = Counter(employee for (employee, _), state in work.items() if state == "work")
        employees = []
        for target in fairness["employee_targets"]:
            employee = target["employee_id"]
            minutes = scheduled[employee] * problem.grid.slot_minutes
            deviation = abs(minutes - target["target_minutes"])
            employees.append(
                {**target, "scheduled_minutes": minutes, "deviation_minutes": deviation}
            )
            metrics["fairness_deviation_minutes"] += deviation
        summaries["fairness_summary"] = {
            "evaluation_period": deepcopy(fairness["evaluation_period"]),
            "scale": "absolute_minutes",
            "normalized": False,
            "employees": employees,
        }
    violations = []
    baseline = problem.baseline
    if baseline is not None:
        work_changes = sum(
            work.get(key, "off") != baseline["work"].get(key, "off")
            for key in work.keys() | baseline["work"].keys()
        )
        role_changes = sum(
            roles.get(key) != baseline["roles"].get(key)
            for key in roles.keys() | baseline["roles"].keys()
        )
        metrics["plan_changes"] = work_changes + role_changes
        summaries["change_summary"] = {
            "plan_id": baseline["plan_id"],
            "unit": "slot_components",
            "work_changes": work_changes,
            "role_changes": role_changes,
            "total_changes": work_changes + role_changes,
        }
        for index, part in enumerate(problem.request.get("fixed_parts", [])):
            start, end = problem.grid.interval(part["interval"], f"/fixed_parts/{index}/interval")
            for component in part["components"]:
                old, current = (
                    (baseline["work"], work) if component == "work" else (baseline["roles"], roles)
                )
                default = "off" if component == "work" else None
                for slot in range(start, end):
                    key = part["employee_id"], slot
                    if (
                        old.get(key, default) != current.get(key, default)
                        and len(violations) < 1000
                    ):
                        violations.append(
                            diagnostic(
                                "FIXED_PART_VIOLATION",
                                "基準計画の固定部分が変更されています。",
                                f"/fixed_parts/{index}",
                                [part["id"], part["employee_id"]],
                                component=component,
                                slot=slot,
                            )
                        )
    return violations, metrics, summaries
