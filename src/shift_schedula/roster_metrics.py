"""計画内の勤務費用と指定区間の目標偏差。"""

from collections import defaultdict
from copy import deepcopy

from .contract import parse_datetime, reject
from .model import reference, unique


def duty_slots(duty, grid):
    return {
        slot
        for interval in duty["intervals"]
        for slot in range(*grid.interval(interval, "/duty_balance/intervals"))
    }


def validate(problem):
    request, grid = problem.request, problem.grid
    costs, duties = request.get("costs"), request.get("duty_balance", [])
    metrics = {o["metric"] for o in request["objectives"]}
    if request["problem_type"] != "roster" and (costs or duties):
        reject("UNSUPPORTED_CONDITION", "費用と指定区間の評価は roster 専用です。")
    if (costs is not None) != ("scheduled_cost" in metrics):
        reject("MISSING_COST_OBJECTIVE", "単価と勤務費用目的は対にして指定します。", "/costs")
    employees = set(problem.available)
    if costs is not None:
        if type(costs["units_per_currency"]) is not int:
            reject("INVALID_INTEGER", "倍率は整数で指定します。", "/costs/units_per_currency")
        rates = costs["employee_rates"]
        ids = unique(rates, "employee_id", "/costs/employee_rates")
        for i, rate in enumerate(rates):
            path = f"/costs/employee_rates/{i}"
            reference(rate["employee_id"], employees, path + "/employee_id")
            if type(rate["units_per_minute"]) is not int:
                reject("INVALID_INTEGER", "単価は整数で指定します。", path + "/units_per_minute")
        if ids != employees:
            reject("MISSING_EMPLOYEE_RATE", "全従業員の単価が必要です。", "/costs/employee_rates")
        rates = {r["employee_id"]: r["units_per_minute"] for r in rates}
        bound = sum(
            len(c.work_slots) * grid.slot_minutes * rates[c.employee_id] for c in problem.candidates
        )
        if request.get("continuity"):
            from .continuity import minutes

            bound += sum(
                minutes(d["segments"], grid.start, grid.end) * rates[d["employee_id"]]
                for d in problem.continuity
            )
        if bound > 2**53 - 1:
            reject("INTEGER_EXPRESSION_LIMIT", "費用整数の保守的上界を超えています。", "/costs")
    ids = unique(duties, "id", "/duty_balance")
    objectives = [o for o in request["objectives"] if o["metric"] == "duty_deviation_minutes"]
    if ids != {o["duty_id"] for o in objectives}:
        reject(
            "MISSING_DUTY_OBJECTIVE",
            "評価定義と目的は duty_id で1対1に指定します。",
            "/duty_balance",
        )
    bound = 0
    for i, duty in enumerate(duties):
        path = f"/duty_balance/{i}"
        start, end = grid.interval(duty["evaluation_period"], path + "/evaluation_period")
        for j, interval in enumerate(duty["intervals"]):
            a, b = grid.interval(interval, f"{path}/intervals/{j}")
            if not start <= a < b <= end:
                reject(
                    "INVALID_DUTY_INTERVAL",
                    "区間は評価期間内に指定します。",
                    f"{path}/intervals/{j}",
                )
        unique(duty["employee_targets"], "employee_id", path + "/employee_targets")
        slots = duty_slots(duty, grid)
        upper = defaultdict(int)
        for candidate in problem.candidates:
            upper[candidate.employee_id] += len(candidate.work_slots & slots) * grid.slot_minutes
        if request.get("continuity"):
            from .continuity import covered_slots

            for duty_fact in problem.continuity:
                upper[duty_fact["employee_id"]] += (
                    len(covered_slots(duty_fact["segments"], grid) & slots) * grid.slot_minutes
                )
        for j, target in enumerate(duty["employee_targets"]):
            pointer = f"{path}/employee_targets/{j}"
            reference(target["employee_id"], employees, pointer + "/employee_id")
            if type(target["target_minutes"]) is not int:
                reject("INVALID_INTEGER", "目標は整数で指定します。", pointer + "/target_minutes")
            bound += max(target["target_minutes"], upper[target["employee_id"]])
    if bound > 2**60 - 1:
        reject("INTEGER_EXPRESSION_LIMIT", "偏差整数の保守的上界を超えています。", "/duty_balance")


def prepare(model, problem, shifts, scheduled):
    request, grid = problem.request, problem.grid
    expressions = {}
    if "costs" in request:
        expressions["scheduled_cost"] = sum(
            r["units_per_minute"] * scheduled.get(r["employee_id"], 0)
            for r in request["costs"]["employee_rates"]
        )
    for duty in request.get("duty_balance", []):
        slots = duty_slots(duty, grid)
        deviations = []
        for target in duty["employee_targets"]:
            employee, minutes = target["employee_id"], target["target_minutes"]
            actual = sum(
                len(c.work_slots & slots) * grid.slot_minutes * shifts[c.id]
                for c in problem.candidates
                if c.employee_id == employee
            )
            if request.get("continuity"):
                from .continuity import covered_slots

                actual += sum(
                    len(covered_slots(d["segments"], grid) & slots) * grid.slot_minutes
                    for d in problem.continuity
                    if d["employee_id"] == employee
                )
            deviation = model.new_int_var(
                0, max(len(slots) * grid.slot_minutes, minutes), f"duty_{duty['id']}_{employee}"
            )
            model.add_abs_equality(deviation, actual - minutes)
            deviations.append(deviation)
        expressions["duty_deviation_minutes", duty["id"]] = sum(deviations)
    return expressions


def evaluate(request, grid, solution):
    from .continuity import minutes

    # 元JSONと返却segmentsだけを読む。モデルの候補・係数・正規化区間を使わない。
    segments = defaultdict(list)
    for shift in solution["shifts"]:
        for segment in shift["segments"]:
            segments[shift["employee_id"]].append(
                (
                    parse_datetime(segment["interval"]["start"]),
                    parse_datetime(segment["interval"]["end"]),
                    tuple(
                        (parse_datetime(b["start"]), parse_datetime(b["end"]))
                        for b in segment["breaks"]
                    ),
                )
            )
    metrics = {}
    summaries = {"cost_summary": None, "duty_balance_summary": None}
    if "costs" in request:
        costs = request["costs"]
        rates = {r["employee_id"]: r["units_per_minute"] for r in costs["employee_rates"]}
        employees = []
        for employee in request["employees"]:
            identifier = employee["id"]
            scheduled = minutes(segments[identifier], grid.start, grid.end)
            employees.append(
                {
                    "employee_id": identifier,
                    "units_per_minute": rates[identifier],
                    "scheduled_minutes": scheduled,
                    "cost_units": rates[identifier] * scheduled,
                }
            )
        total = sum(e["cost_units"] for e in employees)
        metrics["scheduled_cost"] = total
        summaries["cost_summary"] = {
            "currency": costs["currency"],
            "units_per_currency": costs["units_per_currency"],
            "evaluation_period": {k: request["planning_window"][k] for k in ("start", "end")},
            "total_units": total,
            "employees": employees,
        }
    if "duty_balance" in request:
        summaries["duty_balance_summary"] = []
        for duty in request["duty_balance"]:
            intervals = []
            for start, end in sorted(
                (parse_datetime(i["start"]), parse_datetime(i["end"])) for i in duty["intervals"]
            ):
                if intervals and start <= intervals[-1][1]:
                    intervals[-1][1] = max(end, intervals[-1][1])
                else:
                    intervals.append([start, end])
            employees = []
            for target in duty["employee_targets"]:
                actual = sum(minutes(segments[target["employee_id"]], a, b) for a, b in intervals)
                employees.append(
                    {
                        **target,
                        "actual_minutes": actual,
                        "deviation_minutes": abs(actual - target["target_minutes"]),
                    }
                )
            total = sum(e["deviation_minutes"] for e in employees)
            metrics["duty_deviation_minutes", duty["id"]] = total
            summaries["duty_balance_summary"].append(
                {
                    "duty_id": duty["id"],
                    "label": duty["label"],
                    "evaluation_period": deepcopy(duty["evaluation_period"]),
                    "intervals": [
                        {
                            "start": a.astimezone(grid.timezone).isoformat(),
                            "end": b.astimezone(grid.timezone).isoformat(),
                        }
                        for a, b in intervals
                    ],
                    "unit": "minutes",
                    "scale": "absolute_deviation",
                    "normalized": False,
                    "total_deviation_minutes": total,
                    "employees": employees,
                }
            )
    return metrics, summaries
