from collections import defaultdict
from dataclasses import dataclass

from .contract import diagnostic
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


def prepare(problem, cp_model):
    model = cp_model.CpModel()
    assignments = {}
    by_employee = defaultdict(list)
    by_slot = defaultdict(list)
    by_role = defaultdict(list)
    for slot, demand in enumerate(problem.demand):
        for role, count in sorted(demand.items()):
            if not count:
                continue
            for employee in sorted(problem.available):
                if slot in problem.available[employee] and role in problem.qualified[employee]:
                    variable = model.new_bool_var(f"assign_{employee}_{slot}_{role}")
                    assignments[employee, slot, role] = variable
                    by_employee[employee].append(variable)
                    by_slot[employee, slot].append((role, variable))
                    by_role[slot, role].append(variable)
            model.add(sum(by_role[slot, role]) == count)
    for values in by_slot.values():
        model.add(sum(variable for _, variable in values) <= 1)

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
            else:
                model.add(sum(switches[employee]) <= int(constraint["limit_count"]))
    objective = 0
    if metric == "preference_penalty":
        objective = sum(
            problem.costs.get((employee, role), 0) * variable
            for (employee, _, role), variable in assignments.items()
        )
    elif metric == "role_switches":
        objective = sum(variable for values in switches.values() for variable in values)
    if metric:
        model.minimize(objective)
    if model.validate():
        raise RuntimeError("Invalid CP-SAT model")
    return model, assignments, objective


def run(problem, cp_model):
    model, variables, objective = prepare(problem, cp_model)
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
        return SatResult(
            "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
            make_solution(problem.grid, assignments),
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
