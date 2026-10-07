"""勤務計画の目標勤務量、基準計画と固定部分を扱う。"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timedelta

from .contract import InvalidInput, diagnostic, parse_datetime, reject, schema_errors


def states(grid, solution, *, continuity=False):
    """共通解から勤務・担当状態を再構成し、候補表やソルバー変数を参照しない。"""
    work, roles = {}, {}
    for index, shift in enumerate(solution["shifts"]):
        segments = shift.get("segments", [shift])
        for segment_index, segment in enumerate(segments):
            path = f"/shifts/{index}/segments/{segment_index}"
            value = segment["interval"]
            if continuity:
                # 状態比較はW内だけ。原区間は保存したまま投影する。
                a, b = parse_datetime(value["start"]), parse_datetime(value["end"])
                if b <= grid.start or a >= grid.end:
                    continue
                value = grid.output_interval(
                    max(0, (a - grid.start) // timedelta(minutes=grid.slot_minutes)),
                    min(grid.slots, (b - grid.start) // timedelta(minutes=grid.slot_minutes)),
                )
            start, end = grid.interval(value, path + "/interval")
            for slot in range(start, end):
                work[shift["employee_id"], slot] = "work"
            for break_index, interval in enumerate(segment["breaks"]):
                value = interval
                if continuity:
                    a, b = parse_datetime(value["start"]), parse_datetime(value["end"])
                    if b <= grid.start or a >= grid.end:
                        continue
                    value = grid.output_interval(
                        max(0, (a - grid.start) // timedelta(minutes=grid.slot_minutes)),
                        min(grid.slots, (b - grid.start) // timedelta(minutes=grid.slot_minutes)),
                    )
                start, end = grid.interval(value, f"{path}/breaks/{break_index}")
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
    mode = request.get("replan_mode")
    metrics = {objective["metric"] for objective in request["objectives"]}
    if request["problem_type"] != "roster" and (
        fairness
        or baseline
        or fixed
        or mode
        or metrics & {"fairness_deviation_minutes", "plan_changes"}
    ):
        reject("UNSUPPORTED_CONDITION", "勤務量・再計画の拡張は roster で指定します。")
    if mode == "rebuild" and (fixed or "plan_changes" in metrics):
        reject("REBUILD_CONFLICT", "rebuild は固定部分・変更最小化を持ちません。", "/replan_mode")
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
        if "plan_changes" in metrics or fixed or mode == "preserve_assigned":
            reject("MISSING_BASELINE", "変更目的と固定部分には基準計画を指定します。", "/baseline")
        return
    source = baseline["source_request"]
    if (
        source.get("schema_version") in {"0.4", "0.5", "0.6"}
        and request["schema_version"] < source["schema_version"]
    ):
        reject(
            "UNSUPPORTED_BASELINE_VERSION",
            "旧版の基準に新しい契約版は指定できません。",
            "/baseline/source_request/schema_version",
        )
    if request["schema_version"] == "0.2" and source.get("schema_version") in (
        "0.3",
        "0.4",
        "0.5",
        "0.6",
    ):
        reject(
            "UNSUPPORTED_BASELINE_VERSION",
            "契約0.2の基準計画は0.1または0.2で指定します。",
            "/baseline/source_request/schema_version",
        )
    if "baseline" in source or "diagnosis" in source:
        reject(
            "NESTED_BASELINE",
            "基準の旧入力に baseline・diagnosis は指定できません。",
            "/baseline/source_request",
        )
    try:
        old = normalize(source)
        violations, _ = verify_solution(
            old,
            baseline["source_solution"],
            require_complete=request["schema_version"] not in {"0.4", "0.5", "0.6"},
        )
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
                {
                    **item,
                    "json_pointer": (
                        "/baseline/source_request"
                        if item["json_pointer"].startswith("/constraints/")
                        else "/baseline/source_solution"
                    )
                    + item["json_pointer"],
                }
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
    work, roles = states(
        grid, baseline["source_solution"], continuity=bool(source.get("continuity"))
    )
    if (
        baseline.get("snapshot_origin")
        and baseline["snapshot_origin"]["request_id"] != source["request_id"]
    ):
        reject(
            "SNAPSHOT_ORIGIN_MISMATCH",
            "スナップショットと元入力のIDが一致しません。",
            "/baseline/snapshot_origin/request_id",
        )
    requirements = []
    for index, part in enumerate(baseline.get("source_fixed_states", [])):
        path = f"/baseline/source_fixed_states/{index}"
        reference(part["employee_id"], old_employees, path + "/employee_id")
        start, end = grid.interval(part["interval"], path + "/interval")
        for component in ("work", "role"):
            if component in part:
                requirements.extend(
                    (
                        (part["employee_id"], slot),
                        component,
                        part[component],
                        path,
                        [part["employee_id"]],
                    )
                    for slot in range(start, end)
                )
    violations = check_fixed_states(requirements, work, roles)
    if violations:
        raise InvalidInput(violations)
    problem.baseline = {**baseline, "work": work, "roles": roles, "employee_ids": old_employees}


def fixed_requirements(problem):
    """担当済み枠の自動固定と明示固定を、比較元の絶対状態へ解決する。"""
    baseline = problem.baseline
    if baseline is None:
        return
    if problem.request.get("replan_mode") == "preserve_assigned":
        for key, role in sorted(baseline["roles"].items()):
            yield key, "work", "work", "/replan_mode", [key[0]]
            yield key, "role", role, "/replan_mode", [key[0], role]
    for index, part in enumerate(problem.request.get("fixed_parts", [])):
        path = f"/fixed_parts/{index}"
        start, end = problem.grid.interval(part["interval"], path + "/interval")
        for component in part["components"]:
            values = baseline["work"] if component == "work" else baseline["roles"]
            default = "off" if component == "work" else None
            for slot in range(start, end):
                key = part["employee_id"], slot
                yield key, component, values.get(key, default), path, [part["id"], key[0]]


def check_fixed_states(requirements, work, roles):
    violations = []
    for key, component, expected, path, related in requirements:
        current = work.get(key, "off") if component == "work" else roles.get(key)
        if current != expected and len(violations) < 1000:
            violations.append(
                diagnostic(
                    "FIXED_PART_VIOLATION",
                    "基準計画の固定部分が変更されています。",
                    path,
                    related,
                    component=component,
                    slot=key[1],
                )
            )
    return violations


def make_baseline(request: dict, solution: dict, plan_id: str) -> dict:
    """契約0.4以降の解を再検証し、ネストを増やさず次の基準計画へ保存する。"""
    from .model import normalize
    from .verify import verify_plan

    problem = normalize(request)
    if (
        request["schema_version"] not in {"0.4", "0.5", "0.6"}
        or request["problem_type"] != "roster"
    ):
        reject("UNSUPPORTED_CONDITION", "make_baseline は契約0.4〜0.6の roster を受け取ります。")
    violations, _, _ = verify_plan(problem, solution)
    if violations:
        raise InvalidInput(violations)
    source = deepcopy(request)
    for field in ("baseline", "fixed_parts", "replan_mode", "diagnosis"):
        source.pop(field, None)
    source["objectives"] = [o for o in source["objectives"] if o["metric"] != "plan_changes"]
    resolved = defaultdict(dict)
    for key, component, value, _, _ in fixed_requirements(problem):
        resolved[key][component] = value
    runs = []
    for (employee, slot), components in sorted(resolved.items()):
        if runs and runs[-1][0] == employee and runs[-1][2] == slot and runs[-1][3] == components:
            runs[-1][2] += 1
        else:
            runs.append([employee, slot, slot + 1, components])
    result = {
        "plan_id": plan_id,
        "source_request": source,
        "source_solution": deepcopy(solution),
        "source_fixed_states": [
            {"employee_id": employee, "interval": problem.grid.output_interval(start, end), **parts}
            for employee, start, end, parts in runs
        ],
        "snapshot_origin": {
            "request_id": request["request_id"],
            "baseline_plan_id": (request.get("baseline") or {}).get("plan_id"),
            "replan_mode": request.get("replan_mode"),
        },
    }
    errors = schema_errors("request", {**source, "baseline": result})
    if errors:
        raise InvalidInput(errors)
    return result


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
    if (
        not request.get("fixed_parts")
        and request.get("replan_mode") != "preserve_assigned"
        and not any(o["metric"] == "plan_changes" for o in request["objectives"])
    ):
        return expressions
    work, breaks, roles = defaultdict(list), defaultdict(list), defaultdict(list)
    for candidate in problem.candidates:
        for slot in candidate.work_slots:
            work[candidate.employee_id, slot].append(shifts[candidate.id])
        for start, end in candidate.breaks:
            for slot in range(start, end):
                breaks[candidate.employee_id, slot].append(shifts[candidate.id])
    if request.get("continuity"):
        from .continuity import covered_slots

        for duty in problem.continuity:
            for slot in covered_slots(duty["segments"], grid):
                work[duty["employee_id"], slot].append(1)
            for slot in covered_slots(duty["segments"], grid, breaks=True):
                breaks[duty["employee_id"], slot].append(1)
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
    for key, component, expected, _, _ in fixed_requirements(problem):
        match = work_match(key, expected) if component == "work" else role_match(key, expected)
        model.add(match == 1)
    return expressions


def evaluate(problem, solution):
    metrics = {"fairness_deviation_minutes": 0, "plan_changes": 0}
    summaries = {"fairness_summary": None, "change_summary": None}
    if problem.request["schema_version"] == "0.6":
        from .continuity import summary

        summaries["continuity_summary"] = (
            summary(problem.request, problem.grid, solution)
            if problem.request.get("continuity")
            else None
        )
    try:
        work, roles = states(
            problem.grid, solution, continuity=bool(problem.request.get("continuity"))
        )
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
        violations.extend(check_fixed_states(fixed_requirements(problem), work, roles))
    return violations, metrics, summaries
