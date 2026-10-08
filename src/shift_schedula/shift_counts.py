"""原勤務の開始日時へ帰属させる、明示目標に対する勤務回数の偏差。"""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime

from .continuity import context_bounds, interval
from .contract import parse_datetime, reject
from .model import reference, unique
from .shift_patterns import category_ranges, classify, model_duties


def matches(duty, balance, categories):
    start, end = (parse_datetime(balance["evaluation_period"][k]) for k in ("start", "end"))
    return start <= parse_datetime(duty["segments"][0]["interval"]["start"]) < end and (
        "category_id" not in balance
        or balance["category_id"] in classify(duty["segments"], categories)
    )


def validate(problem):
    request, grid = problem.request, problem.grid
    balances = request.get("shift_count_balance", [])
    if balances and request["problem_type"] != "roster":
        reject(
            "UNSUPPORTED_CONDITION", "勤務回数の評価は roster 専用です。", "/shift_count_balance"
        )
    identifiers = unique(balances, "id", "/shift_count_balance")
    objectives = [o for o in request["objectives"] if o["metric"] == "shift_count_deviation"]
    if identifiers != {o["balance_id"] for o in objectives}:
        reject(
            "MISSING_SHIFT_COUNT_OBJECTIVE",
            "勤務回数の評価定義と目的は balance_id で1対1に指定します。",
            "/shift_count_balance",
        )
    bounds = context_bounds(request, grid) if request.get("continuity") else (grid.start, grid.end)
    categories = category_ranges(request)
    duties = model_duties(problem)
    bound = 0
    for i, balance in enumerate(balances):
        path = f"/shift_count_balance/{i}"
        period = balance["evaluation_period"]
        if parse_datetime(period["start"]) < bounds[0] or parse_datetime(period["end"]) > bounds[1]:
            reject("INCOMPLETE_HISTORY", "評価期間には確認済みの文脈期間が必要です。", path)
        interval(period, grid, bounds, path + "/evaluation_period")
        if any(
            parse_datetime(period[k]).astimezone(grid.timezone).time() != datetime.min.time()
            for k in ("start", "end")
        ):
            reject("INVALID_COUNT_PERIOD", "回数の評価期間はローカル00:00同士です。", path)
        if "category_id" in balance:
            reference(balance["category_id"], categories, path + "/category_id")
        unique(balance["employee_targets"], "employee_id", path + "/employee_targets")
        upper = defaultdict(int)
        for duty, _, _ in duties:
            upper[duty["employee_id"]] += int(matches(duty, balance, categories))
        for j, target in enumerate(balance["employee_targets"]):
            pointer = f"{path}/employee_targets/{j}"
            reference(target["employee_id"], problem.available, pointer + "/employee_id")
            if type(target["target_count"]) is not int:
                reject("INVALID_INTEGER", "目標回数は整数で指定します。", pointer + "/target_count")
            bound += max(target["target_count"], upper[target["employee_id"]])
    if bound > 2**60 - 1:
        reject(
            "INTEGER_EXPRESSION_LIMIT",
            "回数偏差整数の保守的上界を超えています。",
            "/shift_count_balance",
        )


def prepare(model, problem, shifts):
    categories = category_ranges(problem.request)
    duties = model_duties(problem, shifts)
    expressions = {}
    for balance in problem.request.get("shift_count_balance", []):
        counts = defaultdict(list)
        for duty, variable, _ in duties:
            if matches(duty, balance, categories):
                counts[duty["employee_id"]].append(variable)
        deviations = []
        for target in balance["employee_targets"]:
            employee, goal = target["employee_id"], target["target_count"]
            deviation = model.new_int_var(
                0, max(goal, len(counts[employee])), f"count_{balance['id']}_{employee}"
            )
            model.add_abs_equality(deviation, sum(counts[employee]) - goal)
            deviations.append(deviation)
        expressions["shift_count_deviation", balance["id"]] = sum(deviations)
    return expressions


def evaluate(request, grid, solution):
    # 元JSONと返却原勤務から再構成し、候補係数・ソルバー変数を使わない。
    duties = list(solution["shifts"])
    returned = {s["committed_shift_id"] for s in duties if "committed_shift_id" in s}
    for row in request.get("continuity", {}).get("employees", []):
        duties.extend({**s, "employee_id": row["employee_id"]} for s in row["actual_shifts"])
        duties.extend(
            {**s, "employee_id": row["employee_id"]}
            for s in row["committed_shifts"]
            if s["id"] not in returned
        )
    categories = category_ranges(request)
    metrics, summaries = {}, None
    if "shift_count_balance" in request:
        summaries = []
        for balance in request["shift_count_balance"]:
            period = balance["evaluation_period"]
            start, end = (parse_datetime(period[k]) for k in ("start", "end"))
            counts = defaultdict(int)
            for duty in duties:
                if start <= parse_datetime(duty["segments"][0]["interval"]["start"]) < end and (
                    "category_id" not in balance
                    or balance["category_id"] in classify(duty["segments"], categories)
                ):
                    counts[duty["employee_id"]] += 1
            employees = [
                {
                    **target,
                    "actual_count": counts[target["employee_id"]],
                    "deviation_count": abs(counts[target["employee_id"]] - target["target_count"]),
                }
                for target in balance["employee_targets"]
            ]
            total = sum(e["deviation_count"] for e in employees)
            metrics["shift_count_deviation", balance["id"]] = total
            summaries.append(
                {
                    **{k: deepcopy(balance[k]) for k in ("id", "label", "evaluation_period")},
                    **({"category_id": balance["category_id"]} if "category_id" in balance else {}),
                    "unit": "shifts",
                    "scale": "absolute_deviation",
                    "normalized": False,
                    "total_deviation_count": total,
                    "employees": employees,
                }
            )
    return metrics, {"shift_count_balance_summary": summaries}
