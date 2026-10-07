import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from .contract import diagnostic, parse_datetime
from .flow import make_solution


class BackendUnavailable(ImportError):
    pass


def load_backend():
    """任意依存の読み込みは CP-SAT を選んだ後、探索予算の開始前に行う。"""
    try:
        from ortools import __version__
        from ortools.sat.python import cp_model
    except ImportError as error:
        raise BackendUnavailable from error
    return cp_model, __version__


@dataclass
class SatResult:
    status: str
    solution: dict | None
    values: tuple = ()
    proven_optimal: tuple = ()
    diagnostics: tuple = ()
    search_elapsed_seconds: float = 0.0
    preparation_elapsed_seconds: float = 0.0
    objective_bounds: tuple = ()
    shortage_person_minutes: int | None = None
    shortage_proven_minimal: bool = False
    shortage_bound: float | None = None


def prepare_roster(model, problem):
    grid = problem.grid
    shifts = {c.id: model.new_bool_var(f"shift_{c.id}") for c in problem.candidates}
    by_day, by_employee, coverage = defaultdict(list), defaultdict(list), defaultdict(list)
    for candidate in problem.candidates:
        variable = shifts[candidate.id]
        by_employee[candidate.employee_id].append(candidate)
        by_day[candidate.employee_id, candidate.day.toordinal()].append(variable)
        for slot in candidate.work_slots:
            coverage[candidate.employee_id, slot].append(variable)
    for variables in by_day.values():
        model.add(sum(variables) <= 1)
    if problem.request["schema_version"] in {"0.2", "0.3"}:
        for candidates in by_employee.values():
            model.add_no_overlap(
                model.new_optional_fixed_size_interval_var(
                    c.start, c.end - c.start, shifts[c.id], f"span_{c.id}"
                )
                for c in candidates
            )
    scheduled = {
        employee: sum(len(c.work_slots) * grid.slot_minutes * shifts[c.id] for c in candidates)
        for employee, candidates in by_employee.items()
    }
    histories = {e["id"]: e["history"] for e in problem.request["employees"]}
    first_day = grid.start.astimezone(grid.timezone).date().toordinal()
    days = grid.end.astimezone(grid.timezone).date().toordinal() - first_day
    for constraint in problem.request["constraints"]:
        kind = constraint["type"]
        for employee in constraint["employee_ids"]:
            if kind == "max_scheduled_minutes":
                model.add(scheduled.get(employee, 0) <= int(constraint["limit_minutes"]))
            elif kind == "min_rest_minutes":
                rest = timedelta(minutes=int(constraint["limit_minutes"]))
                candidates = by_employee[employee]
                last = histories[employee]["last_shift_end"]
                if last is not None:
                    last = parse_datetime(last)
                    for c in candidates:
                        start = grid.start + timedelta(minutes=c.start * grid.slot_minutes)
                        if start - last < rest:
                            model.add(shifts[c.id] == 0)
                model.add_no_overlap(
                    model.new_optional_fixed_size_interval_var(
                        c.start * grid.slot_minutes,
                        (c.end - c.start) * grid.slot_minutes + int(constraint["limit_minutes"]),
                        shifts[c.id],
                        f"rest_{constraint['id']}_{c.id}",
                    )
                    for c in candidates
                )
            elif kind == "max_consecutive_days":
                previous = int(histories[employee]["consecutive_work_days_before_window"])
                limit = int(constraint["limit_days"])
                for day in range(first_day, first_day + days):
                    working = model.new_bool_var(f"day_{constraint['id']}_{employee}_{day}")
                    model.add(working == sum(by_day[employee, day]))
                    consecutive = model.new_int_var(
                        0, limit, f"run_{constraint['id']}_{employee}_{day}"
                    )
                    model.add(consecutive == previous + 1).only_enforce_if(working)
                    model.add(consecutive == 0).only_enforce_if(working.Not())
                    previous = consecutive
            elif kind == "min_split_gap_minutes":
                for c in by_employee[employee]:
                    if any(
                        (b[0] - a[1]) * grid.slot_minutes < constraint["limit_minutes"]
                        for a, b in zip(c.segments, c.segments[1:], strict=False)
                    ):
                        model.add(shifts[c.id] == 0)
    return shifts, coverage, scheduled


def prepare(problem, cp_model):
    model = cp_model.CpModel()
    roster = problem.request["problem_type"] == "roster"
    shifts, coverage, scheduled = prepare_roster(model, problem) if roster else ({}, {}, {})
    assignments = {}
    by_employee = defaultdict(list)
    by_slot = defaultdict(list)
    by_role = defaultdict(list)
    shortages = []
    for slot, demand in enumerate(problem.demand):
        for role, count in sorted(demand.items()):
            if not count:
                continue
            for employee in sorted(problem.available):
                possible = (
                    (employee, slot) in coverage if roster else slot in problem.available[employee]
                )
                if possible and role in problem.qualified[employee]:
                    variable = model.new_bool_var(f"assign_{employee}_{slot}_{role}")
                    assignments[employee, slot, role] = variable
                    by_employee[employee].append(variable)
                    by_slot[employee, slot].append((role, variable))
                    by_role[slot, role].append(variable)
            if problem.request["schema_version"] == "0.3":
                shortage = model.new_int_var(0, count, f"shortage_{slot}_{role}")
                model.add(sum(by_role[slot, role]) + shortage == count)
                shortages.append(shortage)
            else:
                model.add(sum(by_role[slot, role]) == count)
    for values in by_slot.values():
        model.add(sum(variable for _, variable in values) <= 1)
    if roster:
        for key, values in by_slot.items():
            model.add(sum(variable for _, variable in values) <= sum(coverage[key]))

    metrics = {o["metric"] for o in problem.request["objectives"]}
    switch_employees = set(problem.available) if "role_switches" in metrics else set()
    for constraint in problem.request["constraints"]:
        if constraint["type"] == "max_role_switches":
            switch_employees.update(constraint["employee_ids"])
    switches = defaultdict(list)
    role_numbers = {role["id"]: i for i, role in enumerate(problem.request["roles"], 1)}
    states = {}
    for (employee, slot), values in by_slot.items():
        if employee not in switch_employees:
            continue
        active = model.new_bool_var(f"active_{employee}_{slot}")
        role = model.new_int_var(0, len(role_numbers), f"role_{employee}_{slot}")
        model.add(active == sum(variable for _, variable in values))
        model.add(role == sum(role_numbers[r] * variable for r, variable in values))
        states[employee, slot] = active, role
    for (employee, slot), (active, role) in states.items():
        if (employee, slot + 1) not in states:
            continue
        next_active, next_role = states[employee, slot + 1]
        switch = model.new_bool_var(f"switch_{employee}_{slot}")
        model.add(switch <= active)
        model.add(switch <= next_active)
        model.add(role != next_role).only_enforce_if(switch)
        model.add(role == next_role).only_enforce_if([active, next_active, switch.Not()])
        switches[employee].append(switch)

    for constraint in problem.request["constraints"]:
        for employee in constraint["employee_ids"]:
            if constraint["type"] == "max_assigned_minutes":
                model.add(
                    sum(by_employee[employee]) * problem.grid.slot_minutes
                    <= int(constraint["limit_minutes"])
                )
            elif constraint["type"] == "max_role_switches":
                model.add(sum(switches[employee]) <= int(constraint["limit_count"]))
    expressions = {
        "preference_penalty": sum(
            problem.costs.get((employee, role), 0) * variable
            for (employee, _, role), variable in assignments.items()
        ),
        "role_switches": sum(variable for values in switches.values() for variable in values),
        "scheduled_minutes": sum(scheduled.values()),
    }
    if problem.request["schema_version"] in {"0.2", "0.3"}:
        from .extensions import prepare as prepare_extensions

        expressions.update(prepare_extensions(model, problem, assignments, shifts, scheduled))
    objectives = tuple(expressions[o["metric"]] for o in problem.request["objectives"])
    if problem.request["schema_version"] == "0.3":
        objectives = (sum(shortages) * problem.grid.slot_minutes, *objectives)
    if objectives:
        model.minimize(objectives[0])
    if model.validate():
        raise RuntimeError("Invalid CP-SAT model")
    return model, assignments, shifts, objectives


def run(problem, cp_model):
    preparation_start = time.perf_counter()
    model, variables, shifts, objectives = prepare(problem, cp_model)
    preparation_elapsed = time.perf_counter() - preparation_start
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = int(problem.request["solver"]["seed"])
    solver.parameters.num_search_workers = 2
    solver.parameters.log_search_progress = False
    budget = problem.request["solver"]["time_limit_seconds"]
    # 準備を終えてから全段階で一つの予算を共有し、段階間の処理も含める。
    start = time.monotonic()
    deadline = start + budget
    best = None
    bounds = [None] * len(objectives)
    partial = problem.request["schema_version"] == "0.3"
    for index, objective in enumerate(objectives or (None,)):
        path = (
            "/shortage_summary"
            if partial and index == 0
            else f"/objectives/{index - int(partial)}"
            if objectives
            else "/solver/time_limit_seconds"
        )
        remaining = budget if index == 0 else deadline - time.monotonic()
        if remaining <= 0:
            status = cp_model.UNKNOWN
        else:
            solver.parameters.max_time_in_seconds = remaining
            status = solver.solve(model)
            if objective is not None and status in {
                cp_model.OPTIMAL,
                cp_model.FEASIBLE,
                cp_model.UNKNOWN,
            }:
                bounds[index] = solver.best_objective_bound
        if status == cp_model.UNKNOWN:
            best = best or SatResult("UNKNOWN", None)
            if best.solution is not None:
                best.status = "FEASIBLE"
            best.diagnostics = (
                diagnostic(
                    "TIME_LIMIT",
                    "探索予算内に目的順序の最適化を完了できませんでした。",
                    path,
                    completed_objectives=max(0, index - int(partial)),
                ),
            )
            break
        if status == cp_model.INFEASIBLE:
            if best is not None:
                # 上位の最適解を固定したモデルには、その解が必ず残る。
                raise RuntimeError("Fixed optimal values became infeasible")
            best = SatResult(
                "INFEASIBLE",
                None,
                diagnostics=(
                    diagnostic("NO_FEASIBLE_PLAN", "すべての必須条件を満たす配置はありません。"),
                ),
            )
            break
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            raise RuntimeError("Unexpected CP-SAT status")
        assignments = defaultdict(list)
        for (employee, slot, role), variable in variables.items():
            if solver.value(variable):
                assignments[employee].append((slot, role))
        solution = make_solution(problem.grid, assignments)
        solution["shifts"] = [
            candidate.output(problem.grid)
            for candidate in problem.candidates
            if solver.value(shifts[candidate.id])
        ]
        values = tuple(int(solver.value(expression)) for expression in objectives)
        if best is not None and values[:index] != best.values[:index]:
            raise RuntimeError("Fixed optimal values changed")
        if best is None or values < best.values:
            best = SatResult("FEASIBLE", solution, values)
        # 解の選択と証明の更新を分け、保持した解にも新しい証明を反映する。
        if status == cp_model.OPTIMAL and best.values[: index + 1] != values[: index + 1]:
            raise RuntimeError("Known solution contradicts optimal value")
        best.status = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        best.proven_optimal = tuple(
            i < index + (status == cp_model.OPTIMAL) for i in range(len(objectives))
        )
        if status == cp_model.FEASIBLE:
            best.diagnostics = (
                diagnostic(
                    "OPTIMALITY_UNPROVEN",
                    "上位目的の最適性が未証明のため、後続の目的は探索しません。",
                    path,
                ),
            )
            break
        if index + 1 < len(objectives):
            model.add(objective == values[index])
            model.minimize(objectives[index + 1])
            if model.validate():
                raise RuntimeError("Invalid CP-SAT model")
    best.search_elapsed_seconds = time.monotonic() - start
    best.preparation_elapsed_seconds = preparation_elapsed
    best.objective_bounds = tuple(bounds)
    if problem.request["schema_version"] == "0.3":
        if best.solution is not None:
            best.shortage_person_minutes = best.values[0]
            best.shortage_proven_minimal = best.values[0] == 0 or best.proven_optimal[0]
            best.values = best.values[1:]
            best.proven_optimal = best.proven_optimal[1:]
            if not best.shortage_person_minutes and all(best.proven_optimal):
                best.status = "OPTIMAL"
        best.shortage_bound = best.objective_bounds[0]
        best.objective_bounds = best.objective_bounds[1:]
    return best
