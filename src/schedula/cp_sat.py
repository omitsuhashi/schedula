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
    cost: int = 0
    diagnostics: tuple = ()


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
    return shifts, coverage, sum(scheduled.values())


def prepare(problem, cp_model):
    model = cp_model.CpModel()
    roster = problem.request["problem_type"] == "roster"
    shifts, coverage, scheduled = prepare_roster(model, problem) if roster else ({}, {}, 0)
    assignments = {}
    by_employee = defaultdict(list)
    by_slot = defaultdict(list)
    by_role = defaultdict(list)
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
            model.add(sum(by_role[slot, role]) == count)
    for values in by_slot.values():
        model.add(sum(variable for _, variable in values) <= 1)
    if roster:
        for key, values in by_slot.items():
            model.add(sum(variable for _, variable in values) <= sum(coverage[key]))

    metric = problem.request["objectives"][0]["metric"] if problem.request["objectives"] else None
    switch_employees = set(problem.available) if metric == "role_switches" else set()
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
    objective = 0
    if metric == "preference_penalty":
        objective = sum(
            problem.costs.get((employee, role), 0) * variable
            for (employee, _, role), variable in assignments.items()
        )
    elif metric == "role_switches":
        objective = sum(variable for values in switches.values() for variable in values)
    elif metric == "scheduled_minutes":
        objective = scheduled
    if metric:
        model.minimize(objective)
    if model.validate():
        raise RuntimeError("Invalid CP-SAT model")
    return model, assignments, shifts, objective


def run(problem, cp_model):
    model, variables, shifts, objective = prepare(problem, cp_model)
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = int(problem.request["solver"]["seed"])
    solver.parameters.num_search_workers = 1
    solver.parameters.log_search_progress = False
    solver.parameters.max_time_in_seconds = problem.request["solver"]["time_limit_seconds"]
    # 準備を終えてから探索する。読み込み・モデル構築は探索時間に含めない。
    status = solver.solve(model)
    if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
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
        return SatResult(
            "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
            solution,
            int(solver.value(objective)),
        )
    if status == cp_model.INFEASIBLE:
        return SatResult(
            "INFEASIBLE",
            None,
            diagnostics=(
                diagnostic("NO_FEASIBLE_PLAN", "すべての必須条件を満たす配置はありません。"),
            ),
        )
    if status == cp_model.UNKNOWN:
        return SatResult(
            "UNKNOWN",
            None,
            diagnostics=(
                diagnostic("TIME_LIMIT", "探索予算内に解や不可能性の証明を得られませんでした。"),
            ),
        )
    raise RuntimeError("Unexpected CP-SAT status")
